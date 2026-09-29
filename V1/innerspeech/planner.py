"""Configs straight from the MRI Experimental Design Planner.

The planner compiles one config per run design and serves each at its own
address, in the design's own order:

    GET /designs/<design>/psychopy                 JSON index: run, file, stem, id
    GET /designs/<design>/psychopy/<id>.yaml       one config

Both are exports, so both need an API key (People → API keys in the planner),
sent as `Authorization: Bearer`. The key and the planner's host come from
`PLANNER_KEY` and `PLANNER_HOST`, in the environment or in `.env` beside
`run_experiment.py`. `.env` is never committed, and nothing written to disk
names the host.

Every fetch mirrors the whole design to `config/planner/<design>/`, so a run can
still go ahead from the last copy when the planner cannot be reached. Nothing
here writes to the database; the caller records where its config came from.
"""
import http.client
import json
import os
import re
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HOST_ENV, KEY_ENV = "PLANNER_HOST", "PLANNER_KEY"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DASHES = "‐‑‒–—―−"                      # all read as "-" when names are compared
TIMEOUT = 10                            # seconds, per request


class PlannerError(Exception):
    """The planner answered, and the answer was no - or it was never asked."""


class Unreachable(PlannerError):
    """No usable answer: the network, a timeout, or the server itself failing."""


class NotFound(PlannerError):
    pass


def load_env(path):
    """Set variables from a `.env` file, without overriding the environment.

    `NAME=value` per line; blank lines, `#` comments (whole-line, or after
    whitespace on an unquoted value), an `export ` prefix and quotes around
    the value are allowed.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = re.split(r"(?:^|\s)#", value, maxsplit=1)[0].strip()
        os.environ.setdefault(name.strip(), value)


def base_url(host):
    """`host`, `host:port` or a full URL -> `https://host[:port]`, no trailing slash.

    Plain http is refused anywhere but this machine: the key would travel in clear.
    """
    text = (host or "").strip().rstrip("/")
    if not text:
        raise PlannerError(f"no planner host: set {HOST_ENV} in .env (see .env.example) "
                           "or pass --host")
    if "://" not in text:
        text = "https://" + text
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PlannerError(f"not a planner address: {host!r}")
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise PlannerError(f"refusing plain http to {parts.hostname}: the API key "
                           "would travel in clear (use https)")
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _tls():
    """PsychoPy.app's Python is a python.org build with no system CA store, so
    prefer the certifi bundle it ships with."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _q(segment):
    return urllib.parse.quote(str(segment), safe="")


class Planner:
    """The planner at `base`, speaking with `key` (may be None for open reads)."""

    def __init__(self, base, key=None, timeout=TIMEOUT):
        self.base, self.key, self.timeout = base, key, timeout
        self._context = None

    def _get(self, path, need_key=True):
        if need_key and not self.key:
            raise PlannerError(
                f"the planner needs an API key: make one under People → API keys and "
                f"set {KEY_ENV} in .env (or pass --offline to use the last download)")
        request = urllib.request.Request(self.base + path)
        if self.key:
            # unredirected: a redirect must never carry the key somewhere else
            request.add_unredirected_header("Authorization", f"Bearer {self.key}")
        if self._context is None:
            self._context = _tls()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout,
                                        context=self._context) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise PlannerError(f"the planner refused ${KEY_ENV} ({exc.code}): make a "
                                   "new key under People → API keys") from None
            if exc.code == 404:
                raise NotFound(path) from None
            if exc.code >= 500:
                raise Unreachable(f"{exc.code} {exc.reason}") from None
            raise PlannerError(f"{exc.code} {exc.reason} for {path}") from None
        except urllib.error.URLError as exc:
            raise Unreachable(str(exc.reason)) from None
        except (OSError, http.client.HTTPException) as exc:
            raise Unreachable(str(exc) or type(exc).__name__) from None

    def _json(self, path, need_key=True):
        body = self._get(path, need_key)
        try:
            return json.loads(body)
        except ValueError:
            raise PlannerError(f"{self.base}{path} did not answer with JSON - "
                               "is that the planner?") from None

    def designs(self):
        """Every design on the planner. Open: needs no key."""
        return self._json("/api/v1/designs", need_key=False).get("designs", [])

    def index(self, design):
        """The design's configs, in its own order."""
        try:
            index = self._json(f"/designs/{_q(design)}/psychopy")
        except NotFound:
            raise PlannerError(f"the planner has no design named {design!r}") from None
        for position, item in enumerate(index.get("configs", [])):
            item.setdefault("index", position)
            item.setdefault("stem", _stem(item.get("file", "")))
        return index

    def config(self, design, item):
        """One config's YAML text.

        Fetched by run design id, the permanent address, from our own base: the
        index's `url` can come back as http:// from behind a proxy, and
        following it would send the key in clear.
        """
        slug = item.get("id") or item["stem"]
        try:
            return self._get(f"/designs/{_q(design)}/psychopy/{_q(slug)}.yaml").decode("utf-8")
        except NotFound:
            raise PlannerError(f"{design} no longer has {item.get('run') or slug!r} - "
                               "it changed while being fetched; try again") from None


# ------------------------------------------------------------ addressing ---
def normalise(text):
    """Case, width, dash and whitespace differences do not tell names apart."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    for dash in DASHES:
        text = text.replace(dash, "-")
    return " ".join(text.casefold().split())


def slug(text):
    """The planner's own file-name slug for a run design's name."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def _stem(file_name):
    return file_name[:-5] if file_name.lower().endswith(".yaml") else file_name


def table(configs):
    """One line per config: position, run design, file, id."""
    width = max((len(c.get("run", "")) for c in configs), default=0)
    return "\n".join(f"  {c['index']:>2}  {c.get('run', ''):<{width}}  "
                     f"{c.get('file', '')}  {c.get('id', '')}" for c in configs)


def find(configs, wanted, design=""):
    """One config by run design name, file stem, run design id, or 0-based position.

    Exact matches only, after `normalise` - at a scanner, a near miss must stop
    rather than run the wrong thing.
    """
    text = normalise(wanted)
    tests = (
        lambda c: normalise(c.get("run")) == text,
        lambda c: text in (c["stem"].lower(), c.get("file", "").lower()),
        lambda c: str(c.get("id", "")).lower() == text,
    )
    for test in tests:
        hits = [c for c in configs if test(c)]
        if len(hits) > 1:
            raise PlannerError(f"{wanted!r} matches {len(hits)} run designs in {design}; "
                               f"use a position or id:\n{table(hits)}")
        if hits:
            return hits[0]
    if text.isdigit() and int(text) < len(configs):
        return configs[int(text)]
    hits = [c for c in configs if c["stem"].lower() == "run-" + slug(text)]
    if len(hits) == 1:
        return hits[0]
    listing = table(configs) if configs else "  (none - the design has no run designs)"
    raise PlannerError(f"no run design {wanted!r} in {design}; it has:\n{listing}")


# ---------------------------------------------------------------- mirror ---
class Mirror:
    """The last copy of one design's configs, at `config/planner/<design>/`."""

    def __init__(self, root, design):
        if not design or design in (".", "..") or re.search(r"[/\\\x00]", design):
            raise PlannerError(f"not a design name: {design!r}")
        self.where = f"config/planner/{design}"
        self.dir = Path(root) / self.where
        self.index_path = self.dir / "index.json"

    def path(self, item):
        name = str(item.get("file", ""))
        if Path(name).name != name or name.startswith(".") or not name.endswith(".yaml"):
            raise PlannerError(f"refusing a config file name from the planner: {name!r}")
        return self.dir / name

    def load(self):
        """The index as last saved, or None."""
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, index, texts):
        """Write every config, then the index; drop configs the index no longer names.

        The index is kept without its `url`s: they name the host, and the
        mirror is committed like any other config.
        """
        paths = [self.path(item) for item in index["configs"]]
        self.dir.mkdir(parents=True, exist_ok=True)
        for path, text in zip(paths, texts):
            _replace(path, text)
        kept = dict(index, configs=[{k: v for k, v in item.items() if k != "url"}
                                    for item in index["configs"]])
        _replace(self.index_path, json.dumps(kept, indent=2, ensure_ascii=False) + "\n")
        for stale in set(self.dir.glob("*.yaml")) - set(paths):
            stale.unlink()
        return paths


def _replace(path, text):
    """Write whole or not at all: a half-written config must never be run."""
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def mirrored(root):
    """Names of the designs with a local copy."""
    parent = Path(root) / "config" / "planner"
    return sorted(p.parent.name for p in parent.glob("*/index.json"))


def sync(client, mirror, design, offline=False, fallback=True):
    """Mirror `design` and return `(index, live, reason)`.

    `live` is False when the last copy stands in, because `offline` asked not
    to try or the planner could not be reached; `reason` then says which. A
    refusal (no key, no such design) is an answer, not an outage, so it raises
    instead of falling back.
    """
    if offline:
        reason = "--offline"
    else:
        try:
            index = client.index(design)
            texts = [client.config(design, item) for item in index.get("configs", [])]
        except Unreachable as exc:
            if not fallback:
                raise PlannerError(f"cannot reach {client.base}: {exc}") from None
            reason = f"planner unreachable ({exc})"
        else:
            index["fetched"] = datetime.now().astimezone().isoformat(timespec="seconds")
            mirror.save(index, texts)
            return index, True, None
    cached = mirror.load()
    if cached is None:
        raise PlannerError(f"{reason}, and there is no copy of {design} in "
                           f"{mirror.where}/ - run `planner --design {design} --download` "
                           "while the planner is reachable")
    return cached, False, reason


def fetched_label(index):
    """`2026-09-28 14:02` from an index's `fetched` stamp."""
    try:
        return datetime.fromisoformat(index["fetched"]).strftime("%Y-%m-%d %H:%M")
    except (KeyError, TypeError, ValueError):
        return "at an unknown time"
