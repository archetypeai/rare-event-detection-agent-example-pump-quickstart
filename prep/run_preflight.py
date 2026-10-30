#!/usr/bin/env python3
"""Run omega-1-4-preflight's static checks — Stages 1 and 3.

`preflight_static.py` is vendored verbatim from
github.com/archetypeai/omega-1-4-preflight (checks/static.py).

Two modes, matching the two points a RED build wants validation:

  Stage 1, raw file      python3 prep/run_preflight.py --raw
      Checks the raw Kaggle recording *before* any processing, so the WARNs
      become prep-stage decisions rather than surprises after the fact.

  Stage 3, prepared sets python3 prep/run_preflight.py --window-size 64
      Checks the n-shot files prep produced. RED has exactly two classes, so
      the vendored pairwise checks (`check_schema_match`, `check_class_balance`,
      `check_window_vs_sampling`) apply directly as normal-vs-fault — no
      generalization needed, unlike OSM's six-state runner.

Exit code is 1 if anything FAILs.
"""
import argparse
import csv
import datetime as dt
import glob
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preflight_static import (  # noqa: E402
    FAIL, PASS, WARN,
    check_class_balance, check_constant_cols, check_feature_scale,
    check_missing, check_nshot_support, check_schema, check_schema_match,
    check_timestamp, check_window_size_range, check_window_vs_sampling,
    summarize_shot_file,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREPARED = os.path.join(REPO, "data", "prepared")
RAW = os.path.join(REPO, "data", "raw", "sensor.csv")
COLOR = {PASS: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", "reset": "\033[0m"}

NORMAL_SHOT = "pump_nshot_normal.csv"
FAULT_SHOTS = ["pump_nshot_pump_breakdown_inc01.csv",
               "pump_nshot_pump_breakdown_inc02.csv"]
GRID_WINDOWS = (16, 32, 64, 128, 256, 512, 1024)


def show(result, prefix=""):
    c = COLOR.get(result.level, "")
    print(f"  {c}{result.level:<4}{COLOR['reset']} {prefix}{result.name}: {result.message}")
    return result.level


def drop_columns(summary, columns):
    """Remove columns from every per-column view, so counts stay consistent.

    Dropping from `feature_cols` alone leaves the per-column dicts populated,
    and checks that iterate those (missing_values, constant_columns) then
    report totals covering columns we excluded.
    """
    drop = set(columns)
    summary.feature_cols = [c for c in summary.feature_cols if c not in drop]
    summary.non_numeric_cols = [c for c in summary.non_numeric_cols if c not in drop]
    for view in (summary.missing_per_col, summary.variance_per_col,
                 summary.min_per_col, summary.max_per_col):
        for c in list(view):
            if c in drop:
                del view[c]


def adapt_raw_summary(summary):
    """Make the raw Kaggle file legible to the vendored checks.

    Two properties of the raw file confuse checks that assume an already-shaped
    input. Both are fixed in the runner so `preflight_static.py` stays verbatim,
    and both are reported, because each one IS a prep-stage decision:

    1. The first column is an unnamed row index (0..220,319). Left in, it is
       counted as a sensor and — with a 2.2e5 range — becomes the column the
       feature-scale check complains about. Prep drops it.
    2. `timestamp` holds ISO-8601 strings, but the check does `float(...)` and
       marks the file non-monotonic when that raises. The design accepts
       ISO-8601 *and* Unix, so this is a limitation of the vendored tool, not a
       defect in the data. We recompute ordering by parsing the ISO values so
       the reported answer is the true one; prep emits Unix seconds.
    """
    notes = []

    index_cols = [c for c in summary.feature_cols if not c.strip()
                  or c.lower().startswith("unnamed")]
    if index_cols:
        drop_columns(summary, index_cols)
        notes.append(f"excluded unnamed row-index column(s) {index_cols} from the "
                     f"feature set — not sensors; prep drops them")

    if not summary.monotonic and summary.timestamp_deltas_median is None:
        stamps = []
        with open(summary.path, newline="") as f:
            for row in csv.DictReader(f):
                raw = (row.get(summary.timestamp_col) or "").strip()
                if not raw:
                    continue
                try:
                    stamps.append(dt.datetime.fromisoformat(raw))
                except ValueError:
                    stamps = []
                    break
        if len(stamps) > 1:
            deltas = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
            summary.monotonic = all(d > 0 for d in deltas)
            summary.timestamp_deltas_median = statistics.median(deltas)
            summary.timestamp_deltas_max = max(deltas)
            notes.append("timestamp is ISO-8601 text, which the vendored check "
                         "cannot float()-parse; re-checked by parsing ISO. "
                         "Prep converts to Unix seconds")
    return notes


def per_file_checks(summary, window_size, levels):
    for check in (check_schema, check_timestamp, check_missing,
                  check_constant_cols, check_feature_scale):
        levels.append(show(check(summary)))
    levels.append(show(check_nshot_support(summary, window_size)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true",
                    help="Stage 1: check the raw Kaggle file instead of the prepared sets")
    ap.add_argument("--window-size", type=int, default=64,
                    help="window the classifier will be fit with (n-shot support check)")
    ap.add_argument("--glob", default=None,
                    help="override which prepared files to check")
    args = ap.parse_args()

    levels = []

    if args.raw:
        if not os.path.exists(RAW):
            sys.exit(f"raw file not found at {RAW} — download it from Kaggle "
                     f"(see README: Data attribution)")
        print(f"== {os.path.relpath(RAW, REPO)} (raw, before any processing)")
        # The raw file carries machine_status, a non-numeric column the checks
        # would flag as a bad feature; it is the label, so exclude it.
        s = summarize_shot_file(RAW, timestamp_col="timestamp")
        # machine_status is the label, not a feature.
        drop_columns(s, ["machine_status"])
        for note in adapt_raw_summary(s):
            print(f"  note  {note}")
        per_file_checks(s, args.window_size, levels)
    else:
        pattern = args.glob or "pump_nshot_*.csv"
        files = sorted(f for f in glob.glob(os.path.join(PREPARED, pattern))
                       if not f.endswith("_labels.csv"))
        if not files:
            sys.exit("no matching files; run prep/prepare_pump_events.py first")

        summaries = {}
        for path in files:
            name = os.path.basename(path)
            print(f"\n== {name}")
            s = summarize_shot_file(path, timestamp_col="timestamp")
            summaries[name] = s
            per_file_checks(s, args.window_size, levels)

        print(f"\n== window size range (grid: {GRID_WINDOWS[0]}..{GRID_WINDOWS[-1]})")
        for w in GRID_WINDOWS:
            levels.append(show(check_window_size_range(w), prefix=f"w={w} "))

        # RED is two-class, so the pairwise checks map straight onto
        # normal vs each fault shot file.
        normal = summaries.get(NORMAL_SHOT)
        if normal:
            print("\n== pairwise checks (normal vs each fault shot file)")
            for fault_name in FAULT_SHOTS:
                fault = summaries.get(fault_name)
                if not fault:
                    continue
                tag = fault_name.replace("pump_nshot_pump_breakdown_", "").replace(".csv", "")
                for res in (check_schema_match(normal, fault),
                            check_class_balance(normal, fault),
                            check_window_vs_sampling(normal, fault,
                                                     args.window_size, "seconds")):
                    levels.append(show(res, prefix=f"normal vs {tag}: "))

    fails, warns = levels.count(FAIL), levels.count(WARN)
    print(f"\nsummary: {levels.count(PASS)} PASS, {warns} WARN, {fails} FAIL")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
