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
./run.sh planner --design V2 --run "Aim 1 — Block localizer run" --participant sub01 --session 1
./run.sh web                # demo any config in the browser; writes nothing
```

`run.sh` uses `python3` if `psychopy` is importable there, otherwise the
interpreter bundled inside `/Applications/PsychoPy.app`. You can also open
`run_experiment.py` in the PsychoPy Coder and press Run.

| flag | effect |
|---|---|
| `--config NAME` | which config to run: `experiment` (default), `glm`, `mvpa`, `time-series`. A path or file name works too |
| `--participant` / `--session` / `--run` | run identity (`--run`, or `--run-number`, defaults to the next unused one) |
| `--blocks N` | shorten the run; condition counts rescale proportionally, and one at 0 stays at 0 |
| `--no-scanner` | start immediately instead of waiting for trigger pulses |
| `--windowed` | do not go fullscreen |
| `--auto` | advance the pre-scan screens with no keypress (display check) |
| `--pilot` | `--blocks N --no-scanner --windowed`, N from the config's `pilot.blocks` (2) |
| `--seed N` | fix the RNG; the seed is recorded either way, so any run can be rebuilt |
| `--quiet` | no terminal readout during the run |
| `--debug` | testing aids. For now: the pause key (space) pauses the run and resumes it (see below) |
| `--overview` / `--no-overview` | draw the overview images before the run (on by default) |
| `--overview-only` | draw the overview images and exit — no window, nothing written to `data/` |

`escape` aborts at any point and still writes everything collected so far.

### Pausing (`--debug`)

With `--debug`, space pauses the run once the scan has started, and space again
resumes it. The screen holds whatever was showing, with a small "paused" line,
and the console prints when the pause started and how long it lasted. `escape`
still aborts while paused.

The run clock stops while paused: `t0` moves forward by the length of the pause,
so the interrupted phase, and every phase after it, keeps its full scheduled
length. The run resumes where it left off rather than skipping ahead. The
scanner keeps acquiring, though, so **a paused run's onsets no longer line up
with its volumes**. `--debug` is for checking the task, not for data you will
analyse. A debug run's record has `"debug": true` and lists every pause as
`{"at": <run-clock s>, "duration": <s>}` (`duration` is `null` if the run was
aborted while paused), and `events.jsonl` gets matching `pause` and `resume`
events.

A different key can be set as `keys.pause: ["p"]` in the config, and the line's
text, size and place as `messages.paused`. The key defaults to space, which is
also the advance key on the instructions screen. That is safe: pausing only
works after `t0`, and a space pressed before then is discarded.

## Configuration

`config/defaults.yaml` lists every setting the task reads, with its default and
a comment. Every config — `config/*.yaml` and every config mirrored from the
planner — is merged over it, so a config only needs the keys it changes:

- mappings merge key by key, so `window: {screen: 1}` changes the screen and
  keeps every other `window:` setting;
- a list or a scalar replaces the default outright, and so does the whole
  `conditions:` block, so a config never inherits conditions it did not list;
- `~` in `defaults.yaml` marks a key every config must set (`experiment`,
  `scanner.tr`, `scanner.trigger_key`, `scanner.wait_for_triggers`,
  `run.n_blocks`, `run.trials_per_block`, `trial.phases`, `conditions`); the
  loader names any that are missing.

Change a default for every design at once in `defaults.yaml`; change it for one
design in that design's config. The planner's configs keep working unchanged,
since anything they leave out comes from `defaults.yaml`. `defaults.yaml` is not
a config itself: it is never listed, drawn or demoed.

The run record's `config` is the merged result with every default filled in
(each condition's fields, each screen's font and colour, each jittered phase's
`p` or `scale`), so it always says exactly what ran. With the defaults as
shipped, a seed builds exactly the run it built before `defaults.yaml` existed.

The values that are not in the config are the task's vocabulary: the `show`
kinds `question`, `cue` and `blank`, the jitter and response kinds, the views,
and the names of events and record fields.

Watch YAML's booleans: bare `yes`, `no`, `on` and `off` are read as true and
false, so quote words like these (`labels: ["yes", "no"]`, `word: "yes"`). The
loader says so if it gets one.

## Run from the planner

The MRI Experimental Design Planner compiles one config per run design, and
`planner` runs one of them directly, with no export and no copying files around:

```bash
cp .env.example .env                            # then fill in the host and your key
./run.sh planner                                # the planner's designs (no key needed)
./run.sh planner --design V2                    # V2's configs: position, run design, file, id
./run.sh planner --design V2 --download         # mirror them all, then exit
./run.sh planner --design V2 --run "Aim 1 — Block localizer run" --participant sub01 --session 1
./run.sh planner --design V2 --run 0 --pilot    # by position
./run.sh planner --design V2 --run 0 --offline  # skip the network, use the last copy
```

| flag | effect |
|---|---|
| `--host` | the planner; a bare host means https. Default: `PLANNER_HOST` from `.env` |
| `--design NAME` | the design, as named in the planner. Without it, list the designs |
| `--run RUN_DESIGN` | the config to run: the run design's name, file stem, id, or 0-based position |
| `--download` | mirror every config of the design, then exit |
| `--offline` | do not contact the planner; use the last copy |
| `--run-number N` | the run number (`--run` here names the run design) |

Every other flag above works the same way after `planner`.

`--run` matches the run design's name exactly, but ignores case, spacing and the
kind of dash, so `Aim 1 — Block localizer run` finds `Aim 1 - Block localizer
run`. After the name it tries the file stem (`run-aim-1-block-localizer-run`),
the run design id (`run-mtmfi9kd-4`, which never changes, so use it in a
protocol) and the position. A name that matches nothing, or matches more than one
run design, stops the run and lists what the design has.

**The host and the key** live in `.env` beside `run_experiment.py`, which is
gitignored. `.env.example` is the committed template:

```bash
PLANNER_HOST=planner.example.org   # the planner's address; a bare host means https
PLANNER_KEY=mrip_…                 # People → API keys in the planner
```

Variables already set in the environment take precedence over `.env`. The key has
no flag, so it never lands in shell history, and it is sent only over https
(plain http only to this machine). Nothing the task writes to disk names the host.
The mirror's `index.json` is saved without the planner's links, and the run
record leaves the host out.

**Every fetch mirrors the whole design** to `config/planner/<design>/`: each
config plus `index.json` (the planner's revision and when it was fetched). Configs
the planner no longer has are removed. Before a run, the overview images of that
design go to `overview/planner/<design>/`.

**If the planner cannot be reached**, the run goes ahead from the last copy,
and the console says so in yellow:

```
   planner  V2 · rev 193437d76b4a · NOT LIVE, planner unreachable (timed out) - copy fetched 2026-09-28 14:02
```

A refusal is different: a missing or revoked key, or no such design, stops the
run. At the scanner, `--offline` gets past it. Either way the run record says
where its config came from:

```json
"planner": {"design": "V2", "rev": "193437d76b4a",
            "id": "run-mtmfi9kd-4", "run": "Aim 1 - Block localizer run",
            "file": "run-aim-1-block-localizer-run.yaml",
            "fetched": "2026-09-28T14:02:11-04:00", "live": true, "reason": null}
```

## Browser demo

`web` serves a page that lists every config, local and from the planner, and plays
any of them in the browser. It is for looking at a design, not for data: it never
starts PsychoPy and writes nothing to `data/`.

```bash
./run.sh web                     # http://127.0.0.1:8765, opened in your browser
./run.sh web --port 9000 --no-open
```

Each card shows the TR, trial count, run length, one trial's phases, the condition
counts and the overview image. **▶ Demo** plays it with the options above the
list. They are remembered in this browser:

| option | effect |
|---|---|
| seed | blank draws one; the run is built by `bank.build_run` from it, as `session.py` does |
| blocks | shortens the run (`--blocks`); never lengthens it |
| scanner | `none` starts at once, `simulate` sends the dummy pulses every TR, `trigger key` waits for you to press it |
| speed | ×1 to ×30 on the run clock; onset drift is measured at ×1 only |
| auto, debug keys, fullscreen | as `--auto`, `--debug` (plus → skips a phase, +/− change speed) and fullscreen |

The stage follows `session.py`: instructions, dummy pulses, t0 at the last one,
then lead-in, trials and lead-out on one absolute schedule, in `height` units.
`escape` aborts. The end screen gives the `./run.sh` command that reruns the same
seed in PsychoPy. That rebuilds the same trials for a participant with no earlier
runs, because a real run prefers questions the participant has not seen.

**The planner.** Designs mirrored in `config/planner/` are listed with their rev
and when they were fetched. *Refresh from planner* mirrors a design again, as
`planner --download` does, and redraws its overview images; *Check the planner*
lists the designs you have not fetched yet. The host and key come from `.env`
as before and never reach the page.

**Debugging** has three views of the same event stream:

- **The debug window** (the *Debug window* button, `d` on the stage, or *Open the
  debug window on start*): the run's header and live block as in the operator
  console, pause, skip, speed, jump to a trial and abort, and a filterable log of
  every trial, phase, pulse and control with each onset's drift in ms. Keys
  pressed there go to the stage, so it can keep the focus.
- **The JS console** (open devtools): one collapsed group per trial, with a phase
  line and onset drift each, and the whole plan as a table when the run starts.
  `window.innerspeech` drives it: `demo('glm', {speed: 10})`, `pause()`,
  `resume()`, `skip()`, `jump(38, 'question')`, `speed(5)`, `abort()`, and
  `state`, `trials`, `events`, `cfg`. `innerspeech.help()` lists them.
- **The HUD** (`h`): run clock, trial, phase countdown, fps and drift, on the stage.

A tab in the background gets no frames from the browser, so its phases are
skipped; the log says so rather than hiding it.

The server listens on 127.0.0.1 only and answers only requests addressed to it.
It serves only `web/` and the images under `questions/` and `overview/`.

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
`inter_trial_gap`, `label_order`, `label_run_length`) are listed in a footnote
and left out of every length shown. A `run:` key counts as implemented when
`config/defaults.yaml` has it.

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
config/defaults.yaml     every setting with its default; every config is merged over it
config/experiment.yaml   the default design — timing, window, conditions, scanner
config/experiment-*.yaml one per analysis aim (glm, mvpa, time-series); pick with --config
config/planner/<design>/ configs mirrored from the design planner (`planner`)
questions/bank.json      the question bank
questions/images/        image stimuli
innerspeech/config.py    YAML loading + validation
innerspeech/bank.py      bank loading, label balancing, jitter, run construction
innerspeech/db.py        the JSON database (the only thing that writes to disk)
innerspeech/session.py   window, timing loop, trigger handling, run flow
innerspeech/console.py   the operator's terminal readout (prints, never records)
innerspeech/overview.py  the overview images of every config (draws, never records)
innerspeech/planner.py   fetching and mirroring configs from the design planner
innerspeech/web.py       the browser demo's server (`web`; never writes to data/)
innerspeech/views/       one class per question view
web/                     the browser demo: launcher, stage, debug window
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
  session, run, RNG seed, a snapshot of the merged config that produced it, all
  trigger times, the lead-in and lead-out (`{name, show, dur, onset, offset}`),
  and every trial with its scheduled durations and measured onsets.

`run_id` is `sub-<participant>_ses-NN_run-NN`, from `paths.run_id`
(`"sub-{participant}_ses-{session:02d}_run-{run:02d}"`). The `lead_in` and
`lead_out` events keep those kinds whatever the phases are called, and carry
the phase's `name` and `show` and its measured `onset` and `offset`.

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
They, and a shape's default size, colour and orientation, and how many a
question may draw, are `views.shapes` in the config. `views.text.pos` and
`views.image.pos` place the text-only question and the picture.

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

A scalar `dur` is fixed; a `[lo, hi]` pair is jittered. `show` is `question`,
`cue`, `blank`, `fixation`, or any screen under `screens:`, a line of text of
your own:

```yaml
screens:
  rest: {text: "·", height: 0.05, color: [0.5, 0.5, 0.5]}   # font and pos from text:
```

The lead-in and lead-out are phases too. A bare number sets only the duration,
as before; the full form sets what is on screen, what the console, the overview
and the demo call it, and jitter:

```yaml
run:
  lead_in:  12.0
  lead_out: {name: settle_out, show: rest, dur: [8.0, 16.0], jitter: geometric}
```

A lead can show `blank` or any screen, but not the question or the cue, since it
belongs to no trial. A jittered lead is drawn after the trials, so a fixed lead
leaves the rest of the run exactly as it was.

`trial.jitter` sets how every `[lo, hi]` phase (leads included) is sampled, and a
phase can override it with its own `jitter:` (and `p:` or `scale:`):

| jitter | draws |
|---|---|
| `geometric` | `lo` plus *n* whole TRs, P(*n*) ∝ `p`(1 − `p`)^*n*, capped at `hi` — the truncated geometric (textbook eq. 5.3). Memoryless, so the participant cannot predict the next event; `jitter_p` (default 0.5) is the chance it comes on the next TR. Needs `hi − lo` ≥ one TR |
| `exponential` | truncated exponential over `[lo, hi]` — short gaps more common. `trial.exponential_scale` (default 0.35) is its mean above `lo` as a share of `hi − lo` |
| `uniform` | uniform over `[lo, hi]` — the default when `jitter` is not set |

`round_jitter_to_tr` snaps `uniform` and `exponential` draws to the TR grid;
`geometric` is already in whole TRs. The loader rejects an unknown `jitter`
rather than falling back to uniform.

## Conditions

`per_run` counts must sum to the run's trial count; the loader refuses to start
otherwise. Within every condition, `run.label_balance_pct` of the trials (50 by
default) get the first answer label; when that is not a whole number of trials,
the one left over gets a random label.

| condition | question shown | participant repeats |
|---|---|---|
| `primary` | yes | the correct answer |
| `passive_read` | yes | nothing (silent) |
| `cue_only` | no | the answer, displayed on the cue itself |
| `constant_word` | yes | the constant word, `word` ("ready" by default) |
| `opposite` | yes | the inverted answer |

Each condition sets `per_run` and `cue`; the rest comes from
`condition_defaults`:

```yaml
condition_defaults:
  show_question: true
  response: answer          # answer | opposite | none | constant (`ready` reads as constant)
  word: ready               # what `constant` trials repeat
  cue_from_response: false  # the cue shows the token, cased by cue.token_case
```

The two answers are `responses.labels` (`["yes", "no"]`); every question in the
bank must have one of them, and `opposite` swaps them. `responses.silent_label`
is how a silent trial reads in the console and the demo.

## Before the scanner

- Set `scanner.trigger_key` and `scanner.wait_for_triggers` (dummy volumes) for
  your site, and confirm `scanner.tr`.
- Check `window.screen` and `window.size` against the projector.
- Replace the placeholder images in `questions/images/`.
- Expand the question bank — a 30-session study needs far more than 80 items.
