"""A memory pool the game initializes again without finalizing it first is finalized first (host/nvn_native.c).

nvnMemoryPoolInitialize cleared the pool object and made a new pool in it, so what Finalize undoes was left behind with
nothing naming it: a physical pool's storage stayed tracked for write watch and imported by the renderer
(hos_gpu_track, hos_gpu_pools), the button prompts kept writing there, and a virtual pool's page table stayed on the
list. Initialize now runs Finalize's work (pool_finalize) when the object still holds a live pool, as nvnTextureInitialize
does for a texture, and logs it (the first four, then at each doubling). After NX2navi (chrg6) commit 6e3dcf6.

The fixture is built from the actual pool_finalize, nvnMemoryPoolInitialize and nvnMemoryPoolFinalize, with the tracking,
the prompts, the renderer and the page tables as counting stubs. The same checks run on Initialize without its re-init
block, and must fail there.

python -I -B tests/test_nvn_pool_reinit.py [--cc clang] [--source host/nvn_native.c]
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    """The source text of the function starting at marker, braces balanced"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint64_t x[32]; } Ctx;
typedef long LONG;
typedef struct { uint32_t magic, flags; uint64_t mem, size, gpu; } nvn_pool;
typedef struct { void *dev; uint64_t mem, size; uint32_t flags; } nvn_pool_builder;
struct nvn_vmap { uint64_t gpu, size, *page; uint32_t *run; struct nvn_vmap *next; };
#define P(i) ((void *)(uintptr_t)c->x[i])
#define U32(i) ((uint32_t)c->x[i])
#define U64(i) (c->x[i])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define NV(name) static void n_##name(Ctx *c, void *u_)
#define NVN_MAGIC(a, b, c, d) ((uint32_t)(a) | (uint32_t)(b) << 8 | (uint32_t)(c) << 16 | (uint32_t)(d) << 24)
#define NVN_MEMORY_POOL_FLAGS_VIRTUAL 0x8
#define VPAGE 0x10000ull
#define VBASE 0x10000000000ull
#define OLOG(...) ((void)0)
#define AcquireSRWLockExclusive(l) ((void)(l))
#define ReleaseSRWLockExclusive(l) ((void)(l))
#define InterlockedIncrement(p) (++*(p))
static int vmap_lock, logs;
static LONG vmap_gen;
static uint64_t next_vbase = VBASE;
static struct nvn_vmap *vmaps, *dead_vmaps;
static void hos_log(const char *fmt, ...) { (void)fmt; logs++; }
static void die(const char *fmt, ...) { printf("die: %s\n", fmt); exit(9); }
static void gw(uint64_t a, uint64_t n) { (void)a; (void)n; }
/* (the storage's write-watch count, by start: hos_gpu_track counts by range) */
static int tracked[4];
static int slot(uint64_t a) { return (int)(a >> 20) & 3; }
static void hos_gpu_track(uint64_t a, uint64_t n, int on) { (void)n; tracked[slot(a)] += on ? 1 : -1; }
static int created, prompts_on[4], vmap_changes;
static void rx_nvn_pool_created(uint64_t a, uint64_t n) { (void)a; (void)n; created++; }
static void rx_nvn_vmap_changing(uint64_t a, uint64_t n) { (void)a; (void)n; vmap_changes++; }
void hos_prompts_pool(uint64_t mem, uint64_t size) { (void)size; prompts_on[slot(mem)]++; }
void hos_prompts_pool_gone(uint64_t mem) { prompts_on[slot(mem)]--; }
static struct nvn_vmap *pool_vmap(const nvn_pool *o) {
    if (!(o->flags & NVN_MEMORY_POOL_FLAGS_VIRTUAL) || o->gpu < VBASE) return NULL;
    for (struct nvn_vmap *m = vmaps; m; m = m->next)
        if (m->gpu == o->gpu) return m;
    return NULL;
}
@SOURCE@
static int fails;
#define CHECK(t, what) do { if (!(t)) { printf("FAIL: %s\n", what); fails++; } } while (0)
static void init(nvn_pool *o, uint64_t mem, uint64_t size, uint32_t flags) {
    nvn_pool_builder b = {0, mem, size, flags};
    Ctx c = {{0}};
    c.x[0] = (uint64_t)(uintptr_t)o, c.x[1] = (uint64_t)(uintptr_t)&b, c.x[30] = 0x80001234;
    n_nvnMemoryPoolInitialize(&c, 0);
}
static void finalize(nvn_pool *o) {
    Ctx c = {{0}};
    c.x[0] = (uint64_t)(uintptr_t)o;
    n_nvnMemoryPoolFinalize(&c, 0);
}
static int listed(void) { int n = 0; for (struct nvn_vmap *m = vmaps; m; m = m->next) n++; return n; }
int main(void) {
    nvn_pool p;
    memset(&p, 0, sizeof p);
    init(&p, 0x100000, 0x10000, 0);
    CHECK(tracked[1] == 1 && prompts_on[1] == 1 && logs == 0, "a first initialize tracks its storage once, and says nothing");
    init(&p, 0x100000, 0x10000, 0);
    CHECK(tracked[1] == 1, "the same storage initialized again is tracked once, not twice");
    CHECK(prompts_on[1] == 1, "the prompts are told of the old pool's end before the new one");
    CHECK(logs == 1, "the re-initialize is logged");
    init(&p, 0x200000, 0x10000, 0);
    CHECK(tracked[1] == 0 && tracked[2] == 1, "a pool initialized over another's object leaves no tracking of the old storage");
    CHECK(prompts_on[1] == 0 && prompts_on[2] == 1, "nor the prompts' registration of it");
    finalize(&p);
    CHECK(tracked[2] == 0 && prompts_on[2] == 0, "Finalize still undoes all of it");
    const int before = logs;
    init(&p, 0x300000, 0x10000, 0);
    CHECK(logs == before && tracked[3] == 1, "a pool finalized before is initialized as a new one, with no log");
    finalize(&p);

    nvn_pool v;
    memset(&v, 0, sizeof v);
    init(&v, 0, 4 * VPAGE, NVN_MEMORY_POOL_FLAGS_VIRTUAL);
    CHECK(listed() == 1, "a virtual pool's page table is listed");
    init(&v, 0, 4 * VPAGE, NVN_MEMORY_POOL_FLAGS_VIRTUAL);
    CHECK(listed() == 1, "a virtual pool initialized again leaves its old page table off the list");
    CHECK(dead_vmaps != NULL, "the old page table is kept for a lookup that may still hold it, as Finalize keeps it");
    finalize(&v);
    CHECK(listed() == 0, "Finalize removes the new one");

    logs = 0;
    nvn_pool q;
    memset(&q, 0, sizeof q);
    init(&q, 0x100000, 0x10000, 0);
    for (int i = 0; i < 40; i++) init(&q, 0x100000, 0x10000, 0);
    /* (three re-initializes before these: the 4th, then the 8th, 16th and 32nd are logged of the 40) */
    CHECK(logs == 4, "logged the first four times, then at each doubling");
    finalize(&q);
    CHECK(tracked[1] == 0, "40 re-initializes and a finalize leave nothing tracked");
    if (!fails) puts("PASS: a memory pool initialized again is finalized first");
    return fails != 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="clang")
    p.add_argument("--source", default=str(ROOT / "host" / "nvn_native.c"), type=Path)
    a = p.parse_args()
    src = a.source.read_text(encoding="utf-8")
    finalize = block(src, "static void pool_finalize(nvn_pool *o)")
    counter = re.search(r"static volatile LONG pool_reinits;\n", src)
    assert counter, "the re-initialize counter is gone"
    init = block(src, "NV(nvnMemoryPoolInitialize)")
    fin = block(src, "static int no_pool(Ctx *c, const char *what)") + "\n" + block(src, "NV(nvnMemoryPoolFinalize)")
    assert "pool_finalize(" in fin, "nvnMemoryPoolFinalize no longer goes through pool_finalize"
    reinit = re.search(r"    if \(o->magic == NVN_MAGIC\('P', 'O', 'O', 'L'\)\) \{.*?\n    \}\n", init, re.S)
    assert reinit and "pool_finalize(o);" in reinit.group(0), "Initialize does not finalize a live pool first"
    with tempfile.TemporaryDirectory(prefix="nvn-pool-reinit-") as tmp:
        def run(initialize):
            c, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture"
            body = "static volatile LONG pool_reinits;\n" + finalize + "\n" + initialize + "\n" + fin + "\n"
            c.write_text(FIXTURE.replace("@SOURCE@", body), encoding="utf-8")
            subprocess.run([a.cc, "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                            "-Wno-unused-variable", "-Wno-unused-but-set-variable", str(c), "-o", str(exe)], check=True)
            return subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        r = run(init)
        print(r.stdout, end="")
        if r.returncode:
            raise SystemExit("FAIL: nvnMemoryPoolInitialize (exit %d)" % r.returncode)
        r = run(init.replace(reinit.group(0), ""))
        if r.returncode == 0 or "tracked once, not twice" not in r.stdout:
            raise SystemExit("FAIL: Initialize without the re-init block passed the same checks:\n" + r.stdout)
        print("PASS: Initialize without the re-init block fails them")


if __name__ == "__main__":
    main()
