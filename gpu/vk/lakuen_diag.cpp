// (LaküenRecomp) lakuen_diag.h: the visual problems' clues for the master log
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "lakuen_diag.h"
#include "vk_gprof.h"     // (the Effect finder's ranking: what the GPU drew most at a mark)
#include "vk_internal.h"  // (logf)
#include "vk_texture.h"   // (texture_frame_no)

namespace mkwvk {
namespace {

struct Unbound {
    uint64_t addr = 0, size = 0;
    uint64_t total = 0, window = 0;      // (the run's, and since the last summary)
    uint64_t first = 0, last = 0;        // (frames)
    int stage = 0;
    bool written = false;
};
std::mutex mu;
std::unordered_map<uint64_t, Unbound> unbound;   // (by program key)
std::atomic<uint64_t> wb_capture{0}, wb_readback{0};
std::atomic<uint64_t> wb_capture_frame{0}, wb_readback_frame{0};   // (the last one's)
std::atomic<bool> changed{false};

// (draws left out by the menu: few programs at a time, so a small table without a lock)
constexpr int kLeft = 8;
std::atomic<uint64_t> left_key[kLeft];
std::atomic<uint64_t> left_count[kLeft];

std::mutex notes_mu;
std::vector<std::string> notes;   // (the Effect finder's changes and the marks, 80 at most, oldest first)
int marks = 0;

std::string clock_now() {
    const time_t now = time(nullptr);
    tm t{};
#ifdef _WIN32
    localtime_s(&t, &now);
#else
    localtime_r(&now, &t);
#endif
    char b[16];
    strftime(b, sizeof b, "%H:%M:%S", &t);
    return b;
}

/// The programs reading zeros, the most first: those seen since frame `since` (0: all), n of them
std::vector<std::pair<uint64_t, Unbound>> top_unbound(uint64_t since, size_t n, bool by_window) {
    std::vector<std::pair<uint64_t, Unbound>> v;
    for (const auto& [k, u] : unbound)
        if (u.last >= since && (!by_window || u.window)) v.emplace_back(k, u);
    std::sort(v.begin(), v.end(), [&](const auto& a, const auto& b) {
        return by_window ? a.second.window > b.second.window : a.second.total > b.second.total;
    });
    if (v.size() > n) v.resize(n);
    return v;
}

void log_unbound(const char* tag, const std::vector<std::pair<uint64_t, Unbound>>& v, bool by_window) {
    for (const auto& [k, u] : v)
        logf("%s   reads zeros: program %016llx stage %d addr %#llx size %#llx%s: %llu times (frames %llu-%llu)", tag,
             (unsigned long long)k, u.stage, (unsigned long long)u.addr, (unsigned long long)u.size,
             u.written ? " (written)" : "", (unsigned long long)(by_window ? u.window : u.total), (unsigned long long)u.first,
             (unsigned long long)u.last);
}

} // namespace

std::string exposure_text();   // (vk_draw.cpp: the last 32 presents' exposure, "present:value ...")

void diag_note(const char* line) {
    std::lock_guard lk(notes_mu);
    if (notes.size() >= 80) notes.erase(notes.begin());
    notes.push_back(clock_now() + " " + line);
}

bool diag_on() {
    static const bool on = [] {
        const char* e = getenv("LAKUEN_DIAG");
        return !(e && e[0] == '0');
    }();
    return on;
}

void diag_unbound(uint64_t key, int stage, uint64_t addr, uint64_t size, bool written) {
    if (!diag_on()) return;
    const uint64_t f = texture_frame_no();
    std::lock_guard lk(mu);
    Unbound& u = unbound[key];
    if (!u.total) u.first = f, u.addr = addr, u.size = size, u.stage = stage, u.written = written;
    u.total++, u.window++, u.last = f;
    changed.store(true, std::memory_order_relaxed);
}

void diag_wb_timeout(bool readback) {
    if (!diag_on()) return;
    (readback ? wb_readback : wb_capture).fetch_add(1, std::memory_order_relaxed);
    (readback ? wb_readback_frame : wb_capture_frame).store(texture_frame_no(), std::memory_order_relaxed);
    changed.store(true, std::memory_order_relaxed);
}

void diag_left_out(uint64_t key) {
    if (!diag_on() || !key) return;
    for (int i = 0; i < kLeft; i++) {
        uint64_t k = left_key[i].load(std::memory_order_relaxed);
        if (!k) left_key[i].compare_exchange_strong(k, key);   // (k: what the slot holds now, key when it was free)
        if (!k || k == key) {
            left_count[i].fetch_add(1, std::memory_order_relaxed);
            return;
        }
    }
}

void diag_tick() {
    if (!diag_on()) return;
    using clock = std::chrono::steady_clock;
    static clock::time_point last = clock::now();
    static bool told_on = false;
    if (!told_on) {
        told_on = true;
        logf("lakuen-diag: on (LAKUEN_DIAG=0 turns it off): programs reading zeros, write-back timeouts and marks go into "
             "the master log");
    }
    const auto now = clock::now();
    if (now - last < std::chrono::seconds(30)) return;
    last = now;
    if (!changed.exchange(false)) return;
    const uint64_t f = texture_frame_no();
    std::lock_guard lk(mu);
    uint64_t window = 0;
    for (const auto& [k, u] : unbound) window += u.window;
    logf("lakuen-diag: %s frame %llu: %zu programs read zeros (%llu times in the last 30 s); write-back timeouts: %llu capture "
         "(last frame %llu), %llu readback (last frame %llu)",
         clock_now().c_str(), (unsigned long long)f, unbound.size(), (unsigned long long)window,
         (unsigned long long)wb_capture.load(), (unsigned long long)wb_capture_frame.load(),
         (unsigned long long)wb_readback.load(), (unsigned long long)wb_readback_frame.load());
    log_unbound("lakuen-diag:", top_unbound(0, 6, true), true);
    for (auto& [k, u] : unbound) u.window = 0;
}

void diag_mark(int n) {
    const uint64_t f = texture_frame_no();
    logf("lakuen-mark: #%d at %s, frame %llu", n, clock_now().c_str(), (unsigned long long)f);
    {
        char b[64];
        snprintf(b, sizeof b, "mark #%d at frame %llu", n, (unsigned long long)f);
        diag_note(b);
        marks = n;
    }
    if (!diag_on()) return;
    logf("lakuen-mark: #%d   exposure by present (about 0 or far off the others: the picture blown out): %s", n,
         exposure_text().c_str());
    {
        std::lock_guard lk(mu);
        const uint64_t since = f > 300 ? f - 300 : 0;   // (about the last 5 to 10 s)
        const auto v = top_unbound(since, 10, false);
        logf("lakuen-mark: #%d   %zu programs read zeros in the last 300 frames (%zu in the run)", n, v.size(), unbound.size());
        log_unbound("lakuen-mark:", v, false);
    }
    const uint64_t wc = wb_capture_frame.load(), wr = wb_readback_frame.load();
    logf("lakuen-mark: #%d   write-back timeouts: %llu capture (last %s), %llu readback (last %s); a readback that timed out "
         "reads what memory held, and the game's light level read back that way blows a scene out to white", n,
         (unsigned long long)wb_capture.load(), wc && f - wc < 300 ? "JUST NOW" : wc ? "earlier" : "none",
         (unsigned long long)wb_readback.load(), wr && f - wr < 300 ? "JUST NOW" : wr ? "earlier" : "none");
    for (int i = 0; i < kLeft; i++)
        if (const uint64_t k = left_key[i].load())
            logf("lakuen-mark: #%d   left out by the menu: program %016llx, %llu draws so far", n, (unsigned long long)k,
                 (unsigned long long)left_count[i].load());
    if (finder_on())
        for (int i = 0; i < 10; i++) {
            uint64_t k = 0;
            double ms = 0, draws = 0;
            if (!finder_entry(i, &k, &ms, &draws)) break;
            logf("lakuen-mark: #%d   GPU pass #%d: program %016llx %.2f ms, %.0f draws a frame", n, i + 1, (unsigned long long)k,
                 ms, draws);
        }
    else
        logf("lakuen-mark: #%d   (turn the Effect finder on for the passes the GPU drew most at the mark)", n);
}

bool diag_write_report(const std::string& path, const std::string& settings) {
    FILE* o = fopen(path.c_str(), "w");
    if (!o) {
        logf("lakuen-diag: %s could not be written", path.c_str());
        return false;
    }
    const uint64_t f = texture_frame_no();
    fprintf(o, "LaküenRecomp master log (debugging), made in the game at %s, frame %llu\n", clock_now().c_str(), (unsigned long long)f);
    fprintf(o, "The builder's lakuen_master_log.txt sums up whole runs after they end; this one is the moment you pressed the row.\n\n");
    const char* par = getenv("RX_VK_PARALLEL");
    fprintf(o, "--- switches\n  RX_VK_PARALLEL=%s (the Parallel recording row and the log's \"parallel recording\" line say what is in use)\n",
            par ? par : "(none)");
    for (const char* k : {"RX_VK_READBACK_WAIT_MS", "RX_VK_PRECOMPILE", "LAKUEN_DIAG", "HOS_AUDIO_PREBUFFER"})
        if (const char* v = getenv(k)) fprintf(o, "  %s=%s\n", k, v);
    fprintf(o, "\n--- settings (the menu's rows)\n%s\n", settings.c_str());
    fprintf(o, "--- exposure by present (the last 32; about 0, or far off the others: the picture blown out to white)\n  %s\n\n",
            exposure_text().c_str());
    fprintf(o, "--- write-back timeouts (the CPU then reads what memory held: the light level among them)\n");
    fprintf(o, "  capture: %llu (last frame %llu)\n  readback: %llu (last frame %llu)\n\n", (unsigned long long)wb_capture.load(),
            (unsigned long long)wb_capture_frame.load(), (unsigned long long)wb_readback.load(),
            (unsigned long long)wb_readback_frame.load());
    {
        std::lock_guard lk(mu);
        const auto v = top_unbound(0, 40, false);
        fprintf(o, "--- programs reading zeros (a storage buffer that could not be bound): %zu\n", unbound.size());
        for (const auto& [k, u] : v)
            fprintf(o, "  %016llx stage %d addr %#llx size %#llx%s: %llu times, frames %llu-%llu%s\n", (unsigned long long)k,
                    u.stage, (unsigned long long)u.addr, (unsigned long long)u.size, u.written ? " (written)" : "",
                    (unsigned long long)u.total, (unsigned long long)u.first, (unsigned long long)u.last,
                    f - u.last < 300 ? "  <- just now" : "");
        fprintf(o, "\n");
    }
    fprintf(o, "--- draws left out by the menu (Effect rows, Effect finder)\n");
    for (int i = 0; i < kLeft; i++)
        if (const uint64_t k = left_key[i].load())
            fprintf(o, "  %016llx: %llu draws\n", (unsigned long long)k, (unsigned long long)left_count[i].load());
    fprintf(o, "\n--- the Effect finder's ranking (GPU time a frame)%s\n", finder_on() ? "" : ": off (turn it on, restart)");
    for (int i = 0; finder_on() && i < 20; i++) {
        uint64_t k = 0;
        double ms = 0, draws = 0;
        if (!finder_entry(i, &k, &ms, &draws)) break;
        fprintf(o, "  #%-2d %016llx %.2f ms, %.0f draws\n", i + 1, (unsigned long long)k, ms, draws);
    }
    {
        std::lock_guard lk(notes_mu);
        fprintf(o, "\n--- this run's Effect finder changes and marks (%d marks)\n", marks);
        for (const auto& l : notes) fprintf(o, "  %s\n", l.c_str());
    }
    fclose(o);
    logf("lakuen-diag: master log (debugging) written: %s", path.c_str());
    return true;
}

} // namespace mkwvk
