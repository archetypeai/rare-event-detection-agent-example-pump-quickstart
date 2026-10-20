#!/usr/bin/env python3
"""Serve: the promoted classifier answering over /query, checked against the delivery.

    python3 fit/serve.py                         # inc04 and inc07, around each breakdown (~15 min)
    python3 fit/serve.py --context 0 --whole     # every window of each file (inc04: ~2 h)
    python3 fit/serve.py --windows-per-query 16  # 16 consecutive windows a query

fit/deliver.py runs the classifier in batch: an agent run per file, the output read
when the run is done. Serving keeps an agent loaded and answers a window in one
round trip, as a pump's historian would ask it every minute for the latest 64
readings. This replays delivery files that way and checks every answer against
the batch output for the same window:

  1. the served variant of fit/test.py's promoted blueprint, made once and reused
     (`<key>-served-records`): the same prototypes, encoder and values, step 1,
     with the CSV source and sink swapped for an `atai-records` serving endpoint;
  2. a bundle of it, run in serving mode;
  3. each file replayed one row at a time: every query holds the latest
     `window_size` rows (`--windows-per-query N` sends N windows at once). By
     default only the windows ending within --context rows of the breakdown;
  4. every answer against batch: `predicted_state`, the class probabilities to
     within 1e-4, and per file the detection (the first `pump_breakdown` window
     overlapping the breakdown, as fit/evaluate_events.py counts it) and the false
     alarms (`pump_breakdown` windows with no fault row), served and batch;
  5. the agent cancelled and deleted, and the bundle deleted, however it went
     (Ctrl-C, SIGTERM and SIGHUP included). Their ids stay in
     fit/out/serve_state.json until then, so fit/cleanup.py finds them after a kill.

Dev only, like serving (https://github.com/archetypeai/agent-serving-example).
A served agent keeps no window between queries, so a query must carry the whole
window. Writes eval_out/serving/.
"""
from __future__ import annotations

import argparse
import copy
import json
import signal
import statistics
import sys
import time

import pandas as pd

from atai import REPO, ROLES, agents_base, load_dotenv, load_state, log, manifest, request, save_state, state_path

MODEL = "red-pump"               # the name a query gives in `model`
FAULT = "pump_breakdown"
OUT = REPO / "eval_out" / "serving"


def get_or_none(url: str):
    try:
        return request("GET", url)
    except SystemExit as e:
        if "(404)" in str(e):
            return None
        raise


def served_document(src: dict, model: str = MODEL) -> dict:
    """The promoted blueprint's document with an atai-records serving source and sink, at step 1."""
    doc = copy.deepcopy(src["document"])
    doc.pop("blueprint_id", None)
    doc["values"]["step_size"] = 1
    endpoint = {"format": "serving", "kind": "http", "protocols": ["atai-records"]}
    doc["connectors"] = {
        "source": {"key": "RecordsSource", "config": {
            **endpoint, "models": [model],
            "data_columns": [{"dtype": "f32", "names": doc["values"]["data_columns"]}],
            "timestamp_column": doc["values"]["timestamp_column"]}},
        "sink": {"key": "RecordsSink", "config": dict(endpoint)},
    }
    doc["name"] = f"{src['name']} (served, records)"
    return doc


def served_blueprint(promoted: str) -> str:
    """The atai-records served variant of `promoted`, created once."""
    key = f"{promoted}-served-records"
    if get_or_none(f"{agents_base()}/blueprints/{key}"):
        return key
    src = request("GET", f"{agents_base()}/blueprints/{promoted}")
    doc = served_document(src)
    bp = request("POST", f"{agents_base()}/blueprints", body={
        "blueprint_key": key, "name": doc["name"], "document": doc,
        "description": f"{promoted} served with atai-records, step 1."})
    log(f"created served blueprint {key} ({bp['id']})")
    return key


def episode(labels: list[str]) -> tuple[int, int] | None:
    """The first and one-past-last row of the file's breakdown."""
    rows = [i for i, s in enumerate(labels) if s == FAULT]
    return (rows[0], rows[-1] + 1) if rows else None


def outcome(preds: list[str], ends: list[int], labels: list[str], window: int) -> dict:
    """Detection latency (rows from onset to the first fault window overlapping the
    breakdown) and false alarms (fault windows with no fault row), for windows
    ending at `ends`."""
    ep = episode(labels)
    hits, false_alarms = [], 0
    for p, end in zip(preds, ends):
        if p != FAULT:
            continue
        lo = end - window + 1
        if not any(s == FAULT for s in labels[lo:end + 1]):
            false_alarms += 1
        if ep and lo < ep[1] and ep[0] <= end:
            hits.append(end)
    return {"latency": (min(hits) - ep[0]) if hits else None, "false_alarms": false_alarms}


def stop(signum, _frame):
    sys.exit(f"stopped by signal {signum}")       # so `finally` deletes the agent and bundle


def main() -> int:
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", nargs="+", default=["inc04", "inc07"], help="delivery files fit/deliver.py delivered")
    ap.add_argument("--context", type=int, default=120,
                    help="replay the windows ending within this many rows of the breakdown (default 120, 2 h)")
    ap.add_argument("--whole", action="store_true", help="replay every window of each file")
    ap.add_argument("--windows-per-query", type=int, default=1, help="1 = live, one window per row (default); up to 16")
    args = ap.parse_args()

    load_dotenv()
    # Match the deployment generation, not one host: dev is api.dev.* and platform.dev.*
    if ".dev." not in agents_base():
        sys.exit("agent serving is on dev only for now (e.g. https://platform.dev.u1.archetypeai.app)")
    bp = load_state(state_path("test")).get("blueprint") or sys.exit("no promoted blueprint: run fit/test.py")
    m = manifest()
    channels, window = m["channels"], bp["values"]["window_size"]
    files = {f["file"].split("/")[-1].removesuffix(".csv"): f for f in m["delivery"]}

    plan = []                                    # (file, data, labels, batch, first window, windows)
    for name in args.files:
        f = files.get(name) or sys.exit(f"{name} is not a delivery file: {', '.join(files)}")
        data = pd.read_csv(ROLES / f["file"])
        labels = pd.read_csv(ROLES / f["labels"]).label.tolist()
        out = REPO / "eval_out" / "delivery" / f"red-output-{name}.csv"
        if not out.exists():
            sys.exit(f"no {out.relative_to(REPO)}: run fit/deliver.py first")
        batch = pd.read_csv(out)
        if len(batch) != len(data) - window + 1:
            sys.exit(f"{name}: the delivery output has {len(batch)} windows, expected {len(data) - window + 1}")
        ep = episode(labels)
        first, last = 0, len(batch) - 1          # window k ends on row k + window - 1
        if not args.whole and ep:
            first = max(0, ep[0] - args.context - window + 1)
            last = min(len(batch) - 1, ep[1] - 1 + args.context - window + 1)
        plan.append((name, data[channels].to_numpy(dtype=float), labels, batch, first, last - first + 1))
    wpq = max(1, min(args.windows_per_query, 16))
    log(f"{len(plan)} file(s), {sum(p[5] for p in plan):,} windows, {wpq} per query; model {bp['key']}")

    key = served_blueprint(bp["key"])
    live = state_path("serve")
    state = load_state(live)
    if state.get("bundle"):
        sys.exit(f"{live} holds an earlier replay's agent and bundle: run fit/cleanup.py first")
    state["bundle"] = request("POST", f"{agents_base()}/bundles", body={"blueprint": key, "name": "RED serve"})["id"]
    save_state(live, state)
    served, latency = {}, []
    t_start = time.time()
    try:
        state["agent"] = request("POST", f"{agents_base()}/bundles/{state['bundle']}/run", body={"mode": "serving"})["id"]
        save_state(live, state)
        log(f"bundle {state['bundle']} · agent {state['agent']}")
        while (status := request("GET", f"{agents_base()}/instances/{state['agent']}").get("status")) != "running":
            if status in ("failed", "cancelled", "canceled", "completed") or time.time() - t_start > 600:
                sys.exit(f"agent {state['agent']} is {status}, not running")
            time.sleep(3)
        for name, X, _, _, first, n in plan:
            got = served[name] = []
            for k in range(0, n, wpq):
                count = min(wpq, n - k)
                lo = first + k
                chunk = X[lo:lo + window + count - 1]
                body = {"model": MODEL, "query": "", "events": [{"type": "data.numeric_array",
                        "event_data": {"contents": [chunk[:, c].tolist() for c in range(len(channels))]}}]}
                t = time.time()
                answer = request("POST", f"{agents_base()}/instances/{state['agent']}/query", body=body)
                latency.append(time.time() - t)
                records = (answer.get("response") or {}).get("data")
                if not isinstance(records, list) or len(records) != count:
                    sys.exit(f"{name} window {lo}: expected {count} records, got {str(answer)[:300]}")
                got.extend(records)
            log(f"  {name}: {n} windows, {time.time() - t_start:.0f} s so far")
    finally:
        done = True
        for method, path, body in ((("POST", f"/instances/{state['agent']}/cancel", {}),
                                    ("DELETE", f"/instances/{state['agent']}", None)) if state.get("agent") else ()) + \
                                  (("DELETE", f"/bundles/{state['bundle']}", None),):
            try:
                request(method, f"{agents_base()}{path}", body=body, raw=method == "DELETE")
            except SystemExit as e:
                if "(404)" not in str(e):
                    log(f"cleanup: {e}; fit/cleanup.py retries it")
                    done = False
                    break
        if done:
            live.unlink()
            log(f"cancelled and deleted {state.get('agent')}, deleted {state['bundle']}")
    elapsed = time.time() - t_start

    rows, per_file = [], []
    for name, _, labels, batch, first, n in plan:
        ref, got = batch.iloc[first:first + n], served[name]
        for k, (s, b) in enumerate(zip(got, ref.itertuples())):
            rows.append({"file": name, "window": first + k, "end_row": first + k + window - 1,
                         "batch_state": b.predicted_state, "served_state": s["predicted_state"],
                         "batch_p_fault": b.p_pump_breakdown, "served_p_fault": float(s["p_pump_breakdown"]),
                         "batch_p_normal": b.p_normal, "served_p_normal": float(s["p_normal"]),
                         "served_invalid": str(s["invalid"]).lower() == "true",
                         "same_state": s["predicted_state"] == b.predicted_state,
                         "same_p": max(abs(float(s["p_pump_breakdown"]) - b.p_pump_breakdown),
                                       abs(float(s["p_normal"]) - b.p_normal)) < 1e-4})
        ends = [first + k + window - 1 for k in range(n)]
        per_file.append({"file": name, "windows": n, "first_end_row": ends[0], "last_end_row": ends[-1],
                         "breakdown_rows": list(episode(labels) or []),
                         "served": outcome([s["predicted_state"] for s in got], ends, labels, window),
                         "batch": outcome(ref.predicted_state.tolist(), ends, labels, window)})

    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    stem = OUT / f"serve_{'_'.join(args.files)}{'_whole' if args.whole else ''}_wpq{wpq}"
    df.to_csv(stem.with_suffix(".csv"), index=False)
    ms = sorted(x * 1000 for x in latency)
    p_diff = pd.concat([(df.served_p_fault - df.batch_p_fault).abs(), (df.served_p_normal - df.batch_p_normal).abs()])
    summary = {"blueprint": bp["key"], "served_blueprint": key, "files": per_file,
               "windows": len(df), "windows_per_query": wpq, "queries": len(latency),
               "same_state": int(df.same_state.sum()), "same_p": int(df.same_p.sum()),
               "max_p_diff": float(p_diff.max()), "invalid": int(df.served_invalid.sum()),
               "latency_ms": {"median": round(statistics.median(ms)), "p95": round(ms[int(0.95 * (len(ms) - 1))]),
                              "max": round(ms[-1])},
               "replay_seconds": round(elapsed, 1)}
    stem.with_suffix(".json").write_text(json.dumps(summary, indent=1))

    print(f"\nserved {len(df):,} windows of {len(plan)} file(s) in {len(latency):,} queries, {elapsed:.0f} s")
    print(f"  against the delivery (batch): predicted_state identical in {summary['same_state']:,}/{len(df):,}, "
          f"probabilities within 1e-4 in {summary['same_p']:,}/{len(df):,} (max difference {summary['max_p_diff']:.1e}); "
          f"invalid {summary['invalid']}")
    print(f"  latency per query: median {summary['latency_ms']['median']} ms, "
          f"p95 {summary['latency_ms']['p95']} ms, max {summary['latency_ms']['max']} ms")
    for r in per_file:
        def fmt(o):
            det = "missed" if o["latency"] is None else f"+{o['latency']} samples"
            return f"{det}, {o['false_alarms']} false alarm(s)"
        print(f"  {r['file']} (rows {r['first_end_row']}-{r['last_end_row']}): served {fmt(r['served'])}; "
              f"batch {fmt(r['batch'])}")
    print(f"  -> {stem.relative_to(REPO)}.csv / .json")
    return 0 if summary["same_state"] == len(df) else 1


if __name__ == "__main__":
    raise SystemExit(main())
