#!/usr/bin/env python3
"""Deliver: run the promoted blueprint in batch sessions, then score offline.

    python3 fit/deliver.py                 # the four test slices, labels held back
    python3 fit/deliver.py --tail          # also the five tail chunks (2018-07-28 -> 08-31)

A package of fit/test.py's promoted blueprint, which already holds the prototypes
and every value the trial pinned, step 1 included: one prediction per row. A
package carries no values; it runs the blueprint as promoted. The package is
deployed as `batch`, and a session runs over each delivery file. Inputs
are data/roles/delivery/, which carry no label column; the labels stay in
data/roles/labels/ until fit/evaluate_events.py reads them.

Sessions encode at ~2.2 windows/s: the slices are ~4.8 h of runs, the tail
~6.3 h. Every output is checked to cover its whole input (an output can be cut
short at `completed`: red_api downloads it again until it reaches the input's
end, and the window count is checked). Network errors are waited out.

Writes eval_out/delivery/ (red-output-<file>.csv, evaluation-*.json) and
fit/out/deliver_state.json (resume: a rerun skips finished files and polls
sessions already started).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from atai import REPO, ROLES, load_dotenv, load_state, log, manifest, save_state, state_path
from red_api import create_package, deploy, download_results, open_session, poll_session, upload_file

OUT = REPO / "eval_out" / "delivery"
TIMEOUT_S = 4 * 3600
NETWORK_WAIT_S, NETWORK_RETRIES = 60, 60   # ride out an outage of up to an hour
lock = threading.Lock()


def rows_of(path: Path) -> list[dict]:
    """An output's rows, without the header repeated at every chunk boundary."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if r.get("finish_timestamp") != "finish_timestamp"]


def complete(out: Path, src: Path, window: int) -> str | None:
    """None when `out` holds one window per row of `src` from row `window`-1 to
    the last, else what is wrong."""
    with open(src, newline="") as fh:
        ts = [int(r["timestamp"]) for r in csv.DictReader(fh)]
    rows = rows_of(out)
    want = len(ts) - window + 1
    if not rows:
        return "empty"
    last = max(int(float(r["finish_timestamp"])) for r in rows)
    if len(rows) != want or last != ts[-1]:
        return f"{len(rows)} windows of {want}, last ends {last} (input ends {ts[-1]})"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tail", action="store_true", help="also deliver the five tail chunks")
    ap.add_argument("--parallel", type=int, default=4)
    args = ap.parse_args()
    load_dotenv()
    m = manifest()
    test = load_state(state_path("test"))
    if "blueprint" not in test:
        raise SystemExit("no promoted blueprint: run fit/test.py first")
    bp = test["blueprint"]
    window = bp["values"]["window_size"]
    STATE = state_path("deliver")
    state = load_state(STATE)
    if state.get("blueprint", bp["key"]) != bp["key"]:
        raise SystemExit(f"{STATE} is for {state['blueprint']}: move it aside to deliver {bp['key']}")
    state["blueprint"] = bp["key"]

    def save():
        with lock:
            save_state(STATE, state)

    if "bundle" in state:
        raise SystemExit(f"{STATE} is from a bundle delivery: move it aside to deliver through a package")
    if "package" not in state:
        state["package"] = create_package(bp["id"], "RED pump delivery")["id"]
        save()
        log(f"package {state['package']} on {bp['key']} (step {bp['values']['step_size']})")
    if "deployment" not in state:
        state["deployment"] = deploy(state["package"], "batch")["id"]
        save()
        log(f"batch deployment {state['deployment']}")

    files = [f for f in m["delivery"] if "incident" in f or args.tail]
    OUT.mkdir(parents=True, exist_ok=True)

    def one(f: dict) -> Path | None:
        src = ROLES / f["file"]
        dst = OUT / f"red-output-{src.stem}.csv"
        if dst.exists() and not complete(dst, src, window):
            return dst
        runs = state.setdefault("sessions", {})
        if src.stem not in runs:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            fid = upload_file(str(src), rename=f"red-pump-delivery__{src.stem}-{stamp}.csv")["file_id"]
            ses = open_session(state["deployment"], [fid])
            with lock:
                runs[src.stem] = ses["id"]
            save()
            log(f"{src.name}: session {ses['id']}")
        if poll_session(runs[src.stem], TIMEOUT_S, interval_s=60) != "completed":
            log(f"{src.name}: session did not report completed; trying /results anyway")
        # red_api waits until the output's last window reaches the input's end;
        # the full count also catches windows missing in the middle.
        if download_results(runs[src.stem], str(dst), input_csv=str(src)):
            problem = complete(dst, src, window)
            if not problem:
                log(f"{src.name}: complete")
                return dst
            log(f"{src.name}: output incomplete ({problem})")
        dst.unlink(missing_ok=True)
        with lock:
            runs.pop(src.stem)
        save()
        log(f"{src.name}: no complete output; rerun to retry")
        return None

    def offline(e: BaseException) -> bool:
        text = f"{type(e).__name__} {e}"
        return any(k in text for k in ("URLError", "urlopen error", "nodename", "timed out",
                                       "Connection", "RemoteDisconnected", "IncompleteRead"))

    def safe(f: dict) -> Path | None:
        for attempt in range(NETWORK_RETRIES + 1):
            try:
                return one(f)
            except (Exception, SystemExit) as e:  # one flaky run must not stop the others
                if offline(e) and attempt < NETWORK_RETRIES:
                    log(f"{f['file']}: network error ({e}); retrying in {NETWORK_WAIT_S} s")
                    time.sleep(NETWORK_WAIT_S)
                    continue
                log(f"{f['file']}: {type(e).__name__}: {e}; rerun to retry")
                return None

    with ThreadPoolExecutor(args.parallel) as pool:
        got = list(pool.map(safe, files))
    missing = [f["file"] for f, g in zip(files, got) if not g]
    if missing:
        log(f"{len(missing)} of {len(got)} outputs missing ({', '.join(missing)}); rerun to resume")
        return 1

    rel = lambda p: str(Path(p).relative_to(REPO))  # noqa: E731  (no home directory in the results)
    rc = 0
    for name, group in (("slices", [g for f, g in zip(files, got) if "incident" in f]),
                        ("tail", [g for f, g in zip(files, got) if "incident" not in f])):
        if not group:
            continue
        stems = [Path(g).stem.removeprefix("red-output-") for g in group]
        rc |= subprocess.run([sys.executable, "fit/evaluate_events.py", "--window-size", str(window),
                              "--labels", "data/roles/labels", "--slices", ",".join(stems),
                              "--platform-output", *map(rel, group),
                              "--json", rel(OUT / f"evaluation-{name}.json")], cwd=REPO).returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
