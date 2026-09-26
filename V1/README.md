# Inner Speech fMRI — PsychoPy task

Minimal stimulus-presentation task for dense single-participant fMRI decoding of
prompted covert yes/no inner speech. See `docs/` for the research strategy the
design follows.

## Run it

```bash
./run.sh --pilot            # windowed, 2 blocks, no scanner — check the display
./run.sh --participant sub01 --session 1
./run.sh --config glm --participant sub01 --session 1   # config/experiment-glm.yaml
./run.sh --overview-only    # draw overview/*.png for every config, then exit
```

`run.sh` uses `python3` if `psychopy` is importable there, otherwise the
interpreter bundled inside `/Applications/PsychoPy.app`. You can also open
`run_experiment.py` in the PsychoPy Coder and press Run.

| flag | effect |
|---|---|
| `--config NAME` | which config to run: `experiment` (default), `glm`, `mvpa`, `time-series`. A path or file name works too |
| `--participant` / `--session` / `--run` | run identity (`--run` defaults to the next unused one) |
| `--blocks N` | shorten the run; condition counts rescale proportionally |
| `--no-scanner` | start immediately instead of waiting for trigger pulses |
| `--windowed` | do not go fullscreen |
| `--auto` | advance the pre-scan screens with no keypress (display check) |
| `--pilot` | `--blocks 2 --no-scanner --windowed` |
| `--seed N` | fix the RNG; the seed is recorded either way, so any run can be rebuilt |
| `--quiet` | no terminal readout during the run |
| `--overview` / `--no-overview` | draw the overview images before the run (on by default) |
| `--overview-only` | draw the overview images and exit — no window, nothing written to `data/` |

`escape` aborts at any point and still writes everything collected so far.

## Overview images

Before every run the task draws what each design in `config/` looks like to
`overview/`, one PNG per config plus `overview.png` comparing them all:

- **`overview/<config>.png`**: TR, trial count and run length at a glance. It
  also shows the trial anatomy (each phase at its mean length, jitter whiskers,
  and a mock-up of the screen), the jitter distribution of each jittered phase,
  an example run block by block, and the condition counts with the question
  views.
- **`overview/overview.png`**: every config side by side, with a summary table,
  one trial per config on a shared axis, run-length ranges, and every example
  run on a single clock. The config chosen with `--config` is marked ▶.

The example runs and jitter draws use the task's own run builder and sampler,
with a fixed seed. That makes the images identical from one launch to the next
until a config, the bank or the code changes. They show *a* run, not the one
about to be presented.

Drawing takes a few seconds. If it fails for any reason, the console prints
`overview  skipped - …` and the run goes ahead. A config that does not load gets
a placeholder image naming the error, and the other configs are still drawn.
`run:` keys that the task does not implement (`inter_block_rest`,
`inter_trial_gap`, `label_*`) are listed in a footnote and left out of every
length shown.

## The operator console

While the run is on screen, the terminal shows where it is:

```
── sub-sub01_ses-01_run-05 ───────────────────────────────────────────────────────────────────
   config   experiment.yaml · inner_speech_v2
   trials   100  (10 blocks × 10)
   bank     80 questions
   phases   fixation_pre › question › blank › answer › fixation_post
   scanner  TR 0.8s · 12 dummy pulses on key `5`
   overview 5 images in overview/
   plan     seed 1846329471 · 3 questions reused · est. 24:20
   ready    instructions on screen - press space
   scan     t0 locked to pulse 12/12

  run    █████████░░░░░░░░░░░░░░░░░  36%   trial 36/100   block 4/10        8:47 / 24:20
  phase  ██████████████░░░░░░░░░░░░ answer          1.8s   fix  ›  que  ›  bla  › [ans] ›  fix
  now    Is a plum a fruit?                                              primary · yes → YES
  next   Is the pictured object an animal?                                 primary · no → NO
```

The last four lines are rewritten in place and count down in real time, so the
log above them stays readable. `answer` is the truth of the proposition and the
token after the arrow is what the participant repeats — they differ on
`opposite` and `constant_word` trials.

Repainting costs ~0.4% of one frame and happens at most `console.refresh_hz`
times a second, just after the buffer swap:

```yaml
console:
  refresh_hz: 10                 # live redraw rate; 0 for one plain line per trial
  colour: true
```

Set `refresh_hz: 0`, pass `--quiet`, or redirect stdout to a file and the live
block degrades to one plain line per trial — which is what you want when you are
keeping a text log of the session.

## Layout

```
config/experiment.yaml   all settings — timing, window, conditions, scanner
config/experiment-*.yaml one per analysis aim (glm, mvpa, time-series); pick with --config
questions/bank.json      the question bank
questions/images/        image stimuli
innerspeech/config.py    YAML loading + validation
innerspeech/bank.py      bank loading, label balancing, jitter, run construction
innerspeech/db.py        the JSON database (the only thing that writes to disk)
innerspeech/session.py   window, timing loop, trigger handling, run flow
innerspeech/console.py   the operator's terminal readout (prints, never records)
innerspeech/overview.py  the overview images of every config (draws, never records)
innerspeech/views/       one class per question view
overview/                the generated overview PNGs
run_experiment.py        entry point
```

## The database

Everything the task produces goes to `data/`, and every write goes through
`innerspeech/db.py`.

- **`data/events.jsonl`** — append-only stream of every event across every run:
  trigger pulses, scan start, each trial phase with its measured onset and
  offset, aborts. Flushed on every write, so a crash still leaves a full record.
- **`data/runs/<run_id>.json`** — one self-contained record per run: participant,
  session, run, RNG seed, a snapshot of the config that produced it, all trigger
  times, and every trial with its scheduled durations and measured onsets.

`run_id` is `sub-<participant>_ses-NN_run-NN`.

Onsets are seconds from the last dummy-volume trigger, so they drop straight
into a GLM design matrix. Each trial records both `answer` (the truth of the
proposition) and `response_token` (what the participant actually repeats) —
these differ on `opposite` and `constant_word` trials, which is what makes the
negative-control analyses possible.

## Questions

One JSON object per question:

```json
{
  "uuid": "…",
  "category": "perceptual_relational",
  "view": "shapes",
  "text": "Is the triangle above the square?",
  "answer": "yes",
  "family": "relpos_triangle_square",
  "params": {"shapes": [{"kind": "triangle", "pos": [0, 0.06]},
                        {"kind": "square",   "pos": [0, -0.16]}]}
}
```

- `view` selects the renderer (below). `params` is view-specific.
- `family` groups paraphrases and close variants so they can be kept in the same
  machine-learning fold later.
- `uuid` must be unique. Stable ids for new questions:
  ```bash
  python3 -c "import uuid;print(uuid.uuid5(uuid.uuid5(uuid.NAMESPACE_URL,'innerspeech'),'YOUR QUESTION TEXT'))"
  ```

The shipped bank has 80 questions, balanced 40 yes / 40 no, across the eight
families in the research strategy. A 100-trial run needs more than that to avoid
repeats — the builder prefers questions this participant has not seen, falls back
to reuse, and records how many were reused as `questions_reused`.

## Views

| view | shows | params |
|---|---|---|
| `text` | question text, centred | — |
| `shapes` | text at top + geometric shapes | `shapes: [{kind, pos, size, color, ori}]` |
| `image` | text at top + an image | `image: "file.png"`, `size: [w, h]` |

Shape kinds: `triangle`, `square`, `diamond`, `pentagon`, `hexagon`, `circle`.

Most question families only need words, so they share `text`. To add a view:
subclass `View` (implement `build`, `prepare`, `draw`), register it in
`innerspeech/views/__init__.py`, and set `"view": "<name>"` on the questions
that use it. Stimuli are created once at startup and only reconfigured per
trial, which keeps the frame loop cheap.

## Timing

Time zero is the last dummy-volume trigger pulse. Every phase boundary is
scheduled as an absolute offset from that instant, so error never accumulates
across a run — measured onsets sit within one or two frames of schedule and the
exact measured values are what get written to the database.

The trial structure is entirely config-driven:

```yaml
trial:
  round_jitter_to_tr: true
  jitter: geometric
  jitter_p: 0.5
  phases:
    - {name: fixation_pre,  show: fixation, dur: [2.0, 6.0]}
    - {name: question,      show: question, dur: 4.0}
    - {name: blank,         show: blank,    dur: 1.0}
    - {name: answer,        show: cue,      dur: 3.0}
    - {name: fixation_post, show: fixation, dur: [2.0, 6.0]}
```

A scalar `dur` is fixed; a `[lo, hi]` pair is jittered. `show` is one of
`fixation`, `question`, `cue`, `blank`.

`trial.jitter` sets how every `[lo, hi]` phase is sampled, and a phase can
override it with its own `jitter:` (and `p:`):

| jitter | draws |
|---|---|
| `geometric` | `lo` plus *n* whole TRs, P(*n*) ∝ `p`(1 − `p`)^*n*, capped at `hi` — the truncated geometric (textbook eq. 5.3). Memoryless, so the participant cannot predict the next event; `jitter_p` (default 0.5) is the chance it comes on the next TR. Needs `hi − lo` ≥ one TR |
| `exponential` | truncated exponential over `[lo, hi]` — short gaps more common |
| `uniform` | uniform over `[lo, hi]` — the default when `jitter` is not set |

`round_jitter_to_tr` snaps `uniform` and `exponential` draws to the TR grid;
`geometric` is already in whole TRs. The loader rejects an unknown `jitter`
rather than falling back to uniform.

## Conditions

`per_run` counts must sum to the run's trial count; the loader refuses to start
otherwise. Labels are balanced within every condition.

| condition | question shown | participant repeats |
|---|---|---|
| `primary` | yes | the correct answer |
| `passive_read` | yes | nothing (silent) |
| `cue_only` | no | the answer, displayed on the cue itself |
| `constant_word` | yes | the constant word "ready" |
| `opposite` | yes | the inverted answer |

## Before the scanner

- Set `scanner.trigger_key` and `scanner.wait_for_triggers` (dummy volumes) for
  your site, and confirm `scanner.tr`.
- Check `window.screen` and `window.size` against the projector.
- Replace the placeholder images in `questions/images/`.
- Expand the question bank — a 30-session study needs far more than 80 items.
