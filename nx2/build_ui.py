"""A terminal build dashboard: the step, the files being compiled, the cache and the ETA, from the build's @@ lines.

    python -I nx2/build_ui.py [--jobs N] [--plain] [--demo] [--attach <log>] [--log <file>] [--make] [-- <args>]

Runs nx2/build.py (--standalone) itself, or nx2/make_game.py with --make; -- attaches the arguments. On a terminal it
takes the screen and redraws ten times a second; elsewhere (CI, a pipe) or with --plain it prints the build's own lines
with a short summary. --attach follows a log another process is writing, and --demo runs a made-up build for the screen
itself (no game files). Control-C stops the build and its compilers; the full log is kept in --log (work/build_ui.log
by default).

The events are make_game.py's docstring's: @@stage, @@progress, @@plan, @@work, @@file, @@eta, @@times, @@done, @@error.
@@work is the new one, printed by build.py when a module's compiler starts (the others say when it ended).
"""
import argparse
import collections
import os
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = [sys.executable, "-I", "-u", "-X", "utf8"]

# (the steps make_game.py names, in the order it runs them; a build.py alone has compile and link)
STEPS = ["read", "lift", "compile", "finish", "shaders", "link"]
MAKE_STEPS = ["read", "lift", "compile", "finish", "shaders"]
BUILD_STEPS = ["compile", "link"]
LABELS = {"read": "Read", "lift": "Lift", "compile": "Compile", "link": "Link", "finish": "Finish",
          "shaders": "Shaders", "prepare": "Prepare"}
ON = {"done": "\x1b[32m", "now": "\x1b[36;1m", "wait": "\x1b[2m", "bad": "\x1b[31;1m", "dim": "\x1b[2m", "off": "\x1b[0m"}
LOGS = 2000   # (the raw lines kept for the tail and for a summary; the file has all of them)


def fmt_time(seconds):
    """00:12:34, for a duration or an ETA"""
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    if seconds >= 3600:
        return "%d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60)
    return "%02d:%02d" % (seconds // 60, seconds % 60)


def clip(text, width):
    """text cut to width; an ANSI-coloured line is measured by its visible text, so paint() is applied after this"""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[:max(0, width - 1)] + "~" if width > 1 else text[:width]


def paint(text, colour, enabled):
    return (ON[colour] + text + ON["off"]) if enabled else text


def progress_bar(done, total, width):
    """[####------]; None when the total is not known yet"""
    if not total or total <= 0:
        return "[" + "." * max(3, width - 2) + "]"
    filled = int(max(0.0, min(1.0, float(done) / total)) * (width - 2))
    return "[" + "#" * filled + "-" * (width - 2 - filled) + "]"


def short_worker(name):
    """ThreadPoolExecutor-0_3 -> #3; a name the builder chose is kept whole"""
    if name.startswith("ThreadPoolExecutor-"):
        return "#" + name.rsplit("_", 1)[-1]
    return name


class BuildState:
    """What the @@ lines say, kept for the screen and for the tests. No game, no build, no clock beyond the events."""

    def __init__(self):
        self.started = time.monotonic()
        self.stages = []                 # (dicts: id, text, start, end, progress)
        self.by_id = {}
        self.current = None
        self.compile_start = None
        self.plan_changed = None
        self.plan_total = None
        self.files_done = 0
        self.files_cached = 0
        self.files_new = 0
        self.files_again = 0
        self.files_failed = 0
        self.in_flight = {}              # worker -> (name, MB, when it started)
        self.eta = None
        self.times = None
        self.done = None
        self.error = None
        self.version = ""
        self.full = False               # (a make_game build: read and lift, so the whole step line is known)
        self.log = collections.deque(maxlen=LOGS)
        self.last_file = ""
        self.lines = 0
        self.finished = None             # (monotonic, exit code, cancelled)

    # ---- the events ----

    def stage(self, step, text=None, now=None):
        now = time.monotonic() if now is None else now
        if self.current and self.current != step:
            old = self.by_id.get(self.current)
            if old and old["end"] is None:
                old["end"] = now
        st = self.by_id.get(step)
        if st is None:
            st = {"id": step, "text": text or LABELS.get(step, step), "start": now, "end": None, "progress": None}
            self.stages.append(st)
            self.by_id[step] = st
        elif text:
            st["text"] = text
        if st["start"] is None:
            st["start"] = now
        if step == "compile" and self.compile_start is None:
            self.compile_start = now
        if step in ("read", "lift"):
            self.full = True
        self.current = step

    def progress(self, value):
        st = self.by_id.get(self.current)
        if st is not None:
            st["progress"] = max(0.0, min(1.0, value))

    def plan(self, changed, total):
        self.plan_changed, self.plan_total = changed, total
        if "compile" not in self.by_id:
            self.stage("compile", "Compiling")

    def work(self, name, mb, worker):
        self.in_flight[worker] = (name, mb, time.monotonic())

    def file(self, name, secs, kind):
        self.files_done += 1
        self.last_file = name
        if kind == "failed":
            self.files_failed += 1
        elif kind == "again":
            self.files_again += 1
        elif (secs is not None and secs <= 0) or kind == "cached":
            self.files_cached += 1
        else:
            self.files_new += 1
        for worker in [w for w, v in self.in_flight.items() if v[0] == name]:
            self.in_flight.pop(worker, None)

    def feed(self, line):
        """One line of the build's stdout; plain lines are kept for the tail, @@ lines change the state"""
        line = line.rstrip("\r\n")
        if not line:
            return
        self.lines += 1
        if not line.startswith("@@"):
            self.log.append(line)
            self._plain(line)
            return
        rest = line[2:]
        bits = rest.split(" ", 3)
        kind = bits[0] if bits else ""
        if kind == "stage":
            step = rest.split(" ", 2)
            if len(step) == 3:
                self.stage(step[1], step[2].strip())
        elif kind == "progress" and len(bits) >= 2:
            try:
                self.progress(float(bits[1]))
            except ValueError:
                pass
        elif kind == "plan" and len(bits) >= 3:
            try:
                self.plan(int(bits[1]), int(bits[2]))
            except ValueError:
                pass
        elif kind == "work" and len(bits) >= 3:
            # (@@work <name> <MB> <worker>: the name has no spaces, the worker is the rest)
            if len(bits) == 4:
                self.work(bits[1], int(bits[2]) if bits[2].isdigit() else 0, bits[3])
            else:
                self.work(bits[1], 0, bits[2])
        elif kind == "file" and len(bits) >= 4:
            try:
                self.file(bits[1], float(bits[2]), bits[3])
            except ValueError:
                pass
        elif kind == "eta" and len(bits) >= 2:
            try:
                self.eta = int(bits[1])
            except ValueError:
                pass
        elif kind == "times" and len(bits) >= 4:
            try:
                self.times = (int(bits[1]), int(bits[2]), int(bits[3]))
            except ValueError:
                pass
        elif kind == "done":
            self.done = rest[5:].strip()
        elif kind == "error":
            self.error = rest[6:].strip() or "the build stopped"
            self.log.append("error: " + self.error)

    def _plain(self, line):
        """The lines the app does not read: the build's own output. A build.py has no @@stage, so the log says where it is"""
        if line.startswith("version:") and not self.version:
            self.version = line
        elif line.startswith("compiled in") and "link" not in self.by_id:
            self.stage("link", "Linking")
        elif line.startswith("linked ") and "finish" not in self.by_id:
            self.stage("finish", "Finishing")

    def finish(self, code, cancelled=False):
        self.finished = (time.monotonic(), code, cancelled)
        if self.current and self.by_id.get(self.current) and self.by_id[self.current]["end"] is None:
            self.by_id[self.current]["end"] = self.finished[0]

    # ---- what the screen asks ----

    def ordered(self):
        known = [self.by_id[s] for s in STEPS if s in self.by_id]
        known += [s for s in self.stages if s["id"] not in STEPS]
        return known

    def elapsed(self, now=None):
        return (time.monotonic() if now is None else now) - self.started

    def compile_seconds(self):
        if self.times:
            return self.times[1]
        if self.compile_start is not None:
            return (self.finished[0] if self.finished else time.monotonic()) - self.compile_start
        return None

    def status(self):
        if self.finished:
            if self.finished[2]:
                return "cancelled"
            return "done" if self.finished[1] == 0 else "failed"
        if self.error:
            return "failed"
        if self.done is not None:
            return "done"
        return "running"


class Screen:
    """The full-screen terminal: the alternate screen, the cursor hidden, redrawn in place. Plain when not a tty"""

    def __init__(self, plain, colour=True):
        self.tty = (not plain) and sys.stdout.isatty()
        self.colour = colour and self.tty and os.environ.get("NO_COLOR") is None
        self.event = threading.Event()
        if self.tty:
            self._ansi()

    @staticmethod
    def _ansi():
        """Windows' console needs its virtual-terminal mode turned on before the escape sequences work"""
        if os.name != "nt":
            return
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:
            pass

    def enter(self):
        if self.tty:
            sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")
            sys.stdout.flush()

    def leave(self):
        if self.tty:
            sys.stdout.write("\x1b[?25h\x1b[?1049l")
            sys.stdout.flush()

    def draw(self, state, command, log_path):
        if not self.tty:
            return
        size = shutil.get_terminal_size((100, 30))
        lines = render_lines(state, size.columns, size.lines, command, log_path, self.colour)
        # (each line is erased to its end: a shorter line must not leave the tail of the one before it)
        out = ["\x1b[H"]
        for line in lines:
            out.append(line + "\x1b[K\n")
        out.append("\x1b[J")
        sys.stdout.write("".join(out))
        sys.stdout.flush()


def render_lines(state, width, height, command, log_path, colour=True):
    """The screen as lines; pure (the tests call it without a terminal). No line is wider than width"""
    now = time.monotonic()
    lines = []
    elapsed = fmt_time(state.elapsed(now))
    eta = fmt_time(state.eta) if state.eta is not None else "--:--"
    title = "Hookshot build"
    right = "elapsed %s   ETA %s" % (elapsed, eta)
    lines.append(clip(title + " " * max(1, width - len(title) - len(right)) + right, width))
    status = state.status()
    colour_status = "bad" if status in ("failed", "cancelled") else "done" if status == "done" else "now"
    head = "  " + paint(status, colour_status, colour) + "   " + command
    if state.version:
        head += "   " + state.version
    lines.append(clip(head, width))

    # the steps: done, now, waiting; the ones a make_game build will still run are shown waiting
    ids = list(MAKE_STEPS if state.full else BUILD_STEPS)
    for st in state.stages:
        if st["id"] not in ids:
            ids.append(st["id"])
    parts = []
    for sid in ids:
        label = LABELS.get(sid, sid)
        st = state.by_id.get(sid)
        if st is None:
            parts.append(paint("[%s]" % label, "wait", colour))
        elif sid == state.current and state.finished is None:
            f = st.get("progress")
            if sid == "compile" and state.plan_total:
                f = float(state.files_done) / max(1, state.plan_total)
            pct = " %d%%" % int(100 * f) if f is not None else ""
            parts.append(paint("[%s%s]" % (label, pct), "now", colour))
        elif st.get("end") is not None:
            parts.append(paint("[%s ok]" % label, "done", colour))
        else:
            parts.append(paint("[%s]" % label, "now", colour))
    if not parts:
        parts = [paint("[Compile]", "now", colour)]
    step_line = "  " + " ".join(parts)
    lines.append(clip(step_line, width))

    # the compile bar and its counts (a build.py alone has no @@stage, but it has @@plan)
    done, total = state.files_done, state.plan_total
    if total:
        pct = int(100.0 * done / max(1, total))
        lines.append(clip("  Compile %s %d / %d  (%d%%)   cached %d  new %d  again %d  failed %d"
                          % (progress_bar(done, total, max(10, min(34, width - 68))), done, total, pct,
                             state.files_cached, state.files_new, state.files_again, state.files_failed), width))
        if state.plan_changed is not None and state.plan_changed != total:
            lines.append(clip("  (the plan rebuilds %d of %d files)" % (state.plan_changed, total), width))
    elif "compile" in state.by_id:
        f = state.by_id["compile"].get("progress")
        lines.append(clip("  Compile %s %s" % (progress_bar(0, 0, max(10, min(34, width - 20))),
                                               "" if f is None else "%d%%" % int(100 * f)), width))
    else:
        lines.append(clip("  %s" % state.by_id.get(state.current, {}).get("text", ""), width))

    # the files being compiled: one row a worker, as @@work says them
    worker_rows = min(6, max(0, height - len(lines) - 5))
    workers = sorted(state.in_flight.items(), key=lambda kv: kv[1][2])
    if workers:
        lines.append(clip("  workers:", width))
        for worker, (name, mb, t0) in workers[:worker_rows]:
            lines.append(clip("    %-6s %-34s %3d MB  %4ds" % (short_worker(worker), name,
                                                              mb, int(now - t0)), width))
    elif state.status() == "running" and "compile" in state.by_id:
        lines.append(clip("  workers: waiting for the next file...", width))

    # the tail of the build's own lines
    fixed = len(lines) + 2       # the log's heading and the footer
    log_rows = max(2, height - fixed)
    lines.append(paint("  log:", "dim", colour))
    tail = [x for x in list(state.log)[-log_rows:] if x.strip()]
    for text in tail[-log_rows:]:
        bad = ("error" in text.lower() or "failed" in text.lower() or "not compiled" in text.lower())
        lines.append(clip("    " + paint(text, "bad", colour) if bad else "    " + text, width))
    if not tail:
        lines.append("    (nothing yet)")
    footer = "  Ctrl+C stops the build" + ("   log: %s" % log_path if width > 70 else "")
    if state.finished:
        footer = "  done in %s   log: %s" % (fmt_time(state.elapsed(now)), log_path)
    lines.append(paint(clip(footer, width), "dim", colour))
    return lines[:height]


def stop_tree(proc):
    """Stop the build and the compilers it started, not just the build.py"""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.killpg(os.getpgid(proc.pid), 15)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_build(cmd, state, screen, log_path, plain):
    """Start the command, feed its lines to the state and the log, draw until it ends; returns its exit code"""
    log = open(log_path, "w", encoding="utf-8", errors="replace", buffering=1)
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1,
                                creationflags=creation, start_new_session=(os.name != "nt"))
    except OSError as e:
        state.error = str(e)
        state.finish(-1)
        log.close()
        return -1
    done = threading.Event()

    def read():
        try:
            for line in proc.stdout:
                log.write(line)
                state.feed(line)
                if not screen.tty:
                    text = line.rstrip("\r\n")
                    if text.startswith(("@@stage ", "@@plan ", "@@eta ", "@@done ", "@@error ")):
                        print("build: " + text[2:], flush=True)
                    elif not text.startswith("@@"):
                        print(text, flush=True)
                screen.event.set()
        finally:
            log.close()
            done.set()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    code = None
    try:
        shown = " ".join(cmd[5:]) if cmd[:5] == PY else " ".join(cmd)
        while proc.poll() is None:
            if screen.tty:
                screen.draw(state, shown, log_path)
                screen.event.wait(0.1)
                screen.event.clear()
            else:
                time.sleep(0.1)
        code = proc.returncode
        done.wait(2)
        state.finish(code)
        if screen.tty:
            end = time.monotonic() + 0.9
            while time.monotonic() < end:
                screen.draw(state, shown, log_path)
                time.sleep(0.15)
    except KeyboardInterrupt:
        stop_tree(proc)
        code = proc.wait()
        state.finish(code if code is not None else -1, cancelled=True)
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        reader.join(timeout=1)
    return code if code is not None else -1


def follow(path, state, screen, plain):
    """--attach: follow a log another build is writing (the same @@ lines); Ctrl+C leaves the build alone"""
    while not os.path.exists(path):
        time.sleep(0.2)
    with open(path, encoding="utf-8", errors="replace") as f:
        while True:
            line = f.readline()
            if line:
                state.feed(line)
                if not screen.tty and not line.startswith("@@"):
                    print(line.rstrip("\r\n"), flush=True)
                screen.event.set()
            else:
                if screen.tty:
                    screen.draw(state, "attached to " + path, path)
                screen.event.wait(0.2)
                screen.event.clear()


def demo_events():
    """A made-up build for the screen: no game, no compiler, generic file names"""
    yield "version: Hookshot demo (no game files)"
    yield "@@stage read Reading your game files"
    yield "@@progress 0.35"
    yield "@@stage lift Translating the game to PC code"
    yield "@@progress 0.65"
    yield "@@stage compile Compiling"
    yield "@@plan 2140 4522"
    yield "4522 files, 6 jobs, -O2"
    names = ["code_000.c", "code_003.c", "code_007.c", "host_main.c", "host_memory.c", "host_audio.c",
             "code_012.c", "host_input.c", "code_021.c", "host_net.c", "code_038.c", "host_vk.c"]
    workers = ["ThreadPoolExecutor-0_0", "ThreadPoolExecutor-0_1", "ThreadPoolExecutor-0_2",
               "ThreadPoolExecutor-0_3", "ThreadPoolExecutor-0_4", "ThreadPoolExecutor-0_5"]
    # (the six jobs a build starts together, then one started as each one ends)
    for i, name in enumerate(names[:6]):
        yield "@@work %s %d %s" % (name, 4 + i % 7, workers[i % len(workers)])
    for i, name in enumerate(names):
        mb = 4 + i % 7
        secs = 1.2 + i % 4
        yield "@@file %s %.1f %s" % (name, secs, "cached" if i % 3 == 0 else "new")
        yield "  %-16s %4d MB  %6.1fs  (%.0fs)" % (name, mb, secs, i * 1.5)
        if i + 6 < len(names):
            nxt = names[i + 6]
            yield "@@work %s %d %s" % (nxt, 4 + (i + 6) % 7, workers[(i + 6) % len(workers)])
        if i in (5, 9):
            yield "@@eta %d" % (900 - i * 60)
    yield "@@stage finish Putting the game folder together"
    yield "@@progress 0.8"
    yield "@@stage shaders Preparing shaders"
    yield "@@times 12 10 -1"
    yield "@@done ~/Games/Hookshot"


def run_demo(state, screen, log_path, plain):
    log = open(log_path, "w", encoding="utf-8", errors="replace", buffering=1)
    try:
        for line in demo_events():
            log.write(line + "\n")
            state.feed(line)
            if not screen.tty:
                text = line.rstrip("\r\n")
                print(text if not text.startswith("@@") else "build: " + text[2:], flush=True)
            else:
                screen.draw(state, "demo (no game files)", log_path)
            time.sleep(0.45 if line.startswith("@@work") else 0.12)
        state.finish(0)
        if screen.tty:
            end = time.monotonic() + 0.8
            while time.monotonic() < end:
                screen.draw(state, "demo (no game files)", log_path)
                time.sleep(0.15)
    finally:
        log.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--jobs", type=int, default=None, help="--jobs for the build (the build's default is 1)")
    p.add_argument("--plain", action="store_true", help="print the build's lines, no full screen")
    p.add_argument("--no-color", action="store_true", help="no ANSI colours")
    p.add_argument("--demo", action="store_true", help="a made-up build, for the screen itself")
    p.add_argument("--attach", metavar="LOG", help="follow a log another build is writing")
    p.add_argument("--log", help="the full log (default: work/build_ui.log)")
    p.add_argument("--make", action="store_true", help="run nx2/make_game.py instead of build.py --standalone")
    p.add_argument("args", nargs=argparse.REMAINDER, help="arguments for the build, after --")
    a = p.parse_args()
    extra = [x for x in a.args if x != "--"]
    state = BuildState()
    screen = Screen(a.plain, not a.no_color)
    log_path = a.log or os.path.join(ROOT, "work", "build_ui.log")
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    if a.demo:
        screen.enter()
        try:
            run_demo(state, screen, log_path, a.plain)
        except KeyboardInterrupt:
            state.finish(130, cancelled=True)
        finally:
            screen.leave()
        code = 0 if not state.error else 1
    elif a.attach:
        screen.enter()
        try:
            follow(a.attach, state, screen, a.plain)
        except KeyboardInterrupt:
            pass
        finally:
            screen.leave()
        code = 0
    else:
        tool = os.path.join(ROOT, "nx2", "make_game.py") if a.make else os.path.join(ROOT, "nx2", "build.py")
        cmd = PY + [tool] + ([] if a.make else ["--standalone"]) + extra
        if a.jobs is not None:
            cmd += ["--jobs", str(a.jobs)]
        if not screen.tty:
            print("build_ui: " + " ".join(cmd), flush=True)
        screen.enter()
        try:
            code = run_build(cmd, state, screen, log_path, a.plain)
        except KeyboardInterrupt:
            code = 130
        finally:
            screen.leave()
    total = fmt_time(state.elapsed())
    compile_time = fmt_time(state.compile_seconds()) if state.compile_seconds() is not None else "--:--"
    status = state.status()
    print("build %s in %s (compile %s); log: %s" % (status, total, compile_time, log_path))
    if state.error:
        print("error: %s" % state.error)
    sys.exit(0 if a.attach or (status == "done" and code == 0) else 130 if status == "cancelled" else 1)


if __name__ == "__main__":
    main()
