"""Shared by the platform-path scripts: the upload cache, polling, state files.

Every id these scripts create is recorded in fit/out/, keyed by deployment, so a
rerun resumes rather than uploading, optimizing or evaluating twice.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import red_api  # noqa: E402
from red_api import agents_base, api_base, deployment, request, upload_file  # noqa: E402,F401

ROLES = REPO / "data" / "roles"
OUT = REPO / "fit" / "out"
CACHE = OUT / "uploads.json"
TERMINAL = {"completed", "failed", "canceled", "cancelled"}

# The `red` blueprint defaults to window 1024 and step 256: at 1024, incident #1
# yields no shots and 2 of 7 incidents can't reach a fault majority, so every
# request pins the window and step. Window 64, step 1 is the archived winner.
SEARCH = {"window_size": "64", "step_size": "1", "metric": "cosine,l1,l2,dot", "trials": 4}
# The archived grid ranked by fault F1: with one event class, foreground macro-F1.
PRIMARY = "event.foreground_macro_f1"


def load_dotenv() -> None:
    """The repo's .env, wherever the script is run from."""
    red_api.load_dotenv(str(REPO / ".env"))


def log(msg: str) -> None:
    print(f"{datetime.datetime.now():%H:%M:%S} {msg}", flush=True)


def manifest() -> dict:
    p = ROLES / "manifest.json"
    if not p.exists():
        sys.exit(f"{p} not found -- run prep/build_roles.py and prep/preflight_roles.py")
    return json.loads(p.read_text())


def base_values(m: dict) -> dict:
    return {"timestamp_column": "timestamp", "data_columns": m["channels"],
            "events": m["classes"], "background": m["background"]}


def upload_all(paths: list, jobs: int = 4) -> dict:
    """Platform file ids for `paths`, uploading only what the cache doesn't hold."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    def key(p: Path) -> str:
        # by content, so a rebuilt but identical file reuses its upload; file ids
        # from one deployment don't exist on another
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        return f"{api_base()}|{p.relative_to(REPO)}|{digest}"

    todo = [p for p in paths if key(p) not in cache]
    if todo:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log(f"uploading {len(todo)} of {len(paths)} files "
            f"({sum(p.stat().st_size for p in todo) / 1e6:,.1f} MB)")

        def one(p: Path):
            rel = str(p.relative_to(ROLES)).replace("/", "__")
            return key(p), upload_file(str(p), rename=f"red-pump-{rel.replace('.csv', '')}-{stamp}.csv")["file_id"]

        OUT.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(jobs) as pool:
            for k, fid in pool.map(one, todo):
                cache[k] = fid
                CACHE.write_text(json.dumps(cache, indent=1))  # an interrupted upload resumes
    return {p: cache[key(p)] for p in paths}


def example(name: str, file_id: str, truth: dict) -> dict:
    return {"name": name, "inputs": [{"type": "file", "id": file_id, "format": "csv"}],
            "ground_truth": {"event": truth}}


def constant(cls: str) -> dict:
    return {"from": {"constant": cls}}


# The platform scores each record once: a window answers only for the rows since
# the previous window ended, collapsed by `downsampling`. At step 1 that is one
# row, so majority_vote equals the default last_record; it matters at a coarser
# step. fit/test.py also scores whole-window majorities, as the design doc does.
COLUMN = {"from": {"column": "label"}, "downsampling": "majority_vote"}


def state_path(kind: str) -> Path:
    return OUT / f"{kind}_state.json"


def load_state(path: Path) -> dict:
    state = json.loads(path.read_text()) if path.exists() else {}
    # Compare deployments, not endpoint strings: the same deployment answers on
    # more than one hostname, and renaming it must not invalidate run state.
    was = state.get("endpoint")
    if was and deployment(was) != deployment(api_base()):
        sys.exit(f"{path} is from {was}, not {api_base()}: move it aside")
    state["endpoint"] = api_base()
    return state


def save_state(path: Path, state: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1))


def wait(kind: str, obj_id: str, every_s: int = 60) -> dict:
    """Poll /agents/<kind>/<id> until terminal."""
    last = None
    while True:
        obj = request("GET", f"{agents_base()}/{kind}/{obj_id}")
        now = (obj["status"], json.dumps(obj.get("progress"), sort_keys=True))
        if now != last:
            log(f"{obj_id}: {obj['status']} {obj.get('progress') or ''}")
            last = now
        if obj["status"] in TERMINAL:
            return obj
        time.sleep(every_s)


def aggregate(report: dict) -> dict:
    t = report["targets"]["event"]
    return {**t["aggregate"], "confusion_matrix": t["confusion_matrix"],
            "class_names": t["class_names"]}
