/* nn::crypto: random bytes from the operating system.

   Kirby Air Riders' first boot (in Dragoon, its fork) stopped here, before its first frame: main's static initialisers
   build a std::random_device, whose getentropy asks nn::crypto::GenerateCryptographicallyRandomBytes, which asks the csrng
   service through the service manager. This runtime answers no service over IPC ("sm:" is answered empty), so the
   SDK's call failed and it aborted (svcBreak from nn::diag::detail::Abort). The call means one thing, fill this buffer
   with random bytes, so it is answered here from the system's own generator: getrandom on Linux, RtlGenRandom on
   Windows (advapi32, which the runtime links already). Ocarina's SDK never reached it at start, so Ocarina is
   unchanged. */
#include "hos.h"
#include <stdint.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
unsigned char __stdcall SystemFunction036(void *buffer, unsigned long length);   /* RtlGenRandom, advapi32 */
#else
#include <errno.h>
#include <sys/random.h>
#endif

/* the system's random bytes into out; 0 when they could not be had */
static int system_random(void *out, size_t n) {
#ifdef _WIN32
    for (size_t at = 0; at < n;) {
        const unsigned long k = n - at > 0x10000000 ? 0x10000000 : (unsigned long)(n - at);
        if (!SystemFunction036((unsigned char *)out + at, k)) return 0;
        at += k;
    }
    return 1;
#else
    for (size_t at = 0; at < n;) {
        const ssize_t k = getrandom((unsigned char *)out + at, n - at, 0);
        if (k < 0) {
            if (errno == EINTR) continue;
            return 0;
        }
        at += (size_t)k;
    }
    return 1;
#endif
}

/* GenerateCryptographicallyRandomBytes(void*, unsigned long): void. The console aborts when it cannot have them, and so
   does this, rather than hand out bytes that are not random. */
HLE(_ZN2nn6crypto36GenerateCryptographicallyRandomBytesEPvm) {
    const uint64_t out = ARG(0), n = ARG(1);
    static int logged;
    if (!logged++) hos_log("crypto: random bytes from the system (%llu asked first, lr %#llx)", (unsigned long long)n,
                           (unsigned long long)c->x[30]);
    if (n && !system_random(GP(out), (size_t)n))
        hos_fatal(c, "crypto: the system gave no random bytes (%llu asked)", (unsigned long long)n);
}
