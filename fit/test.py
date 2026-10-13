#!/usr/bin/env python3
"""Promote the best trial and test it once with the Evals API.

    python3 fit/test.py                  # best trial across fit/optimize.py's runs, on incidents #4-#7
    python3 fit/test.py --optimization opt_...   # the best trial of one optimization
    python3 fit/test.py --trial otr_...  # a specific trial of the best run

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
  * scores it again as fit/evaluate_events.py and the design doc do -- each
    window labelled by the majority of all its rows, ties to the fault -- so the
    result compares with the archived reference;
  * scores each incident: detected or missed, the delay after onset, and false
    alarms on windows with no fault row.

Writes fit/out/test_state.json (resume), fit/out/test.json and
fit/out/test-predictions.ndjson.
"""
from __future__ import annotations

import argparse
import datetime
import json

import pandas as pd

from atai import (COLUMN, OUT, ROLES, agents_base, aggregate, api_base, example, load_dotenv,
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
    bp = request("POST", f"{agents_base()}/optimizations/{opt_id}/trials/{tid}/promote", body={
        "blueprint_key": f"red-pump-{tid}",
        "name": f"RED pump (w {vals['window_size']}, step {vals['step_size']}, {vals['metric']})",
        "description": f"Promoted from {opt_id}; prototypes from normal rows 0-8,191 and incidents #1-#2."})
    log(f"promoted {tid} -> {bp['blueprint_key']} ({bp['id']})")
    return {"id": bp["id"], "key": bp["blueprint_key"], "trial": tid, "values": vals}


def score(files: list, ev: dict, preds: list, window: int, step: int) -> dict:
    by_ex = {}
    for p in preds:
        by_ex.setdefault(p["example"], []).append(p)
    totals = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
    window_majority = dict(totals)
    out, abstained, ties = {}, 0, 0
    for f in files:
        name = (ROLES / f["file"]).stem
        lab = (pd.read_csv(ROLES / f["file"], usecols=["label"]).label == FAULT).to_numpy()
        starts = list(range(0, len(lab) - window + 1, step))
        got = sorted(by_ex.get(name, []), key=lambda p: p["row_index"])
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
            if p["gold"] != g:
                raise SystemExit(f"{name} window at row {s}: platform gold {p['gold']}, the label "
                                 f"column says {g} -- predictions are misaligned")
            if p["abstained"]:
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
        out[name] = {"incident_rows": end - onset, "detected": bool(hits),
                     "delay_samples": (min(w[1] for w in hits) - 1 - onset) if hits else None,
                     "false_alarms": false_alarms, "normal_windows": normal_windows}
    a = aggregate(ev["metrics_report"])
    idx = {n: i for i, n in enumerate(a["class_names"])}
    cm, fi, ni = a["confusion_matrix"], idx[FAULT], idx["normal"]
    platform = {"tp": cm[fi][fi], "fn": cm[fi][ni], "fp": cm[ni][fi], "tn": cm[ni][ni]}
    if totals != platform:
        raise SystemExit(f"offline confusion {totals} != platform {platform}")
    tp, fp, fn = (window_majority[k] for k in ("tp", "fp", "fn"))
    return {"platform": {k: v for k, v in a.items() if k not in ("confusion_matrix", "class_names")},
            "confusion": platform, "abstained": abstained,
            "window_majority": {**window_majority, "fault_f1": 2 * tp / max(2 * tp + fp + fn, 1),
                                "tie_windows": ties},
            "incidents": out}


def report(r: dict) -> None:
    p, v = r["platform"], r["blueprint"]["values"]
    print(f"\neval {r['eval']}  blueprint {r['blueprint']['key']}  "
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
    args = ap.parse_args()
    load_dotenv()
    m = manifest()
    STATE = state_path("test")
    state = load_state(STATE)
    save = lambda: save_state(STATE, state)  # noqa: E731
    if "blueprint" not in state:
        opt_id = args.optimization or best_run(load_state(state_path("optimize")))
        state["optimization"] = opt_id
        state["blueprint"] = promote(opt_id, args.trial)
        save()

    files = m["test"]
    paths = [ROLES / f["file"] for f in files]
    if "eval" not in state:
        ids = upload_all(paths, jobs=4)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ev = request("POST", f"{agents_base()}/evals", body={
            "blueprint_id": state["blueprint"]["id"], "emit_predictions": True,
            "name": f"red-pump test incidents 4-7 {stamp}",
            "examples": [example(p.stem, ids[p], COLUMN) for p in paths]})
        state["eval"] = ev["id"]
        save()
        log(f"eval {ev['id']}: {len(paths)} test files")
    ev = wait("evals", state["eval"])
    if ev["status"] != "completed" or not ev.get("metrics_report"):
        raise SystemExit(f"eval {state['eval']} ended {ev['status']}: {ev.get('error')}")
    pred = next(x["id"] for x in ev["output_artifacts"]
                if x.get("metadata", {}).get("kind") == "predictions")
    raw = request("GET", f"{api_base()}/v0.5/files/download/{pred}", raw=True)
    (OUT / "test-predictions.ndjson").write_bytes(raw)
    v = state["blueprint"]["values"]
    r = score(files, ev, [json.loads(x) for x in raw.decode().splitlines()],
              v["window_size"], v["step_size"])
    r = {"eval": state["eval"], "blueprint": state["blueprint"],
         "optimization": state["optimization"], **r}
    (OUT / "test.json").write_text(json.dumps(r, indent=1))
    report(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
