/* (LaküenRecomp, from Longshot c88f7044 by SadTransGirl (#1814), via HeyListen bbc47d1a) The neighbouring map the OptimizeChangeBank thread preloads, kept while the game's choice only flickers.
   nx2/oot_patches.py hooks the place; host/oot_ocb_hold.c holds the state and reads the switch.

   OptimizeChangeBancMgr (vtable 0x84bc1a28) preloads one neighbouring map at a time: its layouts, then every actor pack
   and model in them, set up on its own thread (f_8002f7a0). Its per-frame update (f_832b9880) picks that map among up to 16
   units the current map lists (+0x408, 0x128 bytes each: +0 in use, +1 asked for, +4 position, +0x10 the layout's path,
   +0x120 LoadRadius, +0x124 priority), from Link's position (+0x1ce8) and velocity (+0x1cf4): of the units whose radius he is
   in, the one he moves towards (largest dot product) while he moves faster than 4 or for a while after (+0x1d38), else
   the nearest. Then it asks for that unit (f_832ba540) and lets go of every other one asked for before (f_832ba400).
   Asking for another map than the one loading or loaded (+0x70; the next one at +0x1e8) cancels it (state +0x2c = 5): the
   thread lets go of everything it set up, and then loads the new one from the start. When the choice flips back, the first
   map is read, decompressed and set up again. So a choice that flickers between two neighbours, or in and out of a radius,
   reloads them over and over with Link standing or circling on one spot: the loaders' ~0.8 of a core in the 4-core fountain
   basin.

   With a hold, a choice other than the map held (the one asked for: the next one, else the one loading or loaded) is taken
   only once it has stayed the choice that long; until then the update sees the held map chosen (asked for again: nothing
   happens; the others let go as before). A first choice (nothing held), a direct request (+0x28) and the game's other mode
   (+0x1d42, two units in turn) are the game's own.

   hold_ns: 0 or less, the game's own choice at every frame. now_ns: any clock that does not go back. */
#ifndef OOT_OCB_HOLD_H
#define OOT_OCB_HOLD_H
#include <stdint.h>

typedef struct {
    int cand;          /* (the choice that differs from the held map, -2: none) */
    int64_t since_ns;  /* (since when it has been the choice) */
} OotOcbHold;
#define OOT_OCB_HOLD_INIT {-2, 0}

/* The unit the update goes on with: chosen (-1: none in range) or held (-1: nothing held) */
static inline int oot_ocb_pick(OotOcbHold *s, int chosen, int held, int64_t hold_ns, int64_t now_ns) {
    if (hold_ns <= 0 || held < 0 || chosen == held) {
        s->cand = -2;
        return chosen;
    }
    if (s->cand != chosen) s->cand = chosen, s->since_ns = now_ns;
    if (now_ns - s->since_ns >= hold_ns) {
        s->cand = -2;
        return chosen;
    }
    return held;
}

/* The switch's value in ms: not set or empty, dflt_ms; a whole number of ms (0: the game's own); "off": 0; else dflt_ms */
static inline int64_t oot_ocb_hold_ms(const char *value, int64_t dflt_ms) {
    if (value && *value) {
        if (value[0] == 'o' && value[1] == 'f' && value[2] == 'f' && !value[3]) return 0;
        int64_t v = 0;
        int digits = 0;
        const char *p = value;
        for (; *p >= '0' && *p <= '9' && v < 100000000; p++) v = v * 10 + (*p - '0'), digits++;
        if (digits && !*p) return v;
    }
    return dflt_ms;
}

/* The manager's layout, as f_832b9880 / f_832ba540 / f_832ba400 read it */
enum {
    OCB_DIRECT = 0x28, OCB_STATE = 0x2c, OCB_CURRENT = 0x70, OCB_PENDING = 0x1e8, OCB_SLOTS = 0x408, OCB_SLOT_SIZE = 0x128,
    OCB_SLOT_PATH = 0x10, OCB_UNITS = 16, OCB_PATH_MAX = 0x100
};

/* Guest reads (size 1, 4 or 8 bytes) for oot_ocb_held: the lifted code's loads in the game, a buffer in the test */
typedef uint64_t (*OotOcbLoad)(void *ctx, uint64_t addr, int size);

static inline int oot_ocb_same(OotOcbLoad ld, void *ctx, uint64_t a, uint64_t b) {
    for (int i = 0; i < OCB_PATH_MAX; i++) {
        const uint64_t x = ld(ctx, a + i, 1);
        if (x != ld(ctx, b + i, 1)) return 0;
        if (!x) return 1;
    }
    return 1;
}

/* The unit (0-15) whose layout the manager mgr goes on with: the one asked for next (+0x1e8), else, while it loads or is
   loaded (state 1-4), the current one (+0x70); -1 when none, or a direct request (+0x28) is in */
static inline int oot_ocb_held(OotOcbLoad ld, void *ctx, uint64_t mgr) {
    if (ld(ctx, mgr + OCB_DIRECT, 1) & 1) return -1;
    const uint64_t pend = ld(ctx, mgr + OCB_PENDING, 8), cur = ld(ctx, mgr + OCB_CURRENT, 8);
    const uint32_t state = (uint32_t)ld(ctx, mgr + OCB_STATE, 4);
    uint64_t want = 0;
    if (pend && ld(ctx, pend, 1)) want = pend;
    else if (state >= 1 && state <= 4 && cur && ld(ctx, cur, 1)) want = cur;
    if (!want) return -1;
    for (int k = 0; k < OCB_UNITS; k++) {
        const uint64_t slot = mgr + OCB_SLOTS + (uint64_t)OCB_SLOT_SIZE * k;
        if (ld(ctx, slot, 1) != 1) continue;
        const uint64_t path = ld(ctx, slot + OCB_SLOT_PATH, 8);
        if (path && oot_ocb_same(ld, ctx, path, want)) return k;
    }
    return -1;
}
#endif
