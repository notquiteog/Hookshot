"""Rename the engine's names from the game it was first made for (MKW) to NX2PC names, in this checkout's tracked files.

The engine (gpu/, host/, nx2/, the builders) began as an MKW recompilation and kept its names: the renderer's interface
MkwVkHost / MkwVkRenderer, the namespace mkwvk, the game ABI's mkw_host.h, the renderer's thread names "mkw_vk ...".
They are the engine's for every game now, and the engine is NX2PC: the aim is to recompile any Switch 2 game, so engine
code takes general names, and a game's name appears only in its profile, its patch module and its docs (docs/one-engine.md). This renames the code-only ones by whole identifier, so a name that is
one game's own (the profile key "mkw", hos_game_is_mkw, HOS_MKW_INTERVAL, "MKW renders ..." in a comment, the
"(mkw-recomp)" origin tags) is never touched: only the identifiers in the table below change.

Not here: the files players have on disk (the pipeline cache's names), which move with a migration in the code; and
upstream code (gpu/third_party), the changelog and the tested-configurations history.

Idempotent: run it again on a newer main, or on a fork's branch before it merges main, and it renames what is left.

    python -I scripts/rename_nx2.py [--check]    # --check: list what would change, change nothing (exit 1 when something would)
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (whole identifiers: a token of [A-Za-z0-9_] is replaced only when it is one of these, or matches a rule below)
NAMES = {
    "MkwHost": "Nx2pcHost",
    "MkwGuestContext": "Nx2pcGuestContext",
    "MkwGameInfo": "Nx2pcGameInfo",
    "MkwFn": "Nx2pcFn",
    "MKW_HOST_VERSION": "NX2PC_HOST_VERSION",
    "MKW_HOST_H": "NX2PC_HOST_H",
    "MKW_EXPORT": "NX2PC_EXPORT",
    "mkw_recomp_attach": "nx2pc_recomp_attach",
    "mkw_recomp_lookup": "nx2pc_recomp_lookup",
    "PFN_mkw_recomp_attach": "PFN_nx2pc_recomp_attach",
    "PFN_mkw_recomp_lookup": "PFN_nx2pc_recomp_lookup",
    "mkw_image_base": "nx2pc_image_base",
    "mkw_main_build_id": "nx2pc_main_build_id",
    "mkw_glue": "nx2pc_glue",              # (host/mkw_glue.c, and its object's name in the profilers' lists)
    "host_mkw_glue": "host_nx2pc_glue",
    "mkw_host": "nx2pc_host",              # (nx2/rt/mkw_host.h)
    "mkw_info": "nx2pc_info",              # (nx2/build.py's generated mkw_info.c)
}
# (any identifier with these in it: the renderer's names, MkwVkHost, MKWVK_API_VERSION, mkwvk_init, nMkwVkJitter, -DMKWVK_...)
PARTS = [("MkwVk", "Nx2pcVk"), ("MKWVK", "NX2PCVK"), ("mkwvk", "nx2pc")]
# (the renderer's thread names, "mkw_vk recorder", and the profilers' prefix match on them, "mkw_vk": in a string, the
# prefix followed by a space or the string's end; and the profile's thread names in docs, mkw_vk_order and the like)
THREADS = re.compile(r'(?<=["\'])mkw_vk(?=[ "\'])')
STRNCMP = re.compile(r'"mkw_vk",\s*6\b')
THREAD_TOKENS = {"mkw_vk_order": "nx2pc_order", "mkw_vk_capture_copy": "nx2pc_capture_copy"}
FILES = {"host/mkw_glue.c": "host/nx2pc_glue.c", "nx2/rt/mkw_host.h": "nx2/rt/nx2pc_host.h"}
SKIP = ("gpu/third_party/", "CHANGELOG.md", "docs/tested-configurations.md", "scripts/rename_nx2.py", ".release-please")
TEXT = (".c", ".h", ".cpp", ".hpp", ".cs", ".xaml", ".py", ".md", ".json", ".txt", ".ps1", ".sh", ".bat", ".cmake", ".yml",
        ".yaml", ".def", ".rc", ".in", ".glsl", ".comp", ".frag", ".vert", "")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def rename_ident(m):
    t = m.group(0)
    if t in NAMES:
        return NAMES[t]
    if t in THREAD_TOKENS:
        return THREAD_TOKENS[t]
    for old, new in PARTS:
        if old in t:
            t = t.replace(old, new)
    return t


def rename_text(text):
    # (a prefix compared by its length: "mkw_vk", 6 is "nx2pc", 5)
    text = STRNCMP.sub('"nx2pc", 5', text)
    return IDENT.sub(rename_ident, THREADS.sub("nx2pc", text))


def tracked():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, check=True).stdout.decode("utf-8")
    return [f for f in out.split("\0") if f]


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="list what would change, change nothing")
    a = p.parse_args()
    changed = []
    for old, new in FILES.items():
        if os.path.exists(os.path.join(ROOT, old)):
            changed.append("%s -> %s" % (old, new))
            if not a.check:
                subprocess.run(["git", "-C", ROOT, "mv", old, new], check=True)
    for f in tracked():
        if f.startswith(SKIP) or os.path.splitext(f)[1].lower() not in TEXT or not os.path.isfile(os.path.join(ROOT, f)):
            continue
        path = os.path.join(ROOT, f)
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        except UnicodeDecodeError:
            continue
        new = rename_text(text)
        if new != text:
            changed.append(f)
            if not a.check:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
    print("\n".join(changed) if changed else "nothing to rename")
    print("%d file%s %s" % (len(changed), "" if len(changed) == 1 else "s", "would change" if a.check else "changed"),
          file=sys.stderr)
    return 1 if a.check and changed else 0


if __name__ == "__main__":
    sys.exit(main())
