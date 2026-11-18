"""The stream's uniform updates of one flush are written without overlapping one another (gpu/vk/vk_replay.cpp
flush_ub_updates, ub_disjoint_writes): updates whose bytes overlap are composed on the CPU in stream order into one write.

Two vkCmdUpdateBuffer of the same bytes with no barrier between them may land in either order. The game updates one uniform
block many times a recording (4, 16 and 64 bytes), and the validation layer's sync check reported each pair as
SYNC-HAZARD-WRITE-AFTER-WRITE (~2000 a second in Kokiri Forest, RX 9070 XT, RADV 26.2.6, VVL 1.4.363,
VK_LAYER_VALIDATE_SYNC=1): on a driver that runs the updates side by side the older bytes could be the ones left for the next
frames. A barrier between overlapping updates cost ~2% fps there; composing them costs none. Source checks plus
ub_disjoint_writes compiled alone and checked against applying every update in order, on fixed and random lists; no game or
GPU required.

python -I -B tests/test_ub_update_order.py (from HeyListen 2a12d65c, Mooseca) [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker):
    """From marker to the brace closing its first one"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <random>
#include <utility>
#include <vector>
struct UbUpdate { uint64_t value; uint64_t dst; std::vector<uint8_t> bytes; };
template <class Updates, class Write>
@@FUNC@@
static int check(const std::deque<UbUpdate>& ups, size_t first, const char* what) {
    uint8_t want[512], got[512];
    std::memset(want, 0xEE, sizeof want), std::memset(got, 0xEE, sizeof got);
    for (size_t i = first; i < ups.size(); i++) std::memcpy(want + ups[i].dst, ups[i].bytes.data(), ups[i].bytes.size());
    std::vector<std::pair<uint64_t, uint64_t>> writes;
    ub_disjoint_writes(ups, first, ups.size(), [&](uint64_t dst, const uint8_t* b, uint64_t n) {
        std::memcpy(got + dst, b, n), writes.push_back({dst, dst + n});
    });
    std::sort(writes.begin(), writes.end());
    for (size_t i = 1; i < writes.size(); i++)
        if (writes[i].first < writes[i - 1].second) { std::printf("FAIL: %s: two writes overlap\n", what); return 1; }
    if (std::memcmp(want, got, sizeof want)) { std::printf("FAIL: %s: the bytes differ from the updates applied in order\n", what); return 1; }
    return 0;
}
static UbUpdate up(uint64_t dst, uint32_t n, uint8_t v) { return {0, dst, std::vector<uint8_t>(n, v)}; }
int main() {
    int fails = 0;
    fails += check({up(0, 16, 1), up(16, 16, 2), up(32, 32, 3)}, 0, "adjacent");
    fails += check({up(0, 64, 1), up(16, 4, 2)}, 0, "a word into a block");
    fails += check({up(16, 4, 2), up(0, 64, 1)}, 0, "a block over a word");
    fails += check({up(0, 16, 1), up(0, 16, 2), up(0, 16, 3)}, 0, "the same block three times");
    fails += check({up(0, 16, 1), up(32, 16, 2), up(8, 32, 3), up(100, 4, 4)}, 0, "across two");
    fails += check({up(0, 16, 9), up(0, 16, 1), up(4, 4, 2)}, 1, "from the recording's first");
    fails += check({up(0, 0, 5), up(0, 8, 1)}, 0, "an empty update");
    std::mt19937 rng(7);
    for (int t = 0; t < 2000 && !fails; t++) {
        std::deque<UbUpdate> ups;
        const int n = 1 + (int)(rng() % 24);
        for (int i = 0; i < n; i++) {
            const uint32_t size = 4u << (rng() % 5);
            ups.push_back(up(4 * (rng() % (448 / 4)), size, (uint8_t)(1 + rng() % 250)));
        }
        fails += check(ups, rng() % 3 == 0 ? rng() % n : 0, "random");
    }
    return fails;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    src = (VK / "vk_replay.cpp").read_text(encoding="utf-8")
    flush = block(src, "void flush_ub_updates(VkCommandBuffer cmd)")
    if "ub_disjoint_writes(ub_updates, ub_first_of_recording, ub_updates.size()," not in flush:
        raise SystemExit("FAIL: flush_ub_updates does not write its updates through ub_disjoint_writes")
    # (LaküenRecomp: the old loop stays behind RX_VK_UB_ORDERED=0, after the ordered path)
    if "RX_VK_UB_ORDERED" not in flush or flush.index("ub_disjoint_writes(") > flush.index("gpu_write(cmd, ub_updates[i]"):
        raise SystemExit("FAIL: flush_ub_updates writes each update as it is by default")
    print("source: flush_ub_updates writes the updates as disjoint ranges")
    func = block(src, "void ub_disjoint_writes(")
    with tempfile.TemporaryDirectory(prefix="ub-update-order-") as tmp:
        cpp, exe = Path(tmp) / "t.cpp", Path(tmp) / "t.exe"
        cpp.write_text(FIXTURE.replace("@@FUNC@@", func), encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise SystemExit(r.stdout + "FAIL: ub_disjoint_writes")
    print("writes: 7 fixed cases and 2000 random lists give the bytes of the updates applied in order, no two writes overlapping")
    print("PASS")


if __name__ == "__main__":
    main()
