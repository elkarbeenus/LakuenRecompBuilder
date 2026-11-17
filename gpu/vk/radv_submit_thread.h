#pragma once

// Mesa reads MESA_VK_ENABLE_SUBMIT_THREAD while RADV creates the device. Keep
// the decision separate from Vulkan so it can be exercised without a GPU.
namespace radv_submit_thread {

enum class Choice {
    set_on,
    user_set,
    switch_off,
    not_radv,
    few_threads,   // (LaküenRecomp, HeyListen's rule 24d1a167: no spare core under 12 hardware threads)
};

inline bool switch_is_off(const char* value) {
    if (!value) return false;
    static const char* const off_values[] = {"", "0", "false", "off", "no"};
    for (const char* off : off_values) {
        const char* a = value;
        const char* b = off;
        while (*a && *b) {
            const char lower = *a >= 'A' && *a <= 'Z' ? static_cast<char>(*a + ('a' - 'A')) : *a;
            if (lower != *b) break;
            ++a;
            ++b;
        }
        if (!*a && !*b) return true;
    }
    return false;
}

// threads: the host's hardware threads. Without the switch the submit thread is made from 12 on (a 5800X3D's 16), not on
// the Steam Deck's or the Legion Go S's 8, where its wake-ups take a core the game's own threads need (HeyListen 24d1a167).
// RX_VK_RADV_SUBMIT_THREAD=1 (any value but the off ones): on whatever the count
inline Choice decide(bool radv, const char* mesa_value, const char* switch_value, long threads = 16) {
    if (!radv) return Choice::not_radv;
    if (mesa_value) return Choice::user_set;
    if (switch_is_off(switch_value)) return Choice::switch_off;
    if (!switch_value && threads < 12) return Choice::few_threads;
    return Choice::set_on;
}

}  // namespace radv_submit_thread
