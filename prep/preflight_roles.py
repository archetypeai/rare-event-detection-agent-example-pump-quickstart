"""Check data/roles/ against the rules Optimize, Evals and delivery depend on.

    python3 prep/preflight_roles.py [--windows 16,32,64]

PASS / FAIL per rule; exits 1 on any FAIL.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
ROLES = REPO / "data" / "roles"
PREPARED = REPO / "data" / "prepared"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--roles", default=str(ROLES))
    ap.add_argument("--windows", default="16,32,64", help="window sizes the search may use")
    args = ap.parse_args(argv)
    roles = Path(args.roles)
    m = json.loads((roles / "manifest.json").read_text())
    windows = [int(w) for w in args.windows.split(",")]
    classes, channels = m["classes"], m["channels"]
    fails = 0

    def check(ok, rule, detail=""):
        nonlocal fails
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {rule}{'  ' + detail if detail else ''}")

    files = {r: m[r] for r in ("training", "validation", "test", "delivery")}
    data = {f["file"]: pd.read_csv(roles / f["file"]) for fs in files.values() for f in fs}

    # Every file: the same columns, a 60 s grid, no gaps or NaN.
    bad = [k for k, d in data.items() if [c for c in d.columns if c not in ("timestamp", "label")] != channels]
    check(not bad, "same channels, same order, in every file", ", ".join(bad))
    bad = [k for k, d in data.items() if not (np.diff(d.timestamp.to_numpy()) == 60).all()]
    check(not bad, "timestamps on an exact 60 s grid, no jump inside a file", ", ".join(bad))
    bad = [k for k, d in data.items() if d[channels].isna().any().any()]
    check(not bad, "no missing values", ", ".join(bad))

    # Rows: each file's rows match its manifest range, and no row is in two files
    # (validation and test are scored; delivery repeats test by design).
    bad = [k for fs in files.values() for f in fs for k in [f["file"]] if len(data[k]) != f["n_rows"]]
    check(not bad, "row counts match the manifest", ", ".join(bad))
    spans = sorted((f["rows"][0], f["rows"][1], f["file"])
                   for r in ("training", "validation", "test") for f in files[r])
    spans.sort()
    clash = [f"{a[2]} / {b[2]}" for a, b in zip(spans, spans[1:]) if b[0] < a[1]]
    check(not clash, "no row in two of training, validation and test", "; ".join(clash))
    tests = {t["incident"]: t for t in files["test"]}
    inside = all(d.get("incident") in tests and tests[d["incident"]]["rows"][0] <= d["rows"][0]
                 and d["rows"][1] <= tests[d["incident"]]["rows"][1] for d in files["delivery"])
    check(inside, "each delivery slice lies inside its incident's test slice")

    # Labels: scored roles carry them, training and delivery don't.
    bad = [f["file"] for r in ("training", "delivery") for f in files[r] if "label" in data[f["file"]]]
    check(not bad, "no label column in training or delivery files", ", ".join(bad))
    bad = [f["file"] for r in ("validation", "test") for f in files[r]
           if "label" not in data[f["file"]] or set(data[f["file"]].label) != set(classes)]
    check(not bad, f"validation and test files have a label column with both classes {classes}", ", ".join(bad))
    bad = []
    for f in files["training"]:
        if f["class"] not in classes or f["fault_rows"] != (f["n_rows"] if f["class"] != m["background"] else 0):
            bad.append(f["file"])
    check(not bad, "each training file is pure: one class, in the class list", ", ".join(bad))
    check({f["class"] for f in files["training"]} == set(classes), "training covers every class")

    bad = []
    for f in files["delivery"]:
        lab = pd.read_csv(roles / f["labels"])
        if len(lab) != f["n_rows"] or not (lab.timestamp.to_numpy() == data[f["file"]].timestamp.to_numpy()).all():
            bad.append(f["labels"])
    check(not bad, "delivery label files line up row for row", ", ".join(bad))
    for d in files["delivery"]:
        t = tests[d["incident"]]
        lab = pd.read_csv(roles / d["labels"]).label.to_numpy()
        off = d["rows"][0] - t["rows"][0]
        if not (lab == data[t["file"]].label.to_numpy()[off:off + len(lab)]).all():
            check(False, f"delivery labels equal the test labels on the same rows ({d['file']})")
            break
    else:
        check(True, "delivery labels equal the test labels on the same rows")

    # Window sizes: every scored incident can reach a fault majority, and every
    # training file yields windows.
    short = [f"inc{f['incident']:02d} ({f['incident_rows'][1] - f['incident_rows'][0]} rows) at w={w}"
             for r in ("validation", "test") for f in files[r] for w in windows
             if 2 * (f["incident_rows"][1] - f["incident_rows"][0]) < w]
    check(not short, f"every scored incident can reach a fault majority at w={args.windows}", "; ".join(short))
    short = [f"{f['file']} at w={w}" for f in files["training"] for w in windows if f["n_rows"] < w]
    check(not short, "every training file is at least one window long", "; ".join(short))

    # Same transform as Stage 2: where a role file and a prepared file cover the
    # same raw rows, the values match.
    cuts = json.loads((PREPARED / "prep_report.json").read_text())["cuts"]
    worst = 0.0
    for name, c in cuts.items():
        p = PREPARED / name
        if not p.exists():
            continue
        prep = pd.read_csv(p)
        lo, hi = c["rows"]
        for fs in files.values():
            for f in fs:
                a, b = max(lo, f["rows"][0]), min(hi, f["rows"][1])
                if a < b:
                    x = data[f["file"]].iloc[a - f["rows"][0]:b - f["rows"][0]][channels].to_numpy()
                    y = prep.iloc[a - lo:b - lo][channels].to_numpy()
                    worst = max(worst, float(np.abs(x - y).max()))
    check(worst <= 1e-6, "values match data/prepared/ wherever both cover a row", f"max |diff| {worst:.1e}")

    print(f"\n{'all checks pass' if not fails else f'{fails} FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
