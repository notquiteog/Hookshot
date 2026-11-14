"""Idle graphics pipelines are given back while video memory is short, and built again when a draw comes back to them
(gpu/vk/vk_draw.cpp release_pass, rebuild_if_released; no game/GPU).

Nothing let a pipeline go: every pipeline a run drew, or made ahead for a draw that never came (kept_ready), held the
driver's memory until the process ended. While the device-local memory in use is over RX_VK_PIPE_RELEASE_PCT percent of the
budget, every 5 s the pass takes up to 256 entries no draw used for RX_VK_PIPE_RELEASE_IDLE_S seconds, oldest first, marks
them released with their pipeline handed to the timeline (pipeline_retire), and destroys kept_ready's at once (never bound).
A lookup of a released entry queues the same full build again, once. The functions are compiled as they are in vk_draw.cpp
over a stand-in table, budget, job queue and builder:
- under pressure, the oldest idle entries go first, at most 256, and kept_ready is emptied and destroyed;
- an entry drawn recently, one still building, one released already and one with no pipeline stay;
- with memory not short nothing goes, nor more often than every 5 s;
- the next pass reports the memory in use when the batch went and now;
- a released entry's next lookup queues one build from the cache and is ready with a new pipeline after it; a second
  lookup queues nothing;
- RX_VK_PIPE_RELEASE=0 keeps them all.

python -I -B tests/test_pipeline_release.py [--cxx g++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
using VkPipeline = uint64_t;
using VkPrimitiveTopology = int;
#define VK_NULL_HANDLE 0
struct Program { uint64_t key; };
struct NvnState {};
struct Targets {};
struct { int device; } dev;
struct ParLock { ParLock() {} };
uint64_t used_mb = 50, budget_mb = 100;
bool vram_usage_now(uint64_t* used, uint64_t* budget) { *used = used_mb << 20, *budget = budget_mb << 20; return true; }
std::vector<std::string> logs;
void logf(const char* f, ...) {
    char b[1024];
    va_list a;
    va_start(a, f);
    vsnprintf(b, sizeof b, f, a);
    va_end(a);
    logs.push_back(b);
}
std::multiset<VkPipeline> destroyed, retired;
void vkDestroyPipeline(int, VkPipeline p, void*) { destroyed.insert(p); }
std::atomic<int64_t> st_pipes_released{0};
void pipeline_retire(VkPipeline p) { retired.insert(p), st_pipes_released++; }
void fast_reap() {}
std::vector<std::function<void()>> queued;
void jobs_push(std::function<void()> f, bool, std::atomic<bool>*, std::function<void()>) { queued.push_back(std::move(f)); }
VkPipeline next_built = 5000;
VkPipeline build_graphics(const Program&, const NvnState&, const Targets&, VkPrimitiveTopology) { return next_built++; }
@ENTRY@
std::unordered_map<uint64_t, std::unique_ptr<PipeEntry>> pipelines;
std::atomic<uint32_t> pipe_clock{1};
std::mutex kept_ready_mu;
std::unordered_map<uint64_t, VkPipeline> kept_ready;
std::atomic<size_t> kept_ready_n{0};
@CODE@
#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); return 1; } } while (0)
PipeEntry* add(uint64_t key, VkPipeline pl, uint32_t drawn, bool ready = true) {
    auto e = std::make_unique<PipeEntry>();
    e->pipeline = pl, e->drawn = drawn, e->ready = ready;
    PipeEntry* p = e.get();
    pipelines.emplace(key, std::move(e));
    return p;
}
int main(int argc, char**) {
    if (argc > 1) {   // (RX_VK_PIPE_RELEASE=0)
        add(1, 101, 0);
        used_mb = 99;
        release_pass(1000);
        CHECK(retired.empty() && !pipelines[1]->released);
        std::puts("PASS: RX_VK_PIPE_RELEASE=0 keeps every pipeline");
        return 0;
    }
    for (uint64_t k = 0; k < 300; k++) add(1000 + k, 10000 + k, (uint32_t)(10 + k));   // (idle, drawn at 10..309)
    PipeEntry* recent = add(1, 101, 990);       // (drawn 10 s ago)
    PipeEntry* building = add(2, 0, 0, false);  // (not ready: a job owns it)
    PipeEntry* failed = add(3, 0, 0);           // (ready with no pipeline: failed)
    PipeEntry* gone = add(4, 104, 0);
    gone->released = true, gone->ready = false, gone->pipeline = 0;
    kept_ready[77] = 777, kept_ready[78] = 778, kept_ready_n = 2;
    used_mb = 50;
    release_pass(1000);   // (memory not short)
    CHECK(retired.empty() && destroyed.empty() && kept_ready.size() == 2);
    used_mb = 90;
    release_pass(1003);   // (under 5 s since the last look)
    CHECK(retired.empty());
    release_pass(1005);
    CHECK(retired.size() == 256);   // (at most 256 a pass)
    for (uint64_t k = 0; k < 256; k++)
        CHECK(retired.count(10000 + k) == 1 && pipelines[1000 + k]->released && !pipelines[1000 + k]->ready &&
              !pipelines[1000 + k]->pipeline);   // (the oldest first)
    CHECK(!pipelines[1000 + 256]->released);   // (the younger ones wait for the next pass)
    CHECK(!recent->released && recent->pipeline == 101 && !building->released && !failed->released);
    CHECK(destroyed.count(777) == 1 && destroyed.count(778) == 1 && kept_ready.empty() && kept_ready_n == 0);
    used_mb = 80;
    release_pass(1010);   // (no longer short: the report of the last batch, nothing more goes)
    CHECK(retired.size() == 256);
    bool reported = false;
    for (const auto& l : logs) reported |= l.find("90 MB when the last batch of idle pipelines went, 80 MB now") != std::string::npos;
    CHECK(reported);
    // (a draw comes back to a released entry: one build, from the cache)
    PipeEntry* back = pipelines[1000].get();
    Program p{1};
    NvnState s;
    Targets at;
    CHECK(rebuild_if_released(back, p, s, at, 0) == back && queued.size() == 1 && !back->released && !back->ready);
    CHECK(rebuild_if_released(back, p, s, at, 0) == back && queued.size() == 1);   // (once)
    queued[0]();
    CHECK(back->ready && back->pipeline == 5000 && st_pipes_rebuilt == 1);
    CHECK(rebuild_if_released(recent, p, s, at, 0) == recent && queued.size() == 1);   // (never released: nothing)
    std::puts("PASS: idle pipelines go while memory is short, oldest first, and a draw builds one again once");
    return 0;
}
"""


def between(text, start, end):
    a = text.index(start)
    return text[a:text.index(end, a)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    entry = between(draw, "struct PipeEntry {", "\n};\n") + "\n};\n"
    code = (between(draw, "std::atomic<int64_t> st_pipes_rebuilt{0};", "\n/// (hookshot) Fast-linked pipelines the full build replaced.")
            + "\n" + between(draw, "/// now: the second of pipe_clock (pipelines_release_tick)\nvoid release_pass(uint32_t now) {",
                             "\n/// part: -1 the whole pipeline"))
    # (the draw stamps the entry; the replay calls the pass at each present, under replay_mu)
    if "if (pe->drawn.load(std::memory_order_relaxed) != now) pe->drawn.store(now, std::memory_order_relaxed);" not in draw:
        raise SystemExit("FAIL: a draw does not stamp the pipeline it uses")
    gp = between(draw, "PipeEntry* graphics_pipeline(", "\n}\n")
    if "return rebuild_if_released(f.pe, p, s, at, topo);" not in gp or "rebuild_if_released(e, p, s, at, topo);" not in gp:
        raise SystemExit("FAIL: a lookup of a released entry does not build it again")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    present = between(replay, "        log_frame_stats();\n", "\n    }\n")
    if "pipelines_release_tick();" not in present:
        raise SystemExit("FAIL: the pass does not run at the present, under replay_mu")
    with tempfile.TemporaryDirectory(prefix="pipeline-release-") as tmp:
        tmp = Path(tmp)
        (tmp / "t.cpp").write_text(FIXTURE.replace("@ENTRY@", entry).replace("@CODE@", code), encoding="utf-8")
        exe = tmp / "pipeline-release"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Wno-unused-parameter", str(tmp / "t.cpp"), "-o", str(exe)],
                       check=True)
        for extra, env in (([], {}), (["off"], {"RX_VK_PIPE_RELEASE": "0"})):
            r = subprocess.run([str(exe)] + extra, capture_output=True, text=True, timeout=30, env=dict(os.environ, **env))
            print(r.stdout, end="")
            if r.returncode:
                raise SystemExit("FAIL: release_pass / rebuild_if_released")


if __name__ == "__main__":
    main()
