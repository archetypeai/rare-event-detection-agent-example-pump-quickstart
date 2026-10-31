#!/usr/bin/env python3
"""Clean up: delete the sessions, deployments and packages the platform path left on the platform.

    python3 fit/cleanup.py            # list what would be deleted, and what stays
    python3 fit/cleanup.py --yes      # delete it

It starts from the packages the stages recorded in fit/out/:

  Stage 9   the serving bridge's, if app-serving/ was killed before it could
            delete them (app_serving_state.json), and fit/library_embeddings.py's
            (library_state.json; the view is already in app-serving/static/).
  Stage 8   fit/serve.py's, if it was killed before it could delete them
            (serve_state.json). A serving deployment holds a serving worker
            until it is stopped.
  Stage 6   the delivery's (deliver_state.json). The outputs are already in
            eval_out/delivery/.

For each package, the platform's own listings (GET /agents/deployments?package_id=,
then GET /agents/sessions?deployment_id=) give its deployments and their sessions,
so ones a stage never recorded, or a rerun replaced, are found too.

Sessions go first, then deployments, then the package: each holds the next. A
session still going is cancelled, and a deployment still up stopped, before it is
deleted; an id already gone counts as done. Progress goes to
fit/out/cleanup_state.json, so a rerun picks up where it stopped.

What stays: the project, its copy of `red`, the promoted blueprints (Stage 5's and
the embeddings one), and the optimizations and eval the README cites. After a
cleanup, rerunning fit/deliver.py needs fit/out/deliver_state.json moved aside,
since its package is gone.
"""
from __future__ import annotations

import argparse
import sys

from atai import load_dotenv, load_state, log, request, save_state, state_path
from red_api import end, lifecycle_url, list_ids

STAGES = {"app_serving": "Stage 9", "library": "Stage 9", "serve": "Stage 8", "deliver": "Stage 6"}
KINDS = ("sessions", "deployments", "packages")


def targets(packages: list, deployments_of, sessions_of) -> list:
    """(stage, kind, id) to delete, each session before its deployment and each
    deployment before its package. `packages` is [(stage, package id)]."""
    out = []
    for stage, pkg in packages:
        dpls = deployments_of(pkg)
        out += [(stage, "sessions", s) for d in dpls for s in sessions_of(d)]
        out += [(stage, "deployments", d) for d in dpls] + [(stage, "packages", pkg)]
    return out


def exists(pkg: str) -> bool:
    try:
        return bool(request("GET", lifecycle_url("packages", pkg)))
    except SystemExit as e:
        if "(404)" in str(e):
            return False
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--yes", action="store_true", help="delete; without it, only list")
    args = ap.parse_args()
    load_dotenv()

    found = {name: load_state(state_path(name)) for name in STAGES}
    for name, st in found.items():
        if st.get("bundle"):
            sys.exit(f"{state_path(name)} holds bundle ids from before packages: delete them with the bundle-era fit/cleanup.py")
    packages = [(STAGES[n], st["package"]) for n, st in found.items() if st.get("package") and exists(st["package"])]
    todo_all = targets(packages, lambda p: list_ids("deployments", package_id=p),
                       lambda d: list_ids("sessions", deployment_id=d))
    done_path = state_path("cleanup")
    done = load_state(done_path)
    gone = set(done.get("deleted", []))
    todo = [t for t in todo_all if t[2] not in gone]
    for stage in ("Stage 9", "Stage 8", "Stage 6"):
        mine = [t for t in todo if t[0] == stage]
        print(f"{stage}: " + ", ".join(f"{sum(t[1] == k for t in mine)} {k}" for k in KINDS) + " to delete")
    print(f"already deleted: {len(gone & {t[2] for t in todo_all})}")
    test = load_state(state_path("test"))
    if test.get("blueprint"):
        print(f"stays: blueprint {test['blueprint']['key']}, the embeddings blueprint, optimization "
              f"{test.get('optimization')} and eval {test.get('eval')}, and the project with its copy of red")
    if not args.yes:
        print("\nnothing deleted: rerun with --yes")
        return 0

    stuck = []
    for k, (stage, kind, obj) in enumerate(todo, 1):
        try:
            end(kind, obj)
            gone.add(obj)
        except SystemExit as e:
            # keep going: one object that will not delete must not strand the rest
            stuck.append((kind, obj, str(e).splitlines()[0][:200]))
        if k % 25 == 0 or k == len(todo):
            done["deleted"] = sorted(gone)
            save_state(done_path, done)
            log(f"deleted {k - len(stuck)}/{len(todo)}")

    if stuck:
        print(f"\n{len(stuck)} object(s) would not delete:")
        for kind, obj, why in stuck:
            print(f"  {kind}/{obj}: {why}")
        print("a session holds its deployment, and a deployment its package: "
              "delete what holds them, then rerun")
        return 1
    for name in ("serve", "app_serving"):
        if found[name].get("package"):
            state_path(name).unlink()
    lib = found["library"]
    if lib.get("package"):                # keep the embeddings blueprint for a rerun and the bridge
        save_state(state_path("library"),
                   {k: v for k, v in lib.items() if k not in ("package", "deployment", "sessions")})
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
