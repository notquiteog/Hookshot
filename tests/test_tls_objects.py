"""vk_draw.cpp's namespace-scope thread_locals need no constructor or destructor: those are TLS_OBJECTs.

With llvm-mingw every use of a thread_local whose type has a constructor or destructor calls the file's TLS init function
(~2.4% of the replay thread before the file's per-thread objects went behind TLS_OBJECT pointers). This fails when a
namespace-scope thread_local's type is a standard container or holds one (directly or through a struct of this file), so a
new one goes through TLS_OBJECT instead. Function-local static thread_locals are guarded at their own use, not by the file's
init function, and are not checked.

The accessor TLS_OBJECT makes is always inlined, and the first use's allocation is not: with the allocation inlined into
it, clang made dw() a function of its own that saved six registers and, the renderer being a shared object on Linux,
called __tls_get_addr on every one of a draw's ~60 uses. This compiles the macro at -O2 -fPIC with --cxx and checks that a
function using an object several times does not call its accessor and, with clang (the builds' compiler), finds the
thread's TLS block at most once (an ELF target's __tls_get_addr calls).

python -I -B tests/test_tls_objects.py [--source gpu/vk/vk_draw.cpp] [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]
# (three functions using one object, each several times, a call between the uses; a second object used once: the asm of
# each use_ must have no call to obj() or other(), and with clang at most one __tls_get_addr)
USES = r"""
struct Obj { int a, b, c; };
TLS_OBJECT(obj, Obj)
TLS_OBJECT(other, std::vector<int>)
}
void opaque(int);
int use_a() { int r = obj().a; opaque(r); r += obj().b; opaque(r); return r + obj().c; }
int use_b(int k) { for (int i = 0; i < k; i++) obj().a += i, opaque(obj().b); return obj().c; }
size_t use_c() { obj().a = 1; other().push_back(obj().b); return other().size() + (size_t)obj().c; }
"""
# (a member of one of these types gives a struct a destructor)
HEAVY = re.compile(r"std::(vector|unordered_map|map|unordered_set|set|string|deque|list|unique_ptr|shared_ptr|function|array)\b")
DECL = re.compile(r"^(?:static\s+)?thread_local\s+(?:const\s+)?([\w:<>,\s*]+?)\s*\b(\w+)\s*(?:\[[^\]]*\]\s*)*(?:=|;|\{)")


def struct_bodies(text):
    """struct name -> its body, for the structs defined at the start of a line"""
    out = {}
    for m in re.finditer(r"(?m)^struct (\w+)\s*\{", text):
        i, depth = m.end(), 1
        while depth and i < len(text):
            depth += (text[i] == "{") - (text[i] == "}")
            i += 1
        out[m.group(1)] = text[m.end():i]
    return out


def heavy_structs(bodies):
    """the structs that hold a heavy member, directly or through another such struct"""
    heavy = {name for name, body in bodies.items() if HEAVY.search(body)}
    while True:
        more = {name for name, body in bodies.items() if name not in heavy and any(re.search(r"\b%s\b" % h, body) for h in heavy)}
        if not more:
            return heavy
        heavy |= more


def function_asm(asm, name):
    """the lines of function name's body in an assembly listing (from its label to the next function's)"""
    m = re.search(r"(?m)^%s:" % re.escape(name), asm)
    if not m:
        raise SystemExit("no %s in the compiled listing" % name)
    end = re.search(r"(?m)^\s*\.(?:cfi_endproc|seh_endproc)\b|^\.Lfunc_end", asm[m.end():])
    return asm[m.end():m.end() + (end.start() if end else len(asm))]


def check_inlined(text, cxx):
    """the macro's accessor carries always_inline and tls_make noinline; compiled, a use calls neither accessor"""
    m = re.search(r"(?ms)^struct TlsOwned \{.*?^#define TLS_OBJECT\(.*?\n\n", text)
    if not m:
        raise SystemExit("no TlsOwned and TLS_OBJECT block where this test looks")
    block = m.group(0)
    if not re.search(r"\[\[gnu::always_inline\]\]\s+inline\s+__VA_ARGS__&\s+name\(\)", block):
        raise SystemExit("TLS_OBJECT's name() is not [[gnu::always_inline]]: outlined, every use finds the TLS block again")
    if not re.search(r"\[\[gnu::noinline,\s*gnu::cold\]\]\s+T&\s+tls_make\(", block):
        raise SystemExit("tls_make is not [[gnu::noinline, gnu::cold]]: the first use's allocation belongs out of line")
    exe = shutil.which(cxx)
    if not exe:
        raise SystemExit("C++ compiler not found: " + cxx)
    with tempfile.TemporaryDirectory(prefix="hookshot-tls-objects-") as tmp:
        src = Path(tmp) / "tls_uses.cpp"
        src.write_text("#include <cstddef>\n#include <vector>\nnamespace {\n" + block + USES, encoding="utf-8")
        out = Path(tmp) / "tls_uses.s"
        flags = ["-std=c++20", "-O2", "-S", "-fPIC", "-Wall", "-Wextra", "-Werror"]
        r = subprocess.run([exe] + flags + [str(src), "-o", str(out)], capture_output=True, text=True, timeout=120,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if r.returncode:
            raise SystemExit("the TLS_OBJECT block does not compile:\n" + r.stdout + r.stderr)
        asm = out.read_text(encoding="utf-8", errors="replace")
        # (GCC finds the block again after each call whatever the inlining, so the count is clang's: the builds')
        clang = "clang" in subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout
    for fn, mangled in (("use_a", "_Z5use_av"), ("use_b", "_Z5use_bi"), ("use_c", "_Z5use_cv")):
        body = function_asm(asm, mangled)
        calls = re.findall(r"(?m)^\s*call[lq]?\s+\*?(\S+)", body)
        accessor = [c for c in calls if re.search(r"3objEv|5otherEv", c)]
        if accessor:
            raise SystemExit("%s calls the accessor (%s): TLS_OBJECT's name() was not inlined" % (fn, accessor[0]))
        tls = sum("__tls_get_addr" in c for c in calls)
        if clang and tls > 1:
            raise SystemExit("%s finds the TLS block %d times (__tls_get_addr): once is enough" % (fn, tls))
    return len(calls)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "gpu/vk/vk_draw.cpp")
    parser.add_argument("--cxx", default=os.environ.get("CXX", "clang++"), help="GCC/Clang C++ compiler")
    args = parser.parse_args()
    text = args.source.read_text(encoding="utf-8")
    check_inlined(text, args.cxx)
    heavy = heavy_structs(struct_bodies(text))
    bad, light = [], 0
    for n, line in enumerate(text.split("\n"), 1):
        m = DECL.match(line)
        if not m:
            continue
        typ, name = m.group(1).strip(), m.group(2)
        if typ.endswith("*"):
            light += 1
            continue
        base = re.sub(r"<.*", "", typ).strip()
        if HEAVY.search(typ) or base in heavy:
            bad.append("%d: %s (%s)" % (n, name, typ))
        else:
            light += 1
    objects = len(re.findall(r"(?m)^TLS_OBJECT\(", text))
    if objects < 10:
        raise SystemExit("only %d TLS_OBJECTs: the file's per-thread objects are not where this test looks" % objects)
    if bad:
        raise SystemExit("thread_locals with a constructor or destructor (use TLS_OBJECT):\n  " + "\n  ".join(bad))
    print("PASS: %d TLS_OBJECTs, their accessor inlined (%s); %d other namespace-scope thread_locals, none with a constructor "
          "or destructor" % (objects, args.cxx, light))


if __name__ == "__main__":
    main()
