"""Run flow and stimulus timing.

Time zero is the last dummy-volume trigger pulse. Every phase boundary is
scheduled as an absolute offset from that instant, so timing error never
accumulates across a 30-minute run. All onsets written to the database are in
that same run-clock timebase and can be used directly as GLM onsets.

With `debug`, the pause key (`keys.pause`) holds the run and
the same key resumes it. The run clock stops while paused, so every remaining
phase keeps its full length - but the scanner does not stop, so a paused run's
onsets no longer line up with its volumes. The record lists every pause.
"""
import random

from psychopy import core, visual
from psychopy.hardware import keyboard

from . import bank, console, db, views


class Abort(Exception):
    """Raised when the operator presses the quit key."""


class Session:
    def __init__(self, cfg, meta, database, seed=None, wait_for_scanner=True,
                 fullscreen=None, auto=False, con=None, debug=False):
        self.cfg = cfg
        self.con = con or console.Console(cfg)
        self.meta = meta
        self.db = database
        self.seed = random.SystemRandom().randrange(2 ** 31) if seed is None else seed
        self.rng = random.Random(self.seed)
        self.wait_for_scanner = wait_for_scanner
        self.fullscreen = fullscreen
        self.auto = auto
        self.debug = debug
        self.pause_keys = list(cfg["keys"]["pause"]) if debug else []
        self.pauses = []
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
            allowGUI=w["allow_gui"], waitBlanking=w["wait_blanking"],
        )
        self.win.mouseVisible = w["mouse_visible"]
        self.frame_dur = self.win.monitorFramePeriod or 1.0 / w["assumed_refresh_hz"]

        t = self.cfg["text"]
        # fixation and every other `screens:` entry: one line of text each
        self.screens = {
            name: visual.TextStim(self.win, text=s["text"], height=s["height"],
                                  color=s["color"], font=s["font"], pos=s["pos"])
            for name, s in self.cfg["screens"].items()
        }
        c = self.cfg["cue"]
        self.cue = visual.TextStim(
            self.win, text="", height=c["height"], color=c["color"], pos=c["pos"],
            font=t["font"],
        )
        self.message = visual.TextStim(
            self.win, text="", height=t["height"], color=t["color"], font=t["font"],
            wrapWidth=t["wrap_width"], alignText=t["align"],
        )
        self.views = views.build_all(self.win, self.cfg)
        self.kb = keyboard.Keyboard()
        if self.debug:
            p = self.cfg["messages"]["paused"]
            self.paused_label = visual.TextStim(
                self.win, text=p["text"].format(keys="/".join(self.pause_keys)),
                height=p["height"], pos=p["pos"], color=p["color"], font=p["font"],
            )

    def close(self):
        if getattr(self, "win", None):
            self.win.close()

    # ------------------------------------------------------- key polling ---
    def _poll(self):
        """Drain the keyboard: record trigger pulses, honour the quit key.

        Returns True when the pause key was pressed (debug runs only).
        """
        quit_keys = self.cfg["keys"]["quit"]
        trigger = self.cfg["scanner"]["trigger_key"]
        paused = False
        for key in self.kb.getKeys([trigger] + list(quit_keys) + self.pause_keys,
                                   waitRelease=False):
            if key.name in quit_keys:
                raise Abort()
            if key.name in self.pause_keys:
                paused = True
                continue
            if self.t0 is not None and self.cfg["scanner"]["log_triggers"]:
                t = self.now()
                self.trigger_times.append(round(t, 4))
                self.db.log("trigger", t=round(t, 4))
        return paused

    def _present(self, draw, t_end):
        """Draw every frame until the run clock reaches `t_end`."""
        onset = None
        while True:
            draw()
            self.win.flip()
            if onset is None:
                onset = self.now()
            if self._poll():
                self._pause(draw)
            self.con.tick(self.now())
            if self.now() >= t_end - self.frame_dur / 2:
                break
        return round(onset, 4), round(self.now(), 4)

    def _pause(self, draw):
        """Hold the current screen until the pause key comes again.

        Moving t0 forward by the pause stops the run clock, so the phase that
        was interrupted, and every one after it, keeps its full length.
        """
        at = self.now()
        start = core.getTime()
        entry = {"at": round(at, 4), "duration": None}   # None if aborted while paused
        self.pauses.append(entry)
        self.db.log("pause", t=round(at, 4))
        self.con.warn("pause", f"paused at {console._clock(at)} - "
                               f"{'/'.join(self.pause_keys)} to resume")
        while True:
            draw()
            self.paused_label.draw()
            self.win.flip()
            if self._poll():
                break
        held = core.getTime() - start
        self.t0 += held
        entry["duration"] = round(held, 4)
        self.db.log("resume", t=round(at, 4), paused_for=round(held, 4))
        self.con.note("resume", f"after {held:.1f}s")

    def _blank(self):
        pass

    def _painters(self, trial=None):
        """What each `show` value draws: every screen, plus the trial's own."""
        painters = {name: stim.draw for name, stim in self.screens.items()}
        painters["blank"] = self._blank
        if trial is not None:
            view = self.views[trial["view"]]
            painters["question"] = view.draw if trial["show_question"] else self._blank
            painters["cue"] = self.cue.draw
        return painters

    # ------------------------------------------------------- run phases ---
    def show_message(self, text, wait_keys):
        """Static screen shown before the scan starts; waits for a keypress."""
        self.message.text = text
        self.message.draw()
        self.win.flip()
        self.kb.clearEvents()
        if self.auto:
            core.wait(self.cfg["pilot"]["auto_advance"])
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
            self.con.note("scan", "no scanner - t0 is now")
            return

        pulses = []
        self.kb.clearEvents()
        while len(pulses) < n:
            self.message.text = self.cfg["messages"]["waiting"].format(
                seen=len(pulses), total=n)
            self.message.draw()
            self.win.flip()
            self.con.waiting(len(pulses), n)
            for key in self.kb.getKeys([trigger] + list(quit_keys), waitRelease=False):
                if key.name in quit_keys:
                    raise Abort()
                pulses.append((key.name, getattr(key, "tDown", None), core.getTime()))
                self.db.log("dummy_trigger", index=len(pulses))

        _, t_down, t_seen = pulses[-1]
        # Prefer the hardware timestamp when it is in the expected timebase.
        tolerance = self.cfg["scanner"]["timestamp_tolerance"]
        self.t0 = t_down if (t_down and abs(t_seen - t_down) < tolerance) else t_seen
        self.db.log("scan_start", t=0.0, simulated=False, pulses=len(pulses),
                    t0_monotonic=round(self.t0, 6))
        self.con.note("scan", f"t0 locked to pulse {len(pulses)}/{n}")

    def run_trial(self, trial):
        """Present one trial. Returns it with measured onsets and offsets filled in."""
        self.views[trial["view"]].prepare(trial)
        self.cue.text = trial["cue"]
        painters = self._painters(trial)

        onsets, offsets = {}, {}
        cursor = trial["t_start"]
        for phase in self.cfg["trial"]["phases"]:
            name = phase["name"]
            start, cursor = cursor, cursor + trial["durations"][name]
            self.con.phase(name, start, cursor)
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

    def run_lead(self, key, start, dur, record):
        """Present the lead-in or lead-out (`key`) from `start` for `dur` seconds.

        The event kind stays `lead_in` / `lead_out` whatever the phase is called,
        so the database reads the same for every config. Returns where it ends.
        """
        lead = self.cfg["run"][key]
        end = start + dur
        self.con.phase(lead["name"], start, end)
        onset, offset = self._present(self._painters()[lead["show"]], end)
        self.db.log(key, name=lead["name"], show=lead["show"], onset=onset,
                    offset=offset)
        record[key] = {"name": lead["name"], "show": lead["show"], "dur": dur,
                       "onset": onset, "offset": offset}
        return round(end, 4)

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
            # after the trials, so a fixed lead leaves the trial draws untouched
            leads = bank.lead_durations(self.cfg, self.rng)
            record["questions_reused"] = reused
            self.db.log("run_built", n_trials=len(trials), reused=reused,
                        seed=self.seed)
            self.con.plan(self.seed, trials, reused, leads)

            self.con.note("ready", "instructions on screen - " + (
                "auto-advancing" if self.auto
                else "press " + "/".join(self.cfg["keys"]["advance"])))
            self.show_message(self.cfg["instructions"], self.cfg["keys"]["advance"])
            self.wait_for_triggers()
            record["t0_monotonic"] = round(self.t0, 6)
            if self.pause_keys:
                # a press left over from the pre-scan screens must not pause frame one
                self.kb.getKeys(self.pause_keys, waitRelease=False)

            # lead-in, trials, lead-out on one continuous schedule
            self.con.trial(None, trials[0])
            cursor = self.run_lead("lead_in", 0.0, leads["lead_in"], record)

            for i, trial in enumerate(trials):
                trial["t_start"] = round(cursor, 4)
                self.con.trial(trial, trials[i + 1] if i + 1 < len(trials) else None)
                self.run_trial(trial)
                cursor = trial["t_end"]
                record["trials"].append(trial)

            self.run_lead("lead_out", cursor, leads["lead_out"], record)
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
            if self.debug:
                record["pauses"] = self.pauses
            path = self.db.write_run(record)
            self.db.log("run_written", path=str(path), n_trials=len(record["trials"]))
            self.close()
        return record, path
