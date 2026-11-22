"""The Builders' game library: every game that builds (nx2/game_profile.py), installed or not, under the base of the Builder's
game folder, read from the one core the three Builders share (`nx2/game_folders.py --library <base> --json`), each row with its
state and Install, Update, Play and Open folder, and Update all (`nx2/make_game.py --update-all`, its `--dry-run` first,
followed by its @@game lines). Game-free: placeholder folders and a placeholder NSO header only; no build runs.

Checked here:
  - nx2/game_folders.py: built_games, base_of and folder_game over placeholder folders (the fallback without the tools), and
    the helpers the Builders name and follow games by: folder_key, shortcut_name (the default game's stays "Hookshot", so a
    player's Hookshot.lnk and hookshot.desktop are the ones made again), title_parts, update_line, copy_key, installed_folders;
  - the Linux Builder (builder/linux/hookshot_builder.py): its form shows the library (library_for runs --library --json),
    Update all runs --update-all --dry-run then --update-all, the self-update after a new Builder updates every game
    (start_make_update), Install and a checked copy of another game use --base, @@game lines are followed, Play starts the
    row's folder, the launcher page and the menu entries are named by the folder's game (one .desktop per game, Ocarina's
    hookshot.desktop "Hookshot" unchanged), and its strings are the shared table's; library_for, game_results, menu_entry,
    add_to_menu and result_text run over placeholder folders;
  - the Qt Builder (builder/py): the same calls (core.library, update_all_click, start_update_all, updater.update_folder's
    update_build_or_all, install_game, build_where, game_framed), its shortcuts and launcher page named by the game, and
    strings.py made from Strings.cs (gen_strings.py) with the library's keys;
  - the WPF Builder (builder/HookshotBuilder): the same calls (Runner.Library, UpdateAllClick, StartUpdateAll,
    Updater.UpdateFolder's UpdateBuildOrAll, InstallGame, BuildWhere, GameFramed), Finder's shortcuts per game with
    Hookshot.lnk for the default one, the launcher page's LaunchSeries/LaunchTitle, Games.cs's profiles and default key
    game_profile.py's, and every language of Strings.cs translating the library's strings; and with .NET, Games.cs compiled
    with tests/builder_games_test.cs answers as game_folders.py does: the games and folders, folder_key, shortcut_name,
    title_parts, update_line, copy_key, the parsed --library --json and Update all's results.

    python -I -B tests/test_builder_games.py [--dotnet dotnet]
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

# (no {dotnet} here: run_all would skip the whole check without it, and only the fixture needs it. On Windows it is required)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import game_folders  # noqa: E402
import game_profile  # noqa: E402

failures = []


def check(ok, what):
    if not ok:
        failures.append(what)
        print("FAIL: " + what)


def placeholder(folder, build_id=None, exe=os.path.join("bin", "hookshot.exe"), image=True, kept=False, version=None):
    """A folder that looks built: image.bin and the game's executable, empty; with build_id, a copy's main that is only an NSO
    header naming that build; kept, a romfs folder beside it (the game files an update builds from); version, its
    hookshot_version.txt"""
    os.makedirs(os.path.join(folder, os.path.dirname(exe) or "."), exist_ok=True)
    open(os.path.join(folder, exe), "wb").close()
    if image:
        open(os.path.join(folder, "image.bin"), "wb").close()
    if build_id:
        os.makedirs(os.path.join(folder, ".hookshot_exefs"), exist_ok=True)
        with open(os.path.join(folder, ".hookshot_exefs", "main"), "wb") as f:
            f.write(b"NSO0" + b"\0" * 0x3c + bytes.fromhex(build_id.ljust(64, "0")))
    if kept:
        os.makedirs(os.path.join(folder, "romfs"), exist_ok=True)
    if version:
        with open(os.path.join(folder, "hookshot_version.txt"), "w", encoding="utf-8") as f:
            f.write("version=%s\n" % version)


def windows_exe(folder):
    """The WPF and Qt Builders' check (Games.cs GameExe, core.game_exe): bin/hookshot.exe, or hookshot.exe"""
    for exe in (os.path.join(folder, "bin", "hookshot.exe"), os.path.join(folder, "hookshot.exe")):
        if os.path.isfile(exe):
            return exe
    return None


def profile(key):
    return game_profile.GAMES[key]


def other_keys():
    """The profiles that build other than the default one, in order"""
    return [p.key for p in game_folders.buildable() if p.key != game_profile.DEFAULT]


def between(src, start, end):
    """The source from start to end (both texts in it), for the checks that read a function's text"""
    a = src.index(start)
    return src[a:src.index(end, a + len(start))]


def method(src, name, lang="py"):
    """A method's text (a class's, or the module's when top), from its def to the next one at the same indent"""
    if lang in ("py", "top"):
        head = "\n    def " if lang == "py" else "\ndef "
        a = src.index(head + name + "(")
        b = src.find(head, a + 1)
        return src[a:b if b > 0 else len(src)]
    a = src.index(name)
    b = re.search(r"\n    (?:///|\S[^\n]*\)\s*(?:=>|\n\s*\{))", src[a + len(name):])
    return src[a:a + len(name) + (b.start() if b else len(src))]


# ---------------- the core's helpers ----------------

def check_game_folders(tmp):
    games = os.path.join(tmp, "Games")
    base = os.path.join(games, "Hookshot")
    first, second = other_keys()[:2]
    placeholder(base, profile(game_profile.DEFAULT).build_id)
    placeholder(base + "-" + second, profile(second).build_id, exe="hookshot.exe")   # (a folder built before the launcher)
    placeholder(base + "-" + first, profile(first).build_id, image=False)            # (not built: no image.bin)
    other = os.path.join(games, "Elsewhere")
    placeholder(other, profile(second).build_id)                                       # (built into the folder the player chose)
    placeholder(os.path.join(games, "NoCopy"))                                         # (no copy kept: named by the rule's profile)

    check([p.key for p in game_folders.buildable()] == [p.key for p in game_profile.GAMES.values() if p.build_id],
          "buildable() is every profile that names a build, in order")
    want = [(game_profile.DEFAULT, profile(game_profile.DEFAULT).game, base), (second, profile(second).game, base + "-" + second)]
    for out in (base, base + os.sep, base + "-" + second, base + "-" + second + os.sep, base + "-" + first):
        got = [(g["key"], g["name"], g["folder"]) for g in game_folders.built_games(out, windows_exe)]
        check(got == want, "built_games(%r): %r, not %r" % (out, got, want))
    got = game_folders.built_games(other, windows_exe)
    check([(g["key"], g["name"], g["folder"]) for g in got] == [(game_profile.DEFAULT, profile(second).game, other)],
          "a game in another's folder by the rule is named by its copy: %r" % (got,))
    check(game_folders.built_games("", windows_exe) == [] and game_folders.built_games(None, windows_exe) == [],
          "nothing for an empty game folder")
    check(game_folders.folder_game(base + "-" + first).key == first, "folder_game reads the copy's build id")
    check(game_folders.folder_game(os.path.join(games, "NoCopy")) is None, "folder_game is None without a copy")
    check(game_folders.base_of(base + "-" + second) == base and game_folders.base_of(base) == base, "base_of strips a suffix only")

    # (the helpers the Builders name and follow games by)
    check(game_folders.folder_key(other) == second, "folder_key: a folder's kept copy names its game, wherever it is")
    check(game_folders.folder_key(os.path.join(games, "NoCopy")) == game_profile.DEFAULT,
          "folder_key: a folder with no copy and no suffix is the default game's")
    check(game_folders.folder_key(os.path.join(games, "Empty-" + first)) == first, "folder_key: else its folder by the rule")
    check(game_folders.shortcut_name(game_profile.DEFAULT) == "Hookshot",
          "the default game's shortcut keeps its name (Hookshot.lnk, hookshot.desktop's Hookshot): %r"
          % game_folders.shortcut_name(game_profile.DEFAULT))
    for key in other_keys():
        name = game_folders.shortcut_name(key)
        check(name == profile(key).game.replace(":", "") + " (Hookshot)" and not re.search(r'[\\/:*?"<>|]', name),
              "another game's shortcut is named by it, a name a file can take: %r" % name)
    check(game_folders.title_parts("The Legend of Zelda: Ocarina of Time") == ("THE LEGEND OF ZELDA", "Ocarina of Time"),
          "title_parts splits a series from its title")
    check(game_folders.title_parts("Mario Kart World") == ("", "Mario Kart World"), "title_parts keeps a name without a series")
    lines = {"@@game start %s %s" % (second, other): ("start", second, other),
             "@@game end %s updated v9.9.9" % second: ("end", second, "updated", "v9.9.9"),
             "@@game end %s failed The build stopped: no room" % first: ("end", first, "failed", "The build stopped: no room"),
             "@@game end %s missing" % first: ("end", first, "missing", None),
             "@@game end %s rebuild choose this game's files once to update it" % second:
                 ("end", second, "rebuild", "choose this game's files once to update it"),
             "@@stage compile": None, "@@game middle x y": None}
    for line, want_line in lines.items():
        check(game_folders.update_line(line) == want_line, "update_line(%r): %r" % (line, game_folders.update_line(line)))
    for key in [p.key for p in game_folders.buildable()]:
        said = "This is the version Hookshot supports (build %s)." % profile(key).build_id[:8]
        check(game_folders.copy_key(said) == key, "copy_key reads the check's build: %r" % said)
    check(game_folders.copy_key("This is build abcdef01. Hookshot supports build e0f3ccfa.") is None,
          "copy_key is None for a copy no profile knows")
    lib = game_folders.library(base, game_exe=windows_exe, engine="v9.9.9")
    check(game_folders.installed_folders(lib) == [f for g in lib if g["built"] for f in [g["folder"]] + g["other_folders"]],
          "installed_folders: each built game's folders")
    return [base, base + "-" + second, other, os.path.join(games, "NoCopy"), os.path.join(games, "Missing"), base + "-" + first]


def library_base(tmp, exe):
    """A base with the default game built, kept and due, another game not installed, and a third built without its game files
    (rebuild), as --library --json gives it"""
    base = os.path.join(tmp, "Library", "Hookshot")
    first, second = other_keys()[:2]
    placeholder(base, profile(game_profile.DEFAULT).build_id, exe=exe, kept=True, version="v0.0.1")
    placeholder(base + "-" + second, profile(second).build_id, exe=exe, version="v0.0.1")
    return base, first, second


# ---------------- the Linux Builder ----------------

def check_linux_builder(tmp):
    src = (ROOT / "builder" / "linux" / "hookshot_builder.py").read_text(encoding="utf-8")
    form = between(src, "    def show_form(self):", "    def T(self, key):")
    check("games = self.library_games()" in form and "self.games_list(f, games)" in form,
          "the Linux Builder's form shows the game library")
    check('os.path.join(ROOT, "nx2", "game_folders.py"), "--library", base, "--json"]' in between(src, "def library_for(", "def game_results("),
          "the Linux Builder reads the library from game_folders.py --library --json")
    lst = method(src, "games_list")
    check("command=lambda f=g[\"folder\"]: self.play_and_close(f)" in lst, "the Linux Builder's Play starts the row's own folder")
    check('subprocess.Popen(["xdg-open", f])' in lst, "the Linux Builder's rows open their folder")
    check("self.install_menu(g, b)" in lst and "self.update_all_click" in lst and "self.update_game_row(f)" in lst,
          "the Linux Builder's rows have Install, Update and Update all")
    check('if not g["built"] or not g["kept"]:' in lst, "a folder with no game files kept offers Install, not Update")
    check('["--base", g["base"]]' in method(src, "install") and '"--game-%s" % g["key"]' in method(src, "install"),
          "the Linux Builder installs a game's copy checked to be it, into its own folder (--base)")
    click = method(src, "update_all_click")
    check('"--update-all", base, "--dry-run"]' in click and "self.start_update_all(base," in click,
          "the Linux Builder's Update all says what it would do first (--dry-run), then runs it")
    start = method(src, "start_update_all")
    check('"--update-all", base, "--work-base", cache_dir()]' in start and '"--work"' not in start,
          "the Linux Builder's Update all runs --update-all with its build files folder (--work-base)")
    check("self.T(\"LibTitle\")" in form and "self.T(\"LibSub\")" in form and "Build your game" not in form,
          "the Linux Builder's heading is every game's, from the string table")
    check('update_all = ttk.Button(head, text=self.T("LibUpdateAll"), cursor="hand2"' in lst and 'self.T("LibNothing")' in lst and
          "Link.TButton" not in lst.split("update_all = ")[1].split("\n")[0], "the Linux Builder's Update all is a button, saying why when disabled")
    check(all(".grid(row=2 * i, column=%d" % c in lst for c in (1, 2, 3)) and "elide_middle(full, room" in lst,
          "the Linux Builder's rows share three button columns and elide a folder's middle to the room they leave")
    update = method(src, "start_make_update")
    check("if self.fetched and self.tools and have and have != self.tools:" in update and
          "return self.start_update_all(" in update and "if len(folders) > 1:" in update,
          "after a self-update the Linux Builder updates every installed game, one game alone as before")
    check('where = self.build_where(out) if getattr(self, "copy_game", None)' in method(src, "build") and
          'else ["--base", out]' in method(src, "build_where"),
          "the Linux Builder's Build sends a checked copy of another game to its own folder (--base)")
    check("self.copy_game = game_folders.copy_key(v)" in method(src, "pump"), "the Linux Builder knows the checked copy's game")
    check('line.startswith("@@game "):' in method(src, "on_line") and "self.game_framed(line)" in method(src, "on_line"),
          "the Linux Builder follows Update all's @@game lines")
    check("return self.update_all_done(code)" in method(src, "on_exit"), "the Linux Builder ends Update all with its summary")
    check("game_folders.title_parts(game_profile.GAMES[game_folders.folder_key(folder)].game)" in method(src, "show_launch") and
          '"Ocarina of Time"' not in method(src, "show_launch"),
          "the Linux launcher page shows the folder's game, not always Ocarina")
    check("Ocarina" not in between(src, "def menu_entry(", "def free_gb(") and "entry, title, game = menu_entry(folder)" in src,
          "the Linux menu entry is named by the folder's game")
    check('cp builder/py/hookshot_builder/strings.py "$T/builder/py/hookshot_builder/"' in
          (ROOT / "scripts" / "linux" / "appimage.sh").read_text(encoding="utf-8"),
          "the AppImage carries the Builders' string table")
    try:
        import tkinter  # noqa: F401  (the Builder imports it)
    except ImportError:
        print("the Linux Builder's functions not run: no tkinter here")
        return
    spec = importlib.util.spec_from_file_location("hookshot_builder_games", ROOT / "builder" / "linux" / "hookshot_builder.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    base = os.path.join(tmp, "Linux", "Hookshot")
    first, second = other_keys()[:2]
    placeholder(base, profile(game_profile.DEFAULT).build_id, exe=os.path.join("bin", "hookshot"))
    placeholder(base + "-" + first, profile(first).build_id, exe="hookshot")
    got = [(g["key"], g["folder"]) for g in builder.your_games(base + "-" + first)]
    check(got == [(game_profile.DEFAULT, base), (first, base + "-" + first)], "the Linux Builder's fallback lists its built games: %r" % got)
    check(builder.play_folder_for(base, first) == base + "-" + first and builder.play_folder_for(base, game_profile.DEFAULT) == base,
          "the Linux Builder's --play folders are the rule's")

    lbase, lfirst, lsecond = library_base(tmp, os.path.join("bin", "hookshot"))
    lib = builder.library_for(lbase + "-" + lsecond)
    want = game_folders.library(lbase)
    check(lib == json.loads(json.dumps(want)), "the Linux Builder's library is --library --json's:\n  %r\n  %r" % (lib, want))
    by = {g["key"]: g for g in lib}
    check(by[game_profile.DEFAULT]["built"] and by[game_profile.DEFAULT]["kept"] and not by[lfirst]["built"] and
          by[lsecond]["built"] and not by[lsecond]["kept"] and by[lsecond]["update"] is False,
          "the placeholder library: the default game kept, one not installed, one without its game files")
    lines = ["@@game start %s %s" % (game_profile.DEFAULT, lbase), "@@stage compile", "@@game end %s failed no room" % game_profile.DEFAULT,
             "@@game start %s %s" % (lfirst, lbase + "-" + lfirst), "@@game end %s missing" % lfirst,
             "@@game start %s %s" % (lsecond, lbase + "-" + lsecond), "@@game end %s rebuild %s" % (lsecond, "choose this game's files once to update it")]
    results = builder.game_results(lines)
    check(results == [(game_profile.DEFAULT, lbase, "failed", "no room"), (lfirst, lbase + "-" + lfirst, "missing", None),
                      (lsecond, lbase + "-" + lsecond, "rebuild", "choose this game's files once to update it")],
          "the Linux Builder reads Update all's outcomes, a failed one beside the others: %r" % (results,))
    said = [builder.result_text(r, results) for r in results]
    check(said[0] == "%s: failed: no room" % profile(game_profile.DEFAULT).game and
          said[2] == "%s: choose this game's files once to update it" % profile(lsecond).game,
          "the Linux Builder's summary lines: %r" % said)
    width = len   # (a letter a unit: the room in letters)
    long = "/home/player/a very long folder name/Games/Hookshot-mkw"
    check(builder.elide_middle(long, 100, width) == long, "a path that fits is shown whole")
    cut = builder.elide_middle(long, 21, width)
    check(cut == long[:10] + "…" + long[-10:],
          "a long path keeps as much of both ends as fits, its middle left out: %r" % cut)
    check(builder.text("LibUpdateAll") == "Update all" and builder.text("LibUpdateAll", "fr") == "Tout mettre à jour",
          "the Linux Builder's strings are the shared table's, in the game language chosen")
    check(builder.menu_entry(base) == ("hookshot.desktop", "Hookshot", profile(game_profile.DEFAULT).game),
          "the default game's menu entry keeps its file and name (hookshot.desktop, Hookshot): %r" % (builder.menu_entry(base),))
    check(builder.menu_entry(base + "-" + first) == ("hookshot-%s.desktop" % first, game_folders.shortcut_name(first), profile(first).game),
          "another game's menu entry is its own: %r" % (builder.menu_entry(base + "-" + first),))
    data = os.path.join(tmp, "xdg-data")
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": data}):
        builder.add_to_menu(base)
        builder.add_to_menu(base + "-" + first)
    apps = os.path.join(data, "applications")
    check(sorted(os.listdir(apps)) == sorted(["hookshot.desktop", "hookshot-%s.desktop" % first]), "one menu entry per game: %r" % os.listdir(apps))
    entry = open(os.path.join(apps, "hookshot-%s.desktop" % first), encoding="utf-8").read()
    check("Name=%s\n" % game_folders.shortcut_name(first) in entry and "Comment=%s, built from your copy" % profile(first).game in entry
          and "Ocarina" not in entry, "another game's menu entry is named and described by it:\n" + entry)
    check("Name=Hookshot\n" in open(os.path.join(apps, "hookshot.desktop"), encoding="utf-8").read(), "the default game's entry is Hookshot")


# ---------------- the Qt Builder ----------------

def check_qt_builder():
    py = ROOT / "builder" / "py" / "hookshot_builder"
    core = (py / "core.py").read_text(encoding="utf-8")
    window = (py / "window.py").read_text(encoding="utf-8")
    updater = (py / "updater.py").read_text(encoding="utf-8")
    check('script_output(tools, "game_folders.py", ["--library", base, "--json"])' in core,
          "the Qt Builder reads the library from game_folders.py --library --json, with the tools' Python")
    check("self.fill_games()" in method(window, "refresh"), "the Qt Builder fills the library with the form")
    check(re.search(r"self\.fill_games\(reload=True\)[^\n]*\n\s*self\.show_page\(self\.ready_page\)", window) is not None,
          "the Qt Builder reads the library again when a build ends")
    lib = method(window, "show_library")
    check("self.play_game(g)" in lib and 'core.start_game(g["folder"])' in method(window, "play_game"),
          "the Qt Builder's Play starts the row's own folder")
    check("self.install_menu(g, b)" in lib and "self.update_game_row(g)" in lib and 'if not g["built"] or not g["kept"]:' in lib,
          "the Qt Builder's rows have Install (also for a folder without its game files) and Update")
    check('(["--out", g["folder"]] if g["built"] else ["--base", g["base"]])' in method(window, "install_game") and
          '"--game-" + g["key"]' in method(window, "install_game"),
          "the Qt Builder installs a game's copy checked to be it, into its own folder (--base)")
    check('["--update-all", b, "--dry-run"]' in method(window, "update_all_click") and
          "self.start_update_all(tools, b," in method(window, "update_all_plan"),
          "the Qt Builder's Update all says what it would do first (--dry-run), then runs it")
    check('["--update-all", base, "--work-base", core.work()]' in method(window, "start_update_all") and
          '"--update-all" not in args' in method(window, "run"),
          "the Qt Builder's Update all runs --update-all with the player's build files folder (--work-base), no --work")
    check('Button(self.T("LibUpdateAll"), "quiet")' in window and 'self.T("LibNothing")' in lib and
          "Build your game" not in window and 'sub(self.T("LibSub"))' in window,
          "the Qt Builder's Update all is a button with why it is disabled, and its heading is every game's")
    check("ElidedLabel(g[\"folder\"])" in lib and "Qt.TextElideMode.ElideMiddle" in window and
          all("r, %d)" % c in lib for c in (1, 2, 3)),
          "the Qt Builder's rows share one grid's button columns and elide a folder's middle")
    check("ui.update_build_or_all(tools, folder, fetched)" in updater and
          "self.start_update_all(tools, b, folders)" in method(window, "update_all_or_one") and
          "if len(folders) > 1:" in method(window, "update_all_or_one"),
          "after a self-update the Qt Builder updates every installed game, one game alone as before")
    check("self.build_where()" in method(window, "start_build") and 'return "--out" if same else "--base"' in method(window, "build_where"),
          "the Qt Builder's Build sends a checked copy of another game to its own folder (--base)")
    check('line.startswith("@@game "):' in method(window, "line") and "self.game_framed(line)" in method(window, "line") and
          "gf.update_line(line)" in method(window, "game_framed"), "the Qt Builder follows Update all's @@game lines")
    check("self.end_update_all(failure)" in method(window, "ended"), "the Qt Builder ends Update all with its summary")
    check("gf.title_parts(core.game_name(core.folder_key(folder)))" in method(window, "show_launcher"),
          "the Qt launcher page shows the folder's game, not always Ocarina")
    shortcuts = method(core, "shortcuts", "top")
    check("key = folder_key(game_folder)" in shortcuts and "desktop_link(key)" in shortcuts and "Ocarina" not in shortcuts,
          "the Qt Builder's shortcuts are named and described by the folder's game")
    check("shortcut_name(key) + \".lnk\"" in method(core, "desktop_link", "top") and 'else "Hookshot"' in method(core, "shortcut_name", "top"),
          "the Qt Builder's default shortcut keeps its name (Hookshot.lnk)")
    spec = importlib.util.spec_from_file_location("hookshot_builder_strings", py / "strings.py")
    table = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(table)
    check(table.KEYS == cs_keys(), "strings.py's keys are Strings.cs's (python -I builder/py/gen_strings.py)")
    for key in LIBRARY_KEYS:
        check(key in table.KEYS, "strings.py has %s" % key)


# ---------------- the WPF Builder ----------------

LIBRARY_KEYS = ["LibTitle", "LibMissing", "LibCurrent", "LibUpdate", "LibInstalled", "LibAlsoIn", "LibTaken", "LibInstall",
                "LibUpdateOne", "LibUpdateAll", "LibPickFile", "LibPickFolder", "LibNoFolders", "LibAsk", "LibNothing",
                "LibUpdating", "LibUpdatingOne", "LibAllUpdated", "LibSomeFailed", "ResUpdated", "ResCurrent", "ResWould",
                "ResWouldPlain", "ResMissing", "ResFailed", "LibRebuild", "ResRebuild", "LibSub"]


def cs_keys():
    src = (ROOT / "builder" / "HookshotBuilder" / "Strings.cs").read_text(encoding="utf-8")
    enum = re.search(r"enum S\s*\{(.*?)\}", src, re.S).group(1)
    return [k.strip() for k in re.sub(r"//.*", "", enum).replace("\n", " ").split(",") if k.strip()]


def cs_profiles():
    games = (ROOT / "builder" / "HookshotBuilder" / "Games.cs").read_text(encoding="utf-8")
    table = games[games.index("Profiles =\n"):games.index("};", games.index("Profiles =\n"))]
    default = re.search(r'public const string DefaultKey = "([a-z0-9]+)";', games)
    return re.findall(r'\("([a-z0-9]+)", "([^"]+)", "([0-9a-f]+)"\)', table), default and default.group(1)


def check_wpf_builder():
    rows, default = cs_profiles()
    want = [(p.key, p.game, p.build_id) for p in game_folders.buildable()]
    check(rows == want, "Games.cs's profiles are game_profile.py's that build: %r, not %r" % (rows, want))
    check(default == game_profile.DEFAULT, "Games.cs's default key is game_profile.DEFAULT (%r)" % (default,))
    hb = ROOT / "builder" / "HookshotBuilder"
    window = (hb / "MainWindow.xaml.cs").read_text(encoding="utf-8")
    runner = (hb / "Runner.cs").read_text(encoding="utf-8")
    finder = (hb / "Finder.cs").read_text(encoding="utf-8")
    updater = (hb / "Updater.cs").read_text(encoding="utf-8")
    check('Output(tools, "game_folders.py", new[] { "--library", baseFolder, "--json" })' in runner,
          "the WPF Builder reads the library from game_folders.py --library --json, with the tools' Python")
    check("Runner.Library(tools, b)" in between(window, "    async void LoadLibrary()", "    string LibraryState("),
          "the WPF Builder's library is the core's")
    check("FillGames();" in between(window, "    void Refresh()", "    string? HardDriveWarning()"), "the WPF Builder fills the library with the form")
    check(re.search(r"FillGames\(reload: true\);[^\n]*\n\s*ShowPage\(ReadyPage\);", window) is not None,
          "the WPF Builder reads the library again when a build ends")
    show = between(window, "    void ShowLibrary()", "    Button RowPlayButton(")
    check("RowPlayButton(g)" in show and "StartGame(g.Folder);" in between(window, "    Button RowPlayButton(", "    Button InstallButton("),
          "the WPF Builder's Play starts the row's own folder")
    check("InstallButton(g, taken)" in show and "UpdateGameRow(g)" in show and "if (!g.Built || !g.Kept)" in show,
          "the WPF Builder's rows have Install (also for a folder without its game files) and Update")
    install = between(window, "    void InstallGame(", "    void UpdateGameRow(")
    check('new[] { "--base", g.Base }' in install and '"--game-" + g.Key' in install,
          "the WPF Builder installs a game's copy checked to be it, into its own folder (--base)")
    click = between(window, "    async void UpdateAllClick(", "    string ResultText(")
    check('new[] { "--update-all", b, "--dry-run" }' in click and "StartUpdateAll(tools, b," in click,
          "the WPF Builder's Update all says what it would do first (--dry-run), then runs it")
    check('new List<string> { "--update-all", baseFolder, "--work-base", Storage.Work }' in between(window, "    void StartUpdateAll(", "    void GameFramed(") and
          '!args.Contains("--update-all")' in window,
          "the WPF Builder's Update all runs --update-all with the player's build files folder (--work-base), no --work")
    check("UpdateAllButton.ToolTip = library.Any(g => g.Update == true) ? null : T(S.LibNothing);" in show and
          'x:Name="UpdateAllButton" Style="{StaticResource Quiet}"' in (hb / "MainWindow.xaml").read_text(encoding="utf-8"),
          "the WPF Builder's Update all is a button, its tooltip saying why when disabled")
    check("FilesTitle.Text = T(S.LibTitle);" in window and "FilesSub.Text = T(S.LibSub);" in window and
          "Build your game" not in window, "the WPF Builder's heading is every game's, from the string table")
    check(all('SharedSizeGroup = "%s"' % g in show for g in ("LibInstall", "LibOpen", "LibPlay")) and "MiddleElided(g.Folder)" in show,
          "the WPF Builder's rows share three button columns and elide a folder's middle")
    check("w.UpdateBuildOrAll(tools, folder, all: fetched);" in updater, "the WPF Builder's self-update goes through UpdateBuildOrAll")
    both = between(window, "    internal async void UpdateBuildOrAll(", "    internal void UpdateBuild(")
    check("StartUpdateAll(tools, b, folders);" in both and "folders.Count > 1" in both and "UpdateBuild(tools, folder);" in both,
          "after a self-update the WPF Builder updates every installed game, one game alone as before")
    check("BuildWhere()" in between(window, "    async void StartBuild(", "    string BuildWhere()") and
          '"--out" : "--base"' in between(window, "    string BuildWhere()", "    static bool SamePath("),
          "the WPF Builder's Build sends a checked copy of another game to its own folder (--base)")
    check("Games.ReadGameLine(line) is { } framed" in between(window, "    void Line(string line)", "    void Number(") and
          "EndUpdateAll(failure);" in between(window, "    void Ended(string? failure)", "    void LogToggled("),
          "the WPF Builder follows Update all's @@game lines and ends it with its summary")
    launcher = between(window, "    async void ShowLauncher(string folder)", "    /// (a folder built before")
    check("Games.TitleParts(Games.NameOf(Games.FolderKey(folder)))" in launcher, "the WPF launcher page shows the folder's game")
    xaml = (hb / "MainWindow.xaml").read_text(encoding="utf-8")
    for name in ("GamesBox", "GameList", "UpdateAllButton", "LaunchSeries", "LaunchTitle"):
        check('x:Name="%s"' % name in xaml, "MainWindow.xaml has %s" % name)
    shortcuts = between(finder, "    public static void Shortcuts(", "    /// The last shortcut")
    check("var key = Games.FolderKey(gameFolder);" in shortcuts and "(DesktopLinkFor(key), desktop)" in shortcuts and
          "Games.NameOf(key)" in shortcuts and "Ocarina" not in shortcuts,
          "the WPF Builder's shortcuts are named and described by the folder's game")
    check("public static string DesktopLink => DesktopLinkFor(Games.DefaultKey);" in finder and
          'Games.ShortcutName(key) + ".lnk"' in finder and 'key == DefaultKey ? "Hookshot"' in (hb / "Games.cs").read_text(encoding="utf-8"),
          "the WPF Builder's default shortcut keeps its name (Hookshot.lnk)")
    strings = (hb / "Strings.cs").read_text(encoding="utf-8")
    keys = cs_keys()
    last = max(keys.index(k) for k in LIBRARY_KEYS)
    for name, body in re.findall(r"static readonly string\[\] (\w+) =\s*\{(.*?)\n    \};", strings, re.S):
        n = len(re.findall(r'"((?:[^"\\]|\\.)*)"', body))
        check(n > last, "Strings.cs's %s translates the library's strings (%d strings, the library's last is %d)" % (name, n, last + 1))
    for key in LIBRARY_KEYS:
        check(key in keys, "Strings.cs has %s" % key)
        if "S.%s" % key not in window:
            check(False, "MainWindow.xaml.cs uses S.%s" % key)


def check_wpf_fixture(dotnet, outs, tmp):
    """Games.cs and tests/builder_games_test.cs, compiled without WPF, over the same placeholder folders: every answer the same as
    game_folders.py's"""
    first, second = other_keys()[:2]
    pairs = [("C:\\Games\\Hookshot", game_profile.DEFAULT), ("C:\\Games\\Hookshot\\", second), ("C:\\Games\\Hookshot/", first), ("", second)]
    bases = ["C:\\Games\\Hookshot-" + second, "C:\\Games\\Hookshot-%s\\" % first, "C:\\Games\\Hookshot", "C:\\Games\\-" + second, "D:\\x-oot"]
    keys = outs + [os.path.join(tmp, "Empty-" + first), os.path.join(tmp, "Empty")]
    shortcuts = [p.key for p in game_folders.buildable()]
    titles = [p.game for p in game_folders.buildable()] + ["A: B", ": x", "Plain"]
    lines = ["@@game start %s C:\\My Games\\Hookshot-%s" % (second, second), "@@game end %s updated v1.2.3" % second,
             "@@game end %s failed The build stopped: no room left" % first, "@@game end %s missing" % first,
             "@@game end %s update from v1.0.0" % game_profile.DEFAULT, "@@game end oot current", "@@stage compile", "@@game start"]
    copies = ["This is the version Hookshot supports (build %s)." % p.build_id[:8] for p in game_folders.buildable()] + \
        ["This is build abcdef01. Hookshot supports build e0f3ccfa.", ""]
    lbase, _, _ = library_base(tmp, os.path.join("bin", "hookshot.exe"))
    library = game_folders.library(lbase, game_exe=windows_exe, engine="v9.9.9")
    lib_file = os.path.join(tmp, "library.json")
    with open(lib_file, "w", encoding="utf-8") as f:
        json.dump(library, f, indent=2)
    results_file = os.path.join(tmp, "results.txt")
    with open(results_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines[:5] + ["@@game start %s D:\\Other" % second, "@@game end %s rebuild choose once" % second]) + "\n")

    def none(v):
        return "None" if v is None else v
    want = []
    for out in outs:
        want.append("== " + out)
        want += ["%s\t%s\t%s\t%s" % (g["key"], g["name"], g["folder"], g["base"]) for g in game_folders.built_games(out, windows_exe)]
    want += ["folder\t%s\t%s\t%s" % (b, k, game_folders.folder(b, k)) for b, k in pairs]
    want += ["base\t%s\t%s" % (b, game_folders.base_of(b)) for b in bases]
    want += ["key\t%s\t%s" % (k, game_folders.folder_key(k)) for k in keys]
    want += ["shortcut\t%s\t%s" % (k, game_folders.shortcut_name(k)) for k in shortcuts]
    want += ["title\t%s\t%s\t%s" % ((t,) + game_folders.title_parts(t)) for t in titles]
    for line in lines:
        got = game_folders.update_line(line)
        want.append("line\tNone" if got is None else "line\t" + "\t".join(none(x) for x in got))
    want += ["copy\t%s\t%s" % (c, none(game_folders.copy_key(c))) for c in copies]
    want += ["lib\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" % (
        g["key"], g["name"], g["folder"], g["base"], g["built"], "|".join(g["other_folders"]), g["own_folder"],
        none(g["own_folder_holds"]), none(g["version"]), g["kept"], none(g["update"])) for g in library]
    want.append("installed\t" + "|".join(game_folders.installed_folders(library)))
    folder = ""
    for line in open(results_file, encoding="utf-8").read().splitlines():
        got = game_folders.update_line(line)
        if got and got[0] == "start":
            folder = got[2]
        elif got:
            want.append("result\t%s\t%s\t%s\t%s" % (got[1], folder, got[2], none(got[3])))
    with tempfile.TemporaryDirectory(prefix="builder-games-") as fixture:
        root = Path(fixture)
        shutil.copyfile(ROOT / "tests" / "builder_games_test.cs", root / "Program.cs")
        shutil.copyfile(ROOT / "builder" / "HookshotBuilder" / "Games.cs", root / "Games.cs")
        (root / "NuGet.Config").write_text("<configuration><packageSources><clear/></packageSources></configuration>", encoding="utf-8")
        project = root / "Fixture.csproj"
        args = (list(outs) + ["--folder"] + [x for pair in pairs for x in pair] + ["--base"] + bases + ["--key"] + keys +
                ["--shortcut"] + shortcuts + ["--title"] + titles + ["--line"] + lines + ["--copy"] + copies +
                ["--library", lib_file, "--results", results_file])
        r = run_fixture(dotnet, project, args, "net8.0")
        if r.returncode and no_net8_pack(r.stdout + r.stderr) and os.environ.get("GITHUB_ACTIONS") != "true":
            # (a PC whose .NET SDK is a later one alone, as tests/test_updater_asset_digest.py: built for that SDK's
            # framework, with a line saying so. On a GitHub runner .NET 8 is installed, so it fails instead)
            sdk = subprocess.run([dotnet, "--version"], capture_output=True, text=True, check=True).stdout.strip()
            framework = "net%s.0" % sdk.split(".")[0]
            print("this .NET SDK (%s) has no .NET 8 reference pack: Games.cs is built for %s, not the Builder's net8.0"
                  % (sdk, framework), flush=True)
            r = run_fixture(dotnet, project, args, framework)
        if r.returncode:
            print(r.stdout + r.stderr)
            check(False, "Games.cs's fixture did not build or run")
            return
        got = [line for line in r.stdout.splitlines() if line.strip()]
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                check(False, "Games.cs answers as game_folders.py does, line %d:\n  got  %r\n  want %r" % (i, g, w))
                break
        check(len(got) == len(want), "Games.cs's fixture gave %d lines, game_folders.py %d" % (len(got), len(want)))


def run_fixture(dotnet, project, args, framework):
    project.write_text('''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
<OutputType>Exe</OutputType><TargetFramework>%s</TargetFramework><ImplicitUsings>enable</ImplicitUsings>
<Nullable>enable</Nullable><TreatWarningsAsErrors>true</TreatWarningsAsErrors><NuGetAudit>false</NuGetAudit>
<UseAppHost>false</UseAppHost><RollForward>Major</RollForward>
</PropertyGroup></Project>''' % framework, encoding="utf-8")
    return subprocess.run([dotnet, "run", "--project", str(project), "--configuration", "Release", "--"] + args,
                          capture_output=True, text=True, encoding="utf-8")


def no_net8_pack(out):
    """A build that failed only for want of .NET 8's reference pack: NU1100 with the sources cleared, or NU1101 for the
    pack where the SDK keeps a package folder of its own (Ubuntu's: /usr/lib/dotnet/library-packs)"""
    return "NU1100" in out or "NU1101: Unable to find package Microsoft.NETCore.App.Ref" in out


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dotnet", default="dotnet")
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="builder-games-") as tmp:
        outs = check_game_folders(tmp)
        check_linux_builder(tmp)
        check_qt_builder()
        check_wpf_builder()
        dotnet = shutil.which(a.dotnet)
        if dotnet:
            check_wpf_fixture(dotnet, outs, tmp)
        elif os.name == "nt":
            check(False, "no .NET 8 SDK here: Games.cs's fixture is the Windows run's to check")
        else:
            print("Games.cs not compiled: no .NET here (checked on Windows)")
    if failures:
        sys.exit(1)
    print("PASS: the game library is the core's in every Builder: its rows, Install, Update all and the self-update's, and the "
          "launcher page and shortcuts named by the game, Ocarina's Hookshot.lnk unchanged")


if __name__ == "__main__":
    main()
