/* The recompiled game's side of the emulator ABI (nx2pc_host.h): a64-kit's OS hooks routed to the host table.

   a64-kit's runtime (rt/a64_rt.c) leaves a64_svc to the OS layer and makes a64_on_trap, a64_call_miss and
   a64_cntpct_host weak; this file is the "OS layer" when the game runs inside Eglantine, and adds a64_poll for the
   loop-header polls (nx2/poll.py). Built into hookshot_game.dll with the lifted code (nx2/build.py --dll). */
#include "a64.h"
#include "nx2pc_host.h"
#include <stdio.h>
#include <stdlib.h>

extern const uint32_t a64_fn_count;
extern const uint64_t nx2pc_image_base;
extern const char nx2pc_main_build_id[];

#define SAME(f) _Static_assert(offsetof(GuestContext, f) == offsetof(Nx2pcGuestContext, f), "Nx2pcGuestContext." #f)
SAME(x); SAME(pc); SAME(n); SAME(v); SAME(halted); SAME(vreg); SAME(tpidr_el0); SAME(tpidrro_el0); SAME(fpcr);
SAME(fpsr); SAME(excl_addr); SAME(excl_hi); SAME(excl_size); SAME(excl_valid); SAME(thread); SAME(poll);
_Static_assert(sizeof(GuestContext) == sizeof(Nx2pcGuestContext), "Nx2pcGuestContext size");

static Nx2pcHost host;
static int attached;

void a64_svc(Ctx *c, uint32_t imm) { host.svc(host.user, c, imm); }

void a64_poll(Ctx *c) {
    __atomic_store_n(&c->poll, 0, __ATOMIC_RELAXED);
    host.poll(host.user, c);
}

void a64_on_trap(Ctx *c, uint64_t pc, uint32_t insn, const char *why) {
    if (attached) host.trap(host.user, c, pc, insn, why);
    fprintf(stderr, "[nx2pc] %s at %#llx (insn %08x)\n", why, (unsigned long long)pc, insn);
    abort();
}

int a64_call_miss(Ctx *c, uint64_t target) { return attached && host.call_miss(host.user, c, target); }

uint64_t a64_cntpct_host(void) { return attached ? host.cntpct(host.user) : 0; }

NX2PC_EXPORT int nx2pc_recomp_attach(const Nx2pcHost *h, Nx2pcGameInfo *info) {
    if (info) {
        info->version = NX2PC_HOST_VERSION;
        info->ctx_size = (uint32_t)sizeof(GuestContext);
        info->mem_base = (uint64_t)(uintptr_t)A64_MEM;
        info->image_base = nx2pc_image_base;
        info->functions = a64_fn_count;
#if defined(A64_POLLING)
        info->polls = 1;
#else
        info->polls = 0;
#endif
        info->main_build_id = nx2pc_main_build_id;
    }
    if (!h || h->version != NX2PC_HOST_VERSION || h->ctx_size != sizeof(GuestContext))
        return 1;
    if (!h->svc || !h->poll || !h->trap || !h->call_miss || !h->cntpct)
        return 2;
    host = *h;
    attached = 1;
    return 0;
}

NX2PC_EXPORT Nx2pcFn nx2pc_recomp_lookup(uint64_t guest_addr) { return (Nx2pcFn)a64_lookup(guest_addr); }
