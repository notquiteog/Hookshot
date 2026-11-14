# Play profiles

Profiles the build compiles with, committed so every build of a checkout uses the same ones: the release's builders,
a player's own build (with DLSS or FSR 4 too), and a developer's. Names of Longshot's own functions, a hash of each
one's shape and how often its branches ran: no game code or data.

## hookshot_vk.profdata.xz: the renderer's

The Vulkan back end's play profile (nx2/build.py `RX_VK_PGO`; docs/development.md, "The renderer's play profile"),
compressed with xz. `nx2/make_game.py` unpacks it into the work folder and builds the renderer with it, unless the
checkout's `work/hookshot_vk.profdata` or `RX_VK_PGO` says otherwise; `scripts/linux/appimage.sh` builds the
AppImage's renderer with it. A compiler that can't read it builds the renderer without it.

One profile for every build for now. It ages rather than breaks: a function changed since the recording is compiled as
if there were no profile, the rest keep theirs. Record it again before a release, and when the renderer has changed much.

- Recorded: 2026-11-14, one session of an `RX_VK_PGO=gen` renderer on main 0caf0618, counters cleared once Kokiri
  Forest had loaded and written at the end of the Market walk (Kokiri Forest standing, the teleport, the Market walk)
- GPU and driver: NVIDIA GeForce RTX 3090 (mesh shaders), Linux; Ryzen 9 7900X
- Compiler: the Linux builder's clang (LLVM 23.1.5), so C++ standard library names are libstdc++'s: Windows builds
  (llvm-mingw, libc++) match the renderer's own functions and leave the library's out
- Not yet: other areas (the pipeline tour), the compute fallback (no mesh shaders), a Windows recording
- Measured with it (the same PC, from the Market save, 3 sessions each, median frame): standing 13.53 / 13.49 /
  13.70 ms without, 12.96 / 13.37 / 12.94 ms with; running in the square 15.89 / 16.13 / 15.73 ms without,
  15.13 / 15.67 / 15.52 ms with: about -4 to -5 % standing and -3 % running
