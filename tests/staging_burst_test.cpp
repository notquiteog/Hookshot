// tests/test_staging_burst.py puts vk_texture.cpp's staging() and texture_frame's give-back loop where ACTUAL is and
// runs the cases below: frames that stage, then present, on a clock the fixture moves.
#include <vulkan/vulkan.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace fixture {
void require(bool ok, const char* why) {
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", why);
        std::exit(1);
    }
}
int64_t now_ns = 1'000'000'000;
struct Clock {   // (std::chrono::steady_clock in the code cut out)
    using duration = std::chrono::nanoseconds;
    using rep = duration::rep;
    using period = duration::period;
    using time_point = std::chrono::time_point<Clock, duration>;
    static constexpr bool is_steady = true;
    static time_point now() { return time_point(duration(now_ns)); }
};
struct VmaAllocation_T {};
using VmaAllocation = VmaAllocation_T*;
unsigned makes = 0, destroys = 0;
uint8_t mapped_stand_in;   // (never written: the cases only count arenas)
uint64_t rec_value = 1, completed_value = 0;
struct { VkPhysicalDeviceProperties props{}; } dev;
bool create_buffer(uint64_t, VkBufferUsageFlags, bool, VkBuffer& b, VmaAllocation& a, void** map) {
    a = new VmaAllocation_T;
    b = reinterpret_cast<VkBuffer>(a);
    *map = &mapped_stand_in;
    makes++;
    return true;
}
void destroy_buffer(VkBuffer b, VmaAllocation a) {
    require(a && b == reinterpret_cast<VkBuffer>(a), "an arena is destroyed with its own allocation");
    delete a;
    destroys++;
}
void logf(const char*, ...) {}
enum LogLevel : int { log_error, log_warn, log_info, log_debug, log_trace };
void logf_at(LogLevel, const char*, ...) {}
// (texture_frame's: Linux memory pressure is on, and it has just begun; VRAM is near what the driver allows. The cases
// set them)
bool linux_pressed = false, linux_entered_pressure = false;
uint8_t pool_pressure = 0;   // (vk_texture.cpp: 0 normal, 1 pressed, 2 critical, #637)
template <class A> bool spare_give_back(A&) { return false; }   // (main's SpareArenas: none here, the arena is destroyed)
// (#637 made the arenas 16 MB and keeps two of them warm past staleness: the cases below are this tree's, after it. Longshot's
// fixture still said 64 MB.)
// (main's SpareArenas, off here: no spare arena made ahead, every arena made in staging() as in Longshot's)
#define NVN_TEX_MAX_BYTES (16ull << 30)
struct { std::atomic<int64_t> taken{0}, made_here{0}; } spare_arenas;
bool spare_on() { return false; }
template <class A> bool spare_take(A&) { return false; }
// (staging()'s count of every arena it makes, and their time: the log's "staging ... made so far")
std::atomic<uint64_t> st_arena_makes{0};
std::atomic<int64_t> st_arena_make_ns{0};

/* ACTUAL */

constexpr uint64_t MB = 1ull << 20;
uint64_t keep = 64 * MB;   // (what a card of 6.5 GB or less keeps between loads; 256 MB above)
// One frame: a submission that stages the pieces, then the present. The GPU finishes a frame's submission between that
// frame's present and the next one (one frame in flight)
void frame(const std::vector<uint64_t>& pieces, int64_t ms = 33) {
    rec_value++;
    for (uint64_t n : pieces) require(staging(n).buffer != VK_NULL_HANDLE, "a piece is staged");
    completed_value = rec_value - 1;
    give_back(completed_value, keep);
    now_ns += ms * 1'000'000;
}
uint64_t held() {
    uint64_t n = 0;
    for (const Arena& a : arenas) n += a.size;
    return n;
}

int run(int argc, char** argv) {
    require(argc == 2, "a case");
    const std::string test = argv[1];
    const bool off = getenv("RX_VK_STAGING_BURST_S") && atoll(getenv("RX_VK_STAGING_BURST_S")) == 0;
    dev.props.limits.nonCoherentAtomSize = 64;
    if (test == "consecutive") {
        // a little staged in each of 20 frames in a row: the frame before's arena is not the GPU's to give yet, so two take
        // turns. Kept to 64 MB, the idle one of the two went at every second present and was made again a frame later
        for (int i = 0; i < 20; i++) frame({1 * MB});
        if (off) require(makes == 2, "RX_VK_STAGING_BURST_S=0: the two warm arenas (#637) take turns all the same");
        else require(makes == 2 && destroys == 0, "two arenas made for 20 frames in a row, none given back between");
        require(st_arena_makes.load() == makes, "every arena made is counted, for the log's line");
    } else if (test == "settles") {
        for (int i = 0; i < 20; i++) frame({1 * MB});
        for (int i = 0; i < 70; i++) frame({});   // (2.3 s with nothing staged)
        require(arenas.size() == 2 && held() == 32 * MB, "the load over, the two 16 MB arenas kept warm (#637)");
        for (int i = 0; i < 31; i++) frame({}, 1000);
        require(arenas.size() == 2 && destroys == 0, "nothing staged for 30 s: the two warm arenas still kept (#637), nothing else");
    } else if (test == "cap") {
        frame({60 * MB, 60 * MB, 60 * MB, 60 * MB, 60 * MB, 60 * MB});   // (60 + 60 MB do not fit one arena: six)
        require(arenas.size() == 6, "six arenas for six pieces of 60 MB");
        frame({});
        require(held() == 0, "pieces past an arena's 16 MB have arenas of their own, gone once the GPU is done with them (#637)");
    } else if (test == "big") {
        frame({100 * MB});
        require(arenas.size() == 1 && arenas[0].size == 100 * MB, "a piece over 64 MB has an arena of its size");
        frame({});
        require(arenas.empty(), "an arena over 64 MB goes once the GPU is done with it, used a moment ago or not");
    } else if (test == "keep256") {
        keep = 256 * MB;   // (a card over 6.5 GB: the rule adds nothing to what it keeps)
        for (int i = 0; i < 20; i++) frame({1 * MB});
        require(makes == 2 && destroys == 0, "256 MB kept between loads: two arenas for 20 frames, as before");
        frame({60 * MB, 60 * MB, 60 * MB, 60 * MB, 60 * MB, 60 * MB});
        frame({});
        require(held() == 32 * MB, "256 MB kept between loads: the two warm arenas after a load, its big pieces' own ones gone");
    } else if (test == "pressure") {
        // Linux memory pressure: an idle arena goes after 5 s, not 30, and when the pressure begins the idle ones go at
        // once, the ones a load used a moment ago too
        for (int i = 0; i < 20; i++) frame({1 * MB});
        for (int i = 0; i < 70; i++) frame({});
        require(arenas.size() == 1, "the load over: one arena kept");
        linux_pressed = true;
        for (int i = 0; i < 6; i++) frame({}, 1000);
        require(arenas.empty(), "under memory pressure, nothing staged for 5 s: none kept");
        linux_pressed = false;
        for (int i = 0; i < 20; i++) frame({1 * MB});
        require(arenas.size() == 2, "two arenas taking turns again");
        linux_entered_pressure = true;
        frame({});
        require(arenas.empty(), "the pressure begins: the idle arenas go at once");
    } else if (test == "short") {
        // VRAM near what the driver allows (over 90% of it, or Linux memory pressure on an integrated GPU): the rule is off,
        // and what stays is what the card keeps between loads, as before the rule. On a card of 6.5 GB or less the arenas are
        // VRAM behind the BAR: the 192 MB more would come off what a load's textures need
        pool_pressure = 2;
        frame({60 * MB, 60 * MB, 60 * MB, 60 * MB, 60 * MB, 60 * MB});
        require(arenas.size() == 6, "six arenas for six pieces of 60 MB");
        frame({});
        require(held() == 0, "VRAM short: the big pieces' own arenas gone, no burst kept");
        for (int i = 0; i < 20; i++) frame({1 * MB});
        require(makes == 8, "VRAM short: the two warm arenas take turns, none made every second frame (#637 keeps them)");
        pool_pressure = 0;   // (room again: the rule is back)
        const unsigned before = makes;
        for (int i = 0; i < 20; i++) frame({1 * MB});
        require(makes <= before + 1, "room again: two arenas take turns, none made every second frame");
        frame({60 * MB, 60 * MB, 60 * MB, 60 * MB, 60 * MB, 60 * MB});
        frame({});
        require(held() == 32 * MB, "room again: the two warm arenas kept, the big pieces' own ones gone");
    } else {
        require(false, "a known case");
    }
    return 0;
}
} // namespace fixture
int main(int argc, char** argv) { return fixture::run(argc, argv); }
