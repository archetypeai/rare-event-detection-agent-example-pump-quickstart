#!/usr/bin/env python3
"""Minimal stdlib-only client for the Archetype AI Agent API.

Shared by run_red_fit.py (build phase) and run_red_example.py (inference).
Auth and endpoint come from the environment, with a local .env loaded if
present: ATAI_API_KEY, ATAI_API_ENDPOINT.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# The JOS bucket backing job outputs on dev. A fitted classifier lands at a
# fixed convention path under it; the /results endpoint hands back a presigned
# URL instead, which expires and so cannot be used as a bundle artifact.
JOS_S3_BUCKET = "atai-platform-dev-platform-data-us-west-2"
JOS_OUTPUT_TEMPLATE = ("s3://{bucket}/jos/jobs/{job_id}/agent/worker-0/"
                       "outputs/output/{filename}")


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def api_base() -> str:
    """The deployment root with /api appended — every surface lives under it.

    Accepts a bare root, a /vX.Y suffix or /api itself, so one .env works
    whichever form you have.
    """
    endpoint = os.environ.get("ATAI_API_ENDPOINT", "").rstrip("/")
    if not endpoint:
        sys.exit("ATAI_API_ENDPOINT is not set")
    endpoint = re.sub(r"/api$", "", endpoint)
    endpoint = re.sub(r"/v[0-9]+(\.[0-9]+)*$", "", endpoint)
    return f"{endpoint}/api"


def require_key() -> str:
    load_dotenv()
    key = os.environ.get("ATAI_API_KEY")
    if not key:
        sys.exit("ATAI_API_KEY is not set (put it in .env)")
    return key


def agents_base() -> str:
    return f"{api_base()}/agents"


def bundles_url(bundle_id: str | None = None, suffix: str = "") -> str:
    """URL for the bundles collection, one bundle, or a sub-path of one.

    The collection is PLURAL. It was `/agents/bundle` until the API renamed it,
    and the singular path is gone rather than aliased, so this is a 404 not a
    redirect. Every bundle URL in this repo goes through here so the next rename
    is one edit.

    Verified against dev (api.dev.u1) on 2026-08-14:

      POST /agents/bundles              create a bundle   (was /agents/bundle)
      GET  /agents/bundles/{id}         re-read a bundle  (was /agents/bundle/{id})
      POST /agents/bundles/{id}/run     start a run       — `run` stays SINGULAR
      GET  /agents/bundles?limit=1      200 {data, has_more, next_cursor}
      GET  /agents/bundle?limit=1       404 — the old prefix really is gone

    There is no `/agents/bundles/{id}/runs`. To list a bundle's runs, filter
    GET /agents/instances by bundle_id — see iter_instances(), and note that
    endpoint paginates.
    """
    url = f"{agents_base()}/bundles"
    if bundle_id:
        url = f"{url}/{bundle_id}"
    return f"{url}{suffix}"


def request(method: str, url: str, body=None, headers=None, raw: bool = False,
            retries: int = 4):
    """Call the API, retrying transient network failures.

    Polls run for hours, and a single DNS hiccup or socket timeout used to kill
    the whole client while the platform job carried on running unattended — the
    job then finished with nobody to download its output. Only *network* errors
    retry; an HTTP status is a real answer from the server and still exits.
    """
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {os.environ['ATAI_API_KEY']}")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                return payload if raw else json.loads(payload or b"null")
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {url} failed ({e.code}): {e.read().decode(errors='replace')}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries:
                sys.exit(f"{method} {url} failed after {retries + 1} attempts: {e}")
            wait = 5 * (2 ** attempt)
            print(f"  network error ({e}); retrying in {wait}s "
                  f"[{attempt + 1}/{retries}]")
            time.sleep(wait)


def upload_file(path: str, rename: str | None = None) -> dict:
    """POST a file to /api/files as multipart/form-data."""
    boundary = uuid.uuid4().hex
    filename = rename or os.path.basename(path)
    content = open(path, "rb").read()
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: text/csv\r\n\r\n",
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(f"{api_base()}/files", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {os.environ['ATAI_API_KEY']}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"upload of {path} failed ({e.code}): {e.read().decode(errors='replace')}")


# Since the 2026-10-12 re-seed the `red` blueprint's head is the empty model
# slot `classification_head` (an optimization fills it), and nothing is read from
# a classifier's own metadata: window, metric, columns, `events` and `background`
# all come from values (window 1024, metric l1 and no events by default). A
# bundle that brings its own classifier names it in `artifacts`, points the slot
# at it, and pins everything the classifier was fit with.
CLASSIFIER_SLOT = "classification_head"
CLASSES = ["normal", "pump_breakdown"]


def classifier_bundle(name: str, classifier: str, input_csv: str, window_size: int,
                      metric: str, step_size: int, artifact_key: str = "red-classifier") -> dict:
    """The body of POST /agents/bundles for the canonical `red` blueprint with an
    `s3://` classifier fitted at `window_size` / `metric` on `input_csv`'s columns."""
    with open(input_csv, newline="") as fh:
        header = next(csv.reader(fh))
    return {"blueprint": "red", "name": name,
            "values": {"timestamp_column": header[0], "data_columns": header[1:],
                       "window_size": window_size, "step_size": step_size, "metric": metric,
                       "events": CLASSES, "background": CLASSES[0]},
            "models": {CLASSIFIER_SLOT: artifact_key},
            "artifacts": {artifact_key: classifier}}


def blueprint_must_exist(key: str) -> None:
    req = urllib.request.Request(f"{agents_base()}/blueprints/{key}")
    req.add_header("Authorization", f"Bearer {os.environ['ATAI_API_KEY']}")
    try:
        with urllib.request.urlopen(req):
            return
    except urllib.error.HTTPError as e:
        if e.code == 404:
            sys.exit(f"blueprint '{key}' is not registered in your org — ask an org admin.")
        raise


def poll_agent(agent_id: str, timeout_s: int, interval_s: int = 20) -> str:
    """Poll until terminal, streaming new audit events as they appear."""
    agents = agents_base()
    deadline = time.time() + timeout_s
    seen: set[str] = set()
    status = "running"
    while status == "running" and time.time() < deadline:
        time.sleep(interval_s)
        status = request("GET", f"{agents}/instances/{agent_id}").get("status")
        for ev in request("GET", f"{agents}/instances/{agent_id}/events").get("data", []):
            marker = f"{ev.get('created_at')}{ev.get('message')}"
            if marker not in seen:
                seen.add(marker)
                print(f"  [{ev.get('level', 'info')}] {ev.get('created_at', '')}  "
                      f"{ev.get('message', '')}")
        print(f"  {time.strftime('%H:%M:%S')} status={status}")
    return status


def iter_instances(bundle_id: str | None = None, page_size: int = 100):
    """Yield agent instances, newest first, following the cursor to the end.

    /agents/instances paginates: {data, has_more, next_cursor}. A single-page
    fetch is the trap here — it returns HTTP 200 with a plausible-looking list,
    so a bundle with more runs than one page silently downloads a subset and
    nothing looks wrong.

    The cursor parameter is `after`. Verified on dev 2026-08-14: `cursor`,
    `next_cursor`, `starting_after` and `page_cursor` are all accepted with 200
    and then IGNORED, returning page 1 again — so a wrong guess here is either
    an infinite loop or a silent truncation, never an error.

    There is no server-side bundle filter, so bundle_id is applied client-side.
    """
    after = None
    while True:
        url = f"{agents_base()}/instances?limit={page_size}"
        if after:
            url += f"&after={urllib.parse.quote(after)}"
        page = request("GET", url)
        rows = page.get("data") or []
        for rec in rows:
            if bundle_id is None or rec.get("bundle_id") == bundle_id:
                yield rec
        if not page.get("has_more") or not rows:
            return
        after = page.get("next_cursor") or rows[-1].get("id")
        if not after:
            return


def jos_job_id(agent_id: str) -> str | None:
    """The JOS job id, read straight off the instance record.

    This used to scrape the audit events for "dispatched to JOS as job_…". The
    id is now a first-class `job_id` field on the instance, so the regex (and
    its dependence on log wording) is gone.
    """
    return request("GET", f"{agents_base()}/instances/{agent_id}").get("job_id")


# The platform can report a run completed while its output file is still being
# written (a known issue, seen in the TEP example's deliveries), so the output
# counts as complete only once its last window ends at the input's end: within
# one window span (an output row's finish - start) plus a minute. The same check
# as the agent-skills RED and AD skills.
END_SLACK_S = 60
OUTPUT_WAIT_S = 600


def tail_row(path: str) -> tuple[list[str], list[str]]:
    """A CSV's header and last row, read from the file's end."""
    with open(path, "rb") as f:
        header = next(csv.reader([f.readline().decode()]))
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - (1 << 20)))
        last = f.read().strip().split(b"\n")[-1].decode()
    return header, next(csv.reader([last]))


def output_reaches_end(output_csv: str, input_csv: str) -> bool | None:
    """Whether the output's last window ends at the input's last row. None when
    the output carries no window span or the timestamps aren't numbers."""
    try:
        head, row = tail_row(output_csv)
        finish = float(row[head.index("finish_timestamp")])
        span = finish - float(row[head.index("start_timestamp")])
        end = float(tail_row(input_csv)[1][0])
    except (ValueError, IndexError, StopIteration):
        return None
    return end - finish <= max(span, 0) + END_SLACK_S


def wait_until_complete(save, output_csv: str, input_csv: str) -> bool:
    """save() downloads the output; again every 15 s while it ends early.
    False when it still ends early after OUTPUT_WAIT_S."""
    deadline = time.time() + OUTPUT_WAIT_S
    while output_reaches_end(output_csv, input_csv) is False:
        if time.time() > deadline:
            print(f"  WARNING: the output still ends before the input "
                  f"{OUTPUT_WAIT_S // 60} min after the run finished; rerun to download it again")
            return False
        print("  run finished; output still being written, downloading again in 15 s")
        time.sleep(15)
        save()
    return True


ARTIFACT_WAIT_S = 600          # how long to wait for artifacts after a run reports completed


def artifact_status(item: dict) -> str | None:
    """An output's own completion status, or None if the platform reports none.

    A run reports `completed` while its artifacts are still being written.
    Measured: 66 consecutive samples -- about a minute -- with a run reporting
    completed while one output held 25,504 of an eventual 50,547 bytes.
    Reading it gives a well-formed file that is simply short, so nothing
    downstream notices. The console shows the same pairing, run COMPLETED
    beside artifact PARTIAL.
    """
    return (item.get("data", {}).get("file_attributes", {})
                .get("job_output", {}).get("status"))


def complete_results(fetch, wait_s: int = ARTIFACT_WAIT_S) -> list:
    """The run's outputs, once every one reports complete.

    Needs nothing but the agent id, unlike a content check, which compares the
    output against the input and so only works for the client that produced
    the run. An absent status reads as ready, so a deployment that reports
    none is not blocked; the wait is bounded.
    """
    deadline = time.time() + wait_s
    waited = False
    while True:
        items = fetch()
        pending = [i for i in items if artifact_status(i) not in (None, "complete")]
        if not pending:
            if waited:
                print("  every artifact reports complete")
            return items
        if time.time() > deadline:
            print(f"  WARNING {len(pending)} artifact(s) still incomplete after "
                  f"{wait_s // 60} min; collecting anyway")
            return items
        waited = True
        print(f"  {len(items) - len(pending)} of {len(items)} artifacts ready; waiting")
        time.sleep(15)


def download_results(agent_id: str, out_path: str, input_csv: str | None = None) -> str | None:
    """Fetch /results and save the first output to out_path; with input_csv, wait
    until the output reaches the input's end (None if it never does)."""
    def _fetch():
        r = request("GET", f"{agents_base()}/instances/{agent_id}/results")
        return r.get("data", r if isinstance(r, list) else [])

    items = complete_results(_fetch)
    if not items:
        print("  no results returned")
        return None
    # Each result nests the useful fields under an inner "data" object; the
    # `ref` there is a presigned URL that expires (~20 min), so download now.
    print(f"results ({len(items)}):")
    for item in items:
        inner = item.get("data") or {}
        print(f"  {inner.get('filename') or item.get('id')}  "
              f"({inner.get('num_bytes', '?')} bytes)")
    inner = items[0].get("data") or {}
    ref = inner.get("ref") or item.get("ref") or item.get("url")
    if not ref:
        print("  results carried no download ref")
        return None

    def save() -> None:
        # A fitted-artifact ref is an absolute presigned S3 URL; a run-output ref
        # is a relative platform path ("/files/download/<name>") that resolves
        # under the /api prefix and needs the bearer token.
        if ref.startswith("http"):
            with urllib.request.urlopen(ref) as resp:
                payload = resp.read()
        else:
            payload = request("GET", f"{api_base()}{ref}", raw=True)
        open(out_path, "wb").write(payload)

    save()
    if input_csv and not wait_until_complete(save, out_path, input_csv):
        return None
    print(f"saved output to {out_path}")
    return out_path
