"""The touch screen's states (host/nn_hid.c): no touch, in every form a game reads them with.

The three handlers and their sampling counter are cut out of production unmodified and run against fake guest memory:

  states<1>   GetTouchScreenStates<1>(TouchScreenState<1>*, int count): one state (16 + 0x28 bytes) written, zero but
              its sampling number, and nothing past it; a count below 1 writes nothing; a buffer not wholly the game's
              is not written (Kirby Air Riders' first read, which the lifted SDK aborted on).
  states<16>  the <16> form still writes one state of 16 + 16 * 0x28 bytes.
  state<1>    the single form still writes one state, and the sampling numbers of all three go up together.

python -I -B tests/test_touch_screen_states.py [--cc gcc]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "gcc"]

FIXTURE = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint64_t x[32]; } Ctx;
typedef long long LONG64;
static LONG64 InterlockedIncrement64(volatile LONG64 *p) { return ++*p; }
#define HLE(sym) static void sym(Ctx *c)
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
enum { MEMORY = 2048 };
static unsigned char memory[MEMORY];
#define GP(a) ((void *)(memory + (a)))
#define G64(a) (*(uint64_t *)GP(a))
static void *hos_guest_range(uint64_t a, uint64_t n) { return a < MEMORY && n <= MEMORY - a ? GP(a) : NULL; }
@HANDLERS@
#define CALL(fn, a0, a1) do { Ctx c = {{0}}; c.x[0] = (a0); c.x[1] = (a1); fn(&c); r = c.x[0]; } while (0)
int main(void) {
    uint64_t r;
    memset(memory, 0xa5, sizeof memory);
    CALL(_ZN2nn3hid20GetTouchScreenStatesILm1EEEiPNS0_16TouchScreenStateIXT_EEEi, 64, 4);
    CHECK(r == 1 && G64(64) == 1);
    for (int i = 8; i < 16 + 0x28; i++) CHECK(memory[64 + i] == 0);
    CHECK(memory[64 + 16 + 0x28] == 0xa5);
    memset(memory, 0xa5, sizeof memory);
    CALL(_ZN2nn3hid20GetTouchScreenStatesILm1EEEiPNS0_16TouchScreenStateIXT_EEEi, 64, 0);
    CHECK(r == 0 && memory[64] == 0xa5);
    CALL(_ZN2nn3hid20GetTouchScreenStatesILm1EEEiPNS0_16TouchScreenStateIXT_EEEi, MEMORY - 16, 1);
    CHECK(r == 0 && memory[MEMORY - 16] == 0xa5);
    CALL(_ZN2nn3hid20GetTouchScreenStatesILm16EEEiPNS0_16TouchScreenStateIXT_EEEi, 128, 16);
    CHECK(r == 1 && G64(128) == 2 && memory[128 + 16 + 16 * 0x28] == 0xa5 && memory[128 + 15 + 16 * 0x28] == 0);
    CALL(_ZN2nn3hid19GetTouchScreenStateILm1EEEvPNS0_16TouchScreenStateIXT_EEE, 1536, 0);
    CHECK(G64(1536) == 3);
    printf("PASS: the touch screen's states, no touch, in each form\n");
    return 0;
}
'''


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cc", default=os.environ.get("CC", "gcc"))
    a = p.parse_args()
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    parts = ["static volatile LONG64 touch_sampling;"] + [block(hid, "HLE(_ZN2nn3hid" + n) for n in (
        "20GetTouchScreenStatesILm16EEEiPNS0_16TouchScreenStateIXT_EEEi)",
        "20GetTouchScreenStatesILm1EEEiPNS0_16TouchScreenStateIXT_EEEi)",
        "19GetTouchScreenStateILm1EEEvPNS0_16TouchScreenStateIXT_EEE)")]
    if "static volatile LONG64 touch_sampling;" not in hid:
        raise SystemExit("host/nn_hid.c: the touch screen's sampling counter is not where this check expects it")
    with tempfile.TemporaryDirectory(prefix="touch-states-") as tmp:
        src, exe = Path(tmp, "f.c"), Path(tmp, "f")
        src.write_text(FIXTURE.replace("@HANDLERS@", "\n".join(parts)), encoding="utf-8")
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Werror", "-Wno-unused-function", "-o", str(exe), str(src)],
                       check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
