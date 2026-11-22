# LaküenRecomp resync list

## Where we stand (2026-11-22)

- The original Hookshot repository is no longer reachable; its last state we have is `upstream/main` (2026-11-13). We carry
  all of it, plus about 140 commits of our own and ports (about 7,000 lines in 150 files).
- HeyListen branched from Hookshot on 2026-11-10 and moved everything under `engine/`. It lacks about 900 of Hookshot's last
  commits (for example the program cache, `vk_progcache.cpp`), and has about 1,560 of its own.
- ReLink is a squashed import of an older Hookshot state (2026-11-13, "0.6.1") without the builder and most tests.
- Longshot's public `dev` has not moved since 2026-11-11.

Tried and dropped: our delta on HeyListen's tree (181 conflicts, 19 files gone, Hookshot's last commits lost) and a full merge
of HeyListen (over 1,400 conflicts). The resync is done as larger blocks ported onto our base instead, on
`resync-upstream-2026-11`.

## What we have that the others have not (keep)

| Area | Change | Switch / note |
|---|---|---|
| Handheld | Task/mesh draws on the compute path on RADV RDNA2; handheld defaults for AMD integrated GPUs (RADV keeps the mesh optimizer) | |
| Handheld | Fixed render resolution per device (Deck 50 %, Legion Go S 67 %), Handheld profile once on AMD handhelds, RAM floor for textures, 2 GB cap | `LAKUEN_SHADOWS=0` |
| Handheld | Shadow maps at half size on AMD handhelds; shadow quality goes down (Medium, Low, Very low, Off) | |
| Handheld | Sleep timer on 8-thread Linux handhelds, frame generation off on first start; Legion Go S code tuning (Zen 3+) | |
| Handheld | Game Mode VRS drop (`RX_VK_HALF_RATE_SHADING` chosen by the driver environment) | `host/hos_main.c` |
| VRAM | Low-end defaults on cards of 8 GB or less, compaction off on integrated GPUs, 4 MB import chunks, import trim, eviction of the excess only, render targets let go as newer ones cover them, paging surge prevention | |
| VRAM | Dead targets every frame (`RX_VK_DEAD_EVERY`), memory freed off the render thread (`RX_VK_FREE_LATER`) | |
| Replay | Flat per-draw caches (`flat_map.h`), accessor-once in the hot calls, short command buffers skip the dry pass, staging arena tails suballocated, per-thread upload budget (`RX_VK_UPLOAD_BUDGET_SUM`) | |
| Replay | Ordered uniform updates (`RX_VK_UB_ORDERED`), uploads take only their own copies (`RX_VK_FIRST_UPLOAD_OWN`, `RX_VK_REUPLOAD_OWN`) | |
| Replay | Pipeline per program object (`RX_VK_PIPE_BY_PROGRAM`), light-meter-only readback (`RX_VK_READBACK_STRICT`, opt-in) | |
| Shaders | Prediction limits (300k SPIR-V words, 2 GB available), shader preparation all at start (profiles v4) | `predict_limits.h` |
| Effects | Exposure meter cleared on the GPU (`meter_zero_on` / `meter_hold_on`), effect passes 2 and 3 always drawn, fog density / brightness / ground fog rows | |
| Host | Virtual cores (`HOS_VCORES`), `HOS_OS_YIELD`, `HOS_VC_YIELD_FAST`, `HOS_CV_WAKE_SKIP`, discard yields its core, sync-object table with live bytes, used-memory query (`HOS_MEMINFO_OLD`) | |
| Host | Frame carry below 60 fps (`HOS_FRAME_CARRY`), map preload hold (`HOS_OCB_HOLD_MS`), three more whole-frame sites (song rhythm above 60 fps) | |
| Linux | Mesa submit thread from 12 hardware threads, game's SDL2 first under Steam, controller and gyroscope fixes, audio cushion 30 ms, builds at nice 10 | |
| Builder | LaküenRecomp builder (Linux and Windows): device profiles, master log of the last five runs, report zip, transfer saves, shut down / standby when done, in-app updates from this fork's releases | `builder/linux/*`, `builder/HookshotBuilder/*` |

## Ported onto the resync branch

| From | Change | Switch | Shader stamp |
|---|---|---|---|
| HeyListen c9603f6670 (Longshot 9027e7374, SadTransGirl) | Vegetation: indirect mesh draws keep their passes, arguments converted at the game's barriers | `RX_VK_MESH_CONV` (2 default, 1 ring fill only, 0 old way) | unchanged |

## What the others have that we have not (candidates)

| Source | Change | Note |
|---|---|---|
| HeyListen 97e584e325 (after Lichii bd0171f7, 282a585a) | Clustered lights sample their own shadow maps (handle tables as descriptor arrays) | `RX_VK_HANDLE_TABLES`; changes the shader stamp (one new preparation) |
| HeyListen | `HOS_EVENT_FAST`, `RX_VK_RETIRED_COMPACT`, `CAP_GET_FALLBACK`, `CAP_RANGES_REUSE`, `PASS_SAMPLE_MASK`, `DESC_POOL_KEEP` | not ported yet |
| HeyListen | Frames in flight (`RX_VK_FRAMES_IN_FLIGHT`, off by default), native main loop (`HL_MAINLOOP`, off by default) | large, depends on their native engine |
| HeyListen | Fixes above 60 fps | need HeyListen's hook system |
| ReLink | Upscalers' own sharpness, detailed FPS counter | check |

## Left out on purpose

- Windows/Nvidia-only work where it costs handheld performance.
- HeyListen's A/B counters (`HOS_AB`), Fritchii's experiment system.

## Open problems

- White haze ("sauna") on the PC: nobody upstream has fixed it; suspected in shader translation (precision or bloom), or in the
  fog / exposure workaround rows.
