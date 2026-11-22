"""RX_VK_MESH_CONV (gpu/vk/mesh_conv.h): the indirect mesh draws' ring slots and the batch at the game's barriers, on a model of
the replay; no Vulkan, GPU or game data.

tests/mesh_conv_test.cpp replays made-up streams in order with the replay's own list of the ops a batch's scan steps over
(cut here from vk_replay.cpp mesh_conv_at_barrier) and checks that every indirect mesh draw reads {its arguments' count words
as they are at the draw, 1, 1}, converted at the draw (0, 1) or at the barrier before it (2), with the value changing between
recordings (HOS_AB) and the ring coming round. Then variants that must fail: slots at 16 bytes as before (the ring filled
once is then wrong), a draw that stores to memory not dropping the batch, the scan stepping over buffer clears, a slot the ring
came round onto used. The source checks: vk_draw.cpp drops the batch at a dispatch and at a draw whose program writes memory,
reads the switch at each recording's start, and fills the ring once with 1s; the replay
scans right after the game's barrier and names each mesh draw's op.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block, between  # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
MUST_FAIL = ("align16", "no_drop", "clearbuf_passes", "no_hold", "rescan_before")


def fail(msg):
    print("FAIL: " + msg)
    raise SystemExit(1)


def source_checks(src):
    draw = (src / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    replay = (src / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    if "mesh_batch_drop();" not in block(draw, "void dispatch(VkCommandBuffer cmd, NvnState& s, uint32_t x"):
        fail("vk_draw.cpp dispatch() does not drop the batch")
    body = block(draw, "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d) {")
    if "if (mesh_batch.live() && (writes_memory(p) || p.fallback)) mesh_batch_drop();" not in body:
        fail("vk_draw.cpp draw() does not drop the batch for a program that writes memory")
    if body.index("mesh_indirect_convert(cmd, d);") > body.index("mesh_batch_drop();"):
        fail("vk_draw.cpp draw(): the batch is dropped before the draw takes its own slot")
    if "mesh_conv_begin_recording();" not in block(draw, "void draw_begin_recording(int slot, VkCommandBuffer cmd"):
        fail("vk_draw.cpp: the switch is not read (and the batch let go) at each recording's start")
    begin = block(draw, "void mesh_conv_begin_recording() {")
    if "mesh_mode = mesh_conv_env();" not in begin or "mesh_batch.clear();" not in begin:
        fail("vk_draw.cpp mesh_conv_begin_recording: not the switch's value, or the batch kept")
    make = block(draw, "bool mesh_ring_make() {")
    if "vkCmdFillBuffer(c, mesh_ring, 0, VK_WHOLE_SIZE, 1u);" not in make or "vkWaitForFences" not in make:
        fail("vk_draw.cpp mesh_ring_make: the ring is not filled with 1s and waited for")
    conv = block(draw, "bool mesh_indirect_convert(VkCommandBuffer cmd, const DrawArgs& d) {")
    if "mesh_batch.take(cmd, d.op)" not in conv or "mesh_conv::still_holds(" not in conv or \
            "mesh_conv::take(" not in block(draw, "bool mesh_ring_slot("):
        fail("vk_draw.cpp: a draw's slot is not taken from the batch with its checks, or not from mesh_conv::take")
    if "if (mode >= 1 && mesh_ring_filled.load(std::memory_order_acquire)) {" not in conv:
        fail("vk_draw.cpp mesh_indirect_convert: the fill is left out without the ring filled once")
    barrier = between(replay, "        case NOP_BARRIER:", "        // ---- work ----")
    if not 0 <= barrier.index('full_barrier(cmd, "barrier (the game\'s nvnCommandBufferBarrier)");') < \
            barrier.index("mesh_conv_at_barrier(cmd, p + h.size, end);"):
        fail("vk_replay.cpp: the batch is not scanned right after the game's full barrier")
    loop = block(replay, "void replay(VkCommandBuffer& cmd, NvnState& s, const uint8_t* p, const uint8_t* end")
    rescan = "if (p == mesh_rescan_at) mesh_conv_at_barrier(cmd, p + h.size, end, true);"
    if rescan not in loop or loop.index(rescan) < loop.index("switch (h.op) {") or             loop.index(rescan) < loop.index("maybe_split(cmd);"):
        fail("vk_replay.cpp: the scan after the op that ended the last one is not made once the op (and a part's end) is recorded")
    if "da.op = p;" not in between(replay, "        case NOP_DRAW_MESH: {", "        case NOP_DISPATCH: {"):
        fail("vk_replay.cpp: a mesh draw does not carry its op")
    ops = between(replay, "static const uint32_t pass_ops[] = {", "};")
    return ops[len("static const uint32_t pass_ops[] = {"):]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "clang++"))
    parser.add_argument("--source", type=Path, default=ROOT, help="a checkout to check (the negative control: main)")
    args = parser.parse_args()
    cxx = shutil.which(args.cxx)
    if not cxx:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    src = args.source
    if not (src / "gpu/vk/mesh_conv.h").exists():
        fail("gpu/vk/mesh_conv.h is missing: no RX_VK_MESH_CONV")
    pass_ops = source_checks(src)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="longshot-mesh-conv-") as folder:
        tmp = Path(folder)
        (tmp / "mesh_conv_pass_ops.inc").write_text("#define PASS_OPS " + " ".join(pass_ops.split()) + "\n", encoding="utf-8")
        exe = tmp / ("mesh_conv.exe" if os.name == "nt" else "mesh_conv")
        cmd = [cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers", "-I" + str(src),
               "-I" + str(src / "gpu/render"), "-I" + str(tmp), str(ROOT / "tests/mesh_conv_test.cpp"), "-o", str(exe)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, creationflags=flags)
        if r.returncode:
            print(r.stdout + r.stderr)
            fail("the model did not build")
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120, creationflags=flags)
        print(r.stdout.strip())
        if r.returncode:
            fail("RX_VK_MESH_CONV's model: a draw read other records than its arguments'")
        for v in MUST_FAIL:
            r = subprocess.run([str(exe), v], capture_output=True, text=True, timeout=120, creationflags=flags)
            print(r.stdout.strip())
            if r.returncode == 0:
                fail("the broken variant %s was not caught" % v)
    print("PASS: RX_VK_MESH_CONV's slots and batch on the model (0, 1, 2 and flips between recordings); %d broken variants "
          "caught; the source's drops, switch read, ring fill and scan placement" % len(MUST_FAIL))


if __name__ == "__main__":
    main()
