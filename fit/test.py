#!/usr/bin/env python3
"""Promote the best trial and test it once with the Evals API.

    python3 fit/test.py                  # best trial across fit/optimize.py's runs, on incidents #4-#7
    python3 fit/test.py --optimization opt_...   # the best trial of one optimization
    python3 fit/test.py --trial otr_...  # a specific trial of the best run
    python3 fit/test.py --max-windows 9000   # an eval per file, cut to <= 9,000 windows (the free trial's default)

The promoted blueprint carries the classifier Optimize fitted on the training
files and pins the trial's values. One eval scores it on the test role
(incidents #4-#7, never used for a choice) against the `label` column, each
window labelled by the majority of its rows, with predictions.

With the predictions downloaded, this script pairs each with the rows its window
spans (windows tile each file from row 0 at `step_size`; `row_index` counts
across the whole eval, so a window's position in its file is its rank within its
example) and:
  * checks every prediction's gold label against the file's `label` column, and
    the offline confusion matrix against the platform's. The platform scores each
    record once: a window answers only for the rows since the previous window
    ended (all its rows for the first), so at step 1 a window's gold is its last
    row's label, whatever `downsampling` says;
  * scores it again as fit/evaluate_events.py and the design rule do -- each
    window labelled by the majority of all its rows, ties to the fault -- so the
    result compares with fit/evaluate_events.py's;
  * scores each incident: detected or missed, the delay after onset, and false
    alarms on windows with no fault row.

On the free trial an eval is stopped after 2 hours and runs on CPU, at about
9,000 windows of this pump's 10 channels in 1.5 hours, so there (ATAI_API_ENDPOINT
on try.archetypeai.app) the default is `--max-windows 9000`: an eval per test file,
a longer file cut into pieces of at most that many windows (fit/out/test-pieces/),
`--parallel` at a time, pooled. Consecutive pieces overlap by a window less one
row, so every window of the file is scored exactly once; each eval's confusion
matrix is checked against its report, and the metrics are recomputed from the
pooled counts the way the platform computes them.

Writes fit/out/test_state.json (resume), fit/out/test.json and
fit/out/test-predictions.ndjson.
"""
from __future__ import annotations

import argparse
import datetime
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from atai import (COLUMN, OUT, ROLES, agents_base, aggregate, api_base, example, free_trial, load_dotenv,
                  load_state, log, manifest, request, save_state, state_path, upload_all, wait)

FAULT = "pump_breakdown"


def best_run(opt_state: dict) -> str:
    """The optimization whose best trial scores highest, across fit/optimize.py's runs.
    A tie goes to the one that tried more points (the search over the probe that
    found the same trial), then to the earlier one."""
    best = None
    for r in opt_state.get("runs", []):
        opt = request("GET", f"{agents_base()}/optimizations/{r['optimization']}")
        value = (opt.get("best_trial") or {}).get("objective_value")
        tried = (opt.get("progress") or {}).get("completed", 0)
        log(f"{opt['id']}: {opt['status']}, {tried} trials, best {value}")
        if opt["status"] == "completed" and value is not None and (best is None or (value, tried) > best[1:]):
            best = (opt["id"], value, tried)
    if not best:
        raise SystemExit("no completed optimization with a scored trial: run fit/optimize.py")
    return best[0]


def promote(opt_id: str, trial_id: str | None) -> dict:
    opt = request("GET", f"{agents_base()}/optimizations/{opt_id}")
    trials = request("GET", f"{agents_base()}/optimizations/{opt_id}/trials?limit=1000")["data"]
    tid = trial_id or opt.get("best_trial_id")
    trial = next((t for t in trials if t["id"] == tid), None)
    if not trial or trial["status"] != "completed":
        raise SystemExit(f"trial {tid} of {opt_id} is not a completed trial")
    vals = {**opt["overrides"]["values"], **trial["trial_values"]["values"]}
    if trial.get("promoted_blueprint"):
        bp = trial["promoted_blueprint"]
        log(f"{tid} already promoted -> {bp['blueprint_key']} ({bp['id']})")
        return {"id": bp["id"], "key": bp["blueprint_key"], "trial": tid, "values": vals}
    url = f"{agents_base()}/optimizations/{opt_id}/trials/{tid}/promote"
    body = {
        "name": f"RED pump (w {vals['window_size']}, step {vals['step_size']}, {vals['metric']})",
        "description": f"Promoted from {opt_id}; prototypes from normal rows 0-8,191 and incidents #1-#2."}
    try:
        bp = request("POST", url, body={"blueprint_key": f"red-pump-{tid}", **body})
    except SystemExit as e:
        # choosing the key needs the admin role (a free-trial org has none): let the platform choose it
        if "(403)" not in str(e) or "blueprint_key" not in str(e):
            raise
        bp = request("POST", url, body=body)
    log(f"promoted {tid} -> {bp['blueprint_key']} ({bp['id']})")
    return {"id": bp["id"], "key": bp["blueprint_key"], "trial": tid, "values": vals}


def split(files: list, max_windows: int, window: int, step: int) -> list:
    """Each test file as one piece, or cut into pieces of at most `max_windows` windows.

    Piece j holds the rows of its windows, so consecutive pieces overlap by window -
    step rows and together hold exactly the file's windows. Pieces are written to
    fit/out/test-pieces/ and keep `rows` (the source rows they span) and `of` (the file)."""
    out = []
    for f in files:
        src = ROLES / f["file"]
        lines = src.read_text().splitlines(True)
        n = (len(lines) - 1 - window) // step + 1
        k = -(-n // max_windows)
        if k == 1:
            out.append({**f, "of": src.stem})
            continue
        (OUT / "test-pieces").mkdir(parents=True, exist_ok=True)
        cuts = [round(j * n / k) for j in range(k + 1)]          # window indices
        for j, (a, b) in enumerate(zip(cuts, cuts[1:]), 1):
            lo, hi = a * step, (b - 1) * step + window            # rows [lo, hi) of the file
            piece = OUT / "test-pieces" / f"{src.stem}_part{j}of{k}.csv"
            if not piece.exists():
                piece.write_text(lines[0] + "".join(lines[1 + lo:1 + hi]))
            out.append({**f, "file": piece, "rows": [f["rows"][0] + lo, f["rows"][0] + hi], "of": src.stem})
    return out


def metrics(c: dict) -> dict:
    """The platform's aggregate from counts (each row once; checked against every eval's report)."""
    f1 = lambda p, r: 2 * p * r / (p + r) if p + r else 0.0  # noqa: E731
    pf, rf = c["tp"] / max(c["tp"] + c["fp"], 1), c["tp"] / max(c["tp"] + c["fn"], 1)
    pn, rn = c["tn"] / max(c["tn"] + c["fn"], 1), c["tn"] / max(c["tn"] + c["fp"], 1)
    return {"accuracy": (c["tp"] + c["tn"]) / max(sum(c.values()), 1), "detection_precision": pf,
            "detection_recall": rf, "foreground_macro_f1": f1(pf, rf), "macro_f1": (f1(pf, rf) + f1(pn, rn)) / 2}


def score(files: list, evals: list, preds: list, window: int, step: int) -> dict:
    """Pair predictions with rows; check each eval's confusion and metrics; pool them, and
    each file's pieces into one incident."""
    by_ex = {}
    for p in preds:
        by_ex.setdefault(p["example"], []).append(p)
    window_majority = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
    counts, out, abstained, ties = {}, {}, 0, 0
    for f in files:
        name = (ROLES / f["file"]).stem
        totals = counts[name] = dict.fromkeys(window_majority, 0)
        lab = (pd.read_csv(ROLES / f["file"], usecols=["label"]).label == FAULT).to_numpy()
        starts = list(range(0, len(lab) - window + 1, step))
        # The prediction record carries no row_index, and its `input` is 0 on every
        # row; key.predicted is the window's [start, end] timestamp, so order by
        # its start.
        got = sorted(by_ex.get(name, []), key=lambda p: p["key"]["predicted"][0])
        if len(got) != len(starts):
            raise SystemExit(f"{name}: {len(got)} predictions for {len(starts)} windows at "
                             f"window {window}, step {step}")
        onset, end = (r - f["rows"][0] for r in f["incident_rows"])
        fired, normal_windows, false_alarms = [], 0, 0
        for k, (s, p) in enumerate(zip(starts, got)):
            n_fault = int(lab[s:s + window].sum())
            span = lab[s:s + window] if k == 0 else lab[s + window - step:s + window]
            n_span = int(span.sum())
            # majority over the span, a tie to the label occurring latest
            g = FAULT if (2 * n_span > len(span) or (2 * n_span == len(span) and span[-1])) else "normal"
            if p["expected"] != g:
                raise SystemExit(f"{name} window at row {s}: platform gold {p['expected']}, the label "
                                 f"column says {g} -- predictions are misaligned")
            if p["outcome"] == "missed" or p["predicted"] is None:
                abstained += 1
                continue
            hit = p["predicted"] == FAULT
            totals[("t" if (g == FAULT) == hit else "f") + ("p" if hit else "n")] += 1
            w_fault = 2 * n_fault >= window
            ties += 2 * n_fault == window
            window_majority[("t" if w_fault == hit else "f") + ("p" if hit else "n")] += 1
            if n_fault == 0:
                normal_windows += 1
                false_alarms += hit
            if hit:
                fired.append((s, s + window))
        hits = [w for w in fired if w[0] < end and onset < w[1]]
        delay = (min(w[1] for w in hits) - 1 - onset) if hits else None
        i = out.setdefault(f.get("of", name), {"incident_rows": end - onset, "detected": False, "delay_samples": None,
                                               "false_alarms": 0, "normal_windows": 0})
        i["detected"] |= bool(hits)
        if delay is not None and (i["delay_samples"] is None or delay < i["delay_samples"]):
            i["delay_samples"] = delay
        i["false_alarms"] += false_alarms
        i["normal_windows"] += normal_windows
    pooled = dict.fromkeys(window_majority, 0)
    for ev, names in evals:
        a = aggregate(ev["metrics_report"])
        idx = {n: i for i, n in enumerate(a["class_names"])}
        cm, fi, ni = a["confusion_matrix"], idx[FAULT], idx["normal"]
        platform = {"tp": cm[fi][fi], "fn": cm[fi][ni], "fp": cm[ni][fi], "tn": cm[ni][ni]}
        offline = {k: sum(counts[n][k] for n in names) for k in pooled}
        if offline != platform:
            raise SystemExit(f"{ev['id']}: offline confusion {offline} != platform {platform}")
        ours = metrics(offline)
        # the platform reports a precision of 0/0 (nothing predicted fault) as None
        if any(a[k] is not None and abs(ours[k] - a[k]) > 1e-9 for k in ours):
            raise SystemExit(f"{ev['id']}: metrics from its counts {ours} != the platform's {a}")
        for k in pooled:
            pooled[k] += offline[k]
    tp, fp, fn = (window_majority[k] for k in ("tp", "fp", "fn"))
    return {"platform": metrics(pooled), "confusion": pooled, "abstained": abstained,
            "window_majority": {**window_majority, "fault_f1": 2 * tp / max(2 * tp + fp + fn, 1),
                                "tie_windows": ties},
            "incidents": out}


def report(r: dict) -> None:
    p, v = r["platform"], r["blueprint"]["values"]
    print(f"\neval {', '.join(r['evals'])}  blueprint {r['blueprint']['key']}  "
          f"(window {v['window_size']}, step {v['step_size']}, {v['metric']}; "
          f"{r['abstained']} abstained)")
    print(f"  platform (each row once): fault F1 {p['foreground_macro_f1']:.4f}  macro-F1 {p['macro_f1']:.4f}  "
          f"recall {p['detection_recall']:.4f}  precision {p['detection_precision']:.4f}")
    w = r["window_majority"]
    print(f"  whole-window majority (as fit/evaluate_events.py): fault F1 {w['fault_f1']:.4f}  "
          f"tp {w['tp']} fp {w['fp']} fn {w['fn']} tn {w['tn']}")
    fa = sum(i["false_alarms"] for i in r["incidents"].values())
    nw = sum(i["normal_windows"] for i in r["incidents"].values())
    print(f"  false alarms {fa:,} / {nw:,} = {fa / max(nw, 1):.4f} (windows with no fault row)")
    for name, i in r["incidents"].items():
        when = f"+{i['delay_samples']} samples" if i["detected"] else "MISSED"
        print(f"    {name}  {i['incident_rows']:>5,} rows  {when:<13}  false alarms "
              f"{i['false_alarms']:>4} / {i['normal_windows']:,}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--optimization", help="default: the best of fit/out/optimize_state.json's runs")
    ap.add_argument("--trial", help="default: the optimization's best trial")
    ap.add_argument("--max-windows", type=int,
                    help="an eval per test file, cut to at most N windows (default: one eval of all; 9000 on the free trial)")
    ap.add_argument("--parallel", type=int, default=3, help="evals at once with --max-windows (the free trial runs 3)")
    args = ap.parse_args()
    load_dotenv()
    if args.max_windows is None and free_trial():
        args.max_windows = 9000
        log("free trial (try.archetypeai.app): each job stops after 2 hours, so the test runs as an eval per "
            "file, cut to at most 9,000 windows, 3 at a time, pooled (--max-windows 0 for one eval)")
    m = manifest()
    STATE = state_path("test")
    state = load_state(STATE)
    save = lambda: save_state(STATE, state)  # noqa: E731
    if "blueprint" not in state:
        opt_id = args.optimization or best_run(load_state(state_path("optimize")))
        state["optimization"] = opt_id
        state["blueprint"] = promote(opt_id, args.trial)
        save()

    v = state["blueprint"]["values"]
    files = m["test"]
    if args.max_windows:
        files = split(files, args.max_windows, v["window_size"], v["step_size"])
    paths = [ROLES / f["file"] for f in files]
    groups = [[p] for p in paths] if args.max_windows else [paths]
    if not args.max_windows and "eval" in state:            # this script's single-eval state, before --max-windows
        state.setdefault("evals", [state["eval"]])
    state.setdefault("evals", [])
    if len(state["evals"]) not in (0, len(groups)):
        raise SystemExit(f"{STATE} holds {len(state['evals'])} eval(s), not {len(groups)}: "
                         f"rerun with the same --max-windows, or move it aside")
    ids = upload_all(paths, jobs=4)

    def one(i: int) -> dict:
        if i >= len(state["evals"]) or not state["evals"][i]:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            what = "incidents 4-7" if len(groups) == 1 else groups[i][0].stem
            ev = request("POST", f"{agents_base()}/evals", body={
                "blueprint_id": state["blueprint"]["id"], "emit_predictions": True,
                "name": f"red-pump test {what} {stamp}",
                "examples": [example(p.stem, ids[p], COLUMN) for p in groups[i]]})
            with lock:
                state["evals"] += [None] * (i + 1 - len(state["evals"]))
                state["evals"][i] = ev["id"]
                save()
            log(f"eval {ev['id']}: {len(groups[i])} test file(s)")
        ev = wait("evals", state["evals"][i])
        if ev["status"] != "completed" or not ev.get("metrics_report"):
            with lock:                                      # a rerun starts a new eval for it
                state["evals"][i] = None
                save()
            raise SystemExit(f"eval {ev['id']} ended {ev['status']}: {ev.get('error')}; rerun to retry it")
        return ev

    lock = threading.Lock()
    with ThreadPoolExecutor(args.parallel if len(groups) > 1 else 1) as pool:
        evs = list(pool.map(one, range(len(groups))))
    raw = b""
    for ev in evs:
        pred = next(x["id"] for x in ev["output_artifacts"]
                    if x.get("metadata", {}).get("kind") == "predictions")
        raw += request("GET", f"{api_base()}/files/download/{pred}", raw=True).rstrip(b"\n") + b"\n"
    (OUT / "test-predictions.ndjson").write_bytes(raw)
    r = score(files, [(ev, [p.stem for p in g]) for ev, g in zip(evs, groups)],
              [json.loads(x) for x in raw.decode().splitlines() if x.strip()], v["window_size"], v["step_size"])
    r = {"evals": state["evals"], "max_windows": args.max_windows, "blueprint": state["blueprint"],
         "optimization": state["optimization"], **r}
    (OUT / "test.json").write_text(json.dumps(r, indent=1))
    report(r)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
