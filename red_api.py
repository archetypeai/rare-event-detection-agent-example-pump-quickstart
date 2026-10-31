#!/usr/bin/env python3
"""Minimal stdlib-only client for the Archetype AI Agents API (Agent Lifecycle 2.0).

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


TERMINAL = {"completed", "failed", "cancelled"}


def lifecycle_url(kind: str, obj_id: str | None = None, suffix: str = "") -> str:
    """URL for `packages`, `deployments` or `sessions`, one of them, or a sub-path of one.

    The lifecycle: a blueprint in a project is packaged (its models resolved once,
    no values), the package deployed as `batch` or `serving`, and work runs in
    sessions on a deployment. Every lifecycle URL in this repo goes through here.
    """
    url = f"{agents_base()}/{kind}"
    if obj_id:
        url = f"{url}/{obj_id}"
    return f"{url}{suffix}"


def _wait_for(kind: str, obj_id: str, want: str, waiting: str, timeout_s: int = 600, every_s: int = 3) -> dict:
    t0 = time.time()
    while True:
        obj = request("GET", lifecycle_url(kind, obj_id))
        if obj["status"] == want:
            return obj
        if obj["status"] != waiting or time.time() - t0 > timeout_s:
            sys.exit(f"{obj_id} is {obj['status']}, not {want}: {obj.get('error')}")
        time.sleep(every_s)


def create_package(blueprint_id: str, name: str) -> dict:
    """Package one blueprint for the platform and wait until it is ready. It pins the
    blueprint and the models it resolves to (the Omega encoder, the fitted prototypes)
    and carries no values: it runs the blueprint exactly as promoted."""
    pkg = request("POST", lifecycle_url("packages"),
                  body={"blueprint_ids": [blueprint_id], "target": {"kind": "platform"}, "name": name})
    return _wait_for("packages", pkg["id"], "ready", "building", every_s=5)


def deploy(package_id: str, kind: str) -> dict:
    """Deploy a package as `batch` (ready at once) or `serving` (the agent placed on a
    worker and loaded, usually within seconds; it holds the worker until stopped)."""
    dpl = request("POST", lifecycle_url("deployments"), body={"package_id": package_id, "kind": kind})
    return _wait_for("deployments", dpl["id"], "ready", "deploying")


def open_session(deployment_id: str, file_ids: list[str] | None = None) -> dict:
    """A batch session over `file_ids` (one output per input), or a serving session,
    queried at /sessions/{id}/query once `running`, when none are given."""
    body = {"deployment_id": deployment_id}
    if file_ids:
        body["connectors"] = {"source": [{"type": "file", "id": f, "format": "csv"} for f in file_ids]}
    return request("POST", lifecycle_url("sessions"), body=body)


def wait_running(session_id: str) -> dict:
    return _wait_for("sessions", session_id, "running", "pending")


def end(kind: str, obj_id: str) -> None:
    """Cancel a session still going, or stop a deployment still up, then delete it; a
    package is deleted as it is. An id already gone (404) counts as done."""
    try:
        obj = request("GET", lifecycle_url(kind, obj_id))
    except SystemExit as e:
        if "(404)" in str(e):
            return
        raise
    if kind == "sessions" and obj["status"] not in TERMINAL:
        request("POST", lifecycle_url(kind, obj_id, "/cancel"), body={})
    if kind == "deployments" and obj["status"] not in ("stopped", "failed"):
        request("POST", lifecycle_url(kind, obj_id, "/stop"), body={})
    request("DELETE", lifecycle_url(kind, obj_id), raw=True)


def list_ids(kind: str, **query: str) -> list[str]:
    """Every id of a lifecycle list (`GET /agents/deployments?package_id=…`,
    `GET /agents/sessions?deployment_id=…`), following the `after` cursor."""
    out, after = [], None
    while True:
        url = lifecycle_url(kind) + "?" + urllib.parse.urlencode({**query, "limit": 1000})
        if after:
            url += f"&after={urllib.parse.quote(after)}"
        page = request("GET", url)
        out += [r["id"] for r in page.get("data") or []]
        if not page.get("has_more"):
            return out
        after = page.get("next_cursor")


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


def poll_session(session_id: str, timeout_s: int, interval_s: int = 20) -> str:
    """Poll a batch session until it ends, streaming its events as they appear. A session
    reaches a terminal status and carries `error`; returns the status (`pending` or
    `running` when the timeout came first)."""
    deadline = time.time() + timeout_s
    seen: set[str] = set()
    status = "pending"
    while status not in TERMINAL and time.time() < deadline:
        time.sleep(interval_s)
        ses = request("GET", lifecycle_url("sessions", session_id))
        status = ses.get("status")
        for ev in reversed(request("GET", lifecycle_url("sessions", session_id, "/events")).get("data", [])):
            marker = f"{ev.get('created_at')}{ev.get('message')}"
            if marker not in seen:
                seen.add(marker)
                print(f"  [{ev.get('level', 'info')}] {ev.get('created_at', '')}  {session_id}: "
                      f"{ev.get('message', '')}")
        if ses.get("error"):
            print(f"  {session_id}: {ses['error']}")
        print(f"  {time.strftime('%H:%M:%S')} {session_id} status={status}")
    return status


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

    Needs nothing but the session id, unlike a content check, which compares the
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


def download_results(session_id: str, out_path: str, input_csv: str | None = None) -> str | None:
    """Fetch /results and save the first output to out_path; with input_csv, wait
    until the output reaches the input's end (None if it never does)."""
    def _fetch():
        r = request("GET", lifecycle_url("sessions", session_id, "/results"))
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
        # An absolute URL, or a session output's root path ("/api/files/<fil_…>/content"),
        # resolved against the deployment root, not against /api; it needs the bearer token.
        if ref.startswith("http"):
            with urllib.request.urlopen(ref) as resp:
                payload = resp.read()
        else:
            base = api_base().removesuffix("/api") if ref.startswith("/api/") else api_base()
            payload = request("GET", f"{base}{ref}", raw=True)
        open(out_path, "wb").write(payload)

    save()
    if input_csv and not wait_until_complete(save, out_path, input_csv):
        return None
    print(f"saved output to {out_path}")
    return out_path
