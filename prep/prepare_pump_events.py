#!/usr/bin/env python3
"""Stage 2 — prepare the pump rare-event datasets for the RED agent.

Input: the raw Kaggle pump-sensor file (`sensor.csv`, 220,320 rows, 52 sensor
channels, 1-minute cadence, `machine_status` in {NORMAL, BROKEN, RECOVERING}).

Output (data/prepared/):
  pump_nshot_normal.csv                  normal-operation reference rows
  pump_nshot_pump_breakdown_inc01.csv    fault shots, incident #1
  pump_nshot_pump_breakdown_inc02.csv    fault shots, incident #2
  pump_eval_inc{03..07}.csv              one held-out incident each, with
  pump_eval_inc{03..07}_labels.csv       a row-aligned ground-truth sidecar
  pump_quick_test.csv                    small slice for smoke-testing the platform
  pump_zscore_stats.json                 normalization stats — part of the model
  prep_report.json                       every decision this script made

The RED contract (see docs/): one named rare-event class (`pump_breakdown`)
plus normal. Shots come from the first two incidents only; incidents #3-#7 are
held out and touched only at evaluation.

Usage:
  python3 prep/prepare_pump_events.py                 # write everything
  python3 prep/prepare_pump_events.py --survey-only   # report, write nothing
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
PREPARED = REPO / "data" / "prepared"

# Candidate locations for the raw Kaggle file, in preference order.
RAW_CANDIDATES = [
    REPO / "data" / "raw" / "sensor.csv",
    Path.home() / "Documents/archetypeai-batch-examples-pump-sensor/data/sensor.csv",
    Path.home() / "Downloads/sensor.csv",
]

NORMAL = "normal"
FAULT = "pump_breakdown"

# --- Prep parameters -------------------------------------------------------
# Channels whose NaN fraction exceeds this are dropped. The threshold sits at
# 1% because that is the gap in the data: the 8 channels above it are at
# 2.1-100%, the next one down is at 0.17%. Those 8 are also exactly the
# channels whose dropout coincides with the fault episodes (see the leakage
# audit below), so this one rule removes the leak without hand-picking.
MAX_NAN_FRACTION = 0.01
# Longest NaN run we are willing to interpolate. Matches the `red` blueprint's
# default `window_interpolation_max_gap`, so anything this script hands over is
# inside what the platform would repair itself.
MAX_INTERP_RUN = 16
# Number of fault-separating channels to keep. Omega emits 768 dims per variate
# and concatenates, so 10 channels is a 7,680-dim embedding.
N_CHANNELS = 10
# Channels that read a saturated zero while the pump is down. Unlike the NaN
# dropouts these are real measurements — a stopped pump genuinely reads zero
# flow — so they stay in the default channel set. They do make the task much
# easier, though, so `--hard-mode` drops them to show what the encoder can do
# from the subtler channels alone. Populated by the zero-saturation audit.
ZERO_SATURATION_FAULT_SHARE = 0.20  # >=20% of fault rows exactly zero
ZERO_SATURATION_NORMAL_SHARE = 0.02  # and <2% of normal rows
# Chronological build/eval split. Shot incidents #1-#2 end at row 27,621; the
# first held-out incident starts at row 69,318. Everything at or after
# EVAL_FLOOR is off-limits when choosing channels or normalization stats.
BUILD_CEILING = 30_000
EVAL_FLOOR = 60_000
# Rows of normal lead-in/lead-out context around each held-out incident.
EVAL_CONTEXT = 4_096
# Normal reference rows to cut for the normal prototype.
N_NORMAL_SHOT = 8_192


def find_raw(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise SystemExit(f"raw file not found: {p}")
        return p
    for p in RAW_CANDIDATES:
        if p.exists():
            return p
    raise SystemExit(
        "raw sensor.csv not found. Download the Kaggle pump-sensor dataset to\n"
        "  data/raw/sensor.csv\n"
        "https://www.kaggle.com/datasets/nphantawee/pump-sensor-data")


def nan_runs(mask: np.ndarray, min_len: int = 1) -> list[tuple[int, int]]:
    """Half-open [start, end) runs of True in `mask`, at least min_len long."""
    runs, start = [], None
    for i, flag in enumerate(mask):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_len:
                runs.append((start, i))
            start = None
    if start is not None and len(mask) - start >= min_len:
        runs.append((start, len(mask)))
    return runs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", help="path to the raw Kaggle sensor.csv")
    ap.add_argument("--survey-only", action="store_true",
                    help="print the survey and the decisions, write no files")
    ap.add_argument("--n-channels", type=int, default=N_CHANNELS)
    ap.add_argument("--hard-mode", action="store_true",
                    help="also exclude the zero-saturating channels, so the "
                         "agent cannot key on 'the pump has stopped'")
    ap.add_argument("--suffix", default="",
                    help="suffix for the written filenames, e.g. _hard")
    args = ap.parse_args()

    raw_path = find_raw(args.raw)
    print(f"── reading {raw_path}")
    df = pd.read_csv(raw_path)
    sensors = [c for c in df.columns if c.startswith("sensor_")]
    ts = pd.to_datetime(df["timestamp"])
    print(f"   {len(df):,} rows x {len(sensors)} sensor channels")

    # --- 1. Cadence -------------------------------------------------------
    dt = ts.diff().dt.total_seconds()
    gaps = int((dt.dropna() != 60.0).sum())
    print(f"── cadence: {dt.mode().iloc[0]:.0f}s, {gaps} irregular intervals, "
          f"monotonic={bool(ts.is_monotonic_increasing)}")
    if gaps or not ts.is_monotonic_increasing:
        print("   ! the `red` blueprint validates monotonic timestamps and "
              "sample-rate regularity; irregular input will be marked invalid")

    # --- 2. Labels and incidents -----------------------------------------
    status = df["machine_status"].to_numpy()
    fault_mask = status != "NORMAL"
    incidents = nan_runs(fault_mask)
    print(f"── labels: {int((~fault_mask).sum()):,} {NORMAL}, "
          f"{int(fault_mask.sum()):,} {FAULT} "
          f"({100 * fault_mask.mean():.2f}%) in {len(incidents)} incidents")
    for i, (a, b) in enumerate(incidents, 1):
        broken = int((status[a:b] == "BROKEN").sum())
        print(f"   #{i}: rows {a:,}-{b:,} len={b - a:,} BROKEN={broken} "
              f"start={ts.iloc[a]}")

    shot_incidents, eval_incidents = incidents[:2], incidents[2:]

    # --- 3. Channel triage: the dropout-leakage audit ---------------------
    # A channel that goes dark exactly when the pump faults is a perfect
    # predictor of the label and no predictor of pump physics. Interpolating
    # such a run turns "sensor offline" into the fault signature, so these
    # channels are excluded and the evidence is recorded.
    print(f"── channel triage")
    fault_rows = int(fault_mask.sum())
    audit, dropped_leak = {}, []
    for c in sensors:
        isna = df[c].isna().to_numpy()
        frac = float(isna.mean())
        if frac <= MAX_NAN_FRACTION:
            continue
        long_na = nan_runs(isna, min_len=64)
        na_in_fault = int((isna & fault_mask).sum())
        total_na = int(isna.sum())
        audit[c] = {
            "nan_fraction": round(frac, 4),
            "nan_rows": total_na,
            "nan_rows_inside_incidents": na_in_fault,
            "share_of_nans_inside_incidents": round(na_in_fault / total_na, 4),
            "share_of_incident_rows_nan": round(na_in_fault / fault_rows, 4),
            "long_runs": [[int(a), int(b)] for a, b in long_na],
        }
        dropped_leak.append(c)
    print(f"   dropped, NaN fraction > {MAX_NAN_FRACTION:.0%} ({len(dropped_leak)}): "
          f"{', '.join(dropped_leak)}")
    for c in dropped_leak:
        a = audit[c]
        # Fault-tracking means both: the channel is dark for much of the fault
        # AND essentially all of its darkness is inside a fault. A channel that
        # is simply dead everywhere (sensor_15) fails the second test.
        if a["share_of_incident_rows_nan"] > 0.1 and a["share_of_nans_inside_incidents"] > 0.5:
            print(f"     {c}: NaN over {a['share_of_incident_rows_nan']:.0%} of "
                  f"incident rows; {a['share_of_nans_inside_incidents']:.0%} of "
                  f"its NaNs are inside an incident  <- dropout tracks the fault")

    survivors = [c for c in sensors if c not in dropped_leak]
    dropped_gap = []
    for c in survivors:
        runs = nan_runs(df[c].isna().to_numpy(), min_len=MAX_INTERP_RUN + 1)
        if runs:
            dropped_gap.append(c)
            audit.setdefault(c, {})["long_runs"] = [[int(a), int(b)] for a, b in runs]
    clean = [c for c in survivors if c not in dropped_gap]
    print(f"   dropped, NaN run > {MAX_INTERP_RUN} ({len(dropped_gap)}): "
          f"{', '.join(dropped_gap)}")
    print(f"   {len(clean)} channels are fully interpolatable within "
          f"{MAX_INTERP_RUN} samples")

    # A second, different leak lives in the surviving channels: some read a
    # saturated zero while the pump is down. That is a real measurement, not a
    # prep artifact, so these channels are kept by default — but they make the
    # task close to trivial, so the audit is recorded and --hard-mode drops
    # them. (The sibling batch-examples repo sees the same channels as a
    # `constant_columns` preflight WARN.)
    n_fault, n_norm = int(fault_mask.sum()), int((~fault_mask).sum())
    zero_sat = {}
    for c in clean:
        v = df[c].to_numpy()
        f_share = float((v[fault_mask] == 0).sum() / n_fault)
        n_share = float((v[~fault_mask] == 0).sum() / n_norm)
        if f_share >= ZERO_SATURATION_FAULT_SHARE and n_share < ZERO_SATURATION_NORMAL_SHARE:
            zero_sat[c] = {"zero_share_fault": round(f_share, 4),
                           "zero_share_normal": round(n_share, 4)}
    if zero_sat:
        print(f"   zero-saturation audit — real measurements of a stopped pump, "
              f"kept unless --hard-mode:")
        for c, a in sorted(zero_sat.items(), key=lambda kv: -kv[1]["zero_share_fault"]):
            print(f"     {c}: exactly 0 in {a['zero_share_fault']:.1%} of fault rows "
                  f"vs {a['zero_share_normal']:.2%} of normal rows")
    if args.hard_mode:
        clean = [c for c in clean if c not in zero_sat]
        print(f"   --hard-mode: excluded {len(zero_sat)} zero-saturating "
              f"channels, {len(clean)} remain")

    # --- 4. Interpolate, then select channels on build-visible data only ---
    X = df[clean].interpolate(limit_direction="both")

    build_fault = np.zeros(len(df), bool)
    for a, b in shot_incidents:
        build_fault[a:b] = True
    build_normal = np.zeros(len(df), bool)
    build_normal[:BUILD_CEILING] = True
    build_normal &= ~fault_mask

    separation = {}
    for c in clean:
        mu = X.loc[build_normal, c].mean()
        sd = X.loc[build_normal, c].std() or 1.0
        separation[c] = float(np.abs((X.loc[build_fault, c] - mu) / sd).mean())
    channels = sorted(sorted(separation, key=separation.get, reverse=True)[:args.n_channels])
    print(f"── channel selection (top {args.n_channels} by mean |z| of shot-incident "
          f"rows vs build-region normal; held-out incidents never consulted)")
    for c in sorted(channels, key=separation.get, reverse=True):
        print(f"   {c}: {separation[c]:.2f}")

    # --- 5. Normalization stats -------------------------------------------
    # Z-scored per variate, as the algorithm assumes. Stats come from
    # build-region normal rows only — what a real deployment has at build time.
    stats = {c: {"mean": float(X.loc[build_normal, c].mean()),
                 "std": float(X.loc[build_normal, c].std() or 1.0)}
             for c in channels}
    Z = X[channels].copy()
    for c in channels:
        Z[c] = (Z[c] - stats[c]["mean"]) / stats[c]["std"]

    # Unix seconds. Do NOT use `astype("int64") // 10**9`: pandas 2.x may parse
    # to microsecond resolution, in which case that divides by 1000x too much
    # and collapses a 1-minute cadence below integer resolution — every
    # timestamp becomes equal, and the platform (rightly) marks every window
    # INVALID_STATE for non-monotonic timestamps. Casting the unit is exact
    # whatever resolution pandas chose.
    unix = ts.astype("datetime64[s]").astype("int64")
    labels = np.where(fault_mask, FAULT, NORMAL)

    def frame(lo: int, hi: int) -> pd.DataFrame:
        out = Z.iloc[lo:hi].copy()
        out.insert(0, "timestamp", unix.iloc[lo:hi].to_numpy())
        return out

    def write(frame_: pd.DataFrame, name: str) -> None:
        out_name = name.replace(".csv", f"{args.suffix}.csv")
        frame_.to_csv(PREPARED / out_name, index=False, float_format="%.6f")
        print(f"   {out_name}: {len(frame_):,} rows")

    # --- 6. Cuts ----------------------------------------------------------
    cuts: dict[str, dict] = {}
    print("── cuts")
    if not args.survey_only:
        PREPARED.mkdir(parents=True, exist_ok=True)

    # Fault shots: pure fault rows, one file per incident. Filenames carry the
    # class label — that is how the platform's fitting runner assigns labels,
    # so these files must contain no normal rows.
    for i, (a, b) in enumerate(shot_incidents, 1):
        name = f"pump_nshot_{FAULT}_inc{i:02d}.csv"
        cuts[name] = {"rows": [int(a), int(b)], "n_rows": int(b - a),
                      "label": FAULT, "incident": i}
        if not args.survey_only:
            write(frame(a, b), name)
        else:
            print(f"   {name}: {b - a:,} rows")

    # Normal shots: the longest clean contiguous normal run in the build region.
    normal_runs = [(a, b) for a, b in nan_runs(~fault_mask) if b <= BUILD_CEILING]
    a, b = max(normal_runs, key=lambda r: r[1] - r[0])
    n_lo = a
    n_hi = min(b, a + N_NORMAL_SHOT)
    cuts["pump_nshot_normal.csv"] = {"rows": [int(n_lo), int(n_hi)],
                                     "n_rows": int(n_hi - n_lo), "label": NORMAL}
    if not args.survey_only:
        write(frame(n_lo, n_hi), "pump_nshot_normal.csv")
    else:
        print(f"   pump_nshot_normal.csv: {n_hi - n_lo:,} rows")

    # Held-out eval slices: one incident each, with normal context either side,
    # plus a row-aligned label sidecar.
    for i, (a, b) in enumerate(eval_incidents, start=len(shot_incidents) + 1):
        lo = max(EVAL_FLOOR, a - EVAL_CONTEXT)
        hi = min(len(df), b + EVAL_CONTEXT)
        name = f"pump_eval_inc{i:02d}.csv"
        cuts[name] = {"rows": [int(lo), int(hi)], "n_rows": int(hi - lo),
                      "incident": i, "incident_rows": [int(a), int(b)],
                      "incident_len": int(b - a),
                      "fault_rows": int(fault_mask[lo:hi].sum())}
        if not args.survey_only:
            write(frame(lo, hi), name)
            side = pd.DataFrame({"timestamp": unix.iloc[lo:hi].to_numpy(),
                                 "label": labels[lo:hi]})
            write(side, name.replace(".csv", "_labels.csv"))
        else:
            print(f"   {name}: {hi - lo:,} rows "
                  f"({int(fault_mask[lo:hi].sum()):,} fault)")

    # A small slice for smoke-testing the platform cheaply: the shortest
    # held-out incident with tight context.
    a, b = min(eval_incidents, key=lambda r: r[1] - r[0])
    q_lo, q_hi = max(EVAL_FLOOR, a - 1_024), min(len(df), b + 1_024)
    cuts["pump_quick_test.csv"] = {"rows": [int(q_lo), int(q_hi)],
                                   "n_rows": int(q_hi - q_lo),
                                   "fault_rows": int(fault_mask[q_lo:q_hi].sum())}
    if not args.survey_only:
        write(frame(q_lo, q_hi), "pump_quick_test.csv")
        write(pd.DataFrame({"timestamp": unix.iloc[q_lo:q_hi].to_numpy(),
                            "label": labels[q_lo:q_hi]}),
              "pump_quick_test_labels.csv")
    else:
        print(f"   pump_quick_test.csv: {q_hi - q_lo:,} rows")

    # --- 7. Window-size feasibility --------------------------------------
    # A window is labelled by the design doc's majority rule, so an incident
    # shorter than half a window can never be labelled as the fault. This is
    # what bounds the usable window size from above.
    print("── window-size feasibility (design-doc majority labelling)")
    feasibility = {}
    for w in (16, 32, 64, 128, 256, 512, 1024):
        detectable = [i for i, (a, b) in enumerate(incidents, 1) if (b - a) * 2 >= w]
        # step 1, matching the stride every script here defaults to.
        shot_windows = sum(max(0, b - a - w + 1) for a, b in shot_incidents)
        feasibility[w] = {"detectable_incidents": detectable,
                          "shot_windows_at_step_1": int(shot_windows)}
        print(f"   w={w:<5} incidents that can reach a fault majority: "
              f"{detectable}  | pure-fault shot windows at step 1: {shot_windows:,}")

    # Record the raw file repo-relative when it lives inside the repo, so the
    # committed report does not carry one developer's absolute paths.
    try:
        raw_recorded = str(raw_path.relative_to(REPO))
    except ValueError:
        raw_recorded = str(raw_path)

    report = {
        "raw_file": raw_recorded,
        "raw_rows": int(len(df)),
        "cadence_seconds": 60,
        "irregular_intervals": gaps,
        "timestamps_monotonic": bool(ts.is_monotonic_increasing),
        "classes": [NORMAL, FAULT],
        "incidents": [{"index": i, "rows": [int(a), int(b)], "n_rows": int(b - a),
                       "start": str(ts.iloc[a])}
                      for i, (a, b) in enumerate(incidents, 1)],
        "shot_incidents": [1, 2],
        # Incident #3 ranks the grid search; #4 onward are never looked at
        # until the final evaluation.
        "optimization_incident": 3,
        "held_out_incidents": list(range(4, len(incidents) + 1)),
        "channel_triage": {
            "max_nan_fraction": MAX_NAN_FRACTION,
            "max_interp_run": MAX_INTERP_RUN,
            "dropped_high_nan": dropped_leak,
            "dropped_long_nan_run": dropped_gap,
            "clean_channels": len(clean),
            "nan_dropout_audit": audit,
            "zero_saturation_audit": zero_sat,
            "hard_mode": bool(args.hard_mode),
        },
        "channels": channels,
        "channel_separation": {c: round(separation[c], 4) for c in clean},
        "zscore_stats_source": f"normal rows in [0, {BUILD_CEILING})",
        "cuts": cuts,
        "window_feasibility": feasibility,
    }

    if args.survey_only:
        print("\n(survey only — no files written)")
        return

    (PREPARED / "pump_zscore_stats.json").write_text(json.dumps(stats, indent=2))
    (PREPARED / "prep_report.json").write_text(json.dumps(report, indent=2))
    print(f"── wrote pump_zscore_stats.json and prep_report.json to {PREPARED}")


if __name__ == "__main__":
    main()
