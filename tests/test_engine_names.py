"""Engine code takes general names (docs/one-engine.md rule 7): the names the engine kept from the game it was first made for
(MkwVkHost, mkwvk, mkw_host.h, the "mkw_vk" threads) were renamed to NX2PC names by scripts/rename_nx2.py. This holds the
tree to it: the script's --check finds nothing left to rename. And the script itself: it renames those names and only those,
never one game's own (the profile key "mkw", hos_game_is_mkw, HOS_MKW_INTERVAL, "MKW renders ..." in a comment, the
"(mkw-recomp)" origin tags, the pipeline cache's old file names that the migration reads), and a prefix compared by its
length keeps the right length. Game-free.

    python -I -B tests/test_engine_names.py
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rename_nx2", ROOT / "scripts" / "rename_nx2.py")
rename = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rename)

failures = []


def same(got, want, what):
    if got != want:
        failures.append("%s:\n  got  %r\n  want %r" % (what, got, want))


def main():
    # (the renamed names)
    same(rename.rename_text("namespace mkwvk { struct MkwVkHost; }"), "namespace nx2pc { struct Nx2pcVkHost; }", "the renderer's names")
    same(rename.rename_text("#define MKWVK_API_VERSION 22"), "#define NX2PCVK_API_VERSION 22", "the interface's version")
    same(rename.rename_text('GetProcAddress(m, "mkwvk_init")'), 'GetProcAddress(m, "nx2pc_init")', "a symbol looked up by name")
    same(rename.rename_text('#include "mkw_host.h"\nMKW_EXPORT MkwFn mkw_recomp_lookup(uint64_t a);'),
         '#include "nx2pc_host.h"\nNX2PC_EXPORT Nx2pcFn nx2pc_recomp_lookup(uint64_t a);', "the game ABI's names")
    same(rename.rename_text('SetThreadDescription(GetCurrentThread(), L"mkw_vk replay");'),
         'SetThreadDescription(GetCurrentThread(), L"nx2pc replay");', "a thread's name")
    same(rename.rename_text('if (!strncmp(desc, "mkw_vk", 6)) keep();'), 'if (!strncmp(desc, "nx2pc", 5)) keep();',
         "a prefix compared by its length")
    same(rename.rename_text("cc -DMKWVK_INCLUDES=2 host/mkw_glue.c"), "cc -DNX2PCVK_INCLUDES=2 host/nx2pc_glue.c", "build flags and files")
    # (one game's own names, and history: untouched)
    kept = ('key="mkw", int hos_game_is_mkw(void); getenv("HOS_MKW_INTERVAL"); volatile uint64_t hos_mkw_pacer;\n'
            '// MKW renders its scene at a dynamic size (mkw-recomp) EvilOOT\n'
            'kOldMainFile = "mkw_vk_pipelines.bin"; kOldPlayPrefix = "mkw_vk_pipelines_play_"; oot_patches; Hookshot-mkw')
    same(rename.rename_text(kept), kept, "one game's own names and history")
    # (the tree: nothing left to rename)
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "rename_nx2.py"), "--check"], capture_output=True, text=True)
    if r.returncode != 0:
        failures.append("scripts/rename_nx2.py --check finds names to rename (run it, or use the NX2PC names):\n" + r.stdout)
    if failures:
        print("\n".join("FAIL: " + f for f in failures))
        sys.exit(1)
    print("PASS: the engine's names are NX2PC's; the rename leaves one game's own names alone")


if __name__ == "__main__":
    main()
