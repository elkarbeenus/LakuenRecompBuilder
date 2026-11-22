// RX_VK_MESH_CONV (gpu/vk/mesh_conv.h) on a model of the replay: no Vulkan, no game data. tests/test_mesh_conv.py builds it
// with the replay's own list of the ops a batch scans past (vk_replay.cpp mesh_conv_at_barrier, cut into PASS_OPS).
//
// The model replays made-up command streams in order, as the GPU runs one queue: the game's indirect argument buffers, which
// dispatches, buffer clears and draws whose programs store to memory write; the ring of {x, y, z} records; and each indirect
// mesh draw's read of its records. Every draw must read {the count word of each of its arguments as they are at the draw, 1, 1},
// whichever way it was converted: RX_VK_MESH_CONV 0 (a fill and a copy at the draw), 1 (the copy alone, the ring filled with
// 1s once) and 2 (the copies at the barrier before it, when the batch's scan saw it and nothing that may write memory came
// between), the value changing between recordings as HOS_AB changes it, the recording ending in parts (a new command buffer).
// A small ring makes it come round often (the stale path), and a few draws are of 4096 records.
//
// Variants that must fail (argv[1]): align16 (slots at 16 bytes, as before: a later draw's x words land on y or z), no_drop
// (a draw that stores to memory does not drop the batch), clearbuf_passes (the scan steps over buffer clears, which drop
// nothing), no_hold (a slot the ring came round onto is used), rescan_before (the draws after the op a scan ended at converted
// before the op is recorded).
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <string>
#include <vector>

#define _Static_assert static_assert   // (rx_nvn.h is C)
#include "gpu/render/rx_nvn.h"
#include "gpu/vk/mesh_conv.h"
#include "mesh_conv_pass_ops.inc"   // (#define PASS_OPS: tests/test_mesh_conv.py, from vk_replay.cpp)

namespace {
std::string variant;

// ---- the stream ----
struct Stream {
    std::vector<uint8_t> b;
    template <class T>
    void op(uint32_t code, const T& payload) {
        const uint32_t size = (uint32_t)((8 + sizeof(T) + 7) & ~7u);
        const size_t at = b.size();
        b.resize(at + size);
        const uint32_t h[2] = {code, size};
        std::memcpy(&b[at], h, 8);
        std::memcpy(&b[at + 8], &payload, sizeof(T));
    }
    void bare(uint32_t code) {
        const uint32_t h[2] = {code, 8};
        const size_t at = b.size();
        b.resize(at + 8);
        std::memcpy(&b[at], h, 8);
    }
};
// (the model's own payloads where the real one does not matter: a write's target, a draw's "stores to memory")
struct Write {
    uint32_t buffer, first, n, value;
};
constexpr uint32_t kBuffers = 4, kWords = 4096 * 4 + 64;   // (each buffer: 4096 records of up to 16 bytes)
constexpr uint64_t kBase = 0x100000000ull, kSpan = 0x100000;   // (buffer i at kBase + i * kSpan)

Stream make_stream(std::mt19937& rng, int ops) {
    Stream s;
    auto pick = [&](int n) { return (int)(rng() % (uint32_t)n); };
    for (int i = 0; i < ops; i++) {
        const int r = pick(100);
        if (r < 12) {
            s.op(NOP_BARRIER, (int32_t)(pick(2) ? 0x28 : 0x12));
        } else if (r < 20) {   // (a dispatch: the GPU culling's, writing counts)
            s.op(NOP_DISPATCH, Write{(uint32_t)pick(kBuffers), (uint32_t)pick(kWords - 64), (uint32_t)(1 + pick(64)), (uint32_t)rng()});
        } else if (r < 21) {   // (an event's wait: what the CPU wrote taken at it)
            s.op(NOP_WAIT_EVENT, Write{(uint32_t)pick(kBuffers), (uint32_t)pick(kWords - 64), (uint32_t)(1 + pick(64)), (uint32_t)rng()});
        } else if (r < 23) {
            s.op(NOP_CLEAR_BUF, Write{(uint32_t)pick(kBuffers), (uint32_t)pick(kWords - 64), (uint32_t)(1 + pick(64)), (uint32_t)rng()});
        } else if (r < 55) {   // (an indirect mesh draw; now and then a direct one, or one of 4096 records)
            nvn_p_draw_mesh d{};
            d.kind = 2;
            d.max = pick(20) == 0 ? 4096 : 1 + pick(300);
            d.stride = pick(2) ? 8 : 16;
            d.indirect = pick(10) == 0 ? 0 : kBase + (uint64_t)pick(kBuffers) * kSpan + 4ull * (uint64_t)pick(64);
            s.op(NOP_DRAW_MESH, d);
        } else if (r < 63) {   // (a plain draw; one in four's program stores to memory)
            const bool stores = pick(4) == 0;
            s.op(NOP_DRAW, Write{stores ? (uint32_t)pick(kBuffers) : 0xFFFFFFFFu, (uint32_t)pick(kWords - 64), (uint32_t)(1 + pick(64)),
                                 (uint32_t)rng()});
        } else if (r < 70) {
            s.op(NOP_UPDATE_UB, nvn_p_update_ub{0x5000, 0});
        } else if (r < 74) {
            s.op(NOP_RENDER_ENABLE, nvn_p_flag{pick(5) ? 1 : 0, 0});
        } else if (r < 76) {
            s.op(NOP_REPORT_COUNTER, nvn_p_counter{0, 0x6000});
        } else if (r < 78) {
            s.op(NOP_RESET_COUNTER, nvn_p_counter{0, 0x6000});
        } else {
            s.op(NOP_BIND_PROGRAM, nvn_p_bind_program{nullptr, 0});
        }
    }
    s.bare(NOP_END);
    return s;
}

// ---- the replay and the GPU, in order ----
struct Model {
    uint64_t ring_bytes;
    std::vector<uint32_t> ring;   // (words)
    uint64_t ring_at = 0;         // (mesh_conv::take's count)
    std::vector<std::vector<uint32_t>> args;
    mesh_conv::Batch batch;
    int mode = 0;
    uintptr_t cmd = 1;   // (the command buffer being recorded: a part's end begins another)
    long draws = 0, batched = 0, single = 0, stale = 0, dropped = 0, wrong = 0;
    std::string first_wrong;

    explicit Model(uint64_t ring) : ring_bytes(ring), ring(ring / 4, 0xDEADBEEFu), args(kBuffers, std::vector<uint32_t>(kWords)) {
        std::fill(this->ring.begin(), this->ring.end(), 1u);   // (vk_draw.cpp mesh_ring_make: filled with 1s once)
        uint32_t v = 7;
        for (auto& a : args)
            for (auto& w : a) w = v = v * 1103515245u + 12345u;
    }
    uint64_t take(uint32_t n, uint64_t* start) {
        if (variant == "align16") {   // (the slots as they were: 16-byte aligned)
            const uint64_t bytes = ((uint64_t)n * 12 + 15) & ~15ull;
            uint64_t off = ring_at % ring_bytes;
            if (off + bytes > ring_bytes) ring_at += ring_bytes - off, off = 0;
            *start = ring_at;
            ring_at += bytes;
            return off;
        }
        return mesh_conv::take(ring_at, ring_bytes, n, start);
    }
    void write(const Write& w) {
        if (w.buffer >= kBuffers) return;
        for (uint32_t i = 0; i < w.n; i++) args[w.buffer][w.first + i] = w.value + i;
    }
    uint32_t arg_word(uint64_t indirect, uint64_t byte) const {
        const uint64_t a = indirect - kBase + byte;
        return args[(size_t)(a / kSpan)][(size_t)(a % kSpan / 4)];
    }
    /// a draw's records copied into its slot (mode 0: the slot filled with 1s first)
    void convert(const nvn_p_draw_mesh& d, uint64_t off, bool fill) {
        const uint32_t n = (uint32_t)std::clamp(d.max, 1, 4096);
        const uint32_t stride = d.stride > 0 ? (uint32_t)d.stride : 8;
        if (fill)
            for (uint32_t i = 0; i < n * 3; i++) ring[(size_t)(off / 4) + i] = 1;
        for (uint32_t i = 0; i < n; i++) ring[(size_t)((off + i * mesh_conv::kRecord) / 4)] = arg_word(d.indirect, (uint64_t)i * stride);
    }
    /// another recording thread's draw: its slot taken from the same ring and written (counts of its own, the fill as mode 0)
    void foreign(std::mt19937& rng) {
        const uint32_t n = 1 + rng() % 2000;
        uint64_t start = 0;
        const uint64_t off = take(n, &start);
        for (uint32_t i = 0; i < n * 3; i++) ring[(size_t)(off / 4) + i] = i % 3 ? 1u : rng();
    }
    void drop() {
        if (batch.live()) dropped += (long)(batch.e.size() - batch.next);
        batch.clear();
    }
    const uint8_t* rescan = nullptr;   // (vk_replay.cpp mesh_rescan_at)
    /// right after a barrier of the game's, or right after the op the last scan ended at (vk_replay.cpp mesh_conv_at_barrier)
    void at_barrier(const uint8_t* next, const mesh_conv::Ops& ops, const mesh_conv::Ops& any) {
        batch.clear();
        rescan = nullptr;
        if (mode < 2) return;
        std::vector<mesh_conv::Item> items, after;
        uint32_t stop = 0;
        const uint8_t* at = nullptr;
        if (mesh_conv::scan(ops, next, nullptr, items, ring_bytes / 4, 256, &stop, &at) == mesh_conv::kStopOp) rescan = at;
        (void)any, (void)after;
        for (const auto& it : items) {
            nvn_p_draw_mesh d{};
            d.max = it.max, d.stride = it.stride, d.indirect = it.indirect;
            uint64_t start = 0;
            const uint64_t off = take((uint32_t)std::clamp(it.max, 1, 4096), &start);
            convert(d, off, false);
            batch.e.push_back({it.op, off, start});
        }
        batch.cmd = (const void*)cmd;
    }
    void draw_mesh(const uint8_t* op, const nvn_p_draw_mesh& d) {
        if (!d.indirect) return;
        uint64_t off = 0;
        bool have = false;
        if (mode >= 2) {
            if (const mesh_conv::Entry* e = batch.take((const void*)cmd, op)) {
                if (variant == "no_hold" || mesh_conv::still_holds(ring_at, e->start, ring_bytes)) {
                    off = e->off, have = true, batched++;
                } else {
                    stale++;
                }
            }
        }
        if (!have) {
            uint64_t start = 0;
            off = take((uint32_t)std::clamp(d.max, 1, 4096), &start);
            convert(d, off, mode == 0);
            single++;
        }
        // (the GPU's read: as many records as were converted, each {count word, 1, 1})
        draws++;
        const uint32_t n = (uint32_t)std::clamp(d.max, 1, 4096), stride = d.stride > 0 ? (uint32_t)d.stride : 8;
        for (uint32_t i = 0; i < n; i++) {
            const uint32_t* r = &ring[(size_t)((off + i * mesh_conv::kRecord) / 4)];
            const uint32_t want = arg_word(d.indirect, (uint64_t)i * stride);
            if (r[0] != want || r[1] != 1 || r[2] != 1) {
                if (!wrong++) {
                    char b[200];
                    snprintf(b, sizeof b, "draw %ld (mode %d) record %u: {%u, %u, %u}, the arguments say {%u, 1, 1}", draws, mode, i,
                             r[0], r[1], r[2], want);
                    first_wrong = b;
                }
                break;
            }
        }
    }
};

int run_one(uint32_t seed, uint64_t ring, const mesh_conv::Ops& ops, const mesh_conv::Ops& any, Model& m) {
    std::mt19937 rng(seed);
    const Stream s = make_stream(rng, 4000);
    const uint8_t* p = s.b.data();
    bool enabled = true;
    for (;;) {
        if (rng() % 97 == 0) m.mode = (int)(rng() % 3), m.batch.clear(), m.cmd++;   // (a new recording: HOS_AB's value read)
        else if (rng() % 151 == 0) m.cmd++;                                       // (a part's end: a new command buffer)
        if (rng() % 7 == 0) m.foreign(rng);   // (another segment's thread converting a draw of its own into the shared ring)
        uint32_t h[2];
        std::memcpy(h, p, 8);
        if (h[0] == NOP_END) break;
        const uint8_t* a = p + 8;
        // (rescan_before: the draws after the op that ended a scan converted before that op, not after it)
        if (variant == "rescan_before" && p == m.rescan) m.at_barrier(p + h[1], ops, any);
        switch (h[0]) {
        case NOP_BARRIER: m.at_barrier(p + h[1], ops, any); break;
        case NOP_WAIT_EVENT:   // (met: the CPU's data taken for what follows it, vk_replay.cpp resume_queue's capture)
        case NOP_DISPATCH: case NOP_CLEAR_BUF: {   // (the GPU writes the buffer; a dispatch drops the batch, vk_draw.cpp dispatch())
            Write w;
            std::memcpy(&w, a, sizeof w);
            if (h[0] == NOP_DISPATCH) m.drop();
            m.write(w);
            break;
        }
        case NOP_DRAW: {   // (vk_draw.cpp draw(): a program that writes memory drops the batch, then the draw writes)
            Write w;
            std::memcpy(&w, a, sizeof w);
            if (!enabled) break;
            if (w.buffer < kBuffers && variant != "no_drop") m.drop();
            m.write(w);
            break;
        }
        case NOP_RENDER_ENABLE: {
            nvn_p_flag f;
            std::memcpy(&f, a, sizeof f);
            enabled = f.value != 0;
            break;
        }
        case NOP_DRAW_MESH: {
            nvn_p_draw_mesh d;
            std::memcpy(&d, a, sizeof d);
            if (enabled) m.draw_mesh(p, d);
            break;
        }
        default: break;
        }
        if (variant != "rescan_before" && p == m.rescan) m.at_barrier(p + h[1], ops, any);   // (replay(): after the op)
        p += h[1];
    }
    (void)ring;
    return m.wrong ? 1 : 0;
}
} // namespace

int main(int argc, char** argv) {
    variant = argc > 1 ? argv[1] : "";
    // (the replay's list, from vk_replay.cpp; clearbuf_passes adds buffer clears to it)
    std::vector<uint32_t> pass = {PASS_OPS};
    if (variant == "clearbuf_passes") pass.push_back(NOP_CLEAR_BUF);
    const mesh_conv::Ops ops{NOP_END, NOP_BARRIER, NOP_DRAW_MESH, pass.data(), pass.size()};
    std::vector<uint32_t> all;
    for (uint32_t o = 0; o < NOP_COUNT_; o++)
        if (o != NOP_END && o != NOP_BARRIER && o != NOP_DRAW_MESH) all.push_back(o);
    const mesh_conv::Ops any{NOP_END, NOP_BARRIER, NOP_DRAW_MESH, all.data(), all.size()};
    // (the scan: what it stops at and what it passes, against rx_nvn.h's ops)
    for (uint32_t o : {(uint32_t)NOP_DISPATCH, (uint32_t)NOP_DISPATCH_INDIRECT, (uint32_t)NOP_COPY_B2B, (uint32_t)NOP_CLEAR_BUF,
                       (uint32_t)NOP_SIGNAL_EVENT, (uint32_t)NOP_WAIT_EVENT, (uint32_t)NOP_COPY_B2T, (uint32_t)NOP_COPY_T2B,
                       (uint32_t)NOP_COPY_T2T, (uint32_t)NOP_CLEAR_TEX, (uint32_t)NOP_REPORT_COUNTER})
        if (variant.empty() && mesh_conv::kind_of(ops, o) != mesh_conv::OpKind::Stop) {
            printf("FAIL: the scan steps over op %u, which may write buffer memory\n", o);
            return 1;
        }
    // (slots: every x word at 0 mod 12, slots never overlapping while the ring holds them)
    {
        uint64_t pos = 0, start = 0;
        for (uint32_t n = 1; n < 5000; n += 7) {
            const uint64_t off = mesh_conv::take(pos, 1 << 20, n % 4097 ? n % 4097 : 1, &start);
            if (off % 48 || off + mesh_conv::slot_bytes(n % 4097 ? n % 4097 : 1) > (1u << 20) || start % (1 << 20) != off) {
                printf("FAIL: slot %llu of %u records\n", (unsigned long long)off, n);
                return 1;
            }
        }
    }
    long draws = 0, batched = 0, single = 0, stale = 0, dropped = 0, wrong = 0;
    std::string first;
    for (uint32_t seed = 1; seed <= 60; seed++) {
        const uint64_t ring = seed % 3 == 0 ? (64u << 10) : seed % 3 == 1 ? (256u << 10) : (4u << 20);
        Model m(ring);
        m.mode = (int)(seed % 3);
        run_one(seed, ring, ops, any, m);
        draws += m.draws, batched += m.batched, single += m.single, stale += m.stale, dropped += m.dropped, wrong += m.wrong;
        if (m.wrong && first.empty()) first = "seed " + std::to_string(seed) + ": " + m.first_wrong;
    }
    printf("%s: %ld indirect mesh draws, %ld from a batch, %ld converted at the draw, %ld batch slots the ring came round "
           "onto, %ld batch draws dropped after a write; %ld read records other than their arguments'%s%s\n",
           variant.empty() ? "mesh_conv" : variant.c_str(), draws, batched, single, stale, dropped, wrong, first.empty() ? "" : ": ",
           first.c_str());
    if (variant.empty() && (batched < draws / 10 || !stale || !dropped)) {
        printf("FAIL: the model did not reach every path (batched, stale, dropped)\n");
        return 1;
    }
    return wrong ? 1 : 0;
}
