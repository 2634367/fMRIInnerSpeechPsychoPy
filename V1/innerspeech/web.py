"""A browser demo of every config, local or from the planner.

    ./run.sh web                  # http://127.0.0.1:8765, opened in the browser

Serves `web/` and a small JSON API over the task's own code:

    GET  /api/catalog             config/*.yaml and every design in config/planner/
    GET  /api/planner/designs     the planner's designs (needs PLANNER_HOST, no key)
    POST /api/planner/refresh     {design} -> mirror it, as `planner --download` does
    POST /api/plan                {source, design?, config, seed?, blocks?} -> a run
    GET  /files/<path>            images under questions/ and overview/

A run is built by `bank.build_run` from its seed, exactly as `session.Session`
builds one, and played by the page. Nothing here starts PsychoPy or writes to
`data/`; the only writes are the planner mirror and its overview images, and only
when the page asks for a refresh.

Bound to 127.0.0.1. A request must name this server in `Host` (no DNS rebinding),
a POST must be JSON (no cross-site form posts), and the planner key never leaves
this process.
"""
import json
import os
import random
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from . import bank, config, planner

STATIC_TYPES = {".html": "text/html; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}
FILE_DIRS = ("questions", "overview")         # the only places /files/ reads from
MAX_BODY = 64 * 1024
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")


class BadRequest(Exception):
    """Something the page asked for that cannot be done; the message says why."""


# --------------------------------------------------------------- catalog ---
def local_configs(root):
    """Short name -> path; `experiment`, the task's default, first."""
    found = {config.short_name(p): p for p in (Path(root) / "config").glob("*.yaml")}
    return {k: found[k] for k in sorted(found, key=lambda k: (k != "experiment", k))}


def file_url(path, root):
    """`/files/…` for a file the server will serve, else None."""
    path = Path(path)
    if not path.is_file() or _servable(path, root) is None:
        return None
    rel = path.resolve().relative_to(Path(root).resolve()).as_posix()
    return f"/files/{quote(rel)}?v={int(path.stat().st_mtime)}"


def _servable(path, root):
    """The resolved path when it is an image inside FILE_DIRS, else None."""
    path = Path(path).resolve()
    if path.suffix.lower() not in IMAGE_TYPES:
        return None
    for name in FILE_DIRS:
        if path.is_relative_to((Path(root) / name).resolve()):
            return path
    return None


def summary(path, root, cfg_root=None, overview_png=None):
    """What a card shows about one config; `error` instead when it does not load."""
    item = {"name": config.short_name(path), "file": _relative(path, root),
            "overview": file_url(overview_png, root) if overview_png else None,
            "error": None}
    try:
        cfg = config.load(path, cfg_root)
        run, scanner = cfg["run"], cfg["scanner"]
        tr = scanner["tr"]
        phases = []
        for p in cfg["trial"]["phases"]:
            lo, hi = bank.bounds(p, tr)
            phases.append({"name": p["name"], "show": p["show"], "lo": lo, "hi": hi,
                           "jitter": p.get("jitter") if hi > lo else None,
                           "p": p.get("p") if hi > lo else None})
        n = run["n_blocks"] * run["trials_per_block"]
        lead = run["lead_in"] + run["lead_out"]
        item.update(
            experiment=cfg.get("experiment"), tr=tr,
            trigger_key=scanner["trigger_key"], dummies=scanner["wait_for_triggers"],
            n_blocks=run["n_blocks"], per_block=run["trials_per_block"], n_trials=n,
            lead_in=run["lead_in"], lead_out=run["lead_out"], phases=phases,
            run_len=[round(lead + n * sum(p[k] for p in phases), 2) for k in ("lo", "hi")],
            conditions={k: c["per_run"] for k, c in cfg["conditions"].items()},
            ignored=sorted(f"run.{k}" for k in set(run) - config.RUN_KEYS))
    except Exception as exc:  # noqa: BLE001 - one bad config must not hide the others
        item["error"] = f"{type(exc).__name__}: {exc}"
    return item


def _relative(path, root):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).name


def design_summary(root, name, index, live=False):
    """One mirrored planner design, its configs in the design's own order."""
    mirror = planner.Mirror(root, name)
    shots = Path(root) / "overview" / "planner" / name
    configs = []
    for item in index.get("configs", []):
        head = {k: item.get(k) for k in ("index", "id", "run", "stem")}
        try:
            path = mirror.path(item)
        except planner.PlannerError as exc:
            configs.append({**head, "name": item.get("stem"), "file": item.get("file"),
                            "error": str(exc)})
            continue
        png = shots / f"{config.short_name(path)}.png"
        configs.append({**head, **summary(path, root, root, png)})
    return {"name": index.get("name", name), "key": name, "rev": index.get("rev"),
            "fetched": index.get("fetched"), "fetched_label": planner.fetched_label(index),
            "live": live, "overview": file_url(shots / "overview.png", root),
            "configs": configs}


def catalog(root):
    local = [summary(path, root, None, Path(root) / "overview" / f"{name}.png")
             for name, path in local_configs(root).items()]
    designs = []
    for name in planner.mirrored(root):
        index = planner.Mirror(root, name).load() or {}
        designs.append(design_summary(root, name, index))
    return {"local": local, "overview": file_url(Path(root) / "overview" / "overview.png", root),
            "planner": {"host": bool(os.environ.get(planner.HOST_ENV)), "designs": designs}}


# --------------------------------------------------------------- planner ---
def _client():
    base = planner.base_url(os.environ.get(planner.HOST_ENV))
    return planner.Planner(base, os.environ.get(planner.KEY_ENV))


def remote_designs():
    if not os.environ.get(planner.HOST_ENV):
        return {"host": False, "designs": []}
    try:
        designs = _client().designs()
    except planner.PlannerError as exc:
        return {"host": True, "designs": [], "error": str(exc)}
    return {"host": True, "designs": [{k: d.get(k) for k in ("name", "rev", "title")}
                                      for d in designs]}


def refresh(root, design):
    """Mirror `design` from the planner, then redraw its overview images."""
    try:
        mirror = planner.Mirror(root, design)
        index, _, _ = planner.sync(_client(), mirror, design, fallback=False)
    except planner.PlannerError as exc:
        raise BadRequest(str(exc)) from None
    note = None
    try:
        from . import overview  # only this step needs matplotlib
        paths = {config.short_name(mirror.path(c)): mirror.path(c)
                 for c in index.get("configs", [])}
        overview.write_all(paths, Path(root) / "overview" / "planner" / design, root=root)
    except Exception as exc:  # noqa: BLE001 - the mirror is what matters
        note = f"overview skipped - {type(exc).__name__}: {exc}"
    return {**design_summary(root, design, index, live=True), "note": note}


# ------------------------------------------------------------------- run ---
def resolve(root, body):
    """(config path, root for config.load, source) for a plan request."""
    source, name = body.get("source"), str(body.get("config") or "")
    if source == "local":
        path = local_configs(root).get(name)
        if path is None:
            raise BadRequest(f"no local config {name!r}")
        return path, None, {"source": "local", "config": name}
    if source == "planner":
        design = str(body.get("design") or "")
        try:
            mirror = planner.Mirror(root, design)
            index = mirror.load()
            if index is None:
                raise BadRequest(f"no copy of {design!r} in config/planner/")
            item = planner.find(index.get("configs", []), name, design)
            path = mirror.path(item)
        except planner.PlannerError as exc:
            raise BadRequest(str(exc)) from None
        return path, root, {"source": "planner", "design": index.get("name", design),
                            "key": design, "rev": index.get("rev"),
                            "fetched": index.get("fetched"), "id": item.get("id"),
                            "run": item.get("run"), "config": item.get("stem")}
    raise BadRequest(f"unknown source {source!r}")


def plan(root, body):
    """One run, built by the task's own builder from its seed."""
    path, cfg_root, source = resolve(root, body)
    cfg = config.load(path, cfg_root)
    blocks = body.get("blocks")
    if blocks not in (None, ""):
        blocks = _integer(blocks, "blocks", 1)
        if blocks != cfg["run"]["n_blocks"]:
            cfg["run"]["n_blocks"] = blocks
            config.rebalance(cfg)
    seed = body.get("seed")
    seed = (random.SystemRandom().randrange(2 ** 31) if seed in (None, "")
            else _integer(seed, "seed", 0))

    questions = bank.load(cfg.path("bank"))
    # no already_seen: a demo is a fresh participant, so the same seed rebuilds
    # this run in PsychoPy for anyone without earlier runs
    trials, reused = bank.build_run(questions, cfg, random.Random(seed))
    images = cfg.path("images_dir")
    for trial in trials:
        if trial["view"] == "image":
            trial["image_url"] = file_url(images / trial["params"].get("image", ""), root)
    run = cfg["run"]
    total = run["lead_in"] + run["lead_out"] + sum(sum(t["durations"].values())
                                                   for t in trials)
    return {"seed": seed, "source": {**source, "file": _relative(path, root)},
            "cfg": dict(cfg), "trials": trials, "reused": reused,
            "n_questions": len(questions), "total": round(total, 4)}


def _integer(value, name, least):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise BadRequest(f"{name} must be a whole number, got {value!r}") from None
    if number < least:
        raise BadRequest(f"{name} must be at least {least}")
    return number


# ---------------------------------------------------------------- server ---
class Handler(BaseHTTPRequestHandler):
    server_version = "innerspeech-web"

    @property
    def root(self):
        return self.server.root

    # ---------------------------------------------------------- routing ---
    def do_GET(self):
        if not self._host_ok():
            return
        path = urlsplit(self.path).path
        if path == "/api/catalog":
            return self._api(lambda: catalog(self.root))
        if path == "/api/planner/designs":
            return self._api(remote_designs)
        if path.startswith("/files/"):
            return self._file(path[len("/files/"):])
        return self._static(path)

    def do_POST(self):
        if not self._host_ok():
            return
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        origin = self.headers.get("Origin")
        if ctype != "application/json" or (origin and origin not in self.server.origins):
            return self._send_json({"error": "JSON from this page only"}, HTTPStatus.FORBIDDEN)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send_json({"error": "request too large"},
                                   HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send_json({"error": "not JSON"}, HTTPStatus.BAD_REQUEST)
        path = urlsplit(self.path).path
        if path == "/api/plan":
            return self._api(lambda: plan(self.root, body))
        if path == "/api/planner/refresh":
            return self._api(lambda: refresh(self.root, str(body.get("design") or "")))
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------ guard ---
    def _host_ok(self):
        if self.headers.get("Host", "") in self.server.hosts:
            return True
        self._send_json({"error": "unexpected Host"}, HTTPStatus.FORBIDDEN)
        return False

    # ---------------------------------------------------------- answers ---
    def _api(self, fn):
        try:
            return self._send_json(fn())
        except BadRequest as exc:
            return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - a bad config reaches the page, not a reset socket
            return self._send_json({"error": f"{type(exc).__name__}: {exc}"},
                                   HTTPStatus.UNPROCESSABLE_ENTITY)

    def _static(self, path):
        web = self.server.web.resolve()
        target = (web / unquote(path).lstrip("/")).resolve()
        if target == web:
            target = web / "index.html"
        if (not target.is_relative_to(web) or not target.is_file()
                or target.suffix not in STATIC_TYPES):
            return self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        self._send(target.read_bytes(), STATIC_TYPES[target.suffix])

    def _file(self, rel):
        target = _servable(self.root / unquote(rel), self.root)
        if target is None or not target.is_file():
            return self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        self._send(target.read_bytes(), IMAGE_TYPES[target.suffix.lower()])

    def _send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", status)

    def _send(self, body, ctype, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        """API calls and failures only; static files and images are noise."""
        path = urlsplit(self.path).path if hasattr(self, "path") else ""
        status = str(args[1]) if len(args) > 1 else ""
        if path.startswith("/api/") or not status.startswith(("2", "3")):
            sys.stderr.write(f"   web      {self.command} {path} {status}\n")


class Server(ThreadingHTTPServer):
    daemon_threads = True


def serve(root, port=8765, open_browser=True):
    root = Path(root)
    try:
        httpd = Server(("127.0.0.1", port), Handler)
    except OSError as exc:
        print(f"web: cannot listen on 127.0.0.1:{port} ({exc.strerror or exc}); "
              "try --port", file=sys.stderr)
        return 2
    port = httpd.server_address[1]
    httpd.root, httpd.web = root, root / "web"
    httpd.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    httpd.origins = {f"http://{host}" for host in httpd.hosts}
    url = f"http://127.0.0.1:{port}/"
    print(f"   web      {url}  -  browser demo, writes nothing to data/  -  ctrl-c stops")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.server_close()
    return 0
