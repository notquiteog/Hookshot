"""The game profile: the one place that says which game a build is for, and which addresses, offsets and keys are
that game's rather than the engine's.

The lifter, the Horizon runtime and the Vulkan back end are general; a handful of things are not, and before this file
they were written as literals wherever they were needed: patch modules for one build of one game, offsets into one
game's graphics module, the return address that identifies that module, one game's shader program keys, and the one
build make_game.py accepts. Retargeting meant finding them all, which is the work this file exists to stop repeating.

This is the same seam as Lakitu's (the Mario Kart World fork: nx2/game_profile.py, game/game_profile.h, the GAME_*
macros), so that a profile written for one fork reads the same in the other. Dragoon adds three things it needs:

  - the game is chosen by the build id of the dump's main, as host/hos_main.c's hos_game_is_mkw() always did, and
    not only by a switch: for_build() below. HOOKSHOT_GAME=<key> still overrides it.
  - the return address the runtime captures the graphics module at (Hooks), which was the one place the runtime
    recognised Ocarina by an address on every run, whatever the game.
  - how many Npads the game is served by default (HOS_NPAD_PLAYERS still overrides it).

What belongs here: the game's identity (program id, version, main's build id) as nx2/dump.py reports it; the base of
its main in the lifted image; which lift patch modules and which code patch module apply; the offsets into its
graphics module the frame pacing reads; the return addresses the runtime recognises; the shader program keys the
renderer treats specially; its default player count. What does not: anything true of every Switch 2 title, and the C
text a patch writes, which lives with the patch.

An unknown value is None, never a plausible-looking number. None switches its feature off: the runtime never captures
a graphics module it has no return address for and skips a pacing field it has no offset for, saying so once; a game
with no patch modules is lifted without patches. A wrong address, by contrast, is silent corruption in someone's game.
Every lift patch module also checks the instruction word at each of its sites and leaves a site out when it differs,
so a profile aimed at the wrong build turns its patches off rather than writing C after the wrong instruction.

Which profile: HOOKSHOT_GAME=<key> if set; else the profile whose build id the dump's main has (for_build); else, with
no build id to go by (a build or a check without a dump), DEFAULT. A dump whose build no profile knows gets NONE, which
patches nothing and hooks nothing: lifting an unknown game must not apply Ocarina's patches to it.

    python -I nx2/game_profile.py                       # what the profiles hold
    python -I nx2/game_profile.py --emit-header         # rewrite game/game_profile.h (DEFAULT's) from this file
    python -I nx2/game_profile.py --check-header        # the committed header still matches (tests/test_game_profile.py)
    python -I nx2/game_profile.py --emit-header --game dkb --out <dir>   # one game's header, as a lift writes it
"""
import argparse
import collections
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = os.path.join(HERE, "..", "game", "game_profile.h")

# The project's own name, which is not game data. One constant, as in Lakitu's seam.
PROJECT = "Hookshot"

# The offsets into the game's graphics module that host/nn_vi.c reads (Lakitu's shape, field for field).
Gfx = collections.namedtuple("Gfx", "frame_limiter nominal_fps vrr_mode vrr_gate controller controller_words "
                                    "controller_rate_words")
EMPTY_GFX = Gfx(frame_limiter=None, nominal_fps=None, vrr_mode=None, vrr_gate=None, controller=None,
                controller_words=(), controller_rate_words=())

# The shader program keys the renderer treats specially (Lakitu's shape). A key is the 64-bit hash of a program's
# SASS, so it is per game and per build; the renderer takes prefixes, as its RX_VK_* overrides do.
#   taau:         programs the compute stand-in replaces (gpu/vk/vk_draw.cpp taau_key, RX_VK_TAAU_KEYS)
#   gameplay:     networks treated as the game's own upscale, never dropped when the movie networks are slow
#   network_keep: cooperative-matrix programs kept on cards that run them in software (gpu/vk/vk_shader.cpp)
Upscale = collections.namedtuple("Upscale", "taau gameplay network_keep")
EMPTY_UPSCALE = Upscale(taau=(), gameplay=(), network_keep=())

# (Dragoon) Return addresses the runtime recognises a call of the game's by. Each is the address after a bl in the
# game's main, so it is one build's and nothing else's: on another game the same number is some unrelated call.
#   gfx_clock:      after the graphics module's frame-end GetSystemTick; x19 there is the module (host/hos_thread.c).
#                   Without it no module is captured and nn_vi.c's real-time step and frame-limiter work stay off.
#   present_poll:   after the SleepThread of the present's GPU-event poll (HOS_PRESENT_POLL, HOS_SLEEP_LOG, and the
#                   frame-time breakdown's poll share: host/hos_thread.c)
#   present_events: the nvnEventGetValue calls of that poll (HOS_PRESENT_NOWAIT: host/nvn_native.c)
Hooks = collections.namedtuple("Hooks", "gfx_clock present_poll present_events")
EMPTY_HOOKS = Hooks(gfx_clock=None, present_poll=None, present_events=())


class Profile(object):
    """One game. Everything optional is None or empty when the profile does not know it yet."""

    def __init__(self, key, game, program_id=None, version=None, build_id=None, main_base=None,
                 patch_modules=(), code_patch_module=None, gfx=EMPTY_GFX, upscale=EMPTY_UPSCALE, hooks=EMPTY_HOOKS,
                 npad_players=1, account_users=1, notes=""):
        self.key = key                                # HOOKSHOT_GAME=<this>
        self.game = game                              # the game's name, for logs
        self.program_id = program_id                  # as nx2/dump.py reports it
        self.version = version                        # the update's version number (the .nup title's)
        self.build_id = build_id                      # main's whole build id: for_build() and make_game.py's gate
        self.main_base = main_base                    # main's base in the lifted image
        self.patch_modules = tuple(patch_modules)     # nx2 modules with install(lifter, img[, build_id]), in order
        self.code_patch_module = code_patch_module    # the nx2 module whose patches chunks.edit_c applies to the C
        self.gfx = gfx
        self.upscale = upscale
        self.hooks = hooks
        self.npad_players = npad_players              # 1..8, or "auto": one per attached controller
        self.account_users = account_users            # the console's users (nn::account), 1..8
        self.notes = notes

    def __repr__(self):
        return "<Profile %s: %s>" % (self.key, self.game)


OOT = Profile(
    key="oot",
    game="The Legend of Zelda: Ocarina of Time",
    program_id="0400486024DEC000",
    version=131072,                 # the update; base v65536
    build_id="e0f3ccfaf50065ae4ea01eb5aeb13b1a45da3348",
    main_base=0x80020000,           # after rtld's 0x20000 bytes in Eden's layout (nx2/image.py)
    # (the order lift.py has always installed them in: two modules may add C at one site, in this order)
    patch_modules=("oot_wide", "oot_fov", "oot_jitter", "oot_occlusion"),
    code_patch_module="oot_patches",
    gfx=Gfx(
        frame_limiter=0xfc,         # int: the rate f_8042cd20 sleeps to
        nominal_fps=0x2c8,          # int: the nominal rate the engine steps game time by (60 / it)
        vrr_mode=0x231,             # byte: logged beside the gate; 1 in every run seen
        vrr_gate=0x232,             # byte: f_804fc0f0 stores a rate into +0xfc only while this is set
        controller=0x270,           # the adaptive controller's object; the words below are offsets inside it
        controller_words=(0x58, 0x28, 0x2c, 0x30),       # what HOS_FPS_LOG prints: all four read 60 at 60 fps
        controller_rate_words=(0x58, 0x28, 0x2c),        # what HOS_FPS_FORCE raises (not +0x30, not nominal_fps)
    ),
    upscale=Upscale(
        taau=("fd029a317a9a4b94",),
        gameplay=(0xfd029a317a9a4b94, 0x9dc98871eb7fc101),
        # (9dc98871 resolves the dynamic-resolution scene to 2048x1152; left out, the 3D picture is black under the HUD)
        network_keep=("fd029a317a9a4b94", "9dc98871eb7fc101"),
    ),
    hooks=Hooks(
        gfx_clock=0x8348c770,       # main+0x346c770: after the bl of the graphics module's frame-end GetSystemTick
        present_poll=0x80590520,    # the SleepThread in 0x80590500's `while (nvnEventGetValue(e) != 1)` loop
        present_events=(0x805904a0, 0x80590530),
    ),
    npad_players=1,                 # Ocarina reads Npad No.1 alone, with every device merged into it
    account_users=1,                # one user, "Player": the one there always was
    notes="The game this engine was retargeted to; every value here was measured on its dump.",
)

DKB = Profile(
    key="dkb",
    game="Donkey Kong Bananza",
    # Measured on the dump (Donkey Kong Bananza.nup: base v0, update v458752, add-on content 040074a01bf13001) on
    # 2026-11-13: nx2/dump.py reported the program id and main's build id (sdk 18265dae..., SDK and NVN 20.5.19, no
    # subsdk modules), nx2/nup.py the update's version, and nx2/lift.py's image line put main at 0x80020000.
    program_id="040074A01BF12000",
    version=458752,
    build_id="e25c90c1c136638885659fd55bf8a03b3403489d",
    main_base=0x80020000,
    # Everything below is empty on purpose, as in Dragoon's Kirby profile: nothing game-specific has been found in this
    # build by this engine yet, and a number that looks right is worse than none. Each comment says how it would be
    # found. dkb-pc-recomp (docs/dkb-pc-recomp-survey in the shared notes) has addresses for this build in its own
    # layout; any taken from it must be checked against this lift's instruction words before it goes here.
    #   patch_modules / code_patch_module: none yet.
    patch_modules=(),
    code_patch_module=None,
    #   gfx: the graphics module's frame limiter and refresh gate (HOS_FPS_LOG once a module is known).
    gfx=EMPTY_GFX,
    #   upscale: program keys, from a run (RX_VK_SHADER_CENSUS). The game carries SMAA_For_NDSR.
    upscale=EMPTY_UPSCALE,
    #   hooks.gfx_clock: HOS_TICK_LOG=1 lists GetSystemTick's callers by return address.
    hooks=EMPTY_HOOKS,
    npad_players=1,
    account_users=1,
    notes="Identity measured on the dump; nothing game-specific found yet, so nothing is patched or hooked.",
)

# The profile for a dump whose build no profile knows: nothing patched, nothing hooked, one player.
NONE = Profile(key="none", game="an unknown game",
               notes="No profile knows this build: lifted without patches, and the runtime recognises nothing in it.")

GAMES = collections.OrderedDict((p.key, p) for p in (OOT, DKB, NONE))

# Ocarina stays the default where there is no dump to go by (the committed header, the game-free checks), because it
# is the only game whose values have been measured and checked by running it.
DEFAULT = "oot"


def for_build(build_id):
    """The profile whose build id is main's (a prefix of 8 or more hex digits matches, as the docs quote them), or
    NONE when no profile knows that build."""
    bid = (build_id or "").strip().lower()
    if len(bid) >= 8:
        for p in GAMES.values():
            if p.build_id and (p.build_id.startswith(bid) or bid.startswith(p.build_id)):
                return p
    return NONE


def active(env=None, build_id=None):
    """The profile this lift or build is for: HOOKSHOT_GAME, else the one for main's build id, else DEFAULT."""
    env = os.environ if env is None else env
    key = (env.get("HOOKSHOT_GAME") or "").strip().lower()
    if key:
        if key not in GAMES:
            raise SystemExit("HOOKSHOT_GAME=%s: no such game profile (have %s)" % (key, ", ".join(GAMES)))
        return GAMES[key]
    if build_id:
        return for_build(build_id)
    return GAMES[DEFAULT]


def known_builds():
    """The build ids make_game.py accepts, as (profile, the 8-digit prefix the messages quote)"""
    return [(p, p.build_id[:8]) for p in GAMES.values() if p.build_id]


# ---- the lift ----

def module(name):
    """A game's lift or code patch module by the name a profile gives it. Every one is imported here by name, inside
    this function so that only a lift loads them: nx2/make_game.py's lift_sources() follows import statements to key the
    lift's cache, and a module imported by a name made at run time would be a change to the lift it cannot see."""
    import oot_wide
    import oot_fov
    import oot_jitter
    import oot_occlusion
    import oot_patches
    found = {m.__name__: m for m in (oot_wide, oot_fov, oot_jitter, oot_occlusion, oot_patches)}
    if name not in found:
        raise SystemExit("game profile: no module %r: import it in nx2/game_profile.py's module()" % name)
    return found[name]


def install_patches(lifter, img, profile, build_id="", log=print):
    """The profile's lift patch modules, in its order; lift.py names no game's module itself. A module's install
    takes (lifter, img), or (lifter, img, build_id) when it gates on the build as nx2/oot_fov.py does."""
    if not profile.patch_modules:
        log("patches: the %s profile has no lift patch modules" % profile.key)
        return 0
    total = 0
    for name in profile.patch_modules:
        install = module(name).install
        n = len(inspect.signature(install).parameters)
        total += (install(lifter, img, build_id) if n >= 3 else install(lifter, img)) or 0
    return total


# ---- the C view ----
#
# host/ and gpu/ cannot import Python, so a profile is emitted as game_profile.h. DEFAULT's is committed in game/, so a
# build or a check with no dump needs no generation step (tests/test_game_profile.py fails when it drifts). A lift of a
# dump writes its own profile's header beside the lifted C (<work>/sa/game/game_profile.h), and nx2/build.py puts that
# folder ahead of game/, so the runtime and the renderer are compiled for the game they will run.

def _keys(prefixes):
    return ",".join(prefixes)


def _init(fmt, values):
    """A C array initializer. Empty is one zero, because `{ }` is not C and the count beside it is 0."""
    return "{ %s }" % (", ".join(fmt % v for v in values) if values else "0")


def emit_header(profile=None):
    p = GAMES[DEFAULT] if profile is None else profile
    out = []
    w = out.append
    w("/* The game profile, as C. GENERATED by nx2/game_profile.py --emit-header: do not edit.")
    w(" *")
    w(" * Edit nx2/game_profile.py and run `python -I nx2/game_profile.py --emit-header`. The committed copy is")
    w(" * checked against that file by tests/test_game_profile.py, so an edit here fails the suite. A lift writes the")
    w(" * dump's own profile beside its C, and the build reads that one first.")
    w(" *")
    w(" * A GAME_HAVE_<x> of 0 means this profile does not know that value. The code it guards must then leave the")
    w(" * thing alone rather than guess: an unknown offset is a feature that is off, not a number to invent. */")
    w("#ifndef GAME_PROFILE_H")
    w("#define GAME_PROFILE_H")
    w("")
    w("/* the project, which is not game data. GAME_PROJECT_W is the same name for the Win32 wide-string calls. */")
    w('#define GAME_PROJECT "%s"' % PROJECT)
    w('#define GAME_PROJECT_W L"%s"' % PROJECT)
    w("")
    w('#define GAME_PROFILE_KEY "%s"' % p.key)
    w('#define GAME_NAME "%s"' % p.game)
    w('#define GAME_PROGRAM_ID "%s"' % (p.program_id or ""))
    w("#define GAME_HAVE_PROGRAM_ID %d" % (1 if p.program_id else 0))
    w("#define GAME_VERSION %d" % (p.version or 0))
    w("#define GAME_HAVE_VERSION %d" % (1 if p.version else 0))
    w("/* main's build id: the runtime checks the image it runs against it before it recognises any address */")
    w('#define GAME_BUILD_ID "%s"' % (p.build_id or ""))
    w("#define GAME_HAVE_BUILD_ID %d" % (1 if p.build_id else 0))
    w("")
    w("/* main's base in the lifted image */")
    w("#define GAME_MAIN_BASE 0x%xull" % (p.main_base or 0))
    w("#define GAME_HAVE_MAIN_BASE %d" % (1 if p.main_base is not None else 0))
    w("")
    w("/* offsets into the game's graphics module (host/nn_vi.c's hos_gfx_module) */")
    for name, value in (("FRAME_LIMITER", p.gfx.frame_limiter), ("NOMINAL_FPS", p.gfx.nominal_fps),
                        ("VRR_MODE", p.gfx.vrr_mode), ("VRR_GATE", p.gfx.vrr_gate),
                        ("CONTROLLER", p.gfx.controller)):
        w("#define GAME_GFX_%s 0x%x" % (name, value or 0))
        w("#define GAME_GFX_HAVE_%s %d" % (name, 1 if value is not None else 0))
    w("#define GAME_GFX_CONTROLLER_WORDS %s" % _init("0x%x", p.gfx.controller_words))
    w("#define GAME_GFX_CONTROLLER_WORD_COUNT %d" % len(p.gfx.controller_words))
    w("#define GAME_GFX_CONTROLLER_RATE_WORDS %s" % _init("0x%x", p.gfx.controller_rate_words))
    w("#define GAME_GFX_CONTROLLER_RATE_WORD_COUNT %d" % len(p.gfx.controller_rate_words))
    w("")
    w("/* return addresses the runtime recognises the game's calls by (host/hos_thread.c, host/nvn_native.c) */")
    w("#define GAME_LR_GFX_CLOCK 0x%xull" % (p.hooks.gfx_clock or 0))
    w("#define GAME_HAVE_LR_GFX_CLOCK %d" % (1 if p.hooks.gfx_clock is not None else 0))
    w("#define GAME_LR_PRESENT_POLL 0x%xull" % (p.hooks.present_poll or 0))
    w("#define GAME_HAVE_LR_PRESENT_POLL %d" % (1 if p.hooks.present_poll is not None else 0))
    w("#define GAME_LR_PRESENT_EVENTS %s" % _init("0x%xull", p.hooks.present_events))
    w("#define GAME_LR_PRESENT_EVENT_COUNT %d" % len(p.hooks.present_events))
    w("")
    w("/* shader program keys this game's renderer treats specially; empty: none of them */")
    w('#define GAME_UPSCALE_TAAU_KEYS "%s"' % _keys(p.upscale.taau))
    w('#define GAME_NETWORK_KEEP_KEYS "%s"' % _keys(p.upscale.network_keep))
    w("#define GAME_GAMEPLAY_NETWORK_KEYS %s" % _init("0x%016xull", p.upscale.gameplay))
    w("#define GAME_GAMEPLAY_NETWORK_KEY_COUNT %d" % len(p.upscale.gameplay))
    w("")
    w("/* Npads served when HOS_NPAD_PLAYERS is unset: a count, or -1 for one per attached controller */")
    w("#define GAME_NPAD_PLAYERS %d" % (-1 if p.npad_players == "auto" else int(p.npad_players)))
    w("")
    w("/* the console's users (nn::account) when HOS_ACCOUNT_USERS is unset: host/nn_applet.c */")
    w("#define GAME_ACCOUNT_USERS %d" % int(p.account_users))
    w("")
    w("#endif /* GAME_PROFILE_H */")
    return "\n".join(out) + "\n"


def write_header(folder, profile):
    """The profile's header into folder/game_profile.h (a lift's <work>/sa/game), only when it changes, so a build
    after an unchanged lift does not rebuild the runtime for nothing. Returns the path."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "game_profile.h")
    text = emit_header(profile)
    try:
        with open(path, encoding="utf-8", newline="") as f:
            if f.read() == text:
                return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def header_path():
    return os.path.normpath(HEADER)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--emit-header", action="store_true", help="write game_profile.h (game/'s, or --out's)")
    p.add_argument("--check-header", action="store_true", help="exit 1 when the committed header does not match")
    p.add_argument("--game", help="a profile key (default: %s for the committed header)" % DEFAULT)
    p.add_argument("--build-id", help="choose the profile by main's build id, as a lift does")
    p.add_argument("--out", help="with --emit-header: the folder to write into instead of game/")
    a = p.parse_args(argv)
    if a.game:
        if a.game not in GAMES:
            p.error("no profile %r (have %s)" % (a.game, ", ".join(GAMES)))
        profile = GAMES[a.game]
    elif a.build_id:
        profile = for_build(a.build_id)
    else:
        profile = GAMES[DEFAULT]
    if a.check_header:
        text = emit_header(GAMES[DEFAULT])
        with open(header_path(), encoding="utf-8", newline="") as f:
            have = f.read()
        if have != text:
            print("%s is not what nx2/game_profile.py emits: run python -I nx2/game_profile.py --emit-header"
                  % header_path())
            return 1
        print("%s matches nx2/game_profile.py" % header_path())
        return 0
    if a.emit_header:
        if a.out:
            print("wrote %s for the %s profile" % (write_header(a.out, profile), profile.key))
            return 0
        if profile.key != DEFAULT:
            p.error("game/game_profile.h is %s's; write another game's with --out <folder>" % DEFAULT)
        with open(header_path(), "w", encoding="utf-8", newline="\n") as f:
            f.write(emit_header(profile))
        print("wrote %s for the %s profile" % (header_path(), profile.key))
        return 0
    for key, prof in GAMES.items():
        print("%s%s: %s" % ("* " if prof is profile else "  ", key, prof.game))
        print("    program %s, version %s, build %s" % (prof.program_id, prof.version, prof.build_id))
        print("    main base %s" % ("%#x" % prof.main_base if prof.main_base is not None else None))
        print("    lift patches %s, code patches %s" % (prof.patch_modules or None, prof.code_patch_module))
        print("    graphics module %s" % (prof.gfx,))
        print("    hooks %s" % (prof.hooks,))
        print("    upscale keys %s" % (prof.upscale,))
        print("    npad players %s, users %s" % (prof.npad_players, prof.account_users))
        print("    %s" % prof.notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
