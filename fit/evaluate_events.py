#!/usr/bin/env python3
"""Stage 7 — score downloaded platform outputs against the ground-truth sidecars.

Offline and stdlib-only: no API key, no network, no platform calls. Point it at
output CSVs you already have (from `run_red_example.py`, `run_red_eval.py`, or a
raw `curl` run you downloaded yourself) and it scores them.

Separating this from Stage 6 matters in practice: a run can finish while nothing
is polling it, and re-scoring is something you do repeatedly while a single run
is something you do once. This script never re-runs anything.

Each slice is scored three ways, because window-level averages alone mislead
when the positive class is this rare:

  window level     precision / recall / F1 per class under the design doc's
                   majority rule (a window's truth is the label holding the
                   majority of its rows; ties go to the rare event).
  incident level   detected or missed, and the latency after onset. A slice can
                   score 0.99 accuracy while missing its incident entirely.
  false alarms     fault predictions on windows containing ZERO fault rows.
                   The one metric that stays comparable across window sizes.

Usage:
  # all four held-out slices — list the outputs after one flag
  python3 fit/evaluate_events.py --window-size 64 \\
      --platform-output eval_out_step1/red-output-inc04.csv \\
                        eval_out_step1/red-output-inc05.csv \\
                        eval_out_step1/red-output-inc06.csv \\
                        eval_out_step1/red-output-inc07.csv

  # one slice
  python3 fit/evaluate_events.py --window-size 64 \\
      --platform-output eval_out_step1/red-output-inc04.csv

  # shell glob, or explicit names if your filenames differ
  python3 fit/evaluate_events.py --window-size 64 --platform-output eval_out_step1/*.csv
  python3 fit/evaluate_events.py --window-size 64 --slices inc04,inc05 \\
      --platform-output a.csv b.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PREPARED = REPO / "data" / "prepared"
NORMAL, FAULT = "normal", "pump_breakdown"


def read_rows(path) -> list[dict]:
    """Read a platform output CSV, dropping re-emitted header rows.

    Outputs longer than ~10k rows come back chunked with the header repeated at
    every chunk boundary (observed: every 1,025 lines past line 10,178). No data
    is lost, but a naive DictReader yields rows whose values are the column names.
    """
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    first = next(iter(rows[0]), None) if rows else None
    return [r for r in rows if first is None or r.get(first) != first]


def pick(row: dict, *names: str) -> str | None:
    return next((n for n in names if n in row), None)


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def score_slice(output_path: str, labels_path: Path, window_size: int) -> dict | None:
    preds, truth = read_rows(output_path), read_rows(labels_path)
    if not preds:
        print(f"  {output_path}: empty output")
        return None

    pred_col = pick(preds[0], "predicted_state", "predicted_label", "prediction")
    # Runtime 1.1.9 renamed the output's time column: `timestamp` became the pair
    # `start_timestamp` / `finish_timestamp`. Prefer the FINISH time — that is the
    # window end, which is what the old `timestamp` column carried and what the
    # label sidecar is joined on. Joining on start_timestamp instead would shift
    # every window by window_size-1 rows and quietly produce wrong metrics rather
    # than an error. The legacy names stay as fallbacks so outputs downloaded
    # before the rename still score.
    ts_col = pick(preds[0], "finish_timestamp", "timestamp", "time")
    inv_col = pick(preds[0], "invalid", "invalid_state")
    if not pred_col or not ts_col:
        print(f"  {output_path}: no prediction/timestamp column in {list(preds[0])}")
        return None

    # The platform emits float timestamps ("1530962520.0"); the sidecar carries
    # integer seconds. Join on the numeric value.
    as_ts = lambda v: int(float(v))
    index_of = {as_ts(r["timestamp"]): i for i, r in enumerate(truth)}
    labels = [r["label"] for r in truth]

    tp = fp = fn = tn = invalid = unmatched = 0
    normal_windows = false_alarms = 0
    fired: list[tuple[int, int]] = []

    for row in preds:
        if inv_col and str(row.get(inv_col, "")).strip().lower() in ("true", "1"):
            invalid += 1
            continue
        end = index_of.get(as_ts(row[ts_col]))
        # A window that starts before the slice (an output scored on a narrower
        # cut than it ran on) has rows the labels can't see: not scored.
        if end is None or end < window_size - 1:
            unmatched += 1
            continue
        lo = end - window_size + 1
        span = labels[lo:end + 1]
        n_fault = sum(1 for s in span if s == FAULT)
        is_fault_truth = n_fault * 2 >= len(span)
        is_fault_pred = row[pred_col].strip() == FAULT

        if is_fault_truth and is_fault_pred:
            tp += 1
        elif is_fault_truth:
            fn += 1
        elif is_fault_pred:
            fp += 1
        else:
            tn += 1
        if n_fault == 0:
            normal_windows += 1
            false_alarms += is_fault_pred
        if is_fault_pred:
            fired.append((lo, end + 1))

    scored = tp + fp + fn + tn
    if not scored:
        print(f"  {output_path}: nothing scored ({invalid} invalid, {unmatched} unmatched)")
        return None

    # Contiguous ground-truth episodes in this slice.
    episodes, start = [], None
    for i, lab in enumerate(labels):
        if lab == FAULT and start is None:
            start = i
        elif lab != FAULT and start is not None:
            episodes.append((start, i)); start = None
    if start is not None:
        episodes.append((start, len(labels)))

    detections = []
    for a, b in episodes:
        hits = [w for w in fired if w[0] < b and a < w[1]]
        detections.append({"rows": [a, b], "length": b - a, "detected": bool(hits),
                           "n_windows": len(hits),
                           "latency": (min(w[1] for w in hits) - 1 - a) if hits else None})
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "scored": scored,
            "invalid": invalid, "unmatched": unmatched,
            "false_alarms": false_alarms, "normal_windows": normal_windows,
            "detections": detections}


def report(name: str, m: dict) -> None:
    p, r, f = prf(m["tp"], m["fp"], m["fn"])
    _, _, nf = prf(m["tn"], m["fn"], m["fp"])
    print(f"\n══ {name}  ({m['scored']:,} scored, {m['invalid']} invalid, "
          f"{m['unmatched']} unmatched)")
    print(f"   accuracy {(m['tp'] + m['tn']) / m['scored']:.4f}   "
          f"macro-F1 {(f + nf) / 2:.4f}")
    print(f"   {FAULT:<15} P {p:.4f}  R {r:.4f}  F1 {f:.4f}  (n={m['tp'] + m['fn']})")
    print(f"   confusion       tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']}")
    if m["normal_windows"]:
        print(f"   false alarms    {m['false_alarms']}/{m['normal_windows']} "
              f"= {m['false_alarms'] / m['normal_windows']:.4f} "
              f"(windows with zero fault rows)")
    for d in m["detections"]:
        if d["detected"]:
            print(f"   incident rows {d['rows'][0]}-{d['rows'][1]} (len {d['length']}): "
                  f"DETECTED by {d['n_windows']} window(s), "
                  f"+{d['latency']} samples after onset")
        else:
            print(f"   incident rows {d['rows'][0]}-{d['rows'][1]} (len {d['length']}): "
                  f"MISSED")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--platform-output", action="extend", nargs="+", required=True,
                    help="downloaded output CSV(s). Repeat the flag, pass several "
                         "paths after one flag, or use a shell glob.")
    ap.add_argument("--slices", default=None,
                    help="comma-separated slice names in the same order as the "
                         "outputs (e.g. inc04,inc05). Inferred from filenames "
                         "when omitted.")
    ap.add_argument("--window-size", type=int, default=64,
                    help="the window the classifier was fit with — needed to "
                         "reconstruct which rows each output window spans")
    ap.add_argument("--labels", metavar="DIR",
                    help="score against <DIR>/<slice>_labels.csv, e.g. "
                         "data/roles/labels (default: the data/prepared sidecars)")
    ap.add_argument("--json", metavar="PATH", help="also write results as JSON")
    args = ap.parse_args()

    outputs = args.platform_output
    if args.slices:
        names = [s.strip() for s in args.slices.split(",")]
        if len(names) != len(outputs):
            raise SystemExit(f"--slices has {len(names)} names but "
                             f"{len(outputs)} outputs were given")
    else:
        names = []
        for o in outputs:
            m = re.search(r"(inc\d+|quick_test)", os.path.basename(o))
            if not m:
                raise SystemExit(f"cannot infer the slice from {o!r} — pass --slices")
            names.append(m.group(1))

    results, pooled = {}, {"tp": 0, "fp": 0, "fn": 0, "tn": 0,
                           "false_alarms": 0, "normal_windows": 0}
    for name, out in zip(names, outputs):
        if args.labels:
            labels = Path(args.labels) / f"{name}_labels.csv"
        else:
            stem = "pump_quick_test" if name == "quick_test" else f"pump_eval_{name}"
            labels = PREPARED / f"{stem}_labels.csv"
        if not labels.exists():
            raise SystemExit(f"no label sidecar at {labels}")
        m = score_slice(out, labels, args.window_size)
        if not m:
            continue
        results[name] = m
        report(name, m)
        for k in pooled:
            pooled[k] += m[k]

    if len(results) > 1:
        p, r, f = prf(pooled["tp"], pooled["fp"], pooled["fn"])
        total = pooled["tp"] + pooled["fp"] + pooled["fn"] + pooled["tn"]
        det = [d for m in results.values() for d in m["detections"]]
        caught = [d for d in det if d["detected"]]
        print("\n" + "═" * 64)
        print(f"POOLED over {len(results)} slices ({total:,} windows)")
        print(f"   accuracy {(pooled['tp'] + pooled['tn']) / total:.4f}   "
              f"{FAULT} P {p:.4f} R {r:.4f} F1 {f:.4f}")
        print(f"   false alarms {pooled['false_alarms']}/{pooled['normal_windows']} "
              f"= {pooled['false_alarms'] / max(1, pooled['normal_windows']):.4f}")
        print(f"   incidents detected: {len(caught)}/{len(det)}")
        for d in sorted(det, key=lambda x: x["length"]):
            state = (f"+{d['latency']} samples" if d["detected"] else "MISSED")
            print(f"     {d['length']:>5} rows -> {state}")
        if caught:
            print("   recall tracks incident duration — the shortest events are "
                  "the ones that get missed.")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
