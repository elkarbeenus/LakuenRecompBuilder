// Game- and GPU-free regression for RADV's Mesa submit-thread selection.
//   clang++ -std=c++20 -O2 -Wall -Wextra -Werror gpu/vk/tests/radv_submit_thread_test.cpp -o radv_submit_thread_test
#include <cstdio>

#include "../radv_submit_thread.h"

#define CHECK(condition)                                                                                               \
    do {                                                                                                               \
        if (!(condition)) {                                                                                            \
            std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition);                                        \
            return 1;                                                                                                  \
        }                                                                                                              \
    } while (0)

int main() {
    using radv_submit_thread::Choice;
    using radv_submit_thread::decide;

    CHECK(decide(true, nullptr, nullptr) == Choice::set_on);
    CHECK(decide(true, nullptr, "1") == Choice::set_on);
    CHECK(decide(true, nullptr, "yes") == Choice::set_on);

    CHECK(decide(true, "1", nullptr) == Choice::user_set);
    CHECK(decide(true, "0", nullptr) == Choice::user_set);
    CHECK(decide(true, "", "0") == Choice::user_set);

    CHECK(decide(true, nullptr, "0") == Choice::switch_off);
    CHECK(decide(true, nullptr, "False") == Choice::switch_off);
    CHECK(decide(true, nullptr, "OFF") == Choice::switch_off);
    CHECK(decide(true, nullptr, "no") == Choice::switch_off);
    CHECK(decide(true, nullptr, "") == Choice::switch_off);

    CHECK(decide(false, nullptr, nullptr) == Choice::not_radv);
    CHECK(decide(false, "1", nullptr) == Choice::not_radv);
    CHECK(decide(false, nullptr, "1") == Choice::not_radv);

    CHECK(!radv_submit_thread::switch_is_off(nullptr));
    CHECK(!radv_submit_thread::switch_is_off("1"));
    CHECK(!radv_submit_thread::switch_is_off("00"));
    CHECK(!radv_submit_thread::switch_is_off("offf"));
    return 0;
}
