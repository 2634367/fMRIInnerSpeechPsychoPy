import atexit
import shutil
import sys

CSI = "\x1b["
RESET = f"{CSI}0m"
STYLES = {"dim": 2, "bold": 1, "red": 31, "green": 32, "yellow": 33,
          "magenta": 35, "cyan": 36}
FILLED, EMPTY = "█", "░"

# The token the participant repeats, coloured so a glance is enough.
TOKEN_STYLE = {"yes": "green", "no": "yellow", "ready": "cyan", None: "dim"}


def _write(text):
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (ValueError, OSError):      # stdout closed under us during shutdown
        pass


def _style(names):
    return "".join(f"{CSI}{STYLES[n]}m" for n in names.split())


def _bar(fraction, width):
    n = max(0, min(width, round(fraction * width)))
    return FILLED * n + EMPTY * (width - n)


def _clock(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _fit(text, width):
    """One line, collapsed whitespace, ellipsised to `width`."""
    text = " ".join(str(text).split())
    width = max(8, width)
    return text if len(text) <= width else text[:width - 1] + "…"


def _row(left, right=(), width=80, colour=True):
    """Compose a line from (text, style) parts; `right` is pushed to the margin."""
    used = sum(len(t) for t, _ in left) + sum(len(t) for t, _ in right)
    if used + 2 > width:               # too tight for both columns; keep the left
        right, used = (), sum(len(t) for t, _ in left)
    parts = list(left) + ([(" " * (width - used), "")] if right else []) + list(right)
    if not colour:
        return "".join(t for t, _ in parts)
    return "".join(_style(s) + t + RESET if s else t for t, s in parts)


class Console:
    """Every line the task prints is formatted here."""

    def __init__(self, cfg, enabled=True):
        opts = cfg.get("console") or {}
        self.cfg = cfg
        self.hz = float(opts.get("refresh_hz", 10))
        self.on = bool(enabled)
        self.tty = self.on and self.hz > 0 and sys.stdout.isatty()
        self.colour = self.tty and bool(opts.get("colour", True))
        self.width = min(shutil.get_terminal_size((100, 24)).columns - 1, 110)
        self.bar = 26 if self.width >= 96 else 12

        run = cfg["run"]
        self.n_blocks = run["n_blocks"]
        self.n_trials = run["n_blocks"] * run["trials_per_block"]
        self.phases = [p["name"] for p in cfg["trial"]["phases"]]
        self.name_w = max(len(p) for p in self.phases + ["lead-in", "lead-out"])
        self.total = None              # estimated run duration, filled in by plan()

        self.cur = self.nxt = None
        self.span = ("—", 0.0, 1.0)
        self._painted = 0
        self._due = 0.0
        self._pulses = None
        if self.tty:
            _write(f"{CSI}?25l")
            atexit.register(_write, f"{CSI}?25h")

    # ------------------------------------------------------ terminal I/O ---
    def _erase(self):
        if self._painted:
            _write(f"{CSI}{self._painted}F{CSI}J")   # up to the block, clear below
            self._painted = 0

    def _paint(self, lines):
        """Redraw the live block in place."""
        self._erase()
        _write("\n".join(lines) + "\n")
        self._painted = len(lines)

    def _emit(self, text):
        """Write a line that stays on screen, above the live block."""
        if self.on:
            self._erase()
            _write(text + "\n")

    def _rule(self, label, style="bold"):
        pad = "─" * max(3, self.width - len(label) - 4)
        self._emit(_row([("── ", "dim"), (label, style), (" " + pad, "dim")],
                        (), self.width, self.colour))

    def _say(self, label, value):
        self._emit(_row([(f"   {label:<9}", "dim"), (str(value), "")],
                        (), self.width, self.colour))

    # --------------------------------------------------------- one-offs ---
    def header(self, run_id, config_path, n_questions):
        run, scanner = self.cfg["run"], self.cfg["scanner"]
        self._rule(run_id, "bold cyan")
        self._say("config", f"{config_path.name} · {self.cfg['experiment']}")
        self._say("trials", f"{self.n_trials}  "
                            f"({run['n_blocks']} blocks × {run['trials_per_block']})")
        self._say("bank", f"{n_questions} questions")
        self._say("phases", " › ".join(self.phases))
        self._say("scanner", f"TR {scanner['tr']}s · {scanner['wait_for_triggers']} "
                             f"dummy pulses on key `{scanner['trigger_key']}`")

    def plan(self, seed, trials, reused):
        """The run is built: durations are known, so the length is too."""
        self.total = (self.cfg["run"]["lead_in"] + self.cfg["run"]["lead_out"]
                      + sum(sum(t["durations"].values()) for t in trials))
        self._say("plan", f"seed {seed} · {reused} questions reused · "
                          f"est. {_clock(self.total)}")

    def note(self, label, text):
        self._say(label, text)

    def waiting(self, seen, total):
        """Live pulse counter; repaints only when a pulse arrives."""
        if seen == self._pulses:
            return
        self._pulses = seen
        if self.tty:
            self._paint(["", _row(
                [("  pulses ", "dim"),
                 (_bar(seen / total if total else 1.0, self.bar), "magenta"),
                 (f"  {seen}/{total}", "bold")],
                [(f"waiting for key `{self.cfg['scanner']['trigger_key']}`", "dim")],
                self.width, self.colour)])

    def summary(self, record, path):
        aborted = record["aborted"]
        self._erase()
        self._rule("aborted" if aborted else "complete",
                   "bold red" if aborted else "bold green")
        self._say("trials", f"{len(record['trials'])}/{self.n_trials} recorded · "
                            f"{record.get('questions_reused', 0)} questions reused")
        self._say("duration", f"{_clock(record.get('duration'))} "
                              f"({record.get('duration')} s) · "
                              f"{record['n_triggers']} triggers logged")
        self._say("written", path)

    # -------------------------------------------------------- live block ---
    def trial(self, trial, upcoming=None):
        self.cur, self.nxt = trial, upcoming
        self._due = 0.0
        if trial and self.on and not self.tty:
            self._emit(f"   trial {trial['trial'] + 1:>4}/{self.n_trials}  "
                       f"b{trial['block'] + 1:<2} t={trial['t_start']:>7.1f}s  "
                       f"{trial['condition']:<14}{self._badge(trial):<18}"
                       f"{_fit(trial['text'], 50)}")

    def phase(self, name, t_start, t_end):
        self.span = (name, t_start, t_end)
        self._due = 0.0                # a new phase is worth a frame of its own

    def tick(self, t):
        """Called every frame from the presentation loop; cheap when throttled."""
        if not self.tty or t < self._due:
            return
        self._due = t + 1.0 / self.hz
        self._paint(self._lines(t))

    def _lines(self, t):
        cur = self.cur
        name, t_start, t_end = self.span
        done = cur["trial"] + 1 if cur else 0
        where = f"block {cur['block'] + 1}/{self.n_blocks}" if cur else "lead-in"
        frac = min(1.0, t / self.total) if self.total else 0.0
        left = max(0.0, t_end - t)
        strip = []
        for p in self.phases:                  # constant width: one phase bracketed
            strip += [(" › ", "dim")] if strip else []
            strip += [(f"[{p[:3]}]" if p == name else f" {p[:3]} ",
                       "bold yellow" if p == name else "dim")]
        return [
            "",
            _row([("  run    ", "dim"), (_bar(frac, self.bar), "cyan"),
                  (f" {frac:>4.0%}", "bold"),
                  (f"   trial {done}/{self.n_trials}   {where}", "")],
                 [(f"{_clock(t)} / {_clock(self.total)}", "dim")],
                 self.width, self.colour),
            _row([("  phase  ", "dim"),
                  (_bar(1.0 - left / (t_end - t_start) if t_end > t_start else 1.0,
                        self.bar), "yellow"),
                  (f" {name:<{self.name_w}} ", "bold"), (f"{left:4.1f}s", "")],
                 strip, self.width, self.colour),
            self._question("now", cur, "bold"),
            self._question("next", self.nxt, "dim"),
        ]

    def _badge(self, trial):
        token = trial["response_token"]
        return f"{trial['answer']} → {token.upper() if token else 'SILENT'}"

    def _question(self, label, trial, style):
        if trial is None:
            return _row([(f"  {label:<7}", "dim"), ("—", "dim")],
                        (), self.width, self.colour)
        badge = f"{trial['condition']} · {self._badge(trial)}"
        text = trial["text"] if trial["show_question"] else "(cue only — not shown)"
        return _row([(f"  {label:<7}", "dim"),
                     (_fit(text, self.width - len(badge) - 14), style)],
                    [(badge, TOKEN_STYLE.get(trial["response_token"]))],
                    self.width, self.colour)
