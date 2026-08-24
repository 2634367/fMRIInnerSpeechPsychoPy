"""The common JSON database.

Every piece of data the task produces is written here and nowhere else.

    data/events.jsonl        append-only stream of every event, all runs
    data/runs/<run_id>.json  one self-contained record per run

The JSONL stream is flushed on every write so a crashed or aborted run still
leaves a complete record on disk.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Database:
    def __init__(self, root, run_id):
        self.root = Path(root)
        self.runs_dir = self.root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self._stream = open(self.root / "events.jsonl", "a", encoding="utf-8")

    # -- append-only event stream ------------------------------------------
    def log(self, kind, **fields):
        """Append one event. `t` fields are run-clock seconds (t=0 == scan start)."""
        record = {"ts": now_iso(), "run_id": self.run_id, "kind": kind, **fields}
        self._stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._stream.flush()
        return record

    # -- per-run record ----------------------------------------------------
    def write_run(self, record):
        path = self.runs_dir / f"{self.run_id}.json"
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        return path

    def close(self):
        self._stream.close()

    # -- queries -----------------------------------------------------------
    def seen_question_ids(self, participant=None):
        """UUIDs already presented, so later runs can prefer unseen questions."""
        seen = set()
        for path in self.runs_dir.glob("*.json"):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if participant and rec.get("participant") != participant:
                continue
            for trial in rec.get("trials", []):
                if trial.get("question_uuid"):
                    seen.add(trial["question_uuid"])
        return seen

    def next_run_number(self, participant, session):
        """One past the highest run number recorded for this participant+session."""
        highest = 0
        for path in self.runs_dir.glob("*.json"):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if rec.get("participant") == participant and rec.get("session") == session:
                highest = max(highest, int(rec.get("run", 0)))
        return highest + 1
