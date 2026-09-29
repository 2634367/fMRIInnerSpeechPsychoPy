"""YAML configuration loading."""
from pathlib import Path
import yaml

# The `run:` keys the task implements; the planner writes others, which are ignored.
RUN_KEYS = {"lead_in", "lead_out", "n_blocks", "trials_per_block"}


class Config(dict):
    """A dict with attribute access and a `root` (the project directory)."""

    def __init__(self, data, root):
        super().__init__(data)
        self.root = Path(root)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def path(self, key):
        """Resolve a `paths:` entry against the project root."""
        return self.root / self["paths"][key]


def short_name(path):
    """`config/experiment-glm.yaml` -> `glm`, `config/experiment.yaml` -> `experiment`."""
    stem = Path(path).stem
    return stem[len("experiment-"):] if stem.startswith("experiment-") else stem


def load(path, root=None):
    """`root` resolves `paths:`; by default the directory above the config's own
    (`config/x.yaml` -> the project). Configs mirrored from the planner sit
    deeper, so their caller passes it."""
    path = Path(path).resolve()
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    cfg = Config(data, root or path.parent.parent)
    _resolve_jitter(cfg)
    _validate(cfg)
    return cfg


def _resolve_jitter(cfg):
    """Give every jittered phase its own `jitter` (and `p`), from `trial` defaults.

    Resolved here so the config snapshot in each run record says exactly how
    every phase was sampled.
    """
    trial = cfg["trial"]
    for phase in trial["phases"]:
        if not isinstance(phase["dur"], (list, tuple)):
            continue
        phase.setdefault("jitter", trial.get("jitter", "uniform"))
        if phase["jitter"] == "geometric":
            phase.setdefault("p", trial.get("jitter_p", 0.5))


def _validate(cfg):
    n = cfg["run"]["n_blocks"] * cfg["run"]["trials_per_block"]
    total = sum(c["per_run"] for c in cfg["conditions"].values())
    if total != n:
        raise ValueError(
            f"conditions per_run sums to {total} but the run has {n} trials"
        )
    shows = {p["show"] for p in cfg["trial"]["phases"]}
    unknown = shows - {"fixation", "question", "cue", "blank"}
    if unknown:
        raise ValueError(f"unknown phase `show` values: {sorted(unknown)}")

    tr = cfg["scanner"]["tr"]
    for phase in cfg["trial"]["phases"]:
        kind = phase.get("jitter")
        if kind is None:
            continue
        name = phase["name"]
        if kind not in ("uniform", "exponential", "geometric"):
            raise ValueError(f"phase `{name}`: unknown jitter `{kind}` "
                             "(use uniform, exponential or geometric)")
        if kind != "geometric":
            continue
        if not 0 < phase["p"] < 1:
            raise ValueError(f"phase `{name}`: geometric p must be between 0 and 1, "
                             f"got {phase['p']}")
        lo, hi = phase["dur"]
        if hi - lo < tr - 1e-9:
            raise ValueError(f"phase `{name}`: geometric jitter steps in whole TRs, "
                             f"but [{lo}, {hi}] is shorter than one TR ({tr} s)")


def rebalance(cfg):
    """Scale condition counts to a shortened run. Always sums to the trial count."""
    n = cfg["run"]["n_blocks"] * cfg["run"]["trials_per_block"]
    # a condition at 0 (the planner lists every one) stays at 0
    conds = {k: c for k, c in cfg["conditions"].items() if c["per_run"]}
    if n < len(conds):
        raise ValueError(f"a {n}-trial run cannot hold {len(conds)} conditions")
    total = sum(c["per_run"] for c in conds.values())
    counts = {k: 1 for k in conds}          # keep every condition represented
    share = {k: c["per_run"] / total * (n - len(conds)) for k, c in conds.items()}
    for key, value in share.items():
        counts[key] += int(value)
    # hand the rounding leftovers to the largest fractional parts
    order = sorted(share, key=lambda k: share[k] - int(share[k]), reverse=True)
    for key in order[: n - sum(counts.values())]:
        counts[key] += 1
    for key, value in counts.items():
        conds[key]["per_run"] = value
