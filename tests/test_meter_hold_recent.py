#!/usr/bin/env python3
"""(LaküenRecomp) RX_VK_METER_HOLD holds a zero read of an exposure block only while its program was recorded lately.

The real memory_meter_dispatched / memory_meter_read are cut from gpu/vk/vk_memory.cpp and driven: a block written every frame
(its zero read is a result on its way: held), a block whose program stopped (held for kMeterRecent reads, then its zeros are
the game's), a block never written (never held), and RX_VK_METER_HOLD=2 (every zero read held, as before)."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")

start = SRC.index("namespace {\nstruct MeterUse")
end = SRC.index("    return always || recent;\n}", start) + len("    return always || recent;\n}")
CUT = SRC[start:end]

HARNESS = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <unordered_map>
static std::mutex meter_mu;
static void logf(const char*, ...) {}
static int env_int(const char* n, int d) { const char* v = getenv(n); return v && *v ? atoi(v) : d; }
@CUT@
#define CHECK(c, what) do { if (!(c)) { fprintf(stderr, "FAIL: %s\n", what); return 1; } } while (0)
int main() {
    const bool always = getenv("RX_VK_METER_HOLD") && atoi(getenv("RX_VK_METER_HOLD")) == 2;
    // a block written every frame: each read held
    for (int i = 0; i < 20; i++) { memory_meter_dispatched(0x100); CHECK(memory_meter_read(0x100), "written every frame: held"); }
    // the replay two reads behind: still held
    CHECK(memory_meter_read(0x100) && memory_meter_read(0x100), "the replay behind: held");
    // its program stopped: held for the recent reads, then not
    int held = 0;
    for (int i = 0; i < 30; i++) held += memory_meter_read(0x100);
    if (always) CHECK(held == 30, "RX_VK_METER_HOLD=2: every zero read held");
    else CHECK(held == 5, "a program that stopped: held for 8 reads after its last dispatch (3 above), then its zeros are the game's");
    // a block never written: never held
    if (!always) CHECK(!memory_meter_read(0x200) && !memory_meter_read(0x200), "a block no program writes: not held");
    // written again: held again
    memory_meter_dispatched(0x100);
    CHECK(memory_meter_read(0x100), "written again: held again");
    puts("ok");
    return 0;
}
"""


def main():
    cxx = shutil.which(os.environ.get("CXX", "clang++")) or shutil.which("g++")
    if not cxx:
        print("skip: no C++ compiler")
        return 0
    with tempfile.TemporaryDirectory(prefix="meter-hold-") as d:
        src = Path(d) / "t.cpp"
        src.write_text(HARNESS.replace("@CUT@", CUT), encoding="utf-8")
        exe = Path(d) / "t"
        subprocess.run([cxx, "-std=c++17", "-O1", "-w", str(src), "-o", str(exe)], check=True)
        for env in ({}, {"RX_VK_METER_HOLD": "2"}):
            r = subprocess.run([str(exe)], env={**os.environ, **env}, capture_output=True, text=True)
            if r.returncode:
                sys.stderr.write(r.stderr)
                return 1
    print("PASS meter hold follows the block's program (RX_VK_METER_HOLD)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
