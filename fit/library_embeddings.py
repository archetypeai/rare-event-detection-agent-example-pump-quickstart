#!/usr/bin/env python3
"""Stage 9 prep: the embedding space for app-serving/, recomputed on the platform.

    python3 fit/library_embeddings.py              # 3 batch runs, ~5-30 min with Dev's load
    python3 fit/library_embeddings.py --step 1     # every training window (12,059; ~4x the time and download)

app/ builds its Embedding Space by re-encoding the training shots with a local
Omega checkpoint (fit/build_embedding_landscape.py). The platform path has no
local encoder and nothing to read back: the promoted classifier is a registry
artifact (`aar_...`) with no download route, and the Optimizations and Evals APIs
return metrics and predictions, not embeddings. So the training windows are
encoded again on the platform:

  1. a bundle on fit/test.py's promoted blueprint with `output_embeddings: true`
     and `step_size` 4 (a quarter of the 12,059 training windows: the same cloud
     at a quarter of the download);
  2. one agent per training file (normal, breakdowns #1 and #2), in parallel;
  3. the 10 x 768 embeddings of every window, in the manifest's channel order,
     and PCA 1-2 of them: the cloud, and the projection the app applies to each
     live window. The two class prototypes are the means of each class's
     windows, projected the same way (the classifier fits `strategy: centroid`,
     but its own vectors can't be read).

Writes app-serving/static/red-embedding-landscape.json (the format app/ reads)
and fit/out/library_embeddings/ (the outputs, regenerable). Ids go to
fit/out/library_state.json, so a rerun resumes and fit/cleanup.py can delete
the agents afterwards.
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

from atai import OUT as FIT_OUT, REPO, ROLES, load_dotenv, load_state, log, manifest, request, save_state, state_path
from red_api import bundles_url, download_results, poll_agent, upload_file

CLASSES = ["normal", "pump_breakdown"]
CHECKPOINTING_OFF = {"checkpointing": {"trigger_after_input_byte_size": 0, "trigger_after_delay_ms": 0}}
VIEW = REPO / "app-serving" / "static" / "red-embedding-landscape.json"
DIR = FIT_OUT / "library_embeddings"


def read_embeddings(path: Path, channels: list[str]) -> np.ndarray:
    """[windows, channels x 768] from an output CSV (each embedding cell a JSON list)."""
    csv.field_size_limit(1 << 30)
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("finish_timestamp") == "finish_timestamp" or str(r.get("invalid")).lower() == "true":
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
    ap.add_argument("--step", type=int, default=4, help="stride over the training files (default 4)")
    args = ap.parse_args()
    load_dotenv()
    m = manifest()
    bp = load_state(state_path("test")).get("blueprint") or sys.exit("no promoted blueprint: run fit/test.py")
    channels, window = m["channels"], bp["values"]["window_size"]
    path = state_path("library")
    state = load_state(path)
    if state.get("step", args.step) != args.step:
        sys.exit(f"{path} is for step {state['step']}: move it and {DIR.relative_to(REPO)} aside")
    state["step"] = args.step
    if "bundle" not in state:
        state["bundle"] = request("POST", bundles_url(), body={
            "blueprint": bp["key"], "name": "RED library embeddings",
            "values": {"step_size": args.step, "output_embeddings": True, "runner_config": CHECKPOINTING_OFF}})["id"]
        save_state(path, state)
        log(f"bundle {state['bundle']} on {bp['key']}, step {args.step}, embeddings on")
    DIR.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()                       # the three runs save one state file

    def one(f: dict) -> Path | None:
        src, dst = ROLES / f["file"], DIR / Path(f["file"]).name
        if dst.exists():
            return dst
        runs = state.setdefault("agents", {})
        if f["file"] not in runs:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            fid = upload_file(str(src), rename=f"red-pump-library__{src.stem}-{stamp}.csv")["file_id"]
            agent = request("POST", f"{bundles_url(state['bundle'])}/run", body={
                "connectors": {"source": [{"type": "file", "id": fid, "format": "csv"}]}})["id"]
            with lock:
                runs[f["file"]] = agent
                save_state(path, state)
            log(f"{src.name}: agent {runs[f['file']]}")
        if poll_agent(runs[f["file"]], 4 * 3600, interval_s=60) != "completed":
            log(f"{src.name}: agent did not report completed; trying /results anyway")
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
        emb = read_embeddings(out, channels)
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
