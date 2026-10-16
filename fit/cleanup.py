#!/usr/bin/env python3
"""Clean up: delete the agents and bundles the platform path left on the platform.

    python3 fit/cleanup.py            # list what would be deleted, and what stays
    python3 fit/cleanup.py --yes      # delete it

What it deletes, from the ids the stages recorded in fit/out/:

  Stage 9   the serving bridge's agents and bundle, if app-serving/ was killed
            before it could delete them (app_serving_state.json; the bundle's
            listing also finds an agent it replaced), and the 3 batch agents and
            bundle of fit/library_embeddings.py (library_state.json; the view is
            already in app-serving/static/).
  Stage 8   a serving agent and its bundle, if fit/serve.py was killed before
            it could delete them (serve_state.json). A running serving agent
            holds one of dev's 3 serving workers until it is cancelled or idle
            20 min.
  Stage 6   the delivery agents and their bundle (deliver_state.json). The
            state holds each file's last attempt; the bundle's own listing also
            finds the attempts a rerun replaced. The outputs are already in
            eval_out/delivery/.

Agents go first (a bundle that still has an agent answers 409), a running one is
cancelled before it is deleted, and an id already gone counts as done. Progress
goes to fit/out/cleanup_state.json, so a rerun picks up where it stopped.

What stays: the promoted blueprint and its served copy (deleting a blueprint
takes an org admin's key), and the optimizations and eval the README cites.
After a cleanup, rerunning fit/deliver.py needs fit/out/deliver_state.json moved
aside, since its bundle is gone.
"""
from __future__ import annotations

import argparse
import sys

from atai import TERMINAL, agents_base, load_dotenv, load_state, log, request, save_state, state_path
from red_api import iter_instances

STAGES = {"app": "Stage 9", "serve": "Stage 8", "deliver": "Stage 6"}


def call(method: str, path: str, body=None):
    """None when the object is already gone."""
    try:
        return request(method, f"{agents_base()}{path}", body=body, raw=method == "DELETE")
    except SystemExit as e:
        if "(404)" in str(e):
            return None
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--yes", action="store_true", help="delete; without it, only list")
    args = ap.parse_args()
    load_dotenv()

    bridge = load_state(state_path("app_serving"))
    library = load_state(state_path("library"))
    serve = load_state(state_path("serve"))
    deliver = load_state(state_path("deliver"))
    test = load_state(state_path("test"))
    targets = []                                   # (stage, kind, id), agents before their bundle
    if bridge.get("bundle"):
        agents = set(bridge.get("agents") or []) | ({bridge["agent"]} if bridge.get("agent") else set())
        agents |= {r["id"] for r in iter_instances(bridge["bundle"])}
        targets += [(STAGES["app"], "instances", a) for a in sorted(agents)]
        targets += [(STAGES["app"], "bundles", bridge["bundle"])]
    if library.get("bundle"):
        targets += [(STAGES["app"], "instances", a) for a in sorted(set(library.get("agents", {}).values()))]
        targets += [(STAGES["app"], "bundles", library["bundle"])]
    if serve.get("bundle"):
        targets += [(STAGES["serve"], "instances", serve["agent"])] if serve.get("agent") else []
        targets += [(STAGES["serve"], "bundles", serve["bundle"])]
    if deliver.get("bundle"):
        agents = set(deliver.get("agents", {}).values())
        agents |= {r["id"] for r in iter_instances(deliver["bundle"])}
        targets += [(STAGES["deliver"], "instances", a) for a in sorted(agents)]
        targets += [(STAGES["deliver"], "bundles", deliver["bundle"])]

    done_path = state_path("cleanup")
    done = load_state(done_path)
    gone = set(done.get("deleted", []))
    todo = [t for t in targets if t[2] not in gone]
    for stage in STAGES.values():
        mine = [t for t in todo if t[0] == stage]
        print(f"{stage}: {sum(t[1] == 'instances' for t in mine)} agent(s), "
              f"{sum(t[1] == 'bundles' for t in mine)} bundle(s) to delete")
    print(f"already deleted: {len(gone & {t[2] for t in targets})}")
    bp = test.get("blueprint", {}).get("key")
    if bp:
        print(f"stays: blueprints {bp} and {bp}-served-records (an org admin can delete them); "
              f"optimization {test.get('optimization')} and eval {test.get('eval')}")
    if not args.yes:
        print("\nnothing deleted: rerun with --yes")
        return 0

    for k, (stage, kind, obj) in enumerate(todo, 1):
        if kind == "instances":
            info = call("GET", f"/instances/{obj}")
            if info and info.get("status") not in TERMINAL:
                call("POST", f"/instances/{obj}/cancel", body={})
        call("DELETE", f"/{kind}/{obj}")
        gone.add(obj)
        if k % 25 == 0 or k == len(todo):
            done["deleted"] = sorted(gone)
            save_state(done_path, done)
            log(f"deleted {k}/{len(todo)}")
    for kind, st in (("serve", serve), ("app_serving", bridge)):
        if st.get("bundle"):
            state_path(kind).unlink()
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
