# RED Pump Monitor, served from the platform

A live monitor for the quickstart's agent. Stage 6's delivery files are replayed
as if the pump were running now, and every window goes to a **serving agent** of
the classifier Stage 5 promoted, on the Archetype AI platform. The answers come
back to the sensor traces, the verdict, a timeline and an embedding space.

> The app holds one **serving agent** while it runs, and deletes it when you
> stop it.

It serves this repo's promoted blueprint, and it replays the **delivery** files
(breakdowns #4 and #7, `data/roles/delivery/`), since this repo ships no raw
file. The agent gets each file's z-scored values as written, so every
served window can be checked against Stage 6's batch output; the charts show them
back in engineering units, through `data/prepared/pump_zscore_stats.json`.

## Architecture

```
  data/roles/delivery/inc0{4,7}.csv            fit/out/test_state.json (the promoted blueprint)
                │                                          │   data/roles/manifest.json (channels)
                ▼                                          ▼                     repo .env: ATAI_API_KEY
┌───────────────────────────┐  GET /status    ┌──────────────────────────────┐          │
│ replayer (node)           │  POST /reset    │ serving bridge (node)        │◀─────────┘
│ one delivery file at a    │  POST /start    │ the API key stays here;      │   POST /query   ┌──────────────────────────┐
│ time, data-time pace,     │────────────────▶│ keeps the last 64 rows,      │────────────────▶│ serving agent            │
│ holds off while the agent │  admin :9101    │ one query per row (step 1)   │  the latest 64  │ promoted classifier,     │
│ catches up                │                 │                              │  rows           │ atai-records,            │
└───────────────────────────┘                 └──────────────────────────────┘◀────────────────│ embeddings on            │
  pub │ sensors/red (z-scored)                   sub ▲ sensors/red   │ pub        one record   └──────────────────────────┘
  pub │ pump/raw, pump/status (eng. units)                           │ red/results (state, p_*,
  sub ▲ pump/control, red/results (flow control)                     ▼ 10 × 768 embedding)
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                     mosquitto · TCP :1891 · WebSockets :9009                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
          sub ▼ pump/raw, pump/status, red/results     pub ▲ pump/control (play, pause, seek, speed, slice, reset, onset)
                     web app (SvelteKit, :5181, mqtt.js over ws): sensor traces · verdict · timeline · embedding space
```

- **The serving bridge** (`scripts/serving-bridge.js`) is the agent's local end.
  On start it creates a bundle of the promoted blueprint itself, with values
  `{step_size: 1, output_embeddings: true}`, and starts it as a serving agent; the
  platform supplies the serving connectors, as for Stage 8. Then, for
  every row, it sends the latest 64 rows as one query and publishes the answer on
  `red/results`, with the window's timestamps
  put back (a served agent numbers the rows 0–63 within a query).
- **It answers the replayer's admin calls** (`GET /status`, `POST /reset`,
  `POST /start`, `POST /shutdown` on :9101): a seek or incident switch resets the
  bridge's buffer, so no window mixes two sections. The bridge sends no query
  until its agent is running, and the replayer holds the replay while the bridge
  starts one: at startup, when it replaces a released one, or while all the
  serving workers are taken (the bridge retries every 15 s, doubling to 2 min).
  If answers are lost (the bridge was restarted), the replayer stops waiting for
  them once a new agent runs, or after 20 s.
- **The API key never reaches the browser.** The bridge reads `ATAI_API_ENDPOINT`
  and `ATAI_API_KEY` from the repo's `.env`, the same file the Python stages use.
- **On exit** (Ctrl-C, `npm run stop`) the bridge cancels and deletes its agent and
  deletes its bundle. If it's killed hard, the ids are still in
  `fit/out/app_serving_state.json`, and `python3 fit/cleanup.py --yes` removes them.
  An agent the platform released after 20 minutes without a query (a replay paused
  that long) is deleted and replaced on the next window, retrying while the
  serving workers are all taken. If anything can't be deleted on exit, the bridge
  says so and keeps the ids for `fit/cleanup.py`. See
  [Stop and clean up](#stop-and-clean-up).

**Checked on production, 2026-10-29:** the app ran breakdown #4's demo window
(rows 784–1,869 of `inc04.csv`, 1,023 windows) against a serving agent, each
answer with its 10 × 768 embeddings. Stage 8 checked the same served windows
against Stage 6's output: every `predicted_state` and probability identical,
0 invalid.

## The embedding space: the training windows, recomputed

The promoted classifier is a registry artifact (`aar_…`) with no download route,
and the Optimizations and Evals APIs return metrics and predictions, not
embeddings. So the training windows are encoded again, on the platform:

```sh
python3 fit/library_embeddings.py     # once, from the repo root: 3 batch runs, a few minutes
```

It runs the 3 training files (normal operation and breakdowns #1 and #2) through
the promoted blueprint in **batch** with `output_embeddings: true`, at step 4:
3,016 of the 12,059 training windows. PCA 1–2 of their embeddings (32.5% and 4.0%
of the variance) gives the cloud and the projection, in
`static/red-embedding-landscape.json`; each live window's embedding goes through
the same projection. The two prototypes are the means of each class's windows:
the classifier fits one mean per class, but its own vectors can't be read.
`--step 1` recomputes all 12,059 windows, for the same picture.

## Run it

Prerequisites: Node 20+, `brew install mosquitto`, `git lfs pull`, and Stages 4–6
run (`fit/out/test_state.json` names the promoted blueprint). In the
[repo README](../README.md) this is Stage 9. Then:

```sh
python3 fit/library_embeddings.py     # once, from the repo root (writes static/red-embedding-landscape.json)
cd app-serving
npm install
npm run dev                           # broker + serving bridge + replayer + web
open http://localhost:5181
```

When you're done, stop it and check it cleaned up: [Stop and clean up](#stop-and-clean-up).

### Pace

The platform answers a window in under half a second, so the replay runs at
about 2 rows a second: the replayer holds off whenever the agent falls behind.
Breakdown #4's demo window (240 rows either side of the breakdown) takes about
8 minutes, a whole delivery file about 20. Every window is asked about (step 1),
so every verdict is the one Stage 6 delivered.

## Stop and clean up

A running app holds a serving agent, and so one serving worker,
until the bridge deletes the agent or the platform releases it after 20 minutes
without a query. Closing the browser tab does not stop it.

1. **Stop the app.** Press Ctrl-C **once** in the `npm run dev` terminal and
   wait for `bridge: deleted its agent(s) and bundle …`; a second Ctrl-C can cut
   that short. Or, from `app-serving/` in any terminal (also for an app started
   in the background or from a terminal since closed):

   ```sh
   npm run stop      # SIGTERM to the bridge, waits for it, stops the rest, checks the ports
   ```

   Either way the bridge cancels and deletes its agent, deletes its bundle and
   removes `fit/out/app_serving_state.json`. `npm run stop` ends with
   `all ports free (1891 · 9009 · 9101 · 5181)`; a port still held names its process.

2. **Check nothing is left**, from the repo root:

   ```sh
   ls fit/out/app_serving_state.json        # "No such file": the bridge cleaned up
   set -a; source .env; set +a
   curl -s "$ATAI_API_ENDPOINT/agents/instances?status=running&limit=100" -H "Authorization: Bearer $ATAI_API_KEY" \
     | jq -c '.data[] | select(.mode=="serving") | {id, blueprint, name, created_at}'
   ```

   No line named `RED app-serving` means no agent of this app is running.
   `status=running` filters on the server; `mode=serving` is ignored there, so
   `jq` picks the serving agents (other people's may show up too).

3. **If something is left** (the bridge was killed hard with `kill -9`, the
   machine slept or lost power, or it printed `not everything was deleted`), the
   ids are still in `fit/out/app_serving_state.json`:

   ```sh
   python3 fit/cleanup.py            # lists what it would delete, stage by stage
   python3 fit/cleanup.py --yes      # deletes it
   ```

   It also finds agents the bridge replaced (from the bundle's own listing),
   cancels a running agent before deleting it, and removes the state file when
   done. Without a state file, an agent of yours from the listing above can be
   removed by its id:

   ```sh
   curl -s -X POST "$ATAI_API_ENDPOINT/agents/instances/<agt_id>/cancel" -H "Authorization: Bearer $ATAI_API_KEY" \
     -H "Content-Type: application/json" -d '{}'
   curl -s -X DELETE "$ATAI_API_ENDPOINT/agents/instances/<agt_id>" -H "Authorization: Bearer $ATAI_API_KEY"
   ```

   Its bundle (`bnd_…`, from `GET /agents/instances/<agt_id>`) can then be
   deleted with `DELETE /agents/bundles/<bnd_id>`; a bundle that still has any
   agent, even a cancelled one, answers 409.

`fit/library_embeddings.py`'s 3 batch agents and their bundle hold no serving
worker; `fit/cleanup.py --yes` deletes them too, with the rest of the platform
path's agents (see the [repo README](../README.md)), whenever you're done with them.

## Ports

| MQTT TCP | MQTT WS | Web | Agent admin |
|---|---|---|---|
| 1891 | 9009 | 5181 | 9101 (the serving bridge) |

## Layout

| Path | What |
|---|---|
| `scripts/serving-bridge.js` | the agent: broker ↔ serving agent on the platform, the edge runtime's admin API |
| `scripts/replayer.js` | replays Stage 6's delivery files one at a time, paced by the agent, holding while it starts; reads `app-serving/.env` |
| `scripts/common.js` | what the two scripts share: the repo path and the `.env` files (the repo's for the key, `app-serving/.env` for the app's settings, where an `ATAI_*` line is ignored) |
| `scripts/run-broker.sh`, `scripts/stop.sh`, `mosquitto/` | the broker on 1891 / 9009, and stopping everything (matched by `--app red-serving`, so other demos are left alone) |
| `static/red-embedding-landscape.json` | the recomputed cloud and projection, from `fit/library_embeddings.py` |
| `src/` | the SvelteKit workbench, on the Archetype AI design system 0.19 (`@archetypeai/ds-lib-tokens` and `ds-ui-svelte-console`, from npm) |
| `src/lib/components/ui/` | `patterns/` (the menubar and its lockup, the pane), `custom/` (the panels, the pump plate, the embedding space, Settings) and `primitives/` (Slider and ScrollArea, which the design system's package doesn't ship) |
| `CLAUDE.md`, `ds-manifest.json` | the design system's guide and component catalogue for coding agents, from `npx @archetypeai/ds-cli add ds-config-codeagent --claude`: regenerate them rather than edit |

## Data attribution

The same as the repo: the Kaggle pump sensor dataset, which declares no licence;
see the [repo README](../README.md#data-attribution).
