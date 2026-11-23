"""The x64 stack walks in host/mkw_glue.c (the crash report's, HOS_SAMPLE's and HOS_SAMPLE_ALL's) can't fault: each goes
one frame at a time through unwind_step, which checks the stack pointer, and the frame register when the function has
one, against the walked thread's own stack before RtlVirtualUnwind reads through them, and the new stack pointer after
(issue 383: an unchecked walk read 0x438 in ntdll from sample_all_thread and took the game down). The source checks run
everywhere; where the compiler targets Windows the helpers are also compiled on their own (syntax only).

python -I -B tests/test_sampler_stack_walk.py [--cc clang]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from srccut import block  # noqa: E402


def need(ok, what):
    if not ok:
        raise SystemExit("sampler stack walk: " + what)


def sources():
    src = (ROOT / "host/mkw_glue.c").read_text(encoding="utf-8")
    step = block(src, "static int unwind_step(CONTEXT *ctx, StackRange s)")
    # (the unwinder is called in one place, the step, and nowhere else in the file)
    need(src.count("RtlVirtualUnwind(") == 1 and "RtlVirtualUnwind(" in step, "RtlVirtualUnwind called outside unwind_step")
    need(src.count("RtlLookupFunctionEntry(") == 1, "RtlLookupFunctionEntry called outside unwind_step")
    # (the stack pointer is checked before anything is read, the frame register before the unwind, the result after)
    first = step.index("if (!on_stack(s, ctx->Rsp)) return 0;")
    need(first < step.index("RtlLookupFunctionEntry("), "the stack pointer is not checked before the unwind data is read")
    need(step.index("if (frame_reg && !on_stack(s, (&ctx->Rax)[frame_reg])) return 0;") < step.index("RtlVirtualUnwind("),
         "the frame register is not checked before the unwind")
    need("return on_stack(s, ctx->Rsp) || !ctx->Rip;" in step, "the unwound stack pointer is not checked")
    need("if (rf->UnwindData & 1)" in step, "a chained RUNTIME_FUNCTION entry is read as unwind info")
    stack = block(src, "static StackRange thread_stack(HANDLE th)")
    need('"NtQueryInformationThread"' in stack and "tbi.teb->StackLimit" in stack and "tbi.teb->StackBase" in stack,
         "the walked thread's stack is not taken from its TEB")
    # (each walk steps through it, on the right stack)
    walks = (("static LONG WINAPI report_crash(", "const StackRange stack = own_stack();", "unwind_step(&ctx, stack)"),
             ("static DWORD WINAPI sample_thread(void *p)", "thread_stack(th)", "unwind_step(&ctx, stack)"),
             ("static DWORD WINAPI sample_all_thread(void *p)", "thread_stack(th[i])", "unwind_step(&ctx, stack)"))
    for marker, stack_of, call in walks:
        body = block(src, marker)
        need(stack_of in body and call in body, "%s does not walk through unwind_step on its thread's stack" % marker)
    return src


def compiled(cc, src):
    """the helpers compiled on their own, where cc builds for Windows (windows.h and the unwinder)"""
    try:
        target = subprocess.run([cc, "-dumpmachine"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        print("skip the compile: no %s" % cc)
        return
    if "mingw" not in target and "windows" not in target:
        print("skip the compile: %s builds for %s, not Windows" % (cc, target.strip()))
        return
    start = src.index("typedef struct { uint64_t lo, hi; } StackRange;")
    end = src.index("static LONG WINAPI report_crash(")
    unit = "#include <stdint.h>\n#include <windows.h>\n" + src[start:end].replace("#endif", "") + (
        "int walk(CONTEXT *c) { return unwind_step(c, own_stack()) + unwind_step(c, thread_stack(GetCurrentThread())); }\n")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "walk.c"
        f.write_text(unit, encoding="utf-8")
        r = subprocess.run([cc, "-fsyntax-only", "-std=gnu11", "-Wall", "-Werror", str(f)], capture_output=True, text=True)
        need(r.returncode == 0, "the helpers don't compile on their own:\n" + r.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="clang")
    a = ap.parse_args()
    src = sources()
    compiled(a.cc, src)
    print("PASS: the three stack walks step through unwind_step, which stays on the walked thread's stack")


if __name__ == "__main__":
    main()
