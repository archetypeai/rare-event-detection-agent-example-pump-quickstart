#!/usr/bin/env python3
"""Minimal stdlib-only client for the Archetype AI Agent API.

Shared by fit/ and prep/. Auth and endpoint come from the environment, with a local .env loaded if
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


def deployment(endpoint: str) -> str:
    """What deployment an endpoint addresses, whatever hostname it arrives under.

    api.u1.archetypeai.app and platform.u1.archetypeai.app are one
    deployment under two names: an agent created through either is visible
    through the other. So state written through one name has to load through
    the other. The generation (api, platform) is everything left of the first
    dot; the rest names the deployment, which still separates u1 from u2.
    """
    host = re.sub(r"^[a-z]+://", "", endpoint.strip()).split("/")[0].split(":")[0]
    return re.sub(r"^(api|platform)\.", "", host).lower()


def agents_base() -> str:
    return f"{api_base()}/agents"


def bundles_url(bundle_id: str | None = None, suffix: str = "") -> str:
    """URL for the bundles collection, one bundle, or a sub-path of one.

    The collection is PLURAL; `run` stays singular. Every bundle URL in this
    repo goes through here so a rename is one edit.

      POST /agents/bundles              create a bundle
      GET  /agents/bundles/{id}         re-read a bundle
      POST /agents/bundles/{id}/run     start a run
      GET  /agents/bundles?limit=1      200 {data, has_more, next_cursor}

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

    The cursor parameter is `after`. `cursor`,
    `next_cursor`, `starting_after` and `page_cursor` are all accepted with 200
    and then IGNORED, returning page 1 again — so a wrong guess here is either
    an infinite loop or a silent truncation, never an error.

    The listing DOES take `bundle_id=`, and the platform validates it (a malformed
    id answers 400), so one filtered request replaces walking the whole listing.
    A delivery bundle answers with exactly its runs and `has_more` false. If a
    deployment ever ignores the parameter the rows come back unfiltered, so the
    filter is dropped the moment a row does not match and the walk continues
    client-side.
    """
    after, server_side = None, bundle_id is not None
    while True:
        url = f"{agents_base()}/instances?limit={page_size}"
        if server_side:
            url += f"&bundle_id={urllib.parse.quote(bundle_id)}"
        if after:
            url += f"&after={urllib.parse.quote(after)}"
        try:
            page = request("GET", url)
        except SystemExit:
            if not server_side:
                raise
            server_side, after = False, None      # unsupported: walk it instead
            continue
        rows = page.get("data") or []
        if server_side and any(r.get("bundle_id") != bundle_id for r in rows):
            server_side, after = False, None      # ignored: the rows are everyone's
            continue
        for rec in rows:
            if bundle_id is None or rec.get("bundle_id") == bundle_id:
                yield rec
        if not page.get("has_more") or not rows:
            return
        after = page.get("next_cursor") or rows[-1].get("id")
        if not after:
            return


# The platform can report a run completed while its output file is still being
# written (a known issue), so the output
# counts as complete only once its last window ends at the input's end: within
# one window span (an output row's finish - start) plus a minute. The same check
# as the agent-skills RED and AD skills.
END_SLACK_S = 60
OUTPUT_WAIT_S = 600


# csv.reader caps one field at 128 KB by default. An embeddings column is a
# whole vector in a single quoted field, so the cap is reachable — and it
# raises rather than truncating, which at least fails loudly.
csv.field_size_limit(1 << 31)


def tail_row(path: str) -> tuple[list[str], list[str]]:
    """A CSV's header and last row, read from the file's end.

    The window grows until it holds a complete final record. A fixed window is
    correct only while every row fits inside it, and the failure is silent: a
    window narrower than one row yields a fragment of a field, which still
    parses as a number and reads as an output that stopped early. Growing also
    reads LESS in the common case — 4 KiB rather than a megabyte.
    """
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        header = next(csv.reader([f.readline().decode()]))
        window = 4096
        while True:
            f.seek(max(0, size - window))
            lines = f.read().strip().split(b"\n")
            # A leading partial line proves the trailing one is whole.
            if len(lines) > 1 or window >= size:
                return header, next(csv.reader([lines[-1].decode()]))
            window *= 4


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
