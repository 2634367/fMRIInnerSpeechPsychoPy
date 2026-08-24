"""YAML configuration loading."""
from pathlib import Path
import yaml


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


def load(path):
    path = Path(path).resolve()
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    cfg = Config(data, path.parent.parent)
    _validate(cfg)
    return cfg


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
