"""Overview images of every experiment config.

Drawn before each run, so the operator can see what every design in `config/`
looks like on screen and over time:

    overview/<name>.png    one config: trial anatomy, jitter, an example run
    overview/overview.png  every config side by side

The example runs come from the task's own run builder, and the jitter from its
own sampler, so the pictures cannot drift from what the task does. The seed is
fixed, which means the images change only when a config, the bank or the code
changes. They show *a* run, not the one about to start. Nothing here writes to
the database.
"""
import random
import textwrap
from collections import Counter
from math import ceil, radians
from pathlib import Path

from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib.image import imread
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle, RegularPolygon
from matplotlib.ticker import MultipleLocator, PercentFormatter

from . import bank, config
from .console import _clock

SEED = 1                  # example runs and jitter draws; any fixed value will do
DRAWS = 20000             # jitter samples per phase
DPI = 110

# WSU brand colours; the whole theme is built from these
WSU_GREEN, WSU_DARK_GREEN, WSU_GOLD = "#046A38", "#00482B", "#CBA052"
WSU_BEIGE, WSU_FADED_GOLD, WSU_YELLOW = "#DCD59A", "#E7E3C6", "#F8E08E"
WSU_BLACK, WSU_OFF_WHITE = "#101820", "#F2F1F0"

# surface, ink and hairlines; the greys are WSU black at 75% / 55% over off-white
SURFACE, INK, INK2, MUTED = WSU_OFF_WHITE, WSU_BLACK, "#484E54", "#767A7E"
TITLE, GRID, AXIS, HIGHLIGHT = WSU_DARK_GREEN, WSU_FADED_GOLD, WSU_BEIGE, WSU_YELLOW
# one colour per phase `show` kind, the same in every image. Green and gold carry
# the two events; fixation (WSU black at 52%) and blank stay recessive. Every
# pair clears the colour-blind and normal-vision separation checks. A screen
# from the config's `screens:` is text like the fixation cross, and shares its
# colour.
SHOW_COLOUR = {"fixation": "#7D8185", "question": WSU_GREEN,
               "blank": WSU_FADED_GOLD, "cue": WSU_GOLD}
SHOW_LABEL = {"fixation": "fixation cross", "question": "question",
              "blank": "blank screen", "cue": "answer cue"}
RESPONSE = {"answer": "repeats the answer", "opposite": "repeats the opposite",
            "none": "stays silent"}
VIEW_ORDER = ("text", "shapes", "image")
FALLBACK_FONT = "DejaVu Sans"            # has the cue glyphs ● ○ ◆ ▲ ✖
RC = {"font.family": ["Arial", FALLBACK_FONT], "font.size": 10,
      "text.color": INK, "axes.edgecolor": AXIS, "axes.labelcolor": MUTED,
      "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
      "axes.linewidth": 0.8, "xtick.color": AXIS, "ytick.color": AXIS,
      "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
      "xtick.labelsize": 9, "ytick.labelsize": 9.5, "ytick.major.size": 0}

W, M = 16.0, 0.6          # sheet width and side margin, inches
INNER = W - 2 * M


def write_all(configs, out_dir, selected=None, root=None):
    """Draw every config plus the comparison; return the paths written.

    `configs` maps short names to YAML paths; `root` is passed on to
    `config.load`. PNGs in `out_dir` that no longer belong to a config are
    removed.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    designs = [Design(name, path, root) for name, path in sorted(configs.items())]
    written = []
    with rc_context(RC):
        for d in designs:
            written.append(_save(_config_sheet(d), out_dir / f"{d.name}.png"))
        written.append(_save(_global_sheet(designs, selected), out_dir / "overview.png"))
    for stale in set(out_dir.glob("*.png")) - set(written):
        stale.unlink()
    return written


def _kind(show):
    """The colour key of a `show` value: a custom screen counts as fixation."""
    return show if show in SHOW_COLOUR else "fixation"


def _response(c):
    if c["response"] in ("constant", "ready"):
        return f'repeats "{c["word"]}"'
    return RESPONSE[c["response"]]


def _save(fig, path):
    fig.savefig(path, dpi=DPI, facecolor=SURFACE)
    return path


# ------------------------------------------------------------ one design ---
class Design:
    """One config, loaded, with an example run and its duration statistics."""

    def __init__(self, name, path, root=None):
        self.name, self.path, self.error = name, Path(path), None
        try:
            self.cfg = cfg = config.load(path, root)
            self.where = _relative(self.path, cfg.root)
            questions = bank.load(cfg.path("bank"), cfg["responses"]["labels"])
            rng = random.Random(SEED)
            self.trials, _ = bank.build_run(questions, cfg, rng)
            self.leads = bank.lead_durations(cfg, rng)
        except Exception as exc:        # one bad config must not stop the others
            self.error = f"{type(exc).__name__}: {exc}"
            return

        run, self.tr = cfg["run"], cfg["scanner"]["tr"]
        self.n_trials = run["n_blocks"] * run["trials_per_block"]
        rng = random.Random(SEED)
        self.phases = [self._stats(p, rng) for p in cfg["trial"]["phases"]]
        lead_stats = [self._stats(run[k], rng) for k in config.LEADS]
        self.jittered = [p for p in self.phases + lead_stats if p["hi"] > p["lo"]]

        self.trial_len = [sum(p[k] for p in self.phases) for k in ("lo", "mean", "hi")]
        self.run_len = [sum(p[k] for p in lead_stats) + self.n_trials * t
                        for k, t in zip(("lo", "mean", "hi"), self.trial_len)]
        self.segments = self._timeline()
        self.example_len = self.segments[-1]["t0"] + self.segments[-1]["dur"]
        self.ignored = config.ignored(cfg)

    def _stats(self, phase, rng):
        """A phase with its bounds and a sample of the task's own draws."""
        lo, hi = bank.bounds(phase, self.tr)
        draws = ([bank.sample_duration(phase, rng, self.tr,
                                       self.cfg["trial"]["round_jitter_to_tr"])
                  for _ in range(DRAWS)] if hi > lo else [lo])
        return {**phase, "lo": lo, "hi": hi, "draws": draws,
                "mean": sum(draws) / len(draws)}

    def _timeline(self):
        """Every on-screen segment of the example run, lead-in to lead-out."""
        run = self.cfg["run"]
        segs = [{"t0": 0.0, "dur": self.leads["lead_in"], "show": run["lead_in"]["show"],
                 "kind": "lead", "name": run["lead_in"]["name"], "trial": None}]
        t = self.leads["lead_in"]
        for trial in self.trials:
            for phase in self.cfg["trial"]["phases"]:
                show = phase["show"]
                if show == "question" and not trial["show_question"]:
                    show = "blank"          # what session.py paints on cue-only trials
                dur = trial["durations"][phase["name"]]
                segs.append({"t0": t, "dur": dur, "show": show,
                             "kind": phase["show"], "trial": trial})
                t += dur
        segs.append({"t0": t, "dur": self.leads["lead_out"], "show": run["lead_out"]["show"],
                     "kind": "lead", "name": run["lead_out"]["name"], "trial": None})
        return segs

    def example(self, **match):
        """The first example-run trial matching every `key=value` given."""
        for trial in self.trials:
            if all(trial[k] == v for k, v in match.items()):
                return trial
        return self.trials[0]


def _relative(path, root):
    """`config/glm.yaml`, `config/planner/V2/run-….yaml`: where the operator finds it."""
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return path.name


def _jitter_text(p):
    if p["hi"] == p["lo"]:
        return f"{p['lo']:g} s fixed"
    kind = p.get("jitter", "uniform")
    extra = f" p={p['p']:g}" if kind == "geometric" else ""
    return f"{p['lo']:g}–{p['hi']:g} s · {kind}{extra}"


# ----------------------------------------------------------------- layout ---
class _Sheet:
    """A figure laid out top-down in inches, so screen text can be sized in
    PsychoPy units and nothing depends on a layout engine."""

    def __init__(self, height):
        self.h = height
        self.fig = Figure(figsize=(W, height), dpi=DPI)

    def axes(self, left, top, width, height):
        return self.fig.add_axes((left / W, 1 - (top + height) / self.h,
                                  width / W, height / self.h))

    def text(self, left, top, s, **kw):
        kw.setdefault("va", "top")
        return self.fig.text(left / W, 1 - top / self.h, s, **kw)

    def legend(self, left, top, handles, **kw):
        self.fig.legend(handles=handles, loc="upper left", frameon=False,
                        bbox_to_anchor=(left / W, 1 - top / self.h),
                        ncol=len(handles), fontsize=9.5, handlelength=1.3,
                        borderaxespad=0, columnspacing=1.6, **kw)


def _px(ax, span, px=2):
    """`px` screen pixels in data units, for an axis `span` long."""
    return span * px / (ax.get_position().width * W * DPI)


def _step(span, ticks=12):
    """A round tick step that puts at most `ticks` ticks across `span`."""
    for step in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if span / step <= ticks:
            return step
    return 1200


def _plain(ax, keep=("bottom",)):
    for side in ("left", "right", "top", "bottom"):
        ax.spines[side].set_visible(side in keep)


def _section(sheet, top, title, note):
    sheet.text(M, top, title, fontsize=13, fontweight="bold", color=TITLE)
    sheet.text(M, top + 0.27, note, fontsize=9.5, color=MUTED)


def _phase_legend(sheet, left, top, shows):
    """One swatch per colour; the fixation swatch also names any custom screens."""
    custom = sorted(s for s in shows if s not in SHOW_COLOUR)
    labels = {**SHOW_LABEL, "fixation": ", ".join(
        ([SHOW_LABEL["fixation"]] if "fixation" in shows else []) + custom)}
    kinds = {_kind(s) for s in shows}
    sheet.legend(left, top, [Patch(color=SHOW_COLOUR[k], label=labels[k])
                             for k in SHOW_COLOUR if k in kinds])


def _tiles(sheet, top, tiles):
    """A row of stat tiles, each (label, value, detail)."""
    width = INNER / len(tiles)
    for i, (label, value, detail) in enumerate(tiles):
        x = M + i * width
        sheet.text(x, top, label, fontsize=9.5, color=MUTED)
        sheet.text(x, top + 0.2, value, fontsize=19, fontweight="bold")
        sheet.text(x, top + 0.6, detail, fontsize=9.5, color=INK2)


# ------------------------------------------------------- screen mock-ups ---
def _rgb(colour):
    """PsychoPy rgb (-1..1) to matplotlib (0..1); colour names pass through."""
    if isinstance(colour, (list, tuple)):
        return tuple(min(1.0, max(0.0, (v + 1) / 2)) for v in colour)
    return colour


def _picture(ax, image, pos, size):
    """One picture from `imread`, centred at `pos`, `size` = (width, height) in units.

    imshow crops the axes to the picture, so the screen's own limits go back on.
    """
    (x, y), (w, h) = pos, size
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    ax.imshow(image, extent=(x - w / 2, x + w / 2, y - h / 2, y + h / 2), aspect="auto")
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)


def _screen(ax, cfg, show, trial=None):
    """Draw what PsychoPy puts on screen for one phase, in `height` units."""
    w, h = cfg["window"]["size"]
    half = w / h / 2
    ax.set_xlim(-half, half)
    ax.set_ylim(-0.5, 0.5)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(_rgb(cfg["window"]["color"]))
    for spine in ax.spines.values():
        spine.set_color(AXIS)
    pt = ax.get_position().height * ax.figure.get_figheight() * 72   # points per unit
    font = [cfg["text"]["font"], FALLBACK_FONT]

    def say(text, pos, height, colour, wrap=None, family=None):
        if wrap:
            text = textwrap.fill(text, max(8, int(wrap / (0.5 * height))))
        ax.text(*pos, text, ha="center", va="center", fontsize=height * pt,
                color=_rgb(colour), linespacing=1.15,
                fontfamily=[family, FALLBACK_FONT] if family else font)

    t, views = cfg["text"], cfg["views"]
    if show in cfg["screens"]:
        s = cfg["screens"][show]
        if s.get("image"):                 # `height` tall, width from the picture
            image = imread(cfg.file(s["image"]))
            width = s["height"] * image.shape[1] / image.shape[0]
            _picture(ax, image, s["pos"], (width, s["height"]))
        else:
            say(s["text"], s["pos"], s["height"], s["color"], family=s["font"])
    elif show == "cue" and trial:
        say(trial["cue"], cfg["cue"]["pos"], cfg["cue"]["height"], cfg["cue"]["color"])
    elif show == "question" and trial and trial["show_question"]:
        if trial["view"] == "text":
            say(trial["text"], views["text"]["pos"], t["height"], t["color"],
                t["wrap_width"])
            return
        say(trial["text"], t["title_pos"], t["height"], t["color"], t["wrap_width"])
        params = trial["params"]
        if trial["view"] == "shapes":
            shapes = views["shapes"]
            for spec in params.get("shapes", [])[:shapes["max_shapes"]]:
                colour = _rgb(spec.get("color", shapes["color"]))
                ori = spec.get("ori", shapes["default_ori"].get(spec["kind"], 0.0))
                # both start with a vertex straight up; PsychoPy turns clockwise
                ax.add_patch(RegularPolygon(
                    spec["pos"], shapes["edges"][spec["kind"]],
                    radius=spec.get("size", shapes["size"]),
                    orientation=-radians(ori), color=colour))
        elif trial["view"] == "image":
            image = imread(cfg.path("images_dir") / params["image"])
            size = params.get("size") or (image.shape[1] / h, image.shape[0] / h)
            _picture(ax, image, views["image"]["pos"], size)


def _thumb(sheet, cfg, left, top, height, show, trial, caption):
    w, h = cfg["window"]["size"]
    width = height * w / h
    _screen(sheet.axes(left, top, width, height), cfg, show, trial)
    for i, (text, style) in enumerate(caption):
        sheet.text(left, top + height + 0.08 + i * 0.2, text,
                   fontsize=9.5 if i else 10, **style)
    return width


# ------------------------------------------------------ per-config sheet ---
def _config_sheet(d):
    if d.error:
        sheet = _Sheet(1.9)
        sheet.text(M, 0.35, d.name, fontsize=22, fontweight="bold", color=TITLE)
        sheet.text(M, 0.85, f"{d.path.name} could not be loaded:", fontsize=11, color=INK2)
        sheet.text(M, 1.15, d.error, fontsize=11)
        return sheet.fig

    n_blocks, n_cond = d.cfg["run"]["n_blocks"], len(d.cfg["conditions"])
    sections = [2.1,                                            # header + tiles
                4.6,                                            # trial anatomy
                2.75 if d.jittered else 1.0,                    # jitter
                1.55 + (n_blocks + 2) * 0.27,                   # example run
                0.95 + max(n_cond * 0.36, 1.95),                # conditions
                0.3 + 0.22 * (2 if d.ignored else 1)]           # footnote
    sheet = _Sheet(sum(sections))
    top = 0.3
    for draw, height in zip((_header, _anatomy, _jitter, _raster, _conditions,
                             _footnote), sections):
        draw(sheet, d, top)
        top += height
    return sheet.fig


def _header(sheet, d, top):
    run, tr = d.cfg["run"], d.tr
    sheet.text(M, top, d.name, fontsize=22, fontweight="bold", color=TITLE)
    sheet.text(M, top + 0.45, f"{d.where}  ·  {d.cfg['experiment']}  ·  "
               + "  ›  ".join(p["name"] for p in d.phases), fontsize=10.5, color=INK2)
    lo, mean, hi = d.run_len
    _tiles(sheet, top + 0.9, [
        ("TR", f"{tr:g} s", f"after {d.cfg['scanner']['wait_for_triggers']} dummy volumes"),
        ("Trials per run", f"{d.n_trials}",
         f"{run['n_blocks']} blocks × {run['trials_per_block']}"),
        ("Trial length, mean", f"{d.trial_len[1]:.1f} s",
         f"{d.trial_len[0]:.1f} – {d.trial_len[2]:.1f} s"),
        ("Run length, mean", _clock(mean), f"{_clock(lo)} – {_clock(hi)}"),
        ("Volumes, mean", f"≈ {ceil(mean / tr):,}",
         f"{ceil(lo / tr):,} – {ceil(hi / tr):,}"),
    ])


def _anatomy(sheet, d, top):
    _section(sheet, top, "Trial anatomy",
             "one trial with every phase at its mean length; whiskers span the "
             "jitter range; below, what the participant sees in each phase")
    ax = sheet.axes(M, top + 0.65, INNER, 0.7)
    xmax = d.trial_len[2]
    gap = _px(ax, xmax)
    start = 0.0
    for i, p in enumerate(d.phases):
        ax.broken_barh([(start, max(p["mean"] - gap, p["mean"] / 2))], (0.3, 0.45),
                       facecolors=SHOW_COLOUR[_kind(p["show"])])
        ax.text(start + p["mean"] / 2, 0.85, str(i + 1), ha="center", va="bottom",
                fontsize=9.5, color=INK2)
        if p["hi"] > p["lo"]:
            a, b = start + p["lo"], start + p["hi"]
            ax.plot([a, b], [0.12, 0.12], color=INK2, lw=1)
            ax.plot([a, a, None, b, b], [0.04, 0.2, None, 0.04, 0.2], color=INK2, lw=1)
        start += p["mean"]
    ax.set_xlim(0, xmax)
    ax.set_ylim(0, 1.15)
    ax.set_yticks([])
    ax.xaxis.set_major_locator(MultipleLocator(_step(xmax, 16)))
    ax.xaxis.set_minor_locator(MultipleLocator(d.tr))
    ax.tick_params(axis="x", which="minor", length=2)
    ax.set_xlabel(f"seconds from trial start  ·  minor ticks every TR ({d.tr:g} s)",
                  fontsize=9)
    _plain(ax)

    n = len(d.phases)
    aspect = d.cfg["window"]["size"][0] / d.cfg["window"]["size"][1]
    height = min(1.6, (INNER - (n - 1) * 0.35) / n / aspect)
    gap = min(0.9, (INNER - n * height * aspect) / max(1, n - 1))
    left = M + (INNER - n * height * aspect - (n - 1) * gap) / 2
    first = next(iter(d.cfg["conditions"]))
    rep = d.example(condition=first, show_question=True)
    for i, p in enumerate(d.phases):
        caption = [(f"{i + 1} · {p['name']}", {"fontweight": "bold"}),
                   (_jitter_text(p), {"color": INK2})]
        if p["show"] == "question":
            caption.append((f"e.g. a {rep['view']} question", {"color": MUTED}))
        elif p["show"] == "cue":
            caption.append((f"e.g. the {first} cue", {"color": MUTED}))
        left += _thumb(sheet, d.cfg, left, top + 2.05, height, p["show"], rep,
                       caption) + gap


def _jitter(sheet, d, top):
    if not d.jittered:
        _section(sheet, top, "Jitter", "every phase has a fixed length")
        return
    _section(sheet, top, "Jitter",
             f"how often each length comes up, from {DRAWS:,} draws of the "
             "task's own sampler")
    k = len(d.jittered)
    width = min(3.6, (INNER - (k - 1) * 0.7) / k)
    for i, p in enumerate(d.jittered):
        x = M + i * (width + 0.7)
        sheet.text(x, top + 0.7, p["name"], fontsize=10, fontweight="bold")
        sheet.text(x, top + 0.9, _jitter_text(p), fontsize=9.5, color=INK2)
        ax = sheet.axes(x, top + 1.2, width, 1.05)
        pad = max(0.25, (p["hi"] - p["lo"]) * 0.06)
        span = p["hi"] - p["lo"] + 2 * pad
        colour = INK2
        counts = Counter(round(v, 3) for v in p["draws"])
        if len(counts) <= 40:
            xs = sorted(counts)
            step = min((b - a for a, b in zip(xs, xs[1:])), default=1.0)
            ax.bar(xs, [counts[v] / DRAWS for v in xs], color=colour,
                   width=min(step * 0.6, _px(ax, span, 22)))
        else:
            ax.hist(p["draws"], bins=30, range=(p["lo"], p["hi"]), color=colour,
                    weights=[1 / DRAWS] * DRAWS, rwidth=0.85)
        ax.axvline(p["mean"], color=INK, lw=1)
        ax.text(p["mean"], 1.0, f" mean {p['mean']:.2f} s", fontsize=9,
                transform=ax.get_xaxis_transform(), va="top", color=INK)
        ax.set_xlim(p["lo"] - pad, p["hi"] + pad)
        ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        ax.yaxis.set_major_locator(MultipleLocator(_step_pct(ax)))
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        ax.set_xlabel("seconds", fontsize=9)
        _plain(ax)


def _step_pct(ax):
    top = ax.get_ylim()[1]
    return next(s for s in (0.05, 0.1, 0.2, 0.25, 0.5) if top / s <= 4)


def _raster(sheet, d, top):
    run = d.cfg["run"]
    _section(sheet, top, "Example run",
             f"one run from the task's run builder (seed {SEED}), one row per block, "
             f"{_clock(d.example_len)} long; the symbol on each trial is its condition")
    _phase_legend(sheet, M, top + 0.62, {s["show"] for s in d.segments})
    glyphs = "    ".join(f"{c['cue']} {name}" for name, c in d.cfg["conditions"].items())
    sheet.text(M + 7.2, top + 0.655, glyphs, fontsize=9.5, color=INK2)

    rows = [(d.segments[0]["name"], [d.segments[0]])]
    blocks = {}
    for seg in d.segments[1:-1]:
        blocks.setdefault(seg["trial"]["block"], []).append(seg)
    rows += [(f"block {b + 1}", segs) for b, segs in sorted(blocks.items())]
    rows.append((d.segments[-1]["name"], [d.segments[-1]]))

    label_w = 1.35
    ax = sheet.axes(M + label_w, top + 1.0, INNER - label_w, len(rows) * 0.27)
    xmax = max(segs[-1]["t0"] + segs[-1]["dur"] - segs[0]["t0"] for _, segs in rows)
    gap = _px(ax, xmax)
    pt_per_s = (INNER - label_w) * 72 / xmax
    labels = []
    for y, (name, segs) in enumerate(rows):
        t0 = segs[0]["t0"]
        labels.append(f"{name}  {_clock(t0)}")
        for show in SHOW_COLOUR:
            spans = [(s["t0"] - t0, max(s["dur"] - gap, s["dur"] / 2))
                     for s in segs if _kind(s["show"]) == show]
            if spans:
                ax.broken_barh(spans, (y - 0.32, 0.64), facecolors=SHOW_COLOUR[show])
        for s in segs:
            if s["kind"] != "question":
                continue
            size = min(8.5, 0.8 * s["dur"] * pt_per_s)
            if size >= 4:
                glyph = d.cfg["conditions"][s["trial"]["condition"]]["cue"]
                ax.text(s["t0"] - t0 + s["dur"] / 2, y, glyph,
                        ha="center", va="center", fontsize=size,
                        color=SURFACE if s["show"] == "question" else INK)
        if segs[0]["trial"] is None:
            ax.text(segs[0]["dur"] + xmax * 0.01, y,
                    f"{segs[0]['dur']:g} s of {segs[0]['show']}", va="center",
                    fontsize=9, color=MUTED)
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_yticks(range(len(rows)), labels)
    ax.set_xlim(0, xmax)
    ax.xaxis.set_major_locator(MultipleLocator(_step(xmax, 14)))
    ax.set_xlabel("seconds from the start of the row  ·  the clock after each "
                  "label is where the row starts in the run", fontsize=9)
    _plain(ax)


def _conditions(sheet, d, top):
    conds = d.cfg["conditions"]
    _section(sheet, top, "Conditions",
             "trials per run by condition, and the question views the example run draws")
    names = list(conds)
    left, width = M + 1.75, 2.6
    ax = sheet.axes(left, top + 0.7, width, len(names) * 0.36)
    biggest = max(c["per_run"] for c in conds.values()) or 1
    for y, name in enumerate(names):
        c = conds[name]
        ax.barh(y, c["per_run"], height=0.5, color=INK2)
        cue = (" · cue shows the token" if c["cue_from_response"] else "")
        detail = (f"question {'shown' if c['show_question'] else 'hidden'}"
                  f" · {_response(c)}{cue}")
        ax.text(c["per_run"] + biggest * 0.03, y,
                f"{c['per_run']}  ({c['per_run'] / d.n_trials:.0%})    {detail}",
                va="center", fontsize=9.5, color=INK2)
    ax.set_yticks(range(len(names)), [f"{conds[n]['cue']}  {n}" for n in names])
    ax.set_ylim(len(names) - 0.5, -0.5)
    ax.set_xlim(0, biggest)
    ax.set_xticks([])
    _plain(ax, keep=("left",))

    views = Counter(t["view"] for t in d.trials)
    aspect = d.cfg["window"]["size"][0] / d.cfg["window"]["size"][1]
    x = W - M - len(views) * (1.2 * aspect + 0.35) + 0.35
    for view in sorted(views, key=lambda v: (VIEW_ORDER + (v,)).index(v)):
        rep = d.example(view=view, show_question=True)
        x += _thumb(sheet, d.cfg, x, top + 0.7, 1.2, "question", rep, [
            (f"{view} view", {"fontweight": "bold"}),
            (f"{views[view]} of {d.n_trials} trials", {"color": INK2})]) + 0.35


def _footnote(sheet, d, top):
    lines = [f"Example run and jitter use a fixed seed ({SEED}); a real run draws "
             "its own seed, so its order and jitter differ."]
    if d.ignored:
        lines.append("Not used by the task, so left out of every length above: "
                     + ", ".join(d.ignored) + ".")
    for i, line in enumerate(lines):
        sheet.text(M, top + i * 0.22, line, fontsize=9, color=MUTED)


# ---------------------------------------------------------- global sheet ---
def _global_sheet(designs, selected):
    ok = [d for d in designs if not d.error]
    n, n_ok = len(designs), len(ok)
    sections = [1.35, 1.0 + (n + 1) * 0.34, 1.35 + n_ok * 0.46,
                1.35 + n_ok * 0.42, 1.5 + n_ok * 0.42, 0.6]
    sheet = _Sheet(sum(sections))
    top = 0.3
    sheet.text(M, top, "Inner-speech experiments", fontsize=22, fontweight="bold",
               color=TITLE)
    sheet.text(M, top + 0.45, f"{n} configs in config/  ·  ▶ marks the one "
               "selected with --config  ·  one image per config sits beside this one",
               fontsize=10.5, color=INK2)
    _phase_legend(sheet, M, top + 0.8,
                  set(SHOW_COLOUR) | {s["show"] for d in designs if not d.error
                                      for s in d.segments})
    top += sections[0]

    _table(sheet, designs, selected, top)
    top += sections[1]
    if ok:
        _compare_trials(sheet, ok, selected, top)
        _compare_runs(sheet, ok, selected, top + sections[2])
        _compare_strips(sheet, ok, selected, top + sections[2] + sections[3])
    ignored = sorted({k for d in ok for k in d.ignored})
    note = (f"Example runs use the task's run builder with a fixed seed ({SEED}); "
            "real runs draw their own.")
    if ignored:
        note += " Not used by the task, so left out of every length: " + ", ".join(ignored) + "."
    sheet.text(M, sum(sections) - 0.45, note, fontsize=9, color=MUTED)
    return sheet.fig


def _label(d, selected):
    return f"▶ {d.name}" if d.name == selected else d.name


def _bold_selected(ax, designs, selected):
    for label, d in zip(ax.get_yticklabels(), designs):
        if d.name == selected:
            label.set_fontweight("bold")
            label.set_color(INK)


def _table(sheet, designs, selected, top):
    _section(sheet, top, "At a glance",
             "trial and run lengths are min – max, from the jitter bounds; "
             "the last columns are trials per run by condition")
    conds = {}
    for d in designs:
        if not d.error:
            for name, c in d.cfg["conditions"].items():
                conds.setdefault(name, c["cue"])
    cols = [("config", 0), ("experiment", 1.6), ("TR", 4.1), ("trials", 4.8),
            ("trial length", 6.3), ("run length", 8.0)]
    cond_x = 10.0
    cond_w = (INNER - cond_x) / max(1, len(conds))
    y = top + 0.7
    for text, x in cols:
        sheet.text(M + x, y + 0.14, text, fontsize=9.5, color=MUTED)
    for i, (name, cue) in enumerate(conds.items()):
        x = M + cond_x + (i + 0.5) * cond_w
        sheet.text(x, y - 0.04, cue, fontsize=10, color=INK2, ha="center")
        sheet.text(x, y + 0.14, name, fontsize=8.5, color=MUTED, ha="center")
    y += 0.4
    for d in designs:
        chosen = d.name == selected
        if chosen:
            sheet.fig.add_artist(Rectangle(
                ((M - 0.1) / W, 1 - (y + 0.26) / sheet.h), (INNER + 0.2) / W,
                0.34 / sheet.h, transform=sheet.fig.transFigure, color=HIGHLIGHT,
                zorder=0))
        style = {"fontsize": 10, "fontweight": "bold" if chosen else "normal"}
        sheet.fig.add_artist(Line2D([M / W, (W - M) / W], [1 - (y - 0.05) / sheet.h] * 2,
                                    color=GRID, lw=0.8))
        sheet.text(M, y, _label(d, selected), **style)
        if d.error:
            sheet.text(M + cols[1][1], y, f"could not be loaded - {d.error}",
                       fontsize=10, color=INK2)
            y += 0.34
            continue
        run = d.cfg["run"]
        cells = [d.cfg["experiment"], f"{d.tr:g} s",
                 f"{d.n_trials}  ({run['n_blocks']} × {run['trials_per_block']})",
                 f"{d.trial_len[0]:.1f} – {d.trial_len[2]:.1f} s",
                 f"{_clock(d.run_len[0])} – {_clock(d.run_len[2])}"]
        for text, (_, x) in zip(cells, cols[1:]):
            sheet.text(M + x, y, text, **style)
        for i, name in enumerate(conds):
            c = d.cfg["conditions"].get(name)
            sheet.text(M + cond_x + (i + 0.5) * cond_w, y,
                       "–" if c is None else str(c["per_run"]), ha="center", **style)
        y += 0.34


def _rows_axes(sheet, designs, selected, top, row_h, right=0.0):
    label_w = 1.6
    ax = sheet.axes(M + label_w, top, INNER - label_w - right, len(designs) * row_h)
    ax.set_yticks(range(len(designs)), [_label(d, selected) for d in designs])
    ax.set_ylim(len(designs) - 0.5, -0.5)
    _bold_selected(ax, designs, selected)
    _plain(ax)
    return ax


def _compare_trials(sheet, designs, selected, top):
    _section(sheet, top, "One trial, per config",
             "phases at their mean length on a shared axis; the whisker spans the "
             "shortest to the longest possible trial")
    ax = _rows_axes(sheet, designs, selected, top + 0.7, 0.46, right=2.1)
    xmax = max(d.trial_len[2] for d in designs)
    gap = _px(ax, xmax)
    for y, d in enumerate(designs):
        start = 0.0
        for p in d.phases:
            ax.broken_barh([(start, max(p["mean"] - gap, p["mean"] / 2))],
                           (y - 0.32, 0.4), facecolors=SHOW_COLOUR[_kind(p["show"])])
            start += p["mean"]
        lo, mean, hi = d.trial_len
        ax.plot([lo, hi], [y + 0.24] * 2, color=INK2, lw=1)
        ax.plot([lo, lo, None, hi, hi], [y + 0.16, y + 0.32, None, y + 0.16, y + 0.32],
                color=INK2, lw=1)
        ax.text(xmax * 1.02, y - 0.12, f"mean {mean:.1f} s  ({lo:.1f} – {hi:.1f})",
                va="center", fontsize=9.5, color=INK2)
    ax.set_xlim(0, xmax)
    ax.xaxis.set_major_locator(MultipleLocator(_step(xmax, 16)))
    ax.set_xlabel("seconds from trial start", fontsize=9)


def _minutes_axis(ax, xmax):
    ax.set_xlim(0, xmax)
    ax.xaxis.set_major_locator(MultipleLocator(1 if xmax <= 20 else 2 if xmax <= 40 else 5))
    ax.set_xlabel("minutes from the scan start (the last dummy pulse)", fontsize=9)


def _compare_runs(sheet, designs, selected, top):
    _section(sheet, top, "Run length, per config",
             "shortest to longest possible run, the mean, and the example run")
    ax = _rows_axes(sheet, designs, selected, top + 0.7, 0.42, right=2.1)
    xmax = max(d.run_len[2] for d in designs) / 60 * 1.02
    for y, d in enumerate(designs):
        lo, mean, hi = (v / 60 for v in d.run_len)
        ax.plot([lo, hi], [y, y], color=AXIS, lw=6, solid_capstyle="butt")
        ax.plot([d.example_len / 60], [y], "D", ms=7, color=SHOW_COLOUR["question"],
                mec=SURFACE, mew=2)
        ax.plot([mean], [y], "o", ms=8, color=INK, mec=SURFACE, mew=2)
        ax.text(xmax * 1.02, y, f"{_clock(d.run_len[0])} – {_clock(d.run_len[2])}"
                f"  ·  mean {_clock(d.run_len[1])}", va="center", fontsize=9.5,
                color=INK2)
    _minutes_axis(ax, xmax)
    sheet.legend(M + 8.0, top + 0.02, [
        Line2D([], [], color=AXIS, lw=6, label="possible range"),
        Line2D([], [], ls="", marker="o", ms=8, color=INK, label="mean"),
        Line2D([], [], ls="", marker="D", ms=7, color=SHOW_COLOUR["question"],
               label="example run")])


def _compare_strips(sheet, designs, selected, top):
    _section(sheet, top, "Example run, per config",
             "each config's example run end to end on the same clock: where the "
             "questions fall, and how much of the run is fixation or blank")
    ax = _rows_axes(sheet, designs, selected, top + 0.7, 0.42, right=2.1)
    xmax = max(d.run_len[2] for d in designs) / 60 * 1.02
    for y, d in enumerate(designs):
        for show in SHOW_COLOUR:
            spans = [(s["t0"] / 60, s["dur"] / 60) for s in d.segments
                     if _kind(s["show"]) == show]
            if spans:
                ax.broken_barh(spans, (y - 0.3, 0.6), facecolors=SHOW_COLOUR[show])
        shown = sum(s["dur"] for s in d.segments if s["show"] in ("question", "cue"))
        ax.text(xmax * 1.02, y, f"{shown / d.example_len:.0%} question or cue",
                va="center", fontsize=9.5, color=INK2)
    _minutes_axis(ax, xmax)
