#!/usr/bin/env python
"""Run one functional run of the inner-speech task.

    python run_experiment.py --participant sub01 --session 1
    python run_experiment.py --config glm     # config/experiment-glm.yaml
    python run_experiment.py --pilot          # windowed, short, no scanner
    python run_experiment.py --overview-only  # draw overview/*.png and exit

Or run a config straight from the design planner (`planner --help`):

    python run_experiment.py planner --design V2 --run "Aim 1 — Block localizer run"

Or demo any config in the browser (`web --help`); that writes nothing:

    python run_experiment.py web

Everything the run produces is written to the JSON database under `data/`.
Before each run, overview images of every config are drawn to `overview/`.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
OVERVIEW_DIR = ROOT / "overview"
sys.path.insert(0, str(ROOT))

from innerspeech import bank, config, console, db, planner  # noqa: E402

PLANNER_DOC = """Run a config straight from the MRI Experimental Design Planner.

    python run_experiment.py planner                         # the planner's designs
    python run_experiment.py planner --design V2             # V2's configs
    python run_experiment.py planner --design V2 --download  # mirror them all, then exit
    python run_experiment.py planner --design V2 \\
        --run "Aim 1 — Block localizer run" --participant sub01 --session 1

--run takes a run design's name (case, dashes and spacing do not matter), its
file stem, its id, or its 0-based position. Every fetch mirrors the whole
design to config/planner/<design>/; if the planner cannot be reached, the run
goes ahead from that copy and says so. The planner's host and API key come
from PLANNER_HOST and PLANNER_KEY in .env beside this script (see .env.example)
or the environment; make a key under People → API keys in the planner.
"""

WEB_DOC = """Demo any config in the browser, local or from the planner.

    python run_experiment.py web              # serve on http://127.0.0.1:8765 and open it
    python run_experiment.py web --port 9000 --no-open

The page lists config/*.yaml and every design mirrored in config/planner/, and
plays any of them in the browser with the task's own run builder. It never
starts PsychoPy and writes nothing to data/. A debug view follows the run in a
popup window and in the browser's JS console.
"""


def _config_names():
    return ", ".join(sorted(config.short_name(p) for p in CONFIG_DIR.glob("*.yaml")))


def resolve_config(value):
    """Accept a path, a file name, or a short name like `glm`."""
    for candidate in (Path(value), CONFIG_DIR / value,
                      CONFIG_DIR / f"{value}.yaml",
                      CONFIG_DIR / f"experiment-{value}.yaml"):
        if candidate.is_file():
            return candidate
    raise argparse.ArgumentTypeError(
        f"no config `{value}`; available: {_config_names()}")


def _task_flags(p, *run_number):
    """The flags that shape a run, wherever its config comes from."""
    p.add_argument("--participant", default="sub01")
    p.add_argument("--session", type=int, default=1)
    p.add_argument(*run_number, dest="run", type=int, default=None, metavar="N",
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
    p.add_argument("--quiet", action="store_true",
                   help="no terminal readout during the run")
    p.add_argument("--debug", action="store_true",
                   help="testing aids: space pauses the run and space resumes it. The "
                        "run clock stops while paused, so onsets stop matching the scanner")
    p.add_argument("--overview", action=argparse.BooleanOptionalAction, default=True,
                   help="draw overview images of every config to overview/ "
                        "before the run; on by default")
    p.add_argument("--overview-only", action="store_true",
                   help="draw the overview images and exit, without opening a window")


def parse_local(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="experiment", type=resolve_config,
                   help=f"config file, or a short name ({_config_names()}); "
                        "default: experiment")
    _task_flags(p, "--run", "--run-number")
    return p.parse_args(argv)


def parse_planner(argv):
    """Its own parser rather than an argparse subparser: a subparser's defaults
    would overwrite task flags given before the word `planner`."""
    p = argparse.ArgumentParser(prog=f"{Path(sys.argv[0]).name} planner",
                                description=PLANNER_DOC,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default=os.environ.get(planner.HOST_ENV),
                   help=f"the planner; a bare host means https (default: {planner.HOST_ENV} "
                        "from .env or the environment)")
    p.add_argument("--design", help="design name as in the planner, e.g. V2 "
                                    "(without it: list the designs)")
    what = p.add_mutually_exclusive_group()
    what.add_argument("--run", dest="run_design", metavar="RUN_DESIGN",
                      help="the config to run: run design name, file stem, id or position")
    what.add_argument("--download", action="store_true",
                      help="mirror every config of --design to config/planner/<design>/, "
                           "then exit")
    p.add_argument("--offline", action="store_true",
                   help="do not contact the planner; use the last copy in "
                        "config/planner/<design>/")
    _task_flags(p, "--run-number")
    args = p.parse_args(argv)
    if (args.run_design is not None or args.download) and not args.design:
        p.error("--run and --download need --design")
    if args.download and args.offline:
        p.error("--download needs the planner; drop --offline")
    return args


def parse_web(argv):
    p = argparse.ArgumentParser(prog=f"{Path(sys.argv[0]).name} web",
                                description=WEB_DOC,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8765, help="default: 8765")
    p.add_argument("--no-open", dest="open", action="store_false",
                   help="do not open the page in the default browser")
    return p.parse_args(argv)


def web_main(args):
    from innerspeech import web
    return web.serve(ROOT, port=args.port, open_browser=args.open)


def write_overview(configs, selected, out_dir, root=None):
    """Draw out_dir/*.png for every config; return the paths written."""
    from innerspeech import overview  # only this step needs matplotlib
    return overview.write_all(configs, out_dir, selected=config.short_name(selected), root=root)


def _overview_note(configs, selected, out_dir, root):
    """Draw the overview for the console; never stops a scan."""
    try:
        paths = write_overview(configs, selected, out_dir, root)
    except Exception as exc:  # noqa: BLE001 - the run goes ahead regardless
        return f"skipped - {type(exc).__name__}: {exc}"
    return f"{len(paths)} images in {out_dir.relative_to(ROOT)}/"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["planner"]:
        planner.load_env(ROOT / ".env")
        return planner_main(parse_planner(argv[1:]))
    if argv[:1] == ["web"]:
        planner.load_env(ROOT / ".env")
        return web_main(parse_web(argv[1:]))
    args = parse_local(argv)
    configs = {config.short_name(p): p for p in CONFIG_DIR.glob("*.yaml")}
    return run_task(args, args.config, configs, OVERVIEW_DIR)


def run_task(args, config_path, configs, overview_dir, root=None, source=None):
    """Run `config_path`. `configs` are what the overview draws beside it; `source`
    says where a planner config came from, and goes into the run record."""
    if args.overview_only:
        for path in write_overview(configs, config_path, overview_dir, root):
            print(path.relative_to(ROOT))
        return 0

    cfg = config.load(config_path, root)

    if args.pilot:
        args.no_scanner = args.windowed = True
        args.blocks = args.blocks or 2
    if args.blocks and args.blocks != cfg["run"]["n_blocks"]:
        cfg["run"]["n_blocks"] = args.blocks
        config.rebalance(cfg)

    questions = bank.load(cfg.path("bank"))

    data_dir = cfg.path("data_dir")
    data_dir.mkdir(parents=True, exist_ok=True)
    probe = db.Database(data_dir, run_id="__probe__")
    run_no = args.run or probe.next_run_number(args.participant, args.session)
    probe.close()

    run_id = f"sub-{args.participant}_ses-{args.session:02d}_run-{run_no:02d}"
    database = db.Database(data_dir, run_id)
    meta = {"participant": args.participant, "session": args.session,
            "run": run_no, "pilot": bool(args.pilot), "debug": bool(args.debug)}
    if source:
        meta["planner"] = source

    con = console.Console(cfg, enabled=not args.quiet)
    con.header(run_id, config_path, len(questions))
    if source:
        say = con.note if source["live"] else con.warn
        say("planner", _source_note(source))
    if args.debug:
        keys = "/".join(cfg["keys"].get("pause", ["space"]))
        con.warn("debug", f"{keys} pauses and resumes - onsets will not match the scanner")
    if args.overview:
        con.note("overview", _overview_note(configs, config_path, overview_dir, root))

    from innerspeech import session  # only a run needs PsychoPy
    sess = session.Session(
        cfg, meta, database, seed=args.seed,
        wait_for_scanner=not args.no_scanner,
        fullscreen=False if args.windowed else None,
        auto=args.auto, con=con, debug=args.debug,
    )
    try:
        record, path = sess.run(questions)
    finally:
        database.close()

    con.summary(record, path)
    return 1 if record["aborted"] else 0


# --------------------------------------------------------------- planner ---
def planner_main(args):
    try:
        base = None if args.offline else planner.base_url(args.host)
        client = planner.Planner(base, os.environ.get(planner.KEY_ENV))
        if not args.design:
            return _list_designs(client, args.offline)
        mirror = planner.Mirror(ROOT, args.design)
        index, live, reason = planner.sync(client, mirror, args.design,
                                           offline=args.offline,
                                           fallback=not args.download)
        configs = index.get("configs", [])
        if args.run_design is None:
            _print_index(index, live, reason, mirror, args.download)
            return 0
        chosen = planner.find(configs, args.run_design, args.design)
    except planner.PlannerError as exc:
        print(f"planner: {exc}", file=sys.stderr)
        return 2

    source = {"design": index.get("name", args.design),
              "rev": index.get("rev"), "id": chosen.get("id"), "run": chosen.get("run"),
              "file": chosen.get("file"), "fetched": index.get("fetched"),
              "live": live, "reason": reason}
    paths = {config.short_name(mirror.path(c)): mirror.path(c) for c in configs}
    return run_task(args, mirror.path(chosen), paths,
                    OVERVIEW_DIR / "planner" / args.design, root=ROOT, source=source)


def _list_designs(client, offline):
    if offline:
        names = planner.mirrored(ROOT)
        print("\n".join(f"  {name}" for name in names)
              or "  (no designs mirrored in config/planner/)")
        return 0
    for design in client.designs():
        title = f"  {design.get('title', '')}" if design.get("title") else ""
        print(f"  {design['name']:<12} rev {design.get('rev', '?')}{title}")
    return 0


def _print_index(index, live, reason, mirror, downloaded):
    configs = index.get("configs", [])
    where = mirror.where
    if live:
        print(f"{index.get('name')} · rev {index.get('rev')} · {len(configs)} configs, live")
    else:
        print(f"{index.get('name')} · rev {index.get('rev')} · {reason} - "
              f"copy fetched {planner.fetched_label(index)}")
    if downloaded:
        for item in configs:
            print(f"  {where}/{item['file']}")
        return
    print(planner.table(configs) or "  (no run designs)")
    if live:
        print(f"mirrored to {where}/")


def _source_note(source):
    head = f"{source['design']} · rev {source['rev']}"
    if source["live"]:
        return f"{head} · live"
    return (f"{head} · NOT LIVE, {source['reason']} - "
            f"copy fetched {planner.fetched_label(source)}")


if __name__ == "__main__":
    raise SystemExit(main())
