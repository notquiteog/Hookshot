"""The physics' two water managers keep their 60-Hz steps above a 60 frame-rate cap (nx2/oot_patches.py WHOLE_SITES).

f_83895f20 (InteractiveWaterMgr) and f_838a2660 (ResponsiveWaterMgr) divide the frame's time by 1/60 s, cut the
quotient to whole steps, keep it, and queue min(max(n, 0), 3) fixed steps; with n under 1 the surfaces (water, ice,
sand) are not simulated. Above 60 fps every frame cut to 0 and they stood still. The production patch is applied to
authored updates of that shape and compiled: each manager keeps its own fraction (by its object, x19), 240 Hz and
120 Hz give 60 steps a second, the clamp and the path without frame time stay the game's. Without the patch the same
executable fails the 240-Hz check. After NX2navi (chrg6) commit 750034b. No game files or lifted function body are used.

python -I -B tests/test_water_surface_steps.py [--cc gcc]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

CUT = "    c->x[8]=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,1,3,c->fpcr,&c->fpsr);\n"
UPDATE = ('void %s(Ctx *__restrict A64_NOESC c) {\n' + CUT +
          '    c->x[1] = c->x[8];   /* (kept: under 1, nothing is simulated) */\n'
          '    const int32_t steps = (int32_t)c->x[8];\n'
          '    c->x[0] = (uint32_t)(steps < 0 ? 0 : steps > 3 ? 3 : steps);\n'
          '    if ((int32_t)c->x[1] < 1) c->x[0] = 0;\n'
          '}\n')
LIFTED = ('#include "a64.h"\n' + UPDATE % "f_83895f20" + UPDATE % "f_838a2660" +
          'void f_90000000(Ctx *__restrict A64_NOESC c) {\n' + CUT + '}\n')
CONTEXT = """#pragma once
#define A64_NOESC
typedef struct {
    uint64_t x[32], vreg[32][2];
    uint32_t fpcr, fpsr;
} Ctx;
"""
FIXTURE = r'''#define _CRT_SECURE_NO_WARNINGS
#include "frame_whole.h"
#include <stdio.h>
#include "a64.h"

static FrameWhole fractions;
static int carry = 1;
static int failures;
#define CHECK(test, what) do { if (!(test)) { printf("FAIL: %s\n", what); failures++; } } while (0)

uint32_t hos_frame_whole(uint64_t at, uint32_t amount_bits) {
    return frame_whole(&fractions, at, amount_bits, carry);
}
uint64_t recomp_fp_to_int(uint64_t bits, int in_width, int out_width, int sign,
                         int mode, uint32_t fpcr, uint32_t *fpsr) {
    float amount;
    uint32_t low = (uint32_t)bits;
    memcpy(&amount, &low, sizeof amount);
    (void)in_width; (void)out_width; (void)sign; (void)mode; (void)fpcr; (void)fpsr;
    return (uint64_t)(int64_t)(int32_t)amount;
}
@UPDATE@

typedef void (*Update)(Ctx *);
static uint32_t step(Update f, Ctx *ctx, uint64_t manager, float amount) {
    uint32_t bits;
    memcpy(&bits, &amount, sizeof bits);
    ctx->x[19] = manager;
    ctx->vreg[0][0] = bits;
    f(ctx);
    return (uint32_t)ctx->x[0];
}
static void reset(void) { memset(&fractions, 0, sizeof fractions); }

int main(void) {
    Ctx ctx = {0};
    const uint64_t a = 0x10000, b = 0x20000;
    uint32_t first = 0, second = 0;
    for (int frame = 0; frame < 240; frame++) {
        first += step(f_83895f20, &ctx, a, 0.25f);
        second += step(f_838a2660, &ctx, b, 0.25f);
    }
    CHECK(first == 60, "240-Hz InteractiveWaterMgr must run 60 steps, not zero or 240");
    CHECK(second == 60, "240-Hz ResponsiveWaterMgr must keep its own fraction and run 60");
    reset(); first = 0;
    for (int frame = 0; frame < 120; frame++) first += step(f_838a2660, &ctx, a, 0.5f);
    CHECK(first == 60, "120-Hz manager must run 60 steps");
    reset(); first = 0;
    for (int frame = 0; frame < 144; frame++) first += step(f_83895f20, &ctx, a, 60.0f / 144.0f);
    CHECK(first == 60 || first == 59, "144-Hz manager runs 60 steps, give or take the float's last one");
    reset(); first = 0;
    for (int frame = 0; frame < 30; frame++) first += step(f_83895f20, &ctx, a, 2.0f);
    CHECK(first == 60, "30 fps: two steps a frame, as the game runs them");
    reset();
    CHECK(step(f_83895f20, &ctx, a, 0.75f) == 0 && step(f_838a2660, &ctx, b, 0.25f) == 0,
          "two managers must not share a remainder");
    CHECK(step(f_83895f20, &ctx, a, 0.25f) == 1 && step(f_838a2660, &ctx, b, 0.25f) == 0,
          "one manager stepping must not take the other's fraction");
    reset();
    CHECK(step(f_83895f20, &ctx, a, 4.75f) == 3, "the game's upper clamp stays three");
    CHECK(step(f_83895f20, &ctx, a, -1.0f) == 0 && step(f_83895f20, &ctx, a, 0.0f) == 0, "no time, no steps");
    carry = 0; reset(); first = 0;
    for (int frame = 0; frame < 60; frame++) first += step(f_83895f20, &ctx, a, 1.0f);
    CHECK(first == 60, "the ordinary 60-Hz path is unchanged");
    CHECK(step(f_838a2660, &ctx, a, 0.25f) == 0 && step(f_838a2660, &ctx, a, 1.75f) == 1,
          "without frame time the game's cut remains");
    if (!failures) puts("PASS: water surface steps");
    return failures != 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    patched, count = oot_patches.patch_whole_frames(LIFTED)
    assert count == 2 and patched.count("hos_frame_whole(c->x[19], (uint32_t)c->vreg[0][0]);") == 2, patched
    assert patched.count(CUT) == 1   # (the unrelated function is left alone)
    assert oot_patches.patch_whole_frames(patched) == (patched, 0)
    other = LIFTED.replace("c->x[8]=recomp_fp_to_int", "c->x[9]=recomp_fp_to_int")   # (another game version's code)
    assert oot_patches.patch_whole_frames(other) == (other, 0)
    with tempfile.TemporaryDirectory(prefix="water-surface-steps-") as directory:
        directory = Path(directory)
        (directory / "a64.h").write_text(CONTEXT, encoding="utf-8")
        source, binary = directory / "fixture.c", directory / "fixture.exe"
        command = [args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"),
                   str(source), "-o", str(binary)]
        source.write_text(FIXTURE.replace("@UPDATE@", patched), encoding="utf-8")
        subprocess.run(command, check=True)
        subprocess.run([str(binary)], check=True, timeout=30)
        # (the negative control compiles, then fails the same checks)
        source.write_text(FIXTURE.replace("@UPDATE@", LIFTED), encoding="utf-8")
        subprocess.run(command, check=True)
        native = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
        if native.returncode == 0 or "240-Hz InteractiveWaterMgr" not in native.stdout:
            raise SystemExit("FAIL: the game's own cut did not fail the 240-Hz check")
        print("PASS: the game's own cut rejected by the same 240-Hz checks")


if __name__ == "__main__":
    main()
