// The upscaler's jitter metadata crosses from replay to the game thread. Keep its lock separate from GPU/NGX work.
#pragma once

#include <mutex>

#include "vk_api.h"

namespace nx2vk {

class TemporalJitter {
    std::mutex mu;
    NX2VkJitter sample{};
    uint64_t frame = 0;

public:
    void publish(uint32_t width, uint32_t height, uint32_t phases, uint64_t at) {
        std::lock_guard lock(mu);
        sample = width && height && phases ? NX2VkJitter{width, height, phases} : NX2VkJitter{};
        frame = at;
    }

    NX2VkJitter read(uint64_t now) {
        std::lock_guard lock(mu);
        return frame && now - frame <= 30 ? sample : NX2VkJitter{};
    }
};

} // namespace nx2vk
