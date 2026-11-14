"""The build dashboard's events and screen: no game, no compiler, no terminal.

It feeds the @@ lines make_game.py documents (including the new @@work) to nx2/build_ui.py's model and checks the steps,
the compile counts, the files in flight and the error path; then it renders the screen as plain text. It also checks
that build.py still prints @@work and that make_game.py documents it, since the dashboard's file rows depend on them.
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_ui", ROOT / "nx2" / "build_ui.py")
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

EVENTS = [
    "version: Hookshot test",
    "  code_000.c  8 MB  2s  (1s)",
    "@@stage read Reading your game files",
    "@@progress 0.5",
    "@@stage lift Translating the game to PC code",
    "@@stage compile Compiling",
    "@@plan 2 4",
    "@@work code_001.c 8 ThreadPoolExecutor-0_1",
    "@@work code_002.c 4 ThreadPoolExecutor-0_2",
    "@@file code_001.c 0.0 cached",
    "@@eta 90",
    "@@work code_003.c 2 ThreadPoolExecutor-0_0",
    "@@file code_002.c 1.5 new",
]

state = ui.BuildState()
for line in EVENTS:
    state.feed(line)

assert state.plan_changed == 2 and state.plan_total == 4, state.plan_changed
assert state.files_done == 2 and state.files_cached == 1 and state.files_new == 1, (state.files_done, state.files_cached)
assert state.files_failed == 0
assert list(state.in_flight) == ["ThreadPoolExecutor-0_0"], state.in_flight
assert state.in_flight["ThreadPoolExecutor-0_0"][0] == "code_003.c"
assert state.eta == 90
assert state.current == "compile"
assert state.by_id["read"]["end"] is not None and state.by_id["compile"]["end"] is None
assert state.status() == "running"

text = "\n".join(ui.render_lines(state, 100, 30, "build.py --standalone --jobs 6", "work/build_ui.log", colour=False))
for wanted in ("Hookshot build", "Compile", "2 / 4", "cached 1", "new 1", "workers:", "#0", "code_003.c", "log:"):
    assert wanted in text, wanted
assert "\x1b[" not in text, "colour off must be plain"

state.feed("@@file code_003.c 0.8 new")
state.feed("@@times 30 20 -1")
state.feed("@@done ~/Games/Hookshot")
assert state.status() == "done", state.status()
assert state.times == (30, 20, -1)
assert state.done == "~/Games/Hookshot"
assert not state.in_flight

bad = ui.BuildState()
bad.feed("@@stage compile Compiling")
bad.feed("@@plan 1 2")
bad.feed("@@work code_004.c 9 ThreadPoolExecutor-0_0")
bad.feed("@@file code_004.c 2.0 failed")
bad.feed("@@error compiler ran out of memory")
assert bad.files_failed == 1 and bad.files_done == 1
assert bad.status() == "failed" and "out of memory" in bad.error
bad_text = "\n".join(ui.render_lines(bad, 100, 24, "build.py", "x.log", colour=False))
assert "failed" in bad_text and "out of memory" in bad_text

build = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
assert '@@work %s %d %s' in build, "build.py must announce the file it starts compiling"
protocol = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
assert "@@work <name> <MB> <worker>" in protocol, "the protocol must document @@work"

print("PASS: the build dashboard reads the stages, the plan, the files in flight, the cache and the error path")
