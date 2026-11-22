"""A capture buffer the driver refuses falls back to a spare, then to the need's exact size. Run python -I -B tests/test_capture_get_fallback.py.

gpu/vk/vk_memory.cpp's cap_buf_get (and cap_buf_size) are cut out of the source and run against stand-ins whose buffer creation
can be made to fail for the size class, for every size, or for none:
- the free-list lock is not held while the driver allocates (RX_VK_CAP_GET_FALLBACK=0: it is, as before);
- a spare that fits is taken as before and no buffer is made;
- a refused size class takes the smallest spare that fits, whatever its size (the spare the FIT rule had passed over);
- with no spare, the need's exact size is tried (not rounded up to the class);
- every size refused: false, nothing taken;
- RX_VK_CAP_GET_FALLBACK=0: a refused size class fails the capture, as before.

Ported from Longshot 7daafa7a (#1553, HumanBean), d87dd600 and 4ef972c6's cap_buf_get; the harness is HeyListen's (its cap_buf_get
keeps the spares' FIT rule and has no pre-warm workers).
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from srccut import block

HARNESS = r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>
typedef void* VkBuffer;
typedef void* VmaAllocation;
typedef unsigned VkBufferUsageFlags;
enum { VK_BUFFER_USAGE_TRANSFER_SRC_BIT = 1, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT = 2, VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT = 4 };
struct FreeBuf { VkBuffer buffer; VmaAllocation alloc; void* map; uint64_t size, at, ms; };
static std::vector<FreeBuf> cap_free;
static std::mutex cap_free_mu;
static uint64_t cap_free_bytes, cap_gets, cap_need_max, cap_taken_over, cap_free_low = ~0ull, cap_bufs_made;
static bool cap_fit() { return true; }
enum class MemKind { Capture };
struct MemKindScope { MemKindScope(MemKind) {} };
static void log_alloc_where(const char*, VmaAllocation) {}
#define logf(...) ((void)0)
static bool env_on(const char* n) { const char* v = getenv(n); return v && *v && strcmp(v, "0") != 0; }
static int env_int(const char* n, int d) { const char* v = getenv(n); return v && *v ? atoi(v) : d; }
static bool cap_prewarm_on() { return false; }
static void cap_prewarm_class(uint64_t) {}
static VkBufferUsageFlags cap_buf_usage() { return VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT; }
// (what the driver refuses: sizes at or above refuse_from, or all of them, or none)
static uint64_t refuse_from = ~0ull, last_made = 0;
static int made, lock_free_calls, lock_held_calls;
static bool create_buffer_cached(uint64_t size, VkBufferUsageFlags, VkBuffer& b, VmaAllocation& a, void** map, bool) {
    if (cap_free_mu.try_lock()) cap_free_mu.unlock(), lock_free_calls++;   // (a retiring replay could give a spare back now)
    else lock_held_calls++;
    if (size >= refuse_from) return false;
    static char byte;
    b = &byte, a = &byte, *map = &byte, last_made = size, made++;
    return true;
}
"""
CASES = r"""
static bool get(uint64_t need, uint64_t& size) {
    VkBuffer b = nullptr; VmaAllocation a = nullptr; void* m = nullptr;
    size = 0;
    return cap_buf_get(need, b, a, m, size);
}
int main(int argc, char** argv) {
    const bool off = argc > 1;
    uint64_t size = 0;
    static char x;
    // a fitting spare: taken, nothing made
    cap_free.push_back({&x, &x, &x, 4ull << 20, 0, 0}), cap_free_bytes = 4ull << 20;
    assert(get(3ull << 20, size) && size == (4ull << 20) && made == 0 && cap_free.empty());
    // no spare, the class made: its size
    assert(get(3ull << 20, size) && size == (4ull << 20) && made == 1);
    // the class refused: the exact need (3 MB + 1) is under the refusing size, and is made
    refuse_from = 4ull << 20;
    made = 0;
    const uint64_t need = (3ull << 20) + 4096;
    const bool got = get(need, size);
    if (off) { assert(!got && made == 0 && lock_free_calls == 0 && lock_held_calls > 0); return 0; }
    assert(lock_held_calls == 0 && lock_free_calls > 0);
    assert(got && size == need && made == 1 && last_made == need);
    // the class refused and a (large) spare there: the spare, though the FIT rule would have passed it over
    cap_free.push_back({&x, &x, &x, 64ull << 20, 0, 0}), cap_free_bytes = 64ull << 20;
    made = 0;
    assert(get(need, size) && size == (64ull << 20) && made == 0 && cap_free.empty() && cap_free_bytes == 0);
    // everything refused, no spare: false
    refuse_from = 0;
    assert(!get(need, size) && made == 0);
    std::puts("ok");
}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="c++")
    args = parser.parse_args()
    source = (ROOT / "gpu/vk/vk_memory.cpp").read_text()
    funcs = "\n".join(block(source, m) for m in ("uint64_t cap_buf_size(", "bool cap_buf_get("))
    with tempfile.TemporaryDirectory() as temp:
        fixture = Path(temp) / "get.cpp"
        fixture.write_text(HARNESS + funcs + CASES)
        exe = fixture.with_suffix(".exe")
        subprocess.run([args.cxx, "-std=c++17", "-O1", "-w", "-UNDEBUG", str(fixture), "-o", str(exe)], check=True)
        env = {k: v for k, v in os.environ.items() if k != "RX_VK_CAP_GET_FALLBACK"}
        subprocess.run([str(exe)], check=True, env=env, timeout=30)
        subprocess.run([str(exe), "off"], check=True, env=dict(env, RX_VK_CAP_GET_FALLBACK="0"), timeout=30)
    print("PASS: a refused capture buffer falls back to a spare and to the exact size; RX_VK_CAP_GET_FALLBACK=0 fails it as before")


if __name__ == "__main__":
    main()
