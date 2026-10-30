"""Build the role files for the Optimizations and Evals APIs from the raw recording.

    python3 prep/build_roles.py

Reads data/raw/sensor.csv with the channels and z-score stats Stage 2 chose
(data/prepared/prep_report.json, pump_zscore_stats.json), so every role file is
transformed exactly as the prepared files are, and writes data/roles/:

    training/    normal.csv, pump_breakdown_inc01.csv, pump_breakdown_inc02.csv
                 one class per file, no label column (the class rides in the request)
    validation/  inc03.csv                  label column
    test/        inc04.csv ... inc07.csv    label column
    delivery/    inc04.csv, inc07.csv          no label column; short slices
    labels/      <delivery file>_labels.csv (timestamp, label), for offline scoring
    manifest.json

Slices keep EVAL_CONTEXT normal rows either side of their incident, cut at the
midpoint where two incidents are closer than that, so no row is in two of
training, validation and test. Delivery re-runs two test incidents, #4 (606 rows)
and #7 (76 rows), with DELIVERY_CONTEXT rows either side: inside their test
slices, so ~4,650 windows instead of the test's ~37,600.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "raw" / "sensor.csv"
PREPARED = REPO / "data" / "prepared"
ROLES = REPO / "data" / "roles"

NORMAL, FAULT = "normal", "pump_breakdown"
EVAL_CONTEXT = 4_096
DELIVERY_CONTEXT = 1_024
VALIDATION, TEST, DELIVERY = [3], [4, 5, 6, 7], [4, 7]


def slice_bounds(incidents, n_rows):
    """Context either side of each incident, cut at the midpoint to a neighbour."""
    bounds = {}
    for i, (a, b) in enumerate(incidents):
        lo, hi = a - EVAL_CONTEXT, b + EVAL_CONTEXT
        if i > 0:
            lo = max(lo, (incidents[i - 1][1] + a) // 2)
        if i + 1 < len(incidents):
            hi = min(hi, (b + incidents[i + 1][0]) // 2)
        bounds[i + 1] = (max(lo, 0), min(hi, n_rows))
    return bounds


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--out", default=str(ROLES))
    args = ap.parse_args(argv)

    report = json.loads((PREPARED / "prep_report.json").read_text())
    stats = json.loads((PREPARED / "pump_zscore_stats.json").read_text())
    channels = report["channels"]

    df = pd.read_csv(args.raw)
    ts = pd.to_datetime(df["timestamp"])
    unix = ts.astype("datetime64[s]").astype("int64").to_numpy()
    labels = np.where(df["machine_status"].to_numpy() != "NORMAL", FAULT, NORMAL)
    # Linear interpolation is per column, so interpolating only the chosen
    # channels gives the same values as Stage 2's interpolation of all of them.
    Z = df[channels].interpolate(limit_direction="both")
    for c in channels:
        Z[c] = (Z[c] - stats[c]["mean"]) / stats[c]["std"]

    incidents = [tuple(i["rows"]) for i in report["incidents"]]
    bounds = slice_bounds(incidents, len(df))
    cuts = report["cuts"]

    out = Path(args.out)
    for sub in ("training", "validation", "test", "delivery", "labels"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    def write(rel, lo, hi, with_label):
        d = Z.iloc[lo:hi].copy()
        d.insert(0, "timestamp", unix[lo:hi])
        if with_label:
            d["label"] = labels[lo:hi]
        d.to_csv(out / rel, index=False, float_format="%.6f")
        return {"file": rel, "rows": [int(lo), int(hi)], "n_rows": int(hi - lo),
                "fault_rows": int((labels[lo:hi] == FAULT).sum())}

    def write_labels(entry):
        lo, hi = entry["rows"]
        rel = "labels/" + Path(entry["file"]).stem + "_labels.csv"
        pd.DataFrame({"timestamp": unix[lo:hi], "label": labels[lo:hi]}).to_csv(out / rel, index=False)
        entry["labels"] = rel

    manifest = {"contract": "red-role-files/v1", "classes": [NORMAL, FAULT], "background": NORMAL,
                "channels": channels, "source": "data/raw/sensor.csv",
                "training": [], "validation": [], "test": [], "delivery": []}

    for name, cls in (("pump_nshot_normal.csv", NORMAL),
                      ("pump_nshot_pump_breakdown_inc01.csv", FAULT),
                      ("pump_nshot_pump_breakdown_inc02.csv", FAULT)):
        lo, hi = cuts[name]["rows"]
        rel = "training/" + name.replace("pump_nshot_", "")
        manifest["training"].append({**write(rel, lo, hi, False), "class": cls,
                                     "incident": cuts[name].get("incident")})

    for role, which in (("validation", VALIDATION), ("test", TEST)):
        for i in which:
            lo, hi = bounds[i]
            manifest[role].append({**write(f"{role}/inc{i:02d}.csv", lo, hi, True), "incident": i,
                                   "incident_rows": list(incidents[i - 1])})

    for i in DELIVERY:
        a, b = incidents[i - 1]
        lo, hi = max(a - DELIVERY_CONTEXT, bounds[i][0]), min(b + DELIVERY_CONTEXT, bounds[i][1])
        e = {**write(f"delivery/inc{i:02d}.csv", lo, hi, False), "incident": i,
             "incident_rows": [a, b]}
        write_labels(e)
        manifest["delivery"].append(e)

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for role in ("training", "validation", "test", "delivery"):
        n = sum(f["n_rows"] for f in manifest[role])
        f_rows = sum(f["fault_rows"] for f in manifest[role])
        print(f"{role:<10} {len(manifest[role]):>2} files  {n:>7,} rows  {f_rows:>6,} fault")
    print(f"wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
