# Donkey Kong Bananza on this engine

This branch (`fork/donkey-kong-bananza`) points Hookshot, the Ocarina of Time recompilation, at *Donkey Kong Bananza*
(Switch 2), the way Lakitu (Mario Kart World) and Dragoon (Kirby Air Riders) were started. Game data never enters
this repository: the dump is read where it lies, and the extraction, the lift and the builds stay in the gitignored
`work/`. Where a value comes from the game, this page says how it was found.

## 1. Where it stands (2026-11-13)

| | State |
|---|---|
| The dump | `Donkey Kong Bananza.nup`: base v0, update **v458752 (3.2.0)**, add-on content `040074a01bf13001` (romfs only, 7,270 files) |
| Identity | program `040074A01BF12000`, main build `e25c90c1c136638885659fd55bf8a03b3403489d`, sdk `18265dae...`, SDK and NVN 20.5.19, no subsdk modules |
| Game profile | `dkb` in `nx2/game_profile.py` on Hookshot's seam (#10), chosen by main's build id; identity, saves in `hookshot-dkb`, the movie catch-up off (`video_catchup`); proposed to main as notquiteog/Hookshot#42 |
| Lift | 188,678 functions, 9,102,462 instructions, **100.0000 %** translated, 2,175 jump tables, no TLS descriptors |
| Build | 24 min cold with 6 jobs on a loaded i5-13600K, under 2 min after a host change |
| Boot | **reaches gameplay**: the first-start menu (Normal / Assist Mode), the opening cutscene, the mining tunnel with the HUD, punching, walking, climbing, gold, NPC lines; 60 fps at 700-4,400 draws a frame on an RTX 5060 Ti (Linux, NVIDIA 615.71.09) |
| Where it stops | not found yet past the tunnel's guide movies: with the video buffer reservations (#41) the guide looped 52 times in 5 minutes without an abort (2026-11-14). Since #20, the boot needs the `EnsureSaveData` answer (#40) |

## 2. What stopped it, in boot order, and what fixed it

1. **`nup.py` crashed on the package's add-on content title** (no exefs, directory `0xffffffff`): `IndexError` before
   `make_game.py --check` could name the build. Absent parts now walk to nothing, and the default title is the newest
   one with an exefs. `tests/test_nup_addon_title.py`.
2. **`sm:` speaks TIPC on this firmware**, and its GetServiceHandle reply carried no handle, so the SDK aborted
   (`nn::streamplay::detail::CreateUserServiceByHipc`, svcBreak). `sm:` now answers TIPC, with a session per service
   whose requests are answered empty, and logs the service's name. `tests/test_sm_tipc.py`.
3. **Offline answers** the SDK gives when a thing is absent, where the generic stub said it was there:
   `streamplay::GetRequiredMemorySize` 0 (no GameShare), `bcat::MountDeliveryCacheStorage` 0x47a,
   `account::LoadCachedNintendoAccountInfo` 0x1907c, `account::GetLastOpenedUser` the one user.
4. **`hid::GetTouchScreenState<1>`**, the single-state read, aborted in the lifted SDK (as `GetNpadState` did for
   Dragoon). It is answered with no touch. After this the game reached its first-start menu.
5. **Guide movies through SDK 20's `nn::codec` forms** (`InitializeVp9Decoder` without an output mode, the
   out-pointer ready event, `CodecMode` preferences and pools, the work-buffer size, the native image handle): the
   stubs answered them and the movie thread aborted at the first punch. They now go to the libavcodec VP9 decoder
   already here, and the pool's size is written back at +0x20 / +0x22 where the player reads it.

Also fixed on the way, because they would have bitten any second game:

- **Saves.** On Linux every fork of this engine kept saves in `$XDG_DATA_HOME/hookshot`, so a second game would have
  read and overwritten Ocarina's. Each game now has its own folder (`GAME_SAVES_DIR`: Ocarina `hookshot`, Bananza
  `hookshot-dkb`), and a profile header without one does not compile.
- **The build's shader census** assumed Ocarina's `Pack/ZsDic.pack.zs` and failed at the end of every Bananza build.

## 3. Open, roughly in the order they stop play

1. **Fixed (notquiteog/Hookshot#41, #42): the movie player's abort.** The player counts what it submits; the runtime finished more buffers than that (an acquire before any submission was reached at the next one while its picture went elsewhere, and the end filled no buffer while acquires after it got one again) and the catch-up skipped pictures. Now an early acquire is reserved for the next picture, the end has its own picture, and Bananza's profile turns the catch-up off. The rest of this item is the history: **The movie player's abort** after many loops of a guide movie: `FATAL: the game aborted (nn::diag::detail::AbortImpl)
   (lr 0x80e3ae94)` on MovieOperateThread. The function at main+0xe1ada0 takes the first entry of a list at
   object+0xc30 under a lock and aborts when it is empty. Hookshot's decoder signals a buffer's sync point at once (or
   marks it idle); dkb-pc-recomp found the player needs it signalled only when a picture has been decoded into that
   buffer, up to 8 packets queued before a buffer is reserved, "not ready" as 0x1c266f, and a Flush that keeps
   pictures already decoded into reserved buffers. That model is the fix to write (their `runtime/ov_codec.c`).
2. **`nvnCommandBufferPushGraphicsConstants`** is not implemented (logged, answered 0). The game pushes
   `{1/w, 1/h, w, h}` into graphics root table 0, which its blit shaders read as bank 24 (dkb-pc-recomp). Nothing
   looked wrong yet.
3. **Virtual-core waits** of 200-850 ms appeared while the PC was loaded (load average 79, other builds). dkb-pc-recomp
   lists 23 recursive spin-lock loops in 3.2.0 main that stall heap and RomFS loads under virtual cores; measure
   on an idle PC before acting.
4. **Add-on content**: `aoc::CountAddOnContent` is the generic stub's 0, so the DLC (mounted as "EmeraldRush" on a
   console) is not offered. Not needed to play the base game.
5. **`oe::GetCurrentGraphicsScale`**: Hookshot answers Ocarina's meaning; Bananza maps an int enum 0..2 differently
   (dkb-pc-recomp answers 2). The game renders at its own 2880x1620 now.
6. **`oe::GetDisplayVersion`** answers "1.8.0" (the game logs `ReleaseVersion : 320 (nmeta=1.8.0)`). The update's
   real string is not in the dump; left alone.

## 4. dkb-pc-recomp: what was taken

[dkb-pc-recomp](https://github.com/Lucas-blip-png/dkb-pc-recomp) (`bananza` at `fac48bc`) already plays this game, on a
different architecture (TotK Recomp's: `recomp/`, `runtime/`). It is GPL-3.0-or-later as a whole, with the files from
TotK Recomp under MIT; there is no clause on later changes. Our dump's ExeFS is byte-identical to its `dkb458752`
target (SHA-256 of main, sdk, rtld and npdm all match), so its 3.2.0 findings apply unchanged.

No code was copied: Hookshot's host is shaped differently, and each answer was written here. What was taken are
facts it found by running the game, credited where they are used:

| Rank | Finding | Taken? |
|---|---|---|
| 1 | Offline answers on 3.2.0: streamplay memory 0, BCAT 0x47a, cached account 0x1907c, last opened user | yes (`host/nn_applet.c`) |
| 2 | SDK 20 `nn::codec` VP9 names, and the pool size at +0x20 / +0x22, the preference's +8 / +10 | yes (`host/nn_video.c`) |
| 3 | The movie player's sync-point model (signal on decode, 8 queued packets, 0x1c266f, Flush keeps pictures) | not yet: the next fix (section 3.1) |
| 4 | NVN2 procs Hookshot lacks (`DeviceGetFlags`, `RegisterFastClear*`, `DeviceMessageBuffer*`, `PushGraphicsConstants`, HDR window metadata, ...) | not needed so far: answered 0 and logged; only PushGraphicsConstants was called |
| 5 | Storage usage for colour textures the game binds as images (upscaler output) | not needed: the picture is right |
| 6 | NVN API minor 30 gate at main+0x5c61ac | not needed: Hookshot's 231.40 passes |
| 7 | Memory: below 8 GiB the game crashes at start; it asks ~9 GiB | already met (9,809 MB) |
| 8 | Spin-lock loop heads in 3.2.0 main | not yet: measure first (section 3.3) |
| 9 | Pacing: the 31.25 MHz tick, report timestamps, no held presents, or the game drops to 20 fps | not needed: 60 fps |
| 10 | `GetCurrentGraphicsScale` enum, dynamic-resolution controller sites (38db98 on 3.2.0), the 2880x1620 virtual display | not yet (quality, not boot) |
| 11 | Add-on content mount ("EmeraldRush") | not yet |
| 12 | Layer-change crash guards (1.0.0 only, main+0x410680) | not reached |

The full survey, with addresses, sources and licences, is kept with the session notes, outside this repository.

## 5. Running it here

The build and the runs use the repository's toolchain (`HOOKSHOT_JOBS` modest: the PC is shared):

```sh
python -I nx2/make_game.py --nup "<Donkey Kong Bananza.nup>" --out work/game --work work/build --no-prepare-shaders
python -I scripts/hookshot_ctl.py launch work/game --data work/data --env HOS_AUDIO=0 --env RX_VK_PRECOMPILE=0
```

`--data` keeps a run's saves in a folder of its own. Every run so far had `HOS_AUDIO=0`: sound is untested, and so
are Windows, AMD, a real controller (input came from the control bridge) and the add-on content. At the first start press A once the menu takes input (about 40 s
in), Normal Mode loads the opening; Y punches. Add `--env HOS_NO_MOVIES=1` to get past the guide movies until 3.1 is
fixed.
