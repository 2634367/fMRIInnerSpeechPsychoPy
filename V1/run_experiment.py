#!/usr/bin/env python
"""Run one functional run of the inner-speech task.

    python run_experiment.py --participant sub01 --session 1
    python run_experiment.py --config glm     # config/experiment-glm.yaml
    python run_experiment.py --pilot          # windowed, short, no scanner

Everything the run produces is written to the JSON database under `data/`.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
sys.path.insert(0, str(ROOT))

from innerspeech import bank, config, db, session  # noqa: E402


def _config_names():
    return ", ".join(sorted(_short_name(p) for p in CONFIG_DIR.glob("*.yaml")))


def _short_name(path):
    """`config/experiment-glm.yaml` -> `glm`, `config/experiment.yaml` -> `experiment`."""
    stem = path.stem
    return stem[len("experiment-"):] if stem.startswith("experiment-") else stem


def resolve_config(value):
    """Accept a path, a file name, or a short name like `glm`."""
    for candidate in (Path(value), CONFIG_DIR / value,
                      CONFIG_DIR / f"{value}.yaml",
                      CONFIG_DIR / f"experiment-{value}.yaml"):
        if candidate.is_file():
            return candidate
    raise argparse.ArgumentTypeError(
        f"no config `{value}`; available: {_config_names()}")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="experiment", type=resolve_config,
                   help=f"config file, or a short name ({_config_names()}); "
                        "default: experiment")
    p.add_argument("--participant", default="sub01")
    p.add_argument("--session", type=int, default=1)
    p.add_argument("--run", type=int, default=None,
                   help="run number (default: next unused for this session)")
    p.add_argument("--seed", type=int, default=None,
                   help="RNG seed; recorded either way so any run can be rebuilt")
    p.add_argument("--blocks", type=int, default=None,
                   help="override run.n_blocks, for piloting")
    p.add_argument("--no-scanner", action="store_true",
                   help="start immediately instead of waiting for trigger pulses")
    p.add_argument("--windowed", action="store_true", help="do not go fullscreen")
    p.add_argument("--auto", action="store_true",
                   help="advance the pre-scan screens without a keypress")
    p.add_argument("--pilot", action="store_true",
                   help="shorthand for --blocks 2 --no-scanner --windowed")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = config.load(args.config)

    if args.pilot:
        args.no_scanner = args.windowed = True
        args.blocks = args.blocks or 2
    if args.blocks and args.blocks != cfg["run"]["n_blocks"]:
        cfg["run"]["n_blocks"] = args.blocks
        _rebalance(cfg)

    questions = bank.load(cfg.path("bank"))

    data_dir = cfg.path("data_dir")
    data_dir.mkdir(parents=True, exist_ok=True)
    probe = db.Database(data_dir, run_id="__probe__")
    run_no = args.run or probe.next_run_number(args.participant, args.session)
    probe.close()

    run_id = f"sub-{args.participant}_ses-{args.session:02d}_run-{run_no:02d}"
    database = db.Database(data_dir, run_id)
    meta = {"participant": args.participant, "session": args.session,
            "run": run_no, "pilot": bool(args.pilot)}

    print(f"[{run_id}] {args.config.name}, {len(questions)} questions in bank, "
          f"{cfg['run']['n_blocks'] * cfg['run']['trials_per_block']} trials")

    sess = session.Session(
        cfg, meta, database, seed=args.seed,
        wait_for_scanner=not args.no_scanner,
        fullscreen=False if args.windowed else None,
        auto=args.auto,
    )
    try:
        record, path = sess.run(questions)
    finally:
        database.close()

    status = "ABORTED" if record["aborted"] else "complete"
    print(f"[{run_id}] {status}: {len(record['trials'])} trials, "
          f"{record.get('duration')} s -> {path}")
    return 1 if record["aborted"] else 0


def _rebalance(cfg):
    """Scale condition counts to a shortened run. Always sums to the trial count."""
    n = cfg["run"]["n_blocks"] * cfg["run"]["trials_per_block"]
    conds = cfg["conditions"]
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


if __name__ == "__main__":
    raise SystemExit(main())
