"""Run flow and stimulus timing.

Time zero is the last dummy-volume trigger pulse. Every phase boundary is
scheduled as an absolute offset from that instant, so timing error never
accumulates across a 30-minute run. All onsets written to the database are in
that same run-clock timebase and can be used directly as GLM onsets.
"""
import random

from psychopy import core, visual
from psychopy.hardware import keyboard

from . import bank, db, views


class Abort(Exception):
    """Raised when the operator presses the quit key."""


class Session:
    def __init__(self, cfg, meta, database, seed=None, wait_for_scanner=True,
                 fullscreen=None, auto=False):
        self.cfg = cfg
        self.meta = meta
        self.db = database
        self.seed = random.SystemRandom().randrange(2 ** 31) if seed is None else seed
        self.rng = random.Random(self.seed)
        self.wait_for_scanner = wait_for_scanner
        self.fullscreen = fullscreen
        self.auto = auto
        self.t0 = None
        self.trigger_times = []
        self.aborted = False

    # ------------------------------------------------------------ clock ---
    def now(self):
        """Seconds since the scan start pulse."""
        return core.getTime() - self.t0

    # ------------------------------------------------------------ setup ---
    def open_window(self):
        w = self.cfg["window"]
        self.win = visual.Window(
            size=w["size"],
            fullscr=w["fullscreen"] if self.fullscreen is None else self.fullscreen,
            screen=w["screen"], color=w["color"], units=w["units"],
            allowGUI=False, waitBlanking=True,
        )
        self.win.mouseVisible = w.get("mouse_visible", False)
        self.frame_dur = self.win.monitorFramePeriod or 1.0 / 60.0

        f = self.cfg["fixation"]
        self.fixation = visual.TextStim(
            self.win, text=f["text"], height=f["height"], color=f["color"],
            font=self.cfg["text"]["font"],
        )
        c = self.cfg["cue"]
        self.cue = visual.TextStim(
            self.win, text="", height=c["height"], color=c["color"],
            font=self.cfg["text"]["font"],
        )
        self.message = visual.TextStim(
            self.win, text="", height=self.cfg["text"]["height"],
            color=self.cfg["text"]["color"], font=self.cfg["text"]["font"],
            wrapWidth=self.cfg["text"]["wrap_width"],
        )
        self.views = views.build_all(self.win, self.cfg)
        self.kb = keyboard.Keyboard()

    def close(self):
        if getattr(self, "win", None):
            self.win.close()

    # ------------------------------------------------------- key polling ---
    def _poll(self):
        """Drain the keyboard: record trigger pulses, honour the quit key."""
        quit_keys = self.cfg["keys"]["quit"]
        trigger = self.cfg["scanner"]["trigger_key"]
        for key in self.kb.getKeys([trigger] + list(quit_keys), waitRelease=False):
            if key.name in quit_keys:
                raise Abort()
            if self.t0 is not None and self.cfg["scanner"].get("log_triggers"):
                t = self.now()
                self.trigger_times.append(round(t, 4))
                self.db.log("trigger", t=round(t, 4))

    def _present(self, draw, t_end):
        """Draw every frame until the run clock reaches `t_end`."""
        onset = None
        while True:
            draw()
            self.win.flip()
            if onset is None:
                onset = self.now()
            self._poll()
            if self.now() >= t_end - self.frame_dur / 2:
                break
        return round(onset, 4), round(self.now(), 4)

    def _blank(self):
        pass

    # ------------------------------------------------------- run phases ---
    def show_message(self, text, wait_keys):
        """Static screen shown before the scan starts; waits for a keypress."""
        self.message.text = text
        self.message.draw()
        self.win.flip()
        self.kb.clearEvents()
        if self.auto:
            core.wait(1.0)
            return
        while True:
            keys = self.kb.getKeys(list(wait_keys) + list(self.cfg["keys"]["quit"]),
                                   waitRelease=False)
            for key in keys:
                if key.name in self.cfg["keys"]["quit"]:
                    raise Abort()
                return
            self.message.draw()
            self.win.flip()

    def wait_for_triggers(self):
        """Block until the scanner has sent the dummy-volume pulses."""
        n = self.cfg["scanner"]["wait_for_triggers"]
        trigger = self.cfg["scanner"]["trigger_key"]
        quit_keys = self.cfg["keys"]["quit"]

        if not self.wait_for_scanner:
            self.t0 = core.getTime()
            self.db.log("scan_start", t=0.0, simulated=True, pulses=0)
            return

        pulses = []
        self.kb.clearEvents()
        while len(pulses) < n:
            self.message.text = (
                f"Waiting for the scanner…\n\n{len(pulses)} / {n} pulses"
            )
            self.message.draw()
            self.win.flip()
            for key in self.kb.getKeys([trigger] + list(quit_keys), waitRelease=False):
                if key.name in quit_keys:
                    raise Abort()
                pulses.append((key.name, getattr(key, "tDown", None), core.getTime()))
                self.db.log("dummy_trigger", index=len(pulses))

        _, t_down, t_seen = pulses[-1]
        # Prefer the hardware timestamp when it is in the expected timebase.
        self.t0 = t_down if (t_down and abs(t_seen - t_down) < 1.0) else t_seen
        self.db.log("scan_start", t=0.0, simulated=False, pulses=len(pulses),
                    t0_monotonic=round(self.t0, 6))

    def run_trial(self, trial):
        """Present one trial. Returns it with measured onsets and offsets filled in."""
        view = self.views[trial["view"]]
        view.prepare(trial)
        self.cue.text = trial["cue"]

        painters = {
            "fixation": self.fixation.draw,
            "question": (view.draw if trial["show_question"] else self._blank),
            "cue": self.cue.draw,
            "blank": self._blank,
        }

        onsets, offsets = {}, {}
        cursor = trial["t_start"]
        for phase in self.cfg["trial"]["phases"]:
            name = phase["name"]
            cursor += trial["durations"][name]
            onset, offset = self._present(painters[phase["show"]], cursor)
            onsets[name], offsets[name] = onset, offset
            self.db.log("phase", trial=trial["trial"], phase=name,
                        onset=onset, offset=offset,
                        question_uuid=trial["question_uuid"],
                        condition=trial["condition"], answer=trial["answer"],
                        response_token=trial["response_token"])

        trial["onsets"] = onsets
        trial["offsets"] = offsets
        trial["t_end"] = round(cursor, 4)
        return trial

    # ------------------------------------------------------------- main ---
    def run(self, questions):
        record = {
            "run_id": self.db.run_id,
            "experiment": self.cfg["experiment"],
            **self.meta,
            "seed": self.seed,
            "started": db.now_iso(),
            "aborted": False,
            "config": dict(self.cfg),
            "trials": [],
        }

        self.open_window()
        try:
            trials, reused = bank.build_run(
                questions, self.cfg, self.rng,
                already_seen=self.db.seen_question_ids(self.meta["participant"]),
            )
            record["questions_reused"] = reused
            self.db.log("run_built", n_trials=len(trials), reused=reused,
                        seed=self.seed)

            self.show_message(self.cfg["instructions"], self.cfg["keys"]["advance"])
            self.wait_for_triggers()
            record["t0_monotonic"] = round(self.t0, 6)

            # lead-in, trials, lead-out on one continuous schedule
            cursor = self.cfg["run"]["lead_in"]
            self._present(self.fixation.draw, cursor)
            self.db.log("lead_in", onset=0.0, offset=round(cursor, 4))

            for trial in trials:
                trial["t_start"] = round(cursor, 4)
                self.run_trial(trial)
                cursor = trial["t_end"]
                record["trials"].append(trial)

            cursor += self.cfg["run"]["lead_out"]
            self._present(self.fixation.draw, cursor)
            self.db.log("lead_out", offset=round(cursor, 4))
            record["duration"] = round(self.now(), 4)

        except Abort:
            self.aborted = True
            record["aborted"] = True
            record["duration"] = round(self.now(), 4) if self.t0 else None
            self.db.log("aborted", t=record["duration"])
        finally:
            record["ended"] = db.now_iso()
            record["trigger_times"] = self.trigger_times
            record["n_triggers"] = len(self.trigger_times)
            path = self.db.write_run(record)
            self.db.log("run_written", path=str(path), n_trials=len(record["trials"]))
            self.close()
        return record, path
