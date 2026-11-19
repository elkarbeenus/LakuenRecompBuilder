"""The prediction's limits (gpu/vk/predict_limits.h, from HeyListen d2384687): a program over the size limit is left out, the
prediction stops below the memory reserve, and 0 turns each off. Also that predict_run uses them and Stage notes its size where
the program cache notes its phis (vk_progcache.cpp, outside the shader stamp's files).

python -I -B tests/test_predict_limits.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"

FIXTURE = r'''
#include "predict_limits.h"
#include <cstdio>
using namespace mkwvk::predictlimits;
int main() {
    int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL %s\n", #x); fails++; } } while (0)
    CHECK(too_big(1014000, kDefaultMaxKWords));
    CHECK(too_big(502000, kDefaultMaxKWords));
    CHECK(!too_big(133000, kDefaultMaxKWords));
    CHECK(!too_big(300999, 300));
    CHECK(!too_big(5000000, 0));
    CHECK(low_memory(1000, kDefaultReserveMB));
    CHECK(!low_memory(9000, kDefaultReserveMB));
    CHECK(!low_memory(10, 0));
    return fails != 0;
}
'''


def main():
    draw = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    for needle in ("predictlimits::too_big(words, max_kwords)", "predictlimits::low_memory(memory_left_mb(), reserve_mb)",
                   "RX_VK_PREDICT_MAX_KWORDS", "RX_VK_PREDICT_RESERVE_MB", "MemAvailable"):
        if needle not in draw:
            raise SystemExit("FAIL: vk_draw.cpp has no %s" % needle)
    cache = (VK / "vk_progcache.cpp").read_text(encoding="utf-8")
    if cache.count(".spirv_words = (uint32_t)spirv") != 3:
        raise SystemExit("FAIL: vk_progcache.cpp notes spirv_words at all three places the phis are noted")
    if "spirv_words" in (VK / "vk_shader.cpp").read_text(encoding="utf-8"):
        raise SystemExit("FAIL: vk_shader.cpp is part of the shader stamp: spirv_words is noted outside it")
    cxx = shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        print("PASS (sources; no C++ compiler)")
        return
    with tempfile.TemporaryDirectory(prefix="predict-limits-") as tmp:
        src = Path(tmp) / "t.cpp"
        src.write_text(FIXTURE, encoding="utf-8")
        exe = Path(tmp) / "t"
        build = subprocess.run([cxx, "-std=c++17", "-I", str(VK), str(src), "-o", str(exe)], capture_output=True, text=True)
        if build.returncode:
            raise SystemExit("FAIL: build\n" + build.stderr)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        if run.returncode:
            raise SystemExit("FAIL\n" + run.stdout)
    print("PASS: predict limits")


if __name__ == "__main__":
    main()
