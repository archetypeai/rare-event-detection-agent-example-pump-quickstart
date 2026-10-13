#!/usr/bin/env python3
"""Stage 0 -- fetch the pump-sensor dataset from Kaggle.

    python3 prep/download.py                   # Kaggle API, with your own token
    python3 prep/download.py --from PATH       # use a sensor.csv you already have
    python3 prep/download.py --verify-only     # check what is on disk, fetch nothing

Source: the Kaggle dataset `nphantawee/pump-sensor-data` ("Pump sensor data for
predictive maintenance"). It declares no licence, so this repo does not ship it:
each user downloads it under Kaggle's terms with their own account.

Credentials, the Kaggle API's usual places: KAGGLE_USERNAME and KAGGLE_KEY in the
environment, or ~/.kaggle/kaggle.json (Kaggle -> Settings -> API -> Create New
Token). The key is sent only to kaggle.com and never printed.

Writes data/raw/sensor.csv and checks its SHA-256 against the copy this example
was built from, so every later stage starts from the same bytes. Idempotent: a
file already there with the right hash is not fetched again.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "raw" / "sensor.csv"
DATASET = "nphantawee/pump-sensor-data"
URL = f"https://www.kaggle.com/api/v1/datasets/download/{DATASET}"
SHA256 = "436681c673264b6eff959a41e7cd7fcb313e5c747523d951361063482ac62331"
SIZE = 124_058_460


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verified(path: Path) -> bool:
    return path.exists() and path.stat().st_size == SIZE and sha256(path) == SHA256


def credentials() -> tuple[str, str]:
    user, key = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
    if user and key:
        return user, key
    p = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle")) / "kaggle.json"
    if p.exists():
        c = json.loads(p.read_text())
        return c["username"], c["key"]
    sys.exit("no Kaggle credentials: set KAGGLE_USERNAME and KAGGLE_KEY, or put kaggle.json in "
             "~/.kaggle/ (Kaggle -> Settings -> API -> Create New Token). Or pass --from PATH.")


def fetch() -> bytes:
    user, key = credentials()
    req = urllib.request.Request(URL)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{key}".encode()).decode())
    print(f"downloading {DATASET} from Kaggle (~12 MB zipped) ...", flush=True)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="src", metavar="PATH", help="copy this sensor.csv instead of downloading")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args(argv)

    if verified(RAW):
        print(f"{RAW.relative_to(REPO)}: present, SHA-256 matches")
        return 0
    if args.verify_only:
        print(f"{RAW.relative_to(REPO)}: {'wrong content' if RAW.exists() else 'missing'}")
        return 1

    RAW.parent.mkdir(parents=True, exist_ok=True)
    if args.src:
        shutil.copyfile(args.src, RAW)
    else:
        with zipfile.ZipFile(io.BytesIO(fetch())) as z:
            name = next((n for n in z.namelist() if n.endswith("sensor.csv")), None)
            if not name:
                sys.exit(f"no sensor.csv in the Kaggle archive: {z.namelist()}")
            with z.open(name) as src, open(RAW, "wb") as dst:
                shutil.copyfileobj(src, dst)
    if not verified(RAW):
        sys.exit(f"{RAW.relative_to(REPO)}: SHA-256 {sha256(RAW)} is not the expected {SHA256}; "
                 "the Kaggle dataset may have changed")
    print(f"{RAW.relative_to(REPO)}: {SIZE:,} bytes, SHA-256 matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
