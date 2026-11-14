"""The replay's core is kept between a thread's replays (gpu/vk/vk_replay.cpp ReplayPin, RX_VK_REPLAY_PIN_KEEP).

A thread moved to the core kept for the replay (hos_reserved_cpus) stays there after its replay, until another thread
replays: that one moves it back to the processors it had, then itself onto the core. Before, every replay moved its
thread there and back, two affinity changes a replay (~14 a frame in the Market, 4.3% of the Presentation Thread).

This cuts the pin's code out of vk_replay.cpp, compiles it with stand-ins for the Win32 calls (each thread's mask kept
by the fake SetThreadAffinityMask) and runs real threads through it:
  - a thread's second replay in a row changes nothing;
  - another thread's replay moves the first back to its own processors, and itself onto the core;
  - a replay inside a replay (the capture's and the submit's) counts once;
  - a thread that ends keeping the core leaves it, and the next replay moves no one back;
  - RX_VK_REPLAY_PIN_KEEP=0: there and back at every replay, as before.

python -I -B tests/test_replay_pin_keep.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]

FIXTURE_HEAD = r"""
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <thread>
#include <vector>
typedef void* HANDLE;
typedef uintptr_t DWORD_PTR;
typedef int BOOL;
typedef unsigned long DWORD;
#define FALSE 0
#define DUPLICATE_SAME_ACCESS 0x2
#define CHECK(ok) do { if (!(ok)) { std::fprintf(stderr, "failed line %d\n", __LINE__); std::exit(1); } } while (0)
static const uint64_t CORE = 0x3000, OWN = 0x0fff;   // (the kept core's two logical processors; a thread's own ones)
static HANDLE const PSEUDO = (HANDLE)-2;
static std::mutex fake_mu;
static std::map<int, DWORD_PTR> masks;            // thread number -> its mask
static std::vector<std::pair<int, DWORD_PTR>> calls;   // (thread number, mask set)
static std::atomic<int> next_id{1};
static int closed = 0;
static thread_local int my_id = 0;
static int id_of_current() {
    if (!my_id) my_id = next_id++;
    return my_id;
}
static HANDLE GetCurrentThread() { return PSEUDO; }
static HANDLE GetCurrentProcess() { return (HANDLE)-1; }
static int thread_of(HANDLE h) { return h == PSEUDO ? id_of_current() : (int)(intptr_t)h; }
static BOOL DuplicateHandle(HANDLE, HANDLE src, HANDLE, HANDLE* out, DWORD, BOOL, DWORD) {
    *out = (HANDLE)(intptr_t)thread_of(src);
    return 1;
}
static BOOL CloseHandle(HANDLE) {
    std::lock_guard lk(fake_mu);
    closed++;
    return 1;
}
static DWORD_PTR SetThreadAffinityMask(HANDLE h, DWORD_PTR m) {
    std::lock_guard lk(fake_mu);
    const int t = thread_of(h);
    if (!masks.count(t)) masks[t] = OWN;
    const DWORD_PTR prev = masks[t];
    masks[t] = m;
    calls.push_back({t, m});
    return prev;
}
static bool async_on() { return false; }
static uint64_t replay_pin_mask() { return CORE; }
"""

FIXTURE_TAIL = r"""
static DWORD_PTR mask_of(int t) {
    std::lock_guard lk(fake_mu);
    return masks.count(t) ? masks[t] : OWN;
}
static size_t ncalls() {
    std::lock_guard lk(fake_mu);
    return calls.size();
}
// one replay on its own thread, kept alive until done() (a thread that stays, as the game's submitting threads do)
struct Worker {
    std::mutex mu;
    std::condition_variable cv;
    int todo = 0, id = 0;
    bool quit = false;
    DWORD_PTR during = 0;
    std::thread th;
    Worker() : th([this] {
        id = id_of_current();
        std::unique_lock lk(mu);
        for (;;) {
            cv.wait(lk, [this] { return todo || quit; });
            if (quit) return;
            {
                ReplayPin pin;
                { ReplayPin inner; during = mask_of(id); }   // (the submit's replay inside its capture's)
                during = mask_of(id) == during ? during : 0;
            }
            todo = 0;
            cv.notify_all();
        }
    }) {
        replay();   // (the thread's number known)
        std::lock_guard lk(fake_mu);
        calls.clear();
    }
    void replay() {
        std::unique_lock lk(mu);
        todo = 1;
        cv.notify_all();
        cv.wait(lk, [this] { return !todo; });
    }
    void done() {
        { std::lock_guard lk(mu); quit = true; }
        cv.notify_all();
        th.join();
    }
};
int main(int argc, char** argv) {
    const bool keep = argc > 1 && std::atoi(argv[1]) != 0;
    if (keep) {
        Worker a;   // (its first replay in the constructor: it keeps the core)
        CHECK(mask_of(a.id) == CORE);
        a.replay();
        CHECK(a.during == CORE && ncalls() == 0);   // (a second replay in a row: no change)
        Worker b;   // (b's first replay moves a off, b on)
        CHECK(mask_of(a.id) == OWN && mask_of(b.id) == CORE);
        a.replay();   // (a back on, b off: two changes, no more)
        CHECK(a.during == CORE && mask_of(b.id) == OWN && ncalls() == 2);
        CHECK(calls[0] == std::make_pair(b.id, (DWORD_PTR)OWN) && calls[1] == std::make_pair(a.id, (DWORD_PTR)CORE));
        b.replay();
        CHECK(b.during == CORE && mask_of(a.id) == OWN && ncalls() == 4);
        CHECK(st_pin_moves.load() >= 4);
        b.done();   // (b ends keeping the core: it leaves it)
        { std::lock_guard lk(replay_pin_mu); CHECK(replay_pin_keeper == nullptr); }
        const size_t before = ncalls();
        a.replay();   // (no keeper to move back: one change)
        CHECK(a.during == CORE && ncalls() == before + 1);
        a.done();
        CHECK(closed >= 2);
        std::printf("kept: a replay in a row changes nothing; a change of thread moves the keeper back first\n");
    } else {
        Worker a;
        CHECK(mask_of(a.id) == OWN);   // (back after its replay)
        a.replay();
        CHECK(a.during == CORE && mask_of(a.id) == OWN && ncalls() == 2);   // (there and back, once for the nested pair)
        Worker b;
        a.replay();
        CHECK(mask_of(b.id) == OWN && mask_of(a.id) == OWN);
        a.done(), b.done();
        std::printf("RX_VK_REPLAY_PIN_KEEP=0: there and back at every replay\n");
    }
    return 0;
}
"""


def cut(text, start, end):
    """text from the line starting with start through the first end after it"""
    i = text.index(start)
    j = text.index(end, i) + len(end)
    return text[i:j]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "clang++"), help="GCC/Clang C++ compiler")
    parser.add_argument("--source", type=Path, default=ROOT / "gpu/vk/vk_replay.cpp")
    args = parser.parse_args()
    cxx = shutil.which(args.cxx)
    if not cxx:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    text = args.source.read_text(encoding="utf-8")
    pin = cut(text, "thread_local int replay_pin_depth = 0;", "    ReplayPin& operator=(const ReplayPin&) = delete;\n};")
    for need in ("replay_pin_keep()", "replay_pin_keeper", "RX_VK_REPLAY_PIN_KEEP"):
        if need not in pin:
            raise SystemExit("ReplayPin no longer keeps the core between replays (%s): not what this test checks" % need)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="hookshot-pin-keep-") as tmp:
        src = Path(tmp) / "pin_keep.cpp"
        src.write_text(FIXTURE_HEAD + "#include <condition_variable>\n" + pin + FIXTURE_TAIL, encoding="utf-8")
        exe = Path(tmp) / ("pin_keep.exe" if os.name == "nt" else "pin_keep")
        r = subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-pthread", str(src), "-o", str(exe)],
                           capture_output=True, text=True, timeout=120, creationflags=flags)
        if r.returncode:
            print(r.stdout + r.stderr)
            return 1
        failed = 0
        for keep in ("1", "0"):
            env = dict(os.environ)
            env.pop("RX_VK_REPLAY_PIN_KEEP", None)
            if keep == "0":
                env["RX_VK_REPLAY_PIN_KEEP"] = "0"
            r = subprocess.run([str(exe), keep], capture_output=True, text=True, timeout=30, env=env, creationflags=flags)
            print((r.stdout + r.stderr).strip())
            failed += r.returncode != 0
        if failed:
            return 1
    print("PASS: the replay's core kept between a thread's replays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
