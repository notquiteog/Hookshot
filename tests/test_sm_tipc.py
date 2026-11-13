"""sm: answers in TIPC, and hands out a session for each service it is asked for (host/hos_svc.c sm_tipc_request).

On this firmware the SDK's nn::sm client speaks TIPC: the HIPC header's type is 16 + the command id, and the reply is a
result word, after a moved handle for GetServiceHandle (command 1, the service's name in the request's 8 data bytes).
svc 0x21 answered every session with a CMIF reply. That read as a success for RegisterClient, but GetServiceHandle
found no handle in it, and the SDK aborted: Donkey Kong Bananza's nn::streamplay client ended the game there
(nn::streamplay::detail::CreateUserServiceByHipc, then svcBreak). Game-free.

The fixture compiles sm_tipc_request and its counters, cut from the source, over a stub context, and checks:
- GetServiceHandle: the reply's type is the request's, one data word after a special header with one moved handle;
  the handle is a new 0x7Exxxxxx session, a second request gets another; the result is 0; the log names the service;
- RegisterClient and any other command: one data word, result 0;
- svc 0x21 sends sm:'s sessions' TIPC requests here (every session ConnectToNamedPort("sm:") handed out, not only the
  latest), and only those: another service's session, or a handle past the ones told apart, is not sm:'s.

python -I -B tests/test_sm_tipc.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
COUNTERS = "enum { SM_SESSIONS = 4096 };"
MARKS = ("static volatile LONG ipc_next_session, ipc_sm_marks[SM_SESSIONS / 32];",
         "static void sm_session_mark(uint32_t h) {", "static int sm_session_is(uint32_t h) {")
HELPER = "static void sm_tipc_request(Ctx *c, uint8_t *tls, uint32_t w0) {"


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def function(source, marker):
    check(marker in source, "host/hos_svc.c has no '%s'" % marker)
    start = source.index(marker)
    return source[start:start + re.search(r"^}", source[start:], re.M).end()]


FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef long LONG;
static LONG InterlockedIncrement(volatile LONG *p) { return ++*p; }
static LONG InterlockedOr(volatile LONG *p, LONG v) { LONG o = *p; *p |= v; return o; }
typedef struct { uint64_t x[32]; } Ctx;
#define R_OK 0
static char said[4096];
static void hos_log(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    size_t n = strlen(said);
    vsnprintf(said + n, sizeof said - n, fmt, ap);
    va_end(ap);
    strncat(said, "\n", sizeof said - strlen(said) - 1);
}
@COUNTERS@
@MARKS@
@HELPER@

static uint32_t w(const uint8_t *tls, int i) { uint32_t v; memcpy(&v, tls + 4 * i, 4); return v; }
static void request(uint8_t *tls, uint32_t cmd, const char *name) {
    memset(tls, 0xAA, 0x100);
    const uint32_t h0 = 0x10 + cmd, h1 = name ? 2 : 0;
    memcpy(tls, &h0, 4), memcpy(tls + 4, &h1, 4);
    if (name) { char b[8] = {0}; memcpy(b, name, strlen(name)); memcpy(tls + 8, b, 8); }
}

int main(void) {
    static uint8_t tls[0x100];
    Ctx c = {{0}};
    ipc_next_session = 1;   /* (sm: itself was session 1) */
    request(tls, 0, NULL);
    sm_tipc_request(&c, tls, w(tls, 0));
    CHECK(c.x[0] == 0 && w(tls, 0) == 0x10 && w(tls, 1) == 1 && w(tls, 2) == 0);
    request(tls, 1, "strmply");
    sm_tipc_request(&c, tls, w(tls, 0));
    CHECK(c.x[0] == 0 && w(tls, 0) == 0x11);
    CHECK(w(tls, 1) == (1u | 1u << 31));          /* one data word, a special header */
    CHECK(w(tls, 2) == 1u << 5);                   /* one moved handle, nothing copied, no pid */
    const uint32_t first = w(tls, 3);
    CHECK((first & 0xFF000000u) == 0x7E000000u && first != 0x7E000001u);
    CHECK(w(tls, 4) == 0);                         /* the result */
    CHECK(strstr(said, "GetServiceHandle(\"strmply\")"));
    request(tls, 1, "abcdefgh");                   /* (a name of all 8 bytes, unterminated in the request) */
    sm_tipc_request(&c, tls, w(tls, 0));
    CHECK(w(tls, 3) != first && (w(tls, 3) & 0xFF000000u) == 0x7E000000u && w(tls, 4) == 0);
    CHECK(strstr(said, "GetServiceHandle(\"abcdefgh\")"));
    request(tls, 4, NULL);
    sm_tipc_request(&c, tls, w(tls, 0));
    CHECK(w(tls, 0) == 0x14 && w(tls, 1) == 1 && w(tls, 2) == 0);
    /* several sm: sessions: each one stays sm:'s, a service's session is not, nor a handle past those told apart */
    const uint32_t sm1 = 0x7E000000u + 1, sm2 = 0x7E000000u + 40, sm3 = 0x7E000000u + 4095;
    sm_session_mark(sm1), sm_session_mark(sm2), sm_session_mark(sm3);
    CHECK(sm_session_is(sm1) && sm_session_is(sm2) && sm_session_is(sm3));
    CHECK(!sm_session_is(first) && !sm_session_is(0x7E000000u + 41) && !sm_session_is(0x7E000000u + 4096));
    CHECK(!sm_session_is(0xC0FE0001u) && !sm_session_is(0));
    said[0] = 0;
    sm_session_mark(0x7E000000u + 5000);
    CHECK(!sm_session_is(0x7E000000u + 5000) && strstr(said, "past the 4096"));
    puts("ok");
    return 0;
}
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default=os.environ.get("CC", "cc"))
    a = ap.parse_args()
    source = (ROOT / "host" / "hos_svc.c").read_text(encoding="utf-8")
    check(COUNTERS in source, "host/hos_svc.c has no '%s'" % COUNTERS)
    port = function(source, "    case 0x1F: {")
    check('if (!strncmp(name, "sm:", 4)) sm_session_mark(h);' in port,
          "ConnectToNamedPort no longer marks each sm: session")
    send = function(source, "    case 0x21: {")
    check("sm_session_is((uint32_t)c->x[0]) && (w0 & 0xFFFF) >= 0x10" in send and
          "sm_tipc_request(c, tls, w0);" in send, "svc 0x21 does not send sm:'s TIPC requests to sm_tipc_request")
    check(MARKS[0] in source, "host/hos_svc.c has no '%s'" % MARKS[0])
    marks = MARKS[0] + "\n" + "\n".join(function(source, m) for m in MARKS[1:])
    fixture = FIXTURE.replace("@COUNTERS@", COUNTERS).replace("@MARKS@", marks).replace("@HELPER@", function(source, HELPER))
    with tempfile.TemporaryDirectory(prefix="sm-tipc-") as tmp:
        src, exe = Path(tmp, "sm.c"), Path(tmp, "sm")
        src.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Werror", "-o", str(exe), str(src)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0 and r.stdout.strip() == "ok", "the fixture failed: %s%s" % (r.stdout, r.stderr))
    print("PASS: sm: answers TIPC, a session per service asked for, with its name in the log")


if __name__ == "__main__":
    main()
