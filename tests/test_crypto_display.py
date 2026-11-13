"""Random bytes and the display resolution a game asks the system for, against fake guest memory.

host/nn_crypto.c's GenerateCryptographicallyRandomBytes and host/nn_applet.c's GetDefaultDisplayResolution and its change
event are cut out of production unmodified and compiled with a fake memory, log and event table. Before them, a game that
asked got the lift's generic import stub: 0 and nothing written, and for the random bytes the SDK's own code, which asks
the csrng service through sm: and aborts on the empty answer.

What this pins down:
  random    the buffer is filled to its last byte and not past it, two calls give different bytes, a 0-byte ask writes
            nothing.
  display   the width and height are the runtime's output size (hos_output_size), and the change event is made, not
            signalled.

python -I -B tests/test_crypto_display.py [--cc gcc]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_SKIP = {"windows": "the random half uses getrandom: checked on Linux"}

FIXTURE = r'''
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint64_t x[32]; } Ctx;
#define HLE(sym) static void sym(Ctx *c)
static unsigned char memory[1024];
static void *guest_at(uint64_t a) { CHECK(a <= sizeof memory); return memory + a; }
#define GP(a) guest_at(a)
#define G32(a) (*(uint32_t *)guest_at(a))
#define ARG(n) (c->x[n])
static void hos_log(const char *f, ...) { (void)f; }
static int fatal;
static void hos_fatal(Ctx *c, const char *f, ...) { (void)c; (void)f; fatal = 1; }
static uint32_t hos_output_size(int height) { return height ? 1440 : 2560; }
static uint64_t event_made = 0; static int event_signalled;
static void hos_system_event_init(uint64_t key, int autoclear) { CHECK(!autoclear); event_made = key; }
@CRYPTO@
@DISPLAY@
#define CALL(fn, a0, a1) do { Ctx c = {{0}}; c.x[0] = (a0); c.x[1] = (a1); c.x[30] = 0x1234; fn(&c); } while (0)
int main(void) {
    memset(memory, 0xa5, sizeof memory);
    CALL(_ZN2nn6crypto36GenerateCryptographicallyRandomBytesEPvm, 64, 257);
    CHECK(!fatal && memory[64 + 257] == 0xa5 && memory[63] == 0xa5);   /* (exactly the bytes asked for) */
    unsigned char first[257];
    memcpy(first, memory + 64, sizeof first);
    int all_a5 = 1;
    for (int i = 0; i < 257; i++) all_a5 &= first[i] == 0xa5;
    CHECK(!all_a5);
    CALL(_ZN2nn6crypto36GenerateCryptographicallyRandomBytesEPvm, 64, 257);
    CHECK(memcmp(first, memory + 64, sizeof first) != 0);   /* (different bytes each time) */
    memset(memory + 512, 0xa5, 16);
    CALL(_ZN2nn6crypto36GenerateCryptographicallyRandomBytesEPvm, 512, 0);
    CHECK(memory[512] == 0xa5);
    G32(16) = G32(20) = 0xdeadbeef;
    CALL(_ZN2nn2oe27GetDefaultDisplayResolutionEPiS1_, 16, 20);
    CHECK(G32(16) == 2560 && G32(20) == 1440);
    CALL(_ZN2nn2oe38GetDefaultDisplayResolutionChangeEventEPNS_2os11SystemEventE, 96, 0);
    CHECK(event_made == 96 && !event_signalled);
    printf("PASS: random bytes from the system; the display resolution and its change event\n");
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
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    crypto = (ROOT / "host" / "nn_crypto.c").read_text(encoding="utf-8")
    applet = (ROOT / "host" / "nn_applet.c").read_text(encoding="utf-8")
    random_part = crypto[crypto.index("#ifdef _WIN32"):]   # (its includes, the generator and the HLE: all of it after hos.h)
    display = "\n".join(block(applet, "HLE(_ZN2nn2oe" + n) for n in
                        ("27GetDefaultDisplayResolutionEPiS1_)", "38GetDefaultDisplayResolutionChangeEventEPNS_2os11SystemEventE)"))
    if not re.search(r"getrandom\(", random_part):
        raise SystemExit("host/nn_crypto.c: no getrandom, so the check would look at nothing")
    with tempfile.TemporaryDirectory(prefix="crypto-display-") as tmp:
        src, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture.exe"
        src.write_text(FIXTURE.replace("@CRYPTO@", random_part).replace("@DISPLAY@", display), encoding="utf-8")
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(src), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
