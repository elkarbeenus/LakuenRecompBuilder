#pragma once

// Mesa reads MESA_VK_ENABLE_SUBMIT_THREAD while RADV creates the device. Keep
// the decision separate from Vulkan so it can be exercised without a GPU.
namespace radv_submit_thread {

enum class Choice {
    set_on,
    user_set,
    switch_off,
    not_radv,
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

inline Choice decide(bool radv, const char* mesa_value, const char* switch_value) {
    if (!radv) return Choice::not_radv;
    if (mesa_value) return Choice::user_set;
    if (switch_is_off(switch_value)) return Choice::switch_off;
    return Choice::set_on;
}

}  // namespace radv_submit_thread
