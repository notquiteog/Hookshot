"""The host runtime keeps a game's sizes inside the game's memory, and setjmp slots where they were handed out.

From the 2026-11-14 audit (PR-D). Each check cuts the production code out unmodified and runs it against a model:

  gr        host/hos.h's GR(a, n) (hos_guest_need): a range wholly in the guest window gives its host pointer; one that
            is not (past the end, wrapping) stops the run (hos_fatal) instead of handing out a host address.
  random    host/nn_os_sync.c's GenerateRandomBytes: the game's buffer and size through GR; a size past the end stops
            the run with nothing written; 0 bytes writes nothing.
  sites     add_aux (nn_audio.c) and ReadDirectory (nn_fs.c) take the game's buffers through GR.
  setjmp    host/hos_setjmp.c: past 256 nested setjmp owners, the slots already handed out stay where they are (they
            used to be shifted down under the frames that held them, and a longjmp then restored a dead frame's
            registers); the pushes past it get the spare slot, which no longjmp is taken to; the pops unwind to empty.

(GetNpadStates' count: tests/test_input_background.py, case count-bounds.)

python -I -B tests/test_host_guest_ranges.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "gcc"]


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


COMMON = r'''
#include <setjmp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint64_t x[32]; } Ctx;
typedef long LONG;
typedef long long LONG64;
static LONG64 InterlockedAdd64(volatile LONG64 *p, LONG64 v) { return *p += v; }
#define HLE(sym) static void sym(Ctx *c)
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
enum { MEMORY = 4096 };
static unsigned char memory[MEMORY];
#define HOS_SPACE_END MEMORY
#define GP(a) ((void *)(memory + (a)))
static inline void *hos_guest_range(uint64_t a, uint64_t n) {
    return a < (uint64_t)HOS_SPACE_END && n <= (uint64_t)HOS_SPACE_END - a ? GP(a) : (void *)0;
}
static jmp_buf fatal_jump;
static int fatals;
static void hos_fatal(Ctx *c, const char *fmt, ...) { (void)c; (void)fmt; fatals++; longjmp(fatal_jump, 1); }
static void hos_log(const char *fmt, ...) { (void)fmt; }
'''

GR_MAIN = r'''
int main(void) {
    Ctx cc = {{0}}, *c = &cc;
    CHECK(GR(0, MEMORY) == memory && GR(MEMORY - 8, 8) == memory + MEMORY - 8 && GR(16, 0) == memory + 16);
    if (!setjmp(fatal_jump)) { GR(MEMORY - 8, 9); CHECK(!"past the end"); }
    if (!setjmp(fatal_jump)) { GR(16, 0xFFFFFFFFFFFFFFF8ULL); CHECK(!"a size that wraps"); }
    if (!setjmp(fatal_jump)) { GR(0x8000000000ULL, 1); CHECK(!"outside the window"); }
    CHECK(fatals == 3);
    memset(memory, 0xa5, sizeof memory);
    Ctx r = {{0}};
    r.x[0] = 64; r.x[1] = 256;
    _ZN2nn2os19GenerateRandomBytesEPvm(&r);
    int same = 1;
    for (int i = 0; i < 256; i++) same &= memory[64 + i] == 0xa5;
    CHECK(!same && memory[64 + 256] == 0xa5 && memory[63] == 0xa5);
    memset(memory, 0xa5, sizeof memory);
    r.x[0] = MEMORY - 16; r.x[1] = 0x7fffffff;
    if (!setjmp(fatal_jump)) { _ZN2nn2os19GenerateRandomBytesEPvm(&r); CHECK(!"random bytes past the end"); }
    CHECK(fatals == 4 && memory[MEMORY - 16] == 0xa5);
    r.x[0] = 0; r.x[1] = 0;
    _ZN2nn2os19GenerateRandomBytesEPvm(&r);   /* (0 bytes at 0: nothing asked, nothing checked) */
    printf("PASS: GR and GenerateRandomBytes keep the game's sizes in its memory\n");
    return 0;
}
'''

SJ_MAIN = r'''
int main(void) {
    Ctx cc = {{0}};
    void **bufs[300];
    for (int i = 0; i < 300; i++) {
        bufs[i] = recomp_sj_push(&cc, 1000 + i, 0, 0, 0);
        memcpy(bufs[i], &i, sizeof i);   /* (what recomp_sj_setjmp would have saved there: this push's own) */
    }
    for (int i = 0; i < DEPTH; i++) {   /* (every slot handed out still holds its own push: none moved) */
        SjSlot *s = (SjSlot *)((char *)bufs[i] - offsetof(SjSlot, buf));
        int saved;
        memcpy(&saved, bufs[i], sizeof saved);
        CHECK(saved == i && s->rets[0] == (uint64_t)(1000 + i));
    }
    CHECK(stack->depth == DEPTH && stack->extra == 300 - DEPTH && bufs[DEPTH] == stack->spare.buf);
    for (int i = 299; i >= 0; i--) recomp_sj_pop(bufs[i]);
    CHECK(stack->depth == 0 && stack->extra == 0);
    printf("PASS: setjmp slots stay where they were handed out past %d owners\n", DEPTH);
    return 0;
}
'''


def build_run(cc, tmp, name, source):
    src, exe = Path(tmp, name + ".c"), Path(tmp, name)
    src.write_text(source, encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-Wall", "-Werror", "-Wno-unused-function", "-Wno-unused-variable", "-o", str(exe),
                    str(src)], check=True)
    subprocess.run([str(exe)], check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cc", default=os.environ.get("CC", "gcc"))
    a = p.parse_args()
    hos_h = read("host/hos.h")
    need = block(hos_h, "static inline void *hos_guest_need(")
    gr = re.search(r"^#define GR\(a, n\) .*$", hos_h, re.M).group(0)
    rnd = block(read("host/nn_os_sync.c"), "HLE(_ZN2nn2os19GenerateRandomBytesEPvm)")
    check("GR(" in rnd, "GenerateRandomBytes does not take the game's buffer through GR")
    aux = block(read("host/nn_audio.c"), "static void add_aux(Ctx *c)")
    check(aux.count("GR(ARG(3), bytes)") == 1 and aux.count("GR(ARG(4), bytes)") == 1,
          "add_aux does not take both aux buffers through GR")
    rd = block(read("host/nn_fs.c"), "HLE(_ZN2nn2fs13ReadDirectoryEPlPNS0_14DirectoryEntryENS0_15DirectoryHandleEl)")
    check(rd.count("GR(e, 0x310)") == 2, "ReadDirectory does not take each entry through GR")
    sj = read("host/hos_setjmp.c")
    sj_part = "\n".join([re.search(r"^#define DEPTH .*$", sj, re.M).group(0),
                         re.search(r"^typedef struct \{ uint64_t rets\[4\].*$", sj, re.M).group(0),
                         sj[sj.index("typedef struct { SjSlot slot[DEPTH]"):sj.index("static _Thread_local SjStack *stack;")],
                         "static SjStack *stack;",
                         block(sj, "void **recomp_sj_push("), block(sj, "void recomp_sj_pop(")])
    with tempfile.TemporaryDirectory(prefix="guest-ranges-") as tmp:
        build_run(a.cc, tmp, "gr", COMMON + need + "\n" + gr + "\n" + rnd + GR_MAIN)
        build_run(a.cc, tmp, "sj", COMMON + sj_part + SJ_MAIN)


if __name__ == "__main__":
    main()
