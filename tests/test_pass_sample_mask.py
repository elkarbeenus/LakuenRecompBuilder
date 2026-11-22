"""The pass's sampled-target mask gives the answers the list search gave. Run python -I -B tests/test_pass_sample_mask.py [--cxx clang++].

gpu/vk/vk_draw.cpp's draw_hazards computes the targets a draw samples as one mask, and draw() keeps them in the pass as a mask
(RX_VK_PASS_SAMPLE_MASK; =0: a list of every texture the pass sampled, searched for each sampled texture of each draw, with the
mask kept from it, as before). The pieces are cut out of the source and run over random passes (a few targets, a pool of textures,
draws sampling a few of them): the mask after every draw, and the hazard the draw would find ("samples a target the pass wrote",
"writes a target an earlier draw sampled"), must be the same with the switch on and off, and equal to the answers of the old
formulas written out here.

Ported from Longshot 7daafa7a (#1553, HumanBean), 4ef972c6's draw.cpp part; the check is HeyListen's.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from srccut import between

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

HARNESS = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
static int env_int(const char* n, int d) { const char* v = getenv(n); return v && *v ? atoi(v) : d; }
struct Texture { int id; };
struct Targets { int n; const Texture* color[8]; const Texture* depth; };
struct Pass { std::vector<const Texture*> sampled; uint16_t sampled_targets = 0, written = 0; };
static std::vector<const Texture*> sampled_now;
static std::vector<const Texture*>& gfx_sampled() { return sampled_now; }
static bool pass_trace_on() { return false; }
static bool gprof_on() { return false; }
static uint64_t rng = 88172645463325252ull;
static unsigned rnd(unsigned n) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return (unsigned)(rng % n); }
// (what the old code answered, from its text)
static int old_slot_of(const Targets& at, const Texture* t) {
    for (int i = 0; i < at.n; i++)
        if (at.color[i] == t) return i;
    return at.depth == t ? 8 : -1;
}
static bool old_kind(const Targets& at, uint16_t written, uint16_t writes) {
    for (const Texture* t : gfx_sampled()) {
        const int k = old_slot_of(at, t);
        if (k >= 0 && (written >> k & 1) && !(writes >> k & 1)) return true;
    }
    return false;
}
int main() {
    static Texture pool[24];
    for (int i = 0; i < 24; i++) pool[i].id = i;
    uint64_t hash = 1469598103934665603ull;
    auto mix = [&](uint64_t v) { hash = (hash ^ v) * 1099511628211ull; };
    for (int pass_no = 0; pass_no < 400; pass_no++) {
        Targets at{};
        at.n = 1 + rnd(4);
        // (distinct attachments: one texture bound twice gets a bit for each slot now, the old search only its first: a superset,
        // never a missed hazard)
        const int first = rnd(10);
        for (int i = 0; i < at.n; i++) at.color[i] = &pool[first + i];
        at.depth = rnd(2) ? &pool[first + at.n + rnd(5)] : nullptr;
        Pass pass;
        uint16_t old_total = 0;
        for (int draw = 0; draw < 60; draw++) {
            sampled_now.clear();
            for (unsigned k = rnd(7); k; k--) sampled_now.push_back(&pool[rnd(24)]);
            uint16_t writes = 0;
            for (int i = 0; i < at.n; i++) if (rnd(2)) writes |= (uint16_t)(1u << i);
            if (at.depth && rnd(2)) writes |= 1u << 8;
            uint16_t samples;
            SAMPLES
            const char* kind = KIND;
            if ((kind != nullptr) != old_kind(at, pass.written, writes)) { std::puts("kind differs"); return 1; }
            mix(kind != nullptr);
            TRACK
            for (const Texture* t : gfx_sampled()) { const int s = old_slot_of(at, t); if (s >= 0) old_total |= (uint16_t)(1u << s); }   // (the old mask: per sampled texture its slot)
            if (pass.sampled_targets != old_total) { std::puts("mask differs"); return 1; }
            mix(pass.sampled_targets);
            pass.written |= writes;
        }
    }
    std::printf("%llu\n", (unsigned long long)hash);
}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="c++")
    args = parser.parse_args()
    source = (ROOT / "gpu/vk/vk_draw.cpp").read_text()
    samples = between(source, "    samples = 0;\n    for (const Texture* t : gfx_sampled()) {", "    {   // (hookshot: a draw that samples a target it writes itself")
    samples = "    samples = 0;\n    for (const Texture* t : gfx_sampled()) {" + samples[len("    samples = 0;\n    for (const Texture* t : gfx_sampled()) {"):]
    kind = between(source, "    const char* kind = (samples & pass_.written", ";\n").replace("pass_.written", "pass.written").replace("    const char* kind = ", "").strip()
    track = between(source, "    static const bool mask_on", "    pass_.written |= writes;").replace("pass_.", "pass.")
    text = HARNESS.replace("SAMPLES", samples).replace("KIND", kind).replace("TRACK", track)
    with tempfile.TemporaryDirectory() as temp:
        cpp = Path(temp) / "mask.cpp"
        cpp.write_text(text)
        exe = cpp.with_suffix(".exe")
        subprocess.run([args.cxx, "-std=c++17", "-O1", "-w", str(cpp), "-o", str(exe)], check=True)
        env = {k: v for k, v in os.environ.items() if k != "RX_VK_PASS_SAMPLE_MASK"}
        answers = []
        for name, e in (("on", env), ("off", dict(env, RX_VK_PASS_SAMPLE_MASK="0"))):
            r = subprocess.run([str(exe)], env=e, capture_output=True, text=True, timeout=60)
            if r.returncode:
                raise SystemExit("FAIL: switch %s: %s" % (name, r.stdout.strip() or r.stderr.strip()))
            answers.append(r.stdout.strip())
        on, off = answers
        if on != off:
            raise SystemExit("FAIL: the mask's answers differ from the list's: %s vs %s" % (on, off))
    print("PASS: the sampled-target mask answers as the list search did, over 400 random passes")


if __name__ == "__main__":
    main()
