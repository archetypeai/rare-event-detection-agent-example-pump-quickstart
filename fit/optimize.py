#!/usr/bin/env python3
"""Fit and search on the platform with the Optimizations API.

    python3 fit/optimize.py                                   # the probe: window 64, step 1, four metrics
    python3 fit/optimize.py --new --window 16,32,64 --trials 12   # a grid: every combination
    python3 fit/optimize.py --new --window 16:84 --trials 24      # a random search over windows 16-84

Training is the three class files (normal, incidents #1 and #2), each labelled by
a constant; validation is incident #3 with the `label` column, each window
labelled by the majority of its rows. Both come from data/roles/
(prep/build_roles.py).

Each option takes one value (pinned in `overrides.values` for every trial),
several (searched), or for window and step LOW:HIGH (an inclusive integer
range). The platform draws distinct points at random: a list with no more
points than --trials runs every combination (a grid); a range, or a budget
smaller than the grid, is a random search. Dev seeds the draw from the OS, so
the points differ between runs; each optimization records the ones it drew. `metric` is the classifier's only fit knob; trials that share
`window_size` and `step_size` share one encoder pass, so searching the metric is
nearly free and each window or step adds a pass over every file.

Writes fit/out/optimize_state.json (resume) and fit/out/optimize_<id>.json.
"""
from __future__ import annotations

import argparse
import datetime
import json

from atai import (COLUMN, OUT, PRIMARY, ROLES, SEARCH, agents_base, aggregate, api_base, base_values,
                  constant, example, load_dotenv, load_state, log, manifest, request, save_state,
                  state_path, upload_all, wait)


def values(text: str, cast) -> list:
    return [cast(v) for v in text.split(",") if v]


def build_space(args) -> tuple[dict, dict]:
    """(search_space parameters, pinned values)."""
    space, pinned = {}, {}
    for name, text in (("window_size", args.window), ("step_size", args.step)):
        if ":" in text:
            lo, hi = (int(v) for v in text.split(":"))
            space[name] = {"kind": "value", "spec": {"type": "int_range", "min": lo, "max": hi}}
    for name, vals in (("metric", values(args.metric, str)),
                       ("window_size", values(args.window, int) if ":" not in args.window else []),
                       ("step_size", values(args.step, int) if ":" not in args.step else [])):
        if not vals:
            continue
        if len(vals) > 1 or name == "metric":  # the search space can't be empty
            space[name] = {"kind": "value", "spec": {"type": "categorical", "values": vals}}
        else:
            pinned[name] = vals[0]
    return space, pinned


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    d = SEARCH
    ap.add_argument("--window", default=d["window_size"], help="window_size: comma-separated, or LOW:HIGH")
    ap.add_argument("--step", default=d["step_size"], help="step_size: comma-separated, or LOW:HIGH")
    ap.add_argument("--metric", default=d["metric"], help="cosine,l1,l2,dot")
    ap.add_argument("--primary", default=PRIMARY)
    ap.add_argument("--trials", type=int, default=d["trials"])
    ap.add_argument("--new", action="store_true",
                    help="add another optimization; fit/test.py takes the best trial of all")
    args = ap.parse_args()
    load_dotenv()

    STATE = state_path("optimize")
    state = load_state(STATE)
    if args.new or not state.get("runs"):
        m = manifest()
        train = [(ROLES / f["file"], f["class"]) for f in m["training"]]
        val = [ROLES / f["file"] for f in m["validation"]]
        ids = upload_all([p for p, _ in train] + val)
        space, pinned = build_space(args)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bp = request("GET", f"{agents_base()}/blueprints/red")
        body = {"name": f"red-pump {stamp}", "blueprint_id": bp["id"], "primary": args.primary,
                "overrides": {"values": {**base_values(m), **pinned}},
                "search_space": {"parameters": space}, "budget": {"max_trials": args.trials},
                "training_examples": [example(p.stem, ids[p], constant(c)) for p, c in train],
                "validation_examples": [example(p.stem, ids[p], COLUMN) for p in val]}
        opt = request("POST", f"{agents_base()}/optimizations", body=body)
        state["endpoint"] = api_base()
        state.setdefault("runs", []).append(
            {"optimization": opt["id"],
             "request": {k: v for k, v in body.items() if not k.endswith("_examples")}})
        save_state(STATE, state)
        log(f"optimization {opt['id']}: {args.trials} trial(s), searching {sorted(space)}")

    ok = True
    for run in state["runs"]:
        opt = wait("optimizations", run["optimization"])
        trials = request("GET", f"{agents_base()}/optimizations/{opt['id']}/trials?limit=1000")["data"]
        (OUT / f"optimize_{opt['id']}.json").write_text(
            json.dumps({"optimization": opt, "trials": trials}, indent=1))
        print(f"\noptimization {opt['id']}: {opt['status']}  (pinned "
              f"{json.dumps({k: v for k, v in run['request']['overrides']['values'].items() if k in ('window_size', 'step_size')})})")
        for t in sorted(trials, key=lambda t: t.get("objective_value") or -1, reverse=True):
            a = aggregate(t["metrics_report"]) if t.get("metrics_report") else {}
            print(f"  {t['id']}  {t['status']:<9} {json.dumps(t['trial_values']['values'])}  "
                  + "  ".join(f"{k} {a[k]:.4f}" for k in ("foreground_macro_f1", "macro_f1",
                                                          "detection_recall", "detection_precision")
                              if k in a))
            if a:
                print(f"    confusion {a['class_names']} {a['confusion_matrix']}")
            if t["status"] != "completed":
                print(f"    {json.dumps({k: t.get(k) for k in ('error', 'failure_reason', 'message') if t.get(k)})}")
        ok = ok and opt["status"] == "completed"
    if ok:
        print("\nnext: python3 fit/test.py (promotes the best trial across these runs)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
