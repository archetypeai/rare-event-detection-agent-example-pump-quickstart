#!/usr/bin/env python3
"""Stage 9 prep: the embedding space for app-serving/, recomputed on the platform.

    python3 fit/library_embeddings.py              # the embeddings blueprint, 3 batch sessions, the view
    python3 fit/library_embeddings.py --step 1     # every training window in the view (12,059)

app/ builds its Embedding Space by re-encoding the training shots with a local
Omega checkpoint (fit/build_embedding_landscape.py). The platform path has no
local encoder and nothing to read back: the promoted classifier is a registry
artifact (`aar_...`) with no download route, and the Optimizations and Evals APIs
return metrics and predictions, not embeddings. So the training windows are
encoded again on the platform:

  1. an embeddings blueprint: a package runs a blueprint exactly as promoted and
     can't turn an output on, so a 1-trial optimization in the project at
     fit/test.py's trial's point (window, step 1, metric), with
     `output_embeddings: true` pinned, then promoted. The prototypes it refits are
     the class means of the same windows, so it answers as Stage 5's blueprint;
     app-serving/'s bridge serves it for the live point;
  2. a package of it, one batch deployment, and one session per training file
     (normal, breakdowns #1 and #2), in parallel. The step is the trial's, 1: every
     --step-th window (4 by default, a quarter of the 12,059 training windows: the
     same cloud) is kept, the same windows a step-4 run gives;
  3. the 10 x 768 embeddings of every window, in the manifest's channel order,
     and PCA 1-2 of them: the cloud, and the projection the app applies to each
     live window. The two class prototypes are the means of each class's
     windows, projected the same way (the classifier fits `strategy: centroid`,
     but its own vectors can't be read).

Writes app-serving/static/red-embedding-landscape.json (the format app/ reads)
and fit/out/library_embeddings/ (the outputs, regenerable). Ids go to
fit/out/library_state.json, so a rerun resumes and fit/cleanup.py can delete
the sessions, deployment and package afterwards (the embeddings blueprint stays,
for a rerun and for the app).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from atai import (COLUMN, OUT as FIT_OUT, PRIMARY, REPO, ROLES, agents_base, constant, example, load_dotenv,
                  load_state, log, manifest, request, save_state, state_path, upload_all, wait)
from red_api import create_package, deploy, download_results, open_session, poll_session, upload_file
from test import promote

CLASSES = ["normal", "pump_breakdown"]
VIEW = REPO / "app-serving" / "static" / "red-embedding-landscape.json"
DIR = FIT_OUT / "library_embeddings"


def embeddings_blueprint(m: dict, bp: dict, state: dict, save) -> dict:
    """{id, key} of a blueprint at fit/test.py's trial's point with output_embeddings on: a
    1-trial optimization in the project, then promoted. Resumable through `state`."""
    if state.get("embeddings_blueprint"):
        return state["embeddings_blueprint"]
    if not state.get("embeddings_optimization"):
        base = load_state(state_path("project"))["base"]
        train = [(ROLES / f["file"], f["class"]) for f in m["training"]]
        val = [ROLES / f["file"] for f in m["validation"]]
        ids = upload_all([p for p, _ in train] + val)
        values = {k: v for k, v in bp["values"].items() if k != "metric"}
        o = request("POST", f"{agents_base()}/optimizations", body={
            "name": f"red-pump embeddings {datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}",
            "blueprint_id": base["id"], "primary": PRIMARY, "budget": {"max_trials": 1},
            "overrides": {"values": {**values, "output_embeddings": True}},
            # the search space can't be empty: the metric, with the trial's one value
            "search_space": {"parameters": {"metric": {
                "kind": "value", "spec": {"type": "categorical", "values": [bp["values"]["metric"]]}}}},
            "training_examples": [example(p.stem, ids[p], constant(c)) for p, c in train],
            "validation_examples": [example(p.stem, ids[p], COLUMN) for p in val]})
        state.update(embeddings_optimization=o["id"], blueprint=bp["key"])
        save()
        log(f"optimization {o['id']}: 1 trial at {bp['trial']}'s point "
            f"(w {values['window_size']}, step {values['step_size']}, {bp['values']['metric']}), embeddings on")
    opt = wait("optimizations", state["embeddings_optimization"], every_s=30)
    trials = request("GET", f"{agents_base()}/optimizations/{opt['id']}/trials?limit=10")["data"]
    trial = next((t for t in trials if t["status"] == "completed"), None)
    if opt["status"] != "completed" or not trial:
        sys.exit(f"{opt['id']} is {opt['status']} with no completed trial: move fit/out/library_state.json aside to try again")
    emb = promote(opt["id"], trial["id"], name=f"RED pump, embeddings on ({bp['key']}'s configuration)")
    state["embeddings_blueprint"] = {"id": emb["id"], "key": emb["key"]}
    save()
    return state["embeddings_blueprint"]


def read_embeddings(path: Path, channels: list[str], every: int = 1) -> np.ndarray:
    """[windows, channels x 768] from an output CSV (each embedding cell a JSON list):
    every `every`-th window, as a run at that step would give."""
    csv.field_size_limit(1 << 30)
    rows = []
    with open(path, newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh)):
            if i % every or r.get("finish_timestamp") == "finish_timestamp" or str(r.get("invalid")).lower() == "true":
                continue
            rows.append(np.concatenate([np.asarray(json.loads(r[f"embedding_{c}"]), dtype=np.float32)
                                        for c in channels]))
    return np.stack(rows)


def landscape(by_class: dict[str, np.ndarray], window: int, step: int, n_fitted: int) -> dict:
    """PCA 1-2 of the library, as fit/build_embedding_landscape.py writes it."""
    X = np.concatenate([by_class[c] for c in CLASSES]).astype(np.float64)
    y = np.concatenate([np.full(len(by_class[c]), i) for i, c in enumerate(CLASSES)])
    mean = X.mean(axis=0)
    Xc = X - mean
    _, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    components = Vt[:2]
    # A component's sign is arbitrary: face the way app/'s view does (normal on +PC1,
    # breakdowns on +PC2), so the two apps' clouds look alike.
    means = np.stack([by_class[c].astype(np.float64).mean(axis=0) for c in CLASSES]) - mean
    for k, (cls, sign) in enumerate(((0, 1), (1, 1))):
        if np.sign(means[cls] @ components[k]) != sign:
            components[k] = -components[k]
    coords = Xc @ components.T
    var = S ** 2 / (len(X) - 1)
    explained = (var[:2] / var.sum()).tolist()
    protos = means @ components.T
    return {
        "classes": CLASSES,
        "prototypes": [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in protos],
        "prototype_source": "recomputed: the mean of each class's library windows",
        "dim": int(X.shape[1]),
        "n": int(len(X)),
        "n_fitted": n_fitted,
        "window_size": window,
        "step_size": step,
        "explained_variance": [round(v, 4) for v in explained],
        "mean": [round(float(v), 5) for v in mean],
        "components": [[round(float(v), 6) for v in row] for row in components],
        "shots": [{"x": round(float(coords[i, 0]), 3), "y": round(float(coords[i, 1]), 3), "c": int(y[i])}
                  for i in range(len(X))],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--step", type=int, default=4, help="keep every N-th training window in the view (default 4)")
    args = ap.parse_args()
    load_dotenv()
    m = manifest()
    bp = load_state(state_path("test")).get("blueprint") or sys.exit("no promoted blueprint: run fit/test.py")
    channels, window = m["channels"], bp["values"]["window_size"]
    path = state_path("library")
    state = load_state(path)
    if state.get("bundle") or state.get("step"):
        sys.exit(f"{path} is from a bundle run: move it and {DIR.relative_to(REPO)} aside")
    if state.get("blueprint", bp["key"]) != bp["key"]:
        sys.exit(f"{path} is for {state['blueprint']}, not {bp['key']}: move it and {DIR.relative_to(REPO)} aside")
    lock = threading.Lock()                       # the three sessions save one state file

    def save():
        with lock:
            save_state(path, state)
    if "deployment" not in state:
        emb = embeddings_blueprint(m, bp, state, save)
        if "package" not in state:
            state["package"] = create_package(emb["id"], "RED library embeddings")["id"]
            save()
        state["deployment"] = deploy(state["package"], "batch")["id"]
        save()
        log(f"package {state['package']} of {emb['key']} (step {bp['values']['step_size']}, embeddings on), "
            f"batch deployment {state['deployment']}")
    DIR.mkdir(parents=True, exist_ok=True)

    def one(f: dict) -> Path | None:
        src, dst = ROLES / f["file"], DIR / Path(f["file"]).name
        if dst.exists():
            return dst
        runs = state.setdefault("sessions", {})
        if f["file"] not in runs:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            fid = upload_file(str(src), rename=f"red-pump-library__{src.stem}-{stamp}.csv")["file_id"]
            ses = open_session(state["deployment"], [fid])["id"]
            with lock:
                runs[f["file"]] = ses
            save()
            log(f"{src.name}: session {ses}")
        if poll_session(runs[f["file"]], 4 * 3600, interval_s=60) != "completed":
            log(f"{src.name}: session did not report completed; trying /results anyway")
        if download_results(runs[f["file"]], str(dst) + ".part", input_csv=str(src)):
            Path(str(dst) + ".part").rename(dst)
            log(f"{src.name}: complete")
            return dst
        log(f"{src.name}: no complete output; rerun to retry")
        return None

    with ThreadPoolExecutor(3) as pool:
        got = list(pool.map(one, m["training"]))
    if not all(got):
        return 1

    by_class: dict[str, list] = {c: [] for c in CLASSES}
    n_fitted = 0
    for f, out in zip(m["training"], got):
        emb = read_embeddings(out, channels, args.step)
        by_class[f["class"]].append(emb)
        n_fitted += f["n_rows"] - window + 1
        log(f"{Path(f['file']).name}: {len(emb):,} windows of {f['n_rows'] - window + 1:,} -> {f['class']}")
    view = landscape({c: np.concatenate(v) for c, v in by_class.items()}, window, args.step, n_fitted)
    VIEW.parent.mkdir(parents=True, exist_ok=True)
    VIEW.write_text(json.dumps(view, separators=(",", ":")))
    log(f"library: {view['n']:,} windows of {n_fitted:,} (step {args.step}), PC1+PC2 explain "
        f"{sum(view['explained_variance']):.1%}; prototypes at {view['prototypes']}")
    log(f"wrote {VIEW.relative_to(REPO)} ({VIEW.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
