/* (LaküenRecomp, from Longshot c88f7044 by SadTransGirl (#1814), via HeyListen bbc47d1a) The neighbouring map the
   OptimizeChangeBank thread preloads, kept while the game's choice only flickers: the lifted f_832b9880 hands its choice to
   hos_oot_ocb_pick before it asks for the unit and lets the others go (nx2/oot_patches.py, patch_ocb_hold); host/oot_ocb_hold.h
   has why and the rule.
   HOS_OCB_HOLD_MS=<ms>: a new choice is taken once it has stayed the choice that long (2000 with no switch); 0 or off: the
   game's own choice at every frame. */
#include "hos.h"
#include "oot_ocb_hold.h"
#include <pthread.h>
#include <stdlib.h>

#define OCB_HOLD_DEFAULT_MS 2000

static OotOcbHold hold = OOT_OCB_HOLD_INIT;
static pthread_mutex_t hold_lock = PTHREAD_MUTEX_INITIALIZER;   /* (one manager, updated once a frame; not relied on) */
static int64_t hold_ns = -1;                                    /* (read once, under hold_lock) */
static long long calls, held_back, taken;                       /* (under hold_lock: the log's counts) */

static uint64_t guest_load(void *ctx, uint64_t addr, int size) {
    Ctx *c = (Ctx *)ctx;
    return size == 1 ? recomp_load8(c, addr) : size == 4 ? recomp_load32(c, addr) : recomp_load64(c, addr);
}

/* chosen: the update's unit (x21, its low 32 bits; 0xffffffff none); mgr: the manager (x19). The unit it goes on with */
uint64_t hos_oot_ocb_pick(Ctx *c, uint64_t mgr, uint64_t chosen) {
    const int want = (int)(uint32_t)chosen;
    pthread_mutex_lock(&hold_lock);
    if (hold_ns < 0) {
        hold_ns = oot_ocb_hold_ms(getenv("HOS_OCB_HOLD_MS"), OCB_HOLD_DEFAULT_MS) * 1000000;
        if (hold_ns > 0)
            hos_log("ocb: a new neighbour to preload is taken once it stays the choice %lld ms (HOS_OCB_HOLD_MS; 0: the "
                    "game's own at every frame)", (long long)(hold_ns / 1000000));
    }
    int out = want;
    if (hold_ns > 0) {
        const int held = oot_ocb_held(guest_load, c, mgr), before = hold.cand;
        out = oot_ocb_pick(&hold, want, held, hold_ns, hos_now_ns());
        calls++;
        if (held >= 0 && want != held) {
            if (out == want) taken++;
            else if (hold.cand != before) held_back++;
        }
        if (calls % 18000 == 0)
            hos_log("ocb: %lld choices of another neighbour held back, %lld taken, in %lld updates", held_back, taken, calls);
    }
    pthread_mutex_unlock(&hold_lock);
    return (uint64_t)(uint32_t)out;
}
