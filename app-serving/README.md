# RED Pump Monitor, served from the platform

A live monitor for the quickstart's agent. Stage 6's delivery files are replayed
as if the pump were running now, and every window goes to a **serving agent** of
the classifier Stage 5 promoted, on the Archetype AI platform. The answers come
back to the sensor traces, the verdict, a timeline and an embedding space.

> **Dev only.** Agent serving is on `https://api.dev.u1.archetypeai.app` for first
> internal tests. Dev has **3 serving workers for everyone**: this app holds one
> while it runs, and gives it back when you stop it.

It is the same app as the [full example's
`app-serving/`](https://github.com/archetypeai/rare-event-detection-agent-example/tree/main/app-serving),
with two differences: it serves this repo's promoted blueprint, and it replays the
**delivery** files (breakdowns #4 and #7, `data/roles/delivery/`), since this repo
ships no raw file. The agent gets each file's z-scored values as written, so every
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
│ time, data-time pace,     │────────────────▶│ keeps the last 64 rows,      │────────────────▶│ serving agent (Dev)      │
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
  On start it makes sure the served copy of
  the promoted blueprint exists (`…-served-records`, the one Stage 8 uses), creates
  a bundle with `output_embeddings: true` and starts a serving agent. Then, for
  every row, it sends the latest 64 rows as one query and publishes the answer on
  `red/results`, with the window's timestamps
  put back (a served agent numbers the rows 0–63 within a query).
- **It answers the replayer's admin calls** (`GET /status`, `POST /reset`,
  `POST /start`, `POST /shutdown` on :9101): a seek or incident switch resets the
  bridge's buffer, so no window mixes two sections. The replayer starts before the agent is up; the bridge holds the
  windows until it is, and the replayer's flow control waits for them.
- **The API key never reaches the browser.** The bridge reads `ATAI_API_ENDPOINT`
  and `ATAI_API_KEY` from the repo's `.env`, the same file the Python stages use.
- **On exit** (Ctrl-C, `npm run stop`) the bridge cancels and deletes its agent and
  deletes its bundle. If it's killed hard, the ids are still in
  `fit/out/app_serving_state.json`, and `python3 fit/cleanup.py --yes` removes them.
  An agent the platform released after 20 minutes without a query (a replay paused
  that long) is deleted and replaced on the next window, retrying while Dev's
  serving workers are all taken. If anything can't be deleted on exit, the bridge
  says so and keeps the ids for `fit/cleanup.py`.

**Checked on Dev, 2026-10-16:** breakdown #4's demo window (rows 784–1,869 of
`inc04.csv`), 1,023 windows: every `predicted_state` and every probability
identical to Stage 6's output for the same window, 0 invalid, each with its
10 × 768 embeddings, 301 ms median per query.

## The embedding space: the training windows, recomputed

The promoted classifier is a registry artifact (`aar_…`) with no download route,
and the Optimizations and Evals APIs return metrics and predictions, not
embeddings. So the training windows are encoded again, on the platform:

```sh
python3 fit/library_embeddings.py     # once, from the repo root: 3 batch runs, ~1-30 min with Dev's load
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
run on Dev (`fit/out/test_state.json` names the promoted blueprint). In the
[repo README](../README.md) this is Stage 9. Then:

```sh
python3 fit/library_embeddings.py     # once, from the repo root (writes static/red-embedding-landscape.json)
cd app-serving
npm install
npm run dev                           # broker + serving bridge + replayer + web
open http://localhost:5181
```

`npm run stop` stops all four and checks the ports. To see whether a serving agent
is still running (yours or anyone's), from the repo root:

```sh
set -a; source .env; set +a
curl -s "$ATAI_API_ENDPOINT/agents/instances?status=running&limit=100" -H "Authorization: Bearer $ATAI_API_KEY" \
  | jq -c '.data[] | select(.mode=="serving") | {id, blueprint, name, created_at}'
```

`status=running` filters on the server; `mode=serving` is ignored there, so `jq`
picks the serving agents. The bridge's agent is named `RED app-serving`.

### Pace

The platform answers a window in about a third of a second, so the replay runs at
about 3 rows a second: the replayer holds off whenever the agent falls behind.
Breakdown #4's demo window (240 rows either side of the breakdown) takes about
6 minutes, a whole delivery file about 13. Every window is asked about (step 1),
so every verdict is the one Stage 6 delivered.

## Ports

| MQTT TCP | MQTT WS | Web | Agent admin |
|---|---|---|---|
| 1891 | 9009 | 5181 | 9101 (the serving bridge) |

The same slot as the full example's `app-serving/`, so run one of the two at a time.

## Layout

| Path | What |
|---|---|
| `scripts/serving-bridge.js` | the agent: broker ↔ serving agent on the platform, the edge runtime's admin API |
| `scripts/replayer.js` | replays Stage 6's delivery files one at a time, paced by the agent |
| `scripts/run-broker.sh`, `scripts/stop.sh`, `mosquitto/` | the broker on 1891 / 9009, and stopping everything (matched by `--app red-serving`, so other demos are left alone) |
| `static/red-embedding-landscape.json` | the recomputed cloud and projection, from `fit/library_embeddings.py` |
| `src/` | the SvelteKit workbench |

## Data attribution

The same as the repo: the Kaggle pump sensor dataset, which declares no licence;
see the [repo README](../README.md#data-attribution).
