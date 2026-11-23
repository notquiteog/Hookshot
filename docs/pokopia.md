# Pokémon Pokopia on this engine

*Pokémon Pokopia* (Switch 2) is being brought up on this engine as a new game: its game pack is `packs/pkp/pack.json`
(key `pkp`, chosen by main's build id). It is not released (`released: false`) and has no RecompLauncher tile until it
plays from `main` ([one-engine.md](one-engine.md), order of the work 5). Game data never enters this repository: the
dump is read where it lies, and the extraction, the lift and the builds stay in gitignored work folders. Where a value
comes from the game, this page says how it was found.

## 1. Where it stands (2026-11-22)

| | State |
|---|---|
| The build supported | program `0400A3A01EE4C000`, update **v655360** (the game calls it 2.0.1, Recompia "2.0.1a"), main build **`76a489f3bd3642fa5e18bd83d32c98bacc5f7d0e`**; modules main, sdk, subsdk0 (`multimedia_compat_nx`, nn::movie), rtld |
| Game pack | `pkp`: identity only, saves in `hookshot-pkp`, every profile value empty until measured |
| The dump on the developers' PC | `Pokémon Pokopia.nup` (7.17 GB): base v0 (exefs only) and update v655360 (exefs and the whole romfs). The romfs is complete: 36 files, 7,246,052,773 bytes, Recompia's count for a complete 2.0.1a romfs. **The exefs is damaged** (section 2) |
| Lift | not yet: stops on the damaged modules |
| Plays | not yet run |

### What a player (or the developer) needs

Pokopia **2.0.1a: update v655360, main build `76a489f3…`**, with the base game's romfs merged (a dump of the update
alone may hold 22 of the 36 romfs files, Recompia's fork #128). The exefs must be copied in **binary mode**. The base
game's own main (build `816c5358…`) is an older version, not this one.

## 2. The damaged exefs

`lift.py` stopped at once:

```
ValueError: .../exefs/main: segment 2 is outside the file or larger than any module (2760384 bytes at 0x322a000)
```

The `.nup` holds the modules as they were packed (each zstd frame decompresses to its listed size), but the modules
themselves are shorter than their NSO headers say: main by 980 bytes, sdk by 301, subsdk0 by 31. rtld and main.npdm are
whole, and their SHA-256s are the ones Recompia lists for this build (`game-build/release_b/dump_hashes.json`).

This is what a text-mode copy does (an FTP client's ASCII transfer type): it drops the CR of every CR LF pair. The
evidence:

- main holds 2 CR LF pairs where ~450 are expected in 29 MB of compressed data (sdk 2, subsdk0 1).
- Decoding a segment as LZ4 fails early (subsdk0's text after 42,176 of 518,035 bytes). Putting one CR back before an
  LF a few bytes before the failure lets the same decode run on another 107 KB, to the next failure.
- pokopia-native and Recompia check for exactly this before they build (`nso_short`, "a text-mode FTP copy drops a
  byte from every CR LF pair").

The fix is a new copy of the exefs in binary mode (37 MB: main, sdk, subsdk0, rtld, main.npdm), or a new dump; the
romfs need not be copied again. The builder now says so before it translates anything: `make_game.py`'s
`check_modules` names each short module (engine PR `fix/nso-text-mode-copy`).

Putting the CRs back without a new copy was tried and set aside. Each segment's SHA-256 in the NSO header would check a
repair. But the LZ4 decode often stays "valid" for tens of KB after a missing byte, and a parse that has gone wrong can
fall back into step. A CR placed anywhere in one literal run gives the same parse, so only the hash can choose among
those places. In the text segment, the first 1 KB window that stops decoding as AArch64 (real code ~0 undefined words
in 256, a wrong parse 80 to 190) finds most damage, but not all. The rodata and data segments have no such signal. With
980 places to fix in main alone, that is not worth it when a 37 MB copy fixes it.

Not this: `notquiteog/Elysium`'s `docs/pokopia-nso-format.md` reads the same modules as "an LZ4 variant" (offsets read
as offset - 1). That reading fits the same damage: a plain decode that stops early, segments that end past the file.

## 3. Recompia

[Recompia](https://github.com/Dittobyte/Recompia) (Dittobyte, read at `11953d69`, 2026-11-22, version 0.17.0) is a
full recompilation of this same build. It was read here as a source of facts.

### What it is

- **Licence:** GPL-3.0 (root `LICENSE`, `recomp/LICENSE`, `runtime/LICENSE`), with third-party notices in
  `runtime/THIRD_PARTY_NOTICES.md`, `recomp/THIRD_PARTY.md` and `tools/shaders/licenses/`. Code from it may come into
  this GPL-3.0-or-later project, with credit (as [longshot.md](longshot.md) does: repository, commit, author). A file
  it took from elsewhere carries that file's own licence: the parent project pokopia-native is MIT except its
  `ampere-lower/` (GPL-3.0-or-later), and some answers follow Ryujinx (MIT) or the yuzu family (GPL).
- **Not a Hookshot or NX2PC fork:** its own engine. It is built on
  [nxrecomp](https://github.com/drakolordx7/nxrecomp) (drakolordx7), through its parent project
  [pokopia-native](https://github.com/xFractals/pokopia-native) (xFractals, MIT). It has three parts:
  - a Python AArch64 → C++ lifter (`recomp/nxrecomp`, game config in `recomp/games/pkp/`);
  - a C++20 runtime, "nxrt" (`runtime/`): kernel, services, and NVN on Vulkan, with the game layer in
    `runtime/games/pkp/`;
  - a .NET 10 Maxwell/Ampere shader translator, and a Tauri launcher.
  It is Windows-first; Linux is native (formerly through Proton). It also has Android and macOS ports. Modules are
  placed at main `0x7100000000`, sdk `0x7500000000`, subsdk0 `0x7600000000`, rtld `0x7700000000`.
- **The build:** the same as ours. `recomp/games/pkp/config.py` `BUILDS` has the one main build `76A489F3…`
  ("2.0.1"), and `dump_hashes.json` has program `0400A3A01EE4C000`, "2.0.1 (update 655360)", and each module's
  SHA-256.
- **How far it gets:** all of it. The whole story plays on Windows, Linux, the Steam Deck and Android, with Link Play
  (LAN and relayed), seamless co-op, mods, HDR and 4K. Open in 0.17.0: some co-op edge cases, FSR 3 and DLSS that
  look wrong, a 4K crash in one loading scene (render targets now capped at 3840x2160), and the movies on macOS.

### What it found that this engine will meet

These are leads for the bring-up. Each one gets its own run and an answer written here, in an engine PR where it is
not Pokopia's alone.

| Area | Recompia's answer (file) | Here |
|---|---|---|
| `stpl:u` GameShare | `GetRequiredMemorySize` must be **non-zero** (1 page + 3 per guest): with 0 streamplay aborts (`runtime/src/services/misc_streamplay.cpp`). cmds 2, 3, 5, 7, 8, 9, 300, 502-510 answered, so hosting backs out with 0x3D1F | We answer 0 for Bananza (#14). If Pokopia aborts on it, find which SDK call makes the difference, rather than answering per game |
| Accounts | One user. `GetAccountId` differs per PC (needed for co-op only). `EnsureIdTokenCache` completes with a zero token. The licence-kind context fails 110-300 (`acc.cpp`) | Check against our `nn::account` |
| Applets | The software keyboard for the player's name: config 0x530 bytes, library version 0x140010, `use_utf8` at 0x3AA, and the `ngc:u` name check answered. The error applet is logged and returns success. Shop, MyPage and GameShare matchmaking return "cancelled" (128-22). Player select returns 0x27C. The inline keyboard is refused with 128-712, since 128-35 made the game svcBreak (`am.cpp`) | The name entry is on the first-start path: expect it early |
| Display, graphics | `nv::InitializeGraphics`, `GetGraphicsMemoryInfo`, `vi` display and layer, a 60 Hz vsync event (the first wait aborts without one), HDR luminance setters (`runtime/src/core/switch2.cpp`). `oe` GraphicsScale: word 10, level 0 = full quality | Our `oe::GetCurrentGraphicsScale` answers 1 by default (`graphics_scale` null): measure what the game makes of it, as Bananza's 0 was |
| Movies | subsdk0 is nn::movie. Two VP9 `.webm` movies late in the story (`movie_asset/ounce/MV01`, `MV02`), decoded with libvpx (`runtime/src/media/video_codec.cpp`) | Our VP9 path (Bananza's guide movies, #16, #41). `video_catchup` stays the default until a movie is seen |
| HID | Npad styles are the usual ones. The Joy-Con 2 mouse (cmds 3110-3143, `InitializeNmouse(buf 0xC000, 1920, 1080)`, `InitializeJcms`, `StartJcms` every frame) is used for placing blocks. cmd 214 is the Switch 2 vibration (`hid.cpp`, `hid_jc2_mouse.cpp`) | Check that our hid answers the mouse calls (a stub is enough to boot) |
| Saves | `account/<uid>/` with `G00/CMNDAT.BIN`, `B00/CMNDAT.BIN`, `S00/SYDAT.BIN`, plus STGDAT and SCSHDAT. Saves are journaled. Required size 0, so the data-erase applet is never reached. **RandomEntropy must be random**: a fixed value gave every save the same UUID (`svc_info.cpp`) | Check our `svcGetInfo` RandomEntropy |
| Memory | The game commits a **10.4 GiB heap** at start. Recompia advertises 10.5 GiB total and a 12 GiB heap region; its graphics pools are 332 MiB general and 3,500 MiB render targets (`svc_memory.cpp`, `pkp_gfx_heap.cpp`) | More than Bananza's ~9 GiB: check our total memory answer |
| Online | aoc serves DLC from a folder (Bubbly Basin `0400A3A01EE4D001`). friend, prepo, pctl and bcat are offline. nifm is offline, and its error handlers mean "the user backed out" | As our offline answers |
| NVN | NVN2 231.30, 215 of 726 procs used by main. The shader translator fixed the HFMA2/HADD2 `.H0_NH1` lane swap, and vertex outputs initialised to (0,0,0,1) (RADV drew a black sky and NaN bloom without it) | Renderer leads, general (engine PRs if they show here) |
| Lifter | ~130 function entries in main that discovery misses, used by the cloud island (`config.py` `extra_entries`). rtld's entry has no FDE. 5,077 of main's 5,958 non-PLT `br` are tail calls, not jump tables. Poll loops' loads are lifted as relaxed atomics | Our lift reports coverage: compare once it lifts |
| Speed | 10 poll sleeps of 1 s in boot cost ~12 s of a 45 s boot (hooked in `pkp_core.cpp`) | A patch module if it shows here |

Game hooks in `recomp/games/pkp/main.sites`: 276 mid-hooks, 160 entry hooks and 11 inline sites. Most are extras:
frame rate (multiplier at main+0xbfc4fc, the 60 Hz wait at +0x89e27c), aspect and ultrawide, LOD, the mouse camera,
menus, mods and co-op. One is a frame-boundary hook (+0x1fdcde4) for its play mode. Hooks for render targets above
1080p (+0x17b69e0, +0x17b509c, +0x17c0420, +0x1796810) and the graphics heap (+0x112f008, +0x112fb08) were needed
above 1080p: without them the game failed its init with svcBreak (its fork #49). Their addresses are main offsets of
this same build, so they apply here unchanged, as dkb-pc-recomp's did for Bananza.

### What was taken

No code. One idea, credited where it is used: the check that an NSO is shorter than its header (pokopia-native's
`nso_short`, MIT, carried by Recompia), written again as `make_game.py` `nso_short`.

## 4. Running it (once the dump is whole)

```sh
python -I nx2/make_game.py --nup "<Pokémon Pokopia.nup>" --out <game folder> --work <work folder> --no-prepare-shaders
python -I scripts/hookshot_ctl.py launch <game folder> --data <data folder> --env HOS_AUDIO=0 --env RX_VK_PRECOMPILE=0
```

The profile is chosen by the dump's build id, and the saves go to `hookshot-pkp` under `--data`. Use folders of
your own, never Ocarina's `~/Games/Hookshot` or `~/.local/share/hookshot`.
