// (longshot) The indirect mesh draws' arguments in Vulkan's layout (vk_draw.cpp mesh_indirect_convert): where a draw's
// {count, 1, 1} records go in the ring, and which draws after a barrier of the game's have theirs converted there all at once
// (RX_VK_MESH_CONV=2, vk_replay.cpp NOP_BARRIER). No Vulkan here: tests/mesh_conv_test.cpp runs it on a model of the stream.
//
// RX_VK_MESH_CONV:
//   0  each draw: its pass ended, a full drain, a fill of 1s, a barrier, the copy of its counts, a barrier, the pass begun again
//      with a full barrier (4 barriers, 3 of them drains, and a pass split a draw: the vegetation, ~39 draws a frame at the market)
//   1  the ring filled with 1s once, when it is made: a draw's copy writes only its x words, so the fill and its barrier go;
//      the copy sits between two full barriers, and the pass start right after the second is left out (full_barrier's dedupe)
//   2  as 1, and at each barrier of the game's (already a full one, with the pass ended), the indirect mesh draws up to the next
//      barrier are converted there at once, one full barrier after their copies: those draws no longer end their passes.
//      A draw the batch could not see (after an op that may write memory, a part's end) converts as in 1.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace mesh_conv {

constexpr uint64_t kRecord = 12;   // {x, y, z}: VkDrawMeshTasksIndirectCommandEXT
// (a slot's offset is a multiple of 48, the least common multiple of 16 and 12: every record's x word then lies at a ring byte
// that is 0 mod 12, its y and z words at 4 and 8 mod 12, whichever draw had the slot before. With slots at 16 bytes, a draw's
// x words landed on an earlier draw's y and z words (offset 0, then 16: byte 24 is the first's third x and the second's z), and
// a ring filled with 1s once would have drawn its counts as y = 7 workgroups)
constexpr uint64_t kSlotAlign = 48;
constexpr uint32_t kMaxRecords = 4096;   // (a draw's records: the game's max, clamped as vk_draw.cpp always did)

/// A draw's n records: their bytes in the ring, rounded up to a slot's alignment
constexpr uint64_t slot_bytes(uint32_t n) { return ((uint64_t)n * kRecord + kSlotAlign - 1) / kSlotAlign * kSlotAlign; }

/// The ring's next slot of n records. pos counts every byte the ring ever gave out (and the tail left over where a slot would
/// not fit before the ring's end): it never comes round, so a slot is known to be untouched while pos <= its start + ring
/// (still_holds). Returns the slot's offset in the ring; *start: its start on pos's count
inline uint64_t take(uint64_t& pos, uint64_t ring, uint32_t n, uint64_t* start) {
    const uint64_t bytes = slot_bytes(n);
    uint64_t off = pos % ring;
    if (off + bytes > ring) pos += ring - off, off = 0;   // (the tail: skipped, the slot at the ring's start)
    if (start) *start = pos;
    pos += bytes;
    return off;
}
/// No slot given out since the one that started at start has come round onto it (pos: the ring's count now)
constexpr bool still_holds(uint64_t pos, uint64_t start, uint64_t ring) { return pos <= start + ring; }

// ---- the batch at a barrier of the game's (RX_VK_MESH_CONV=2) ----

/// An indirect mesh draw the batch converts: its op in the stream (what identifies it when draw() gets to it) and its arguments
struct Item {
    const void* op = nullptr;
    uint64_t indirect = 0;
    int32_t max = 0, stride = 0;
};

/// What a stream op does to the batch's arguments read early, at the barrier, instead of at the draw.
enum class OpKind {
    Pass,   // records no GPU write to buffers in stream order: state, binds, draws, attachment clears, uniform updates (below)
    Draw,   // an indirect mesh draw (if it has an indirect address): converted with the batch
    Stop,   // may write buffer memory on the GPU, or ends the stretch: a barrier, a dispatch, a copy, a buffer or texture clear,
            // an event's signal or wait, a counter's report, the stream's end; and any op not known here
};
/// opcodes: rx_nvn.h's NOP_* (passed in so that the header needs no NVN types; vk_replay.cpp and the test give the real ones)
struct Ops {
    uint32_t end, barrier, draw_mesh;
    const uint32_t* pass;   // the ops that are Pass
    size_t npass;
};
inline OpKind kind_of(const Ops& ops, uint32_t op) {
    if (op == ops.draw_mesh) return OpKind::Draw;
    for (size_t i = 0; i < ops.npass; i++)
        if (ops.pass[i] == op) return OpKind::Pass;
    return OpKind::Stop;
}

/// Why a scan ended (the replay's counts of them, a log line every 120 frames)
enum Stop { kStopEnd, kStopBarrier, kStopOp, kStopFull, kStops };

/// The stream from p (the op after a barrier of the game's) on: the indirect mesh draws before the next barrier, the first op
/// that may write buffer memory, the stream's (or the segment's) end at `end` (null: its NOP_END), or the batch's limit
/// (most_bytes of ring slots, most draws). Records are {u32 op, u32 size (header included)} + payload, as in rx_nvn.h;
/// a NOP_DRAW_MESH's payload is {x, y, z, max, stride, kind; u64 indirect, count_addr}. *stop_op: the op it stopped at
/// (kStopOp); *at: where it stopped
inline Stop scan(const Ops& ops, const uint8_t* p, const uint8_t* end, std::vector<Item>& out, uint64_t most_bytes,
                 size_t most, uint32_t* stop_op, const uint8_t** at = nullptr) {
    out.clear();
    uint64_t bytes = 0;
    for (;;) {
        if (at) *at = p;
        if (p == end) return kStopEnd;
        uint32_t h[2];
        std::memcpy(h, p, sizeof h);
        if (h[0] == ops.end) return kStopEnd;
        if (h[0] == ops.barrier) return kStopBarrier;
        if (h[1] < 8) return kStopEnd;   // (a broken record: nothing after it is read)
        switch (kind_of(ops, h[0])) {
        case OpKind::Stop:
            if (stop_op) *stop_op = h[0];
            return kStopOp;
        case OpKind::Draw: {
            struct {
                int32_t x, y, z, max, stride, kind;
                uint64_t indirect, count_addr;
            } d{};
            std::memcpy(&d, p + 8, h[1] - 8 < sizeof d ? h[1] - 8 : sizeof d);
            if (!d.indirect) break;   // (a direct mesh draw: nothing to convert)
            const uint32_t n = (uint32_t)(d.max < 1 ? 1 : d.max > (int32_t)kMaxRecords ? kMaxRecords : d.max);
            if (out.size() >= most || bytes + slot_bytes(n) > most_bytes) return kStopFull;
            bytes += slot_bytes(n);
            out.push_back({p, d.indirect, d.max, d.stride});
            break;
        }
        case OpKind::Pass: break;
        }
        p += h[1];
    }
}

/// The converted draws of the last batch, on the recording thread: taken by draw() in stream order
struct Entry {
    const void* op = nullptr;
    uint64_t off = 0, start = 0;   // (the slot: its ring offset, its start on the ring's count)
};
struct Batch {
    const void* cmd = nullptr;   // (the command buffer the copies went into: a draw recorded into another one cannot use them)
    std::vector<Entry> e;
    size_t next = 0;
    void clear() { cmd = nullptr, e.clear(), next = 0; }
    bool live() const { return cmd && next < e.size(); }
    /// The slot of the draw at op recorded into cmd_now, or null: not in the batch, or the batch was dropped. Entries before it
    /// are passed over (draws the replay did not draw: render disabled, rasterizer discard)
    const Entry* take(const void* cmd_now, const void* op) {
        if (!cmd || cmd_now != cmd) return nullptr;
        for (size_t i = next; i < e.size(); i++)
            if (e[i].op == op) {
                next = i + 1;
                return &e[i];
            }
        return nullptr;
    }
};

} // namespace mesh_conv
