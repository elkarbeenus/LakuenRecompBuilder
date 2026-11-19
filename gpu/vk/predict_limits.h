// (LaküenRecomp, from HeyListen d2384687 by its author) What the prediction of pipelines (predict_run, vk_draw.cpp) holds
// itself to. The pipelines it makes are built for the driver's own cache and let go, so none of them is needed before the game:
// they are speculative, and a cold start (every shader prepared) runs them all in one go. On an RTX 3050 (32 GB) two programs of
// the game's, 502k and 1014k words of SPIR-V, each kept the driver's compiler busy for over three minutes and growing past 11 GB;
// every other program, up to 133k words, took 25 s at most and a few hundred MB. On a handheld with 16 GB that is all there is.
// So:
//  * a program over kDefaultMaxKWords thousand words is left to the draw that needs it (RX_VK_PREDICT_MAX_KWORDS, 0: no limit);
//  * the prediction stops, the rest left to play, when the system has less than kDefaultReserveMB available
//    (RX_VK_PREDICT_RESERVE_MB, 0: no limit; Linux: /proc/meminfo's MemAvailable).
// No Vulkan: tests/test_predict_limits.py.
#pragma once
#include <cstdint>

namespace mkwvk::predictlimits {

constexpr unsigned long long kDefaultMaxKWords = 300;
constexpr unsigned long long kDefaultReserveMB = 2048;

/// A program of `words` 32-bit words of SPIR-V (all its stages) is too big to be predicted when max_kwords is not 0 and it is over it
inline bool too_big(uint64_t words, unsigned long long max_kwords) { return max_kwords && words / 1000 > max_kwords; }

/// The system has less memory left than the prediction wants to leave (reserve_mb 0: it does not look)
inline bool low_memory(unsigned long long left_mb, unsigned long long reserve_mb) { return reserve_mb && left_mb < reserve_mb; }

}  // namespace mkwvk::predictlimits
