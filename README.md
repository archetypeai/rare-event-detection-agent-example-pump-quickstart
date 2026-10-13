# Rare Event Detection on a water pump: quickstart

## TL;DR

- **What:** an agent that watches a water pump's sensors, one reading a minute,
  and flags when the pump has broken down. It learns from **two labelled
  breakdowns** and normal operation: each window of readings is embedded with
  frozen Omega 1.5, and a nearest-prototype classifier compares it with one
  average embedding per class (`normal`, `pump_breakdown`).
- **Data:** a Kaggle recording of one pump over five months, with seven
  breakdowns. It declares [no licence](#data-attribution): Stage 0 downloads the
  raw file with your own Kaggle account; the prepared and role files are in the
  repo.
  - **Training:** normal operation from early April and the first two breakdowns.
  - **Validation and test:** breakdown #3 picks the settings; #4–#7 are the
    one-shot test.
  - **Delivery:** breakdowns #4 and #7 again, run as agents with their labels held
    back, the way an operator would run the agent.
- **The lifecycle:**

| stage | what happens | time (measured 2026-10-13) |
|---|---|---|
| 0 | download the dataset (12 MB zipped) from Kaggle | your connection |
| 1a–1c | check the raw data, prepare it, check again | ~6 s |
| 2–3 | build the files the platform receives, and check them | ~1 s |
| 4 | **Optimize:** fit the prototypes, score 4 distance metrics on validation | 3 min |
| 5 | **promote** the best to a blueprint, **test** it once with the Evals API | 4 min |
| 6 | **deliver:** a bundle from that blueprint, run over the delivery files | 1 min |
| 7 | **score** the delivery against the held-back labels | seconds |

  About **10 minutes** end to end, 8 of them on the platform. Platform times
  vary with load: the same agent runs went at ~4 windows a second that morning
  and ~50 by the afternoon, which would make Stage 6 about 20 minutes.

- **Skip the download:** Stage 1's prepared files and the role files are in the
  repo, in Git LFS. See [Shortcuts](#shortcuts-skip-the-download).

## The scenario

- **A plant has had a handful of failures and labelled two of them.** It wants to
  know when the same thing happens again. Here: a water pump, broken down seven
  times in five months; the customer labels the first two.
- **Settings are chosen on the next breakdown** (validation): #3.
- **We report how the agent does on breakdowns it has never seen** (the test),
  once: #4–#7.
- **We then run it as agents** (the delivery) on #4 and #7 with their labels
  hidden, and score the outputs afterwards: whether each breakdown is caught, how
  soon, and how often the agent fires on normal operation.

### The pump and its breakdowns

220,320 rows, one a minute from 2018-04-01 to 2018-08-31, 52 sensor channels and
a `machine_status`: `NORMAL`, `BROKEN` (one row, the moment of failure) or
`RECOVERING` (the pump down until it is back). `BROKEN` and `RECOVERING` become
one class, `pump_breakdown`: **the agent recognises that the pump has broken down
and is down**, it does not predict the failure.

| # | date | length | role |
|---|---|---|---|
| 1 | 04-12 | 945 rows (16 h) | training |
| 2 | 04-18 | 3,111 rows (2.2 days) | training |
| 3 | 05-19 | 1,313 rows (22 h) | validation |
| 4 | 05-25 | 606 rows (10 h) | test; delivery |
| 5 | 06-28 | 8,391 rows (5.8 days) | test |
| 6 | 07-08 | **42 rows (42 min)** | test |
| 7 | 07-25 | 76 rows (1.3 h) | test; delivery |

Prep keeps 10 of the 52 channels, all motor and bearing measurements: it drops the
8 that go dark during breakdowns (a perfect but meaningless predictor) and 4 with
gaps longer than the platform repairs, then keeps the 10 that best separate the
two training breakdowns from normal, chosen on April data only.

### What each role's files are

Each breakdown is the unit no two roles share; normal context around a
breakdown is cut at the midpoint to the next one, so no row is in two of
training, validation and test.

| role | data | files | rows (normal / breakdown) | labels | used in |
|---|---|---|---|---|---|
| training | normal rows 0–8,191 (April); breakdowns #1, #2 | 3, one per class piece | 8,192 / 4,056 | one class per file, set in the request | 4: every trial |
| validation | breakdown #3 with 4,096 rows of normal context before it | 1 | 7,675 / 1,313 | `label` column | 4: scores each trial |
| test | breakdowns #4–#7, each with up to 4,096 rows of context either side | 4 | 28,760 / 9,115 | `label` column | 5: scored once |
| delivery | breakdowns #4 and #7, 1,024 rows of context either side | 2 | 4,096 / 682 | none (held back in `labels/`) | 6: run; 7: scored |

- **The window is 64 rows (64 minutes)**, the largest that a 42-minute breakdown
  can still fill half of: the classifier compares whole windows, so a breakdown
  shorter than half a window barely moves one.
- **Delivery re-runs two test breakdowns.** Evals already scored them; delivery
  runs the blueprint as an operator would, a bundle at one prediction per row, and
  scores what comes out. #4 and #7 are a long and a short breakdown the test
  caught; #6, the 42-minute one, is missed by every configuration tried.

## Setup

```sh
git clone https://github.com/archetypeai/rare-event-detection-agent-example-pump-quickstart.git
cd rare-event-detection-agent-example-pump-quickstart
python3 -m venv .venv
source .venv/bin/activate          # every later command assumes this
pip install -r requirements.txt    # numpy, pandas
cp .env.example .env               # then set ATAI_API_KEY (needed from Stage 4 on)
```

and a **Kaggle API token** for Stage 0: Kaggle → Settings → API → Create New
Token saves `kaggle.json`; put it in `~/.kaggle/`, or set `KAGGLE_USERNAME` and
`KAGGLE_KEY`.

### Shortcuts: skip the download

Stage 1's output (`data/prepared/`, 8 MB) and Stage 2's (`data/roles/`, 7 MB)
are in the repo, in Git LFS; a clone fetches them (`git lfs pull` if it did
not).

- **Skip Stages 0–2:** `data/roles/` holds everything Stages 3–7 read.

  ```sh
  python3 prep/preflight_roles.py    # Stage 3: all checks pass
  ```

- **Skip Stages 0–1** and build the role files yourself:

  ```sh
  python3 prep/build_roles.py        # Stage 2
  python3 prep/preflight_roles.py    # Stage 3
  ```

  The Stage 1 checks (`prep/run_preflight.py`) need the raw file, so they come
  with Stage 0.

Then go to [Stage 4](#stage-4-optimize).

## The stages

**To run again from scratch,** move `fit/out/` and `eval_out/` aside first: they
hold this repo's run (state files with its ids), and with them `test.py` and
`deliver.py` resume that run instead of starting a new one. Every script runs
from the repo root and is safe to rerun.

### Stage 0: download

```sh
python3 prep/download.py                 # Kaggle API, with your token → data/raw/sensor.csv
python3 prep/download.py --from PATH     # or a sensor.csv you already have
```

Downloads `nphantawee/pump-sensor-data` (12 MB zipped, 124 MB of CSV) and checks
its SHA-256 against the file this example was built from. **Expect:**
`data/raw/sensor.csv: 124,058,460 bytes, SHA-256 matches`.

### Stage 1: check, prepare, check again

```sh
python3 prep/run_preflight.py --raw                  # 1a: the raw file, read-only
python3 prep/prepare_pump_events.py                  # 1b: → data/prepared/
python3 prep/run_preflight.py --window-size 64       # 1c: the prepared training files, read-only
```

- **1a** runs Archetype AI's preflight checks on the raw file. **Expect:**
  `4 PASS, 2 WARN, 0 FAIL`. The WARNs prescribe prep decisions: 52 channels have
  gaps ("forward-fill or drop column; do NOT drop rows"), and `sensor_15` is
  empty.
- **1b** labels the seven breakdowns, drops the channels that go dark exactly when
  the pump fails (dropout would become the signature), keeps 40 that the
  platform can repair, selects 10 on April data, z-scores them with April's
  normal rows and cuts the training files and the slices. **Expect:**

  ```
  ── labels: 205,836 normal, 14,484 pump_breakdown (6.57%) in 7 incidents
     dropped, NaN fraction > 1% (8): sensor_00, sensor_06, sensor_07, sensor_08, sensor_09, sensor_15, sensor_50, sensor_51
     dropped, NaN run > 16 (4): sensor_01, sensor_29, sensor_30, sensor_32
  ```

  and the 10 channels `sensor_02 03 04 05 10 11 12 38 41 42`.
- **1c** re-checks the three training files. **Expect:** `26 PASS, 3 WARN,
  0 FAIL`. The WARNs are about class balance and breakdown #1's 945 rows; a
  nearest-prototype classifier averages each class to one point, so neither
  matters here.

### Stage 2: build the role files

```sh
python3 prep/build_roles.py           # → data/roles/
```

**Expect:**

```
training    3 files   12,248 rows   4,056 fault
validation  1 files    8,988 rows   1,313 fault
test        4 files   37,875 rows   9,115 fault
delivery    2 files    4,778 rows     682 fault
```

### Stage 3: check the role files against the platform's rules

```sh
python3 prep/preflight_roles.py
```

It checks every file is on an exact 60-second grid with the same 10 channels
and no gaps; no row in two of training, validation and test; each delivery slice
inside its breakdown's test slice; labels only where they are scored, with both
classes in validation and test; each training file a single class; and that
every scored breakdown can fill half a window. **Expect:** 15 `PASS` lines, then
`all checks pass`.

### Stage 4: Optimize

```sh
python3 fit/optimize.py
```

1. **Upload** the 3 training files and the validation file. Ids are cached in
   `fit/out/uploads.json`.
2. **Optimize:** create an optimization on the `red` blueprint. Each training
   file is labelled by its class; the validation file is scored on its `label`
   column. The platform embeds every window with Omega 1.5, averages each class's
   embeddings into a prototype and reports the fault F1
   (`event.foreground_macro_f1`) on validation.
3. **Search space:** window 64, one prediction per row (step 1), and the
   classifier's only setting, the **distance metric**: `cosine`, `l1`, `l2` and
   `dot`. The four trials share one pass of the encoder.

**Expect** `uploading 4 of 4 files (2.3 MB)`, `4 trial(s), searching ['metric']`,
then the ranking. Ours:

```
otr_…  completed {"metric": "dot"}     foreground_macro_f1 0.8588  macro_f1 0.9161  detection_recall 0.9216  detection_precision 0.8040
otr_…  completed {"metric": "cosine"}  foreground_macro_f1 0.8474  macro_f1 0.9091  detection_recall 0.9238  detection_precision 0.7826
otr_…  completed {"metric": "l2"}      foreground_macro_f1 0.8400  macro_f1 0.9046  detection_recall 0.9238  detection_precision 0.7702
otr_…  completed {"metric": "l1"}      foreground_macro_f1 0.8328  macro_f1 0.9001  detection_recall 0.9238  detection_precision 0.7581
```

`dot` wins: of the 1,313 breakdown windows it catches 1,210 (recall 0.92), and
four in five of its alarms are real (precision 0.80). The fault F1 is scored
with each row counted once, which at one prediction per row means each window
is labelled by its last row.

Try others with `--new` and `--window` (a list, or `LOW:HIGH`), `--step`,
`--metric`, `--trials`. **Writes:** `fit/out/optimize_<optimization id>.json`.

### Stage 5: promote, then test once

```sh
python3 fit/test.py
```

1. **Promote** the best trial to a blueprint, `red-pump-<trial>`: its settings
   and fitted prototypes become a reusable model.
2. **Evaluate** the 4 test files **once** with the Evals API, with predictions.
3. **Check** every prediction's gold label against the file, and the offline
   confusion matrix against the platform's, then score each breakdown: caught or
   missed, how soon, and false alarms on windows with no breakdown row.

**Expect** (ours):

```
eval evl_…  blueprint red-pump-otr_…  (window 64, step 1, dot; 0 abstained)
  platform (each row once): fault F1 0.9642  macro-F1 0.9762  recall 0.9820  precision 0.9470
  whole-window majority (as fit/evaluate_events.py): fault F1 0.9697  tp 9004 fp 448 fn 115 tn 28056
  false alarms 369 / 28,256 = 0.0131 (windows with no fault row)
    inc04    606 rows  +54 samples    false alarms   45 / 7,550
    inc05  8,391 rows  +0 samples     false alarms  324 / 6,320
    inc06     42 rows  MISSED         false alarms    0 / 6,320
    inc07     76 rows  +60 samples    false alarms    0 / 8,066
```

- **Three of four unseen breakdowns caught**, from two labelled examples: the
  5.8-day #5 on the first window that can show it, #4 54 minutes in, #7 an hour
  in. **#6, 42 minutes long, is missed**, with no false alarm on its slice
  either: too short to move a 64-minute window toward the breakdown prototype.
- **False alarms: 1.31%** of the windows with no breakdown row, most of them
  (324) in the days around #5.
- **Two fault F1s, two labelling rules:** the platform's (each row once: 0.9642)
  and the design rule's (each window by the majority of its rows: 0.9697).
- **This is the one-shot test.** Once you have seen its number, the setting is
  frozen: tuning it further would make the test number optimistic.

**Writes:** `fit/out/test.json`, `fit/out/test-predictions.ndjson` and
`fit/out/test_state.json` (the ids, so a rerun resumes instead of testing again).

### Stage 6: deliver

```sh
python3 fit/deliver.py
```

1. **Bundle:** create a bundle from Stage 5's blueprint, adding only
   `step_size: 1`: one prediction per row.
2. **Run** it over `data/roles/delivery/`, both files at once, uploaded without
   labels.
3. **Download** each output, again until it covers its input (a run can report
   `completed` while its output is still being written).

**Expect:** `bundle bnd_… (ready) on red-pump-otr_…`, two `agent agt_…` lines,
`inc04.csv: complete`, `inc07.csv: complete`, then Stage 7's scores. Each agent
took about 45 seconds here. **Writes:** `eval_out/delivery/red-output-*.csv` and
`fit/out/deliver_state.json`.

### Stage 7: score the delivery

`fit/deliver.py` ends by scoring; to score again:

```sh
python3 fit/evaluate_events.py --window-size 64 --labels data/roles/labels \
    --slices inc04,inc07 --platform-output eval_out/delivery/red-output-inc0{4,7}.csv
```

Each window is labelled by the majority of its rows (the design rule), then
scored three ways: window precision and recall; each breakdown caught or missed,
and how many minutes after onset; false alarms on windows with no breakdown row.

**Expect** (ours):

```
══ inc04  (2,591 scored, 0 invalid, 0 unmatched)
   pump_breakdown  P 0.9040  R 0.9621  F1 0.9322  (n=607)
   false alarms    45/1922 = 0.0234 (windows with zero fault rows)
   incident rows 1024-1630 (len 606): DETECTED by 601 window(s), +54 samples after onset
══ inc07  (2,061 scored, 0 invalid, 0 unmatched)
   pump_breakdown  P 1.0000  R 0.3636  F1 0.5333  (n=77)
   false alarms    0/1922 = 0.0000 (windows with zero fault rows)
   incident rows 1024-1100 (len 76): DETECTED by 28 window(s), +60 samples after onset
POOLED over 2 slices (4,652 windows)
   pump_breakdown P 0.9080 R 0.8947 F1 0.9013
   false alarms 45/3844 = 0.0117
   incidents detected: 2/2
```

- **Both breakdowns caught, at the same minute as the test** (+54 and +60): the
  agent runs and the Evals run give the same answers on the same rows.
- **#7 is caught late and briefly:** 28 of its 77 breakdown windows, starting an
  hour in. A 76-minute breakdown fills a 64-minute window only near its end.
- **#4's 45 false alarms are the test's 45**, all within 1,024 rows of the
  breakdown: the agent fires in the hours around it, not on quiet operation.
  That is why the delivery's false-alarm rate (1.17%) is close to the test's
  (1.31%) even with far less normal context.

**Writes:** `eval_out/delivery/evaluation-slices.json`.

## Results

| stage | measure | ours |
|---|---|---|
| 1–3 | prepared and role files | byte-identical to the full example's; every role check passed |
| 4 | fault F1 on breakdown #3, `dot` / `cosine` / `l2` / `l1` | 0.8588 / 0.8474 / 0.8400 / 0.8328: the full example's, to four decimals |
| 5 | test: fault F1 (whole-window); false alarms; breakdowns caught | 0.9697; 1.31%; 3 of 4 (+54, +0, missed, +60): the full example's |
| 6–7 | delivery: fault F1; false alarms; breakdowns caught | 0.9013; 1.17%; 2 of 2 (+54, +60) |

Prep, Optimize and Evals are deterministic here: this run, from fresh uploads,
a new optimization and a new promoted blueprint, matches the full example's to
the last digit. We ran Stages 4–7 twice from scratch; the second run's 37,623
test predictions and both delivery outputs are byte-identical to the first's,
and only the platform ids differ (`fit/out/` holds the second). If yours differs, something differs in your data or setup, and
the expected outputs above show at which stage.

## What's left out, compared with the full example

| full example | here | why |
|---|---|---|
| delivery of all four test breakdowns and five weeks of normal operation after them | breakdowns #4 and #7, short context | time: ~87,000 windows instead of ~4,700, hours of agent runs at the rates measured that day |
| a 12-point search over windows 16–64, a check of 48 and 80, and a random search | the 4 metrics at window 64 | the window search found window 64 and cost more platform time; the winner is the same |
| the first design: a local grid with Omega 1.5, `red-fitting`, an `s3://` classifier; a live on-device app | none | |

## Repo layout

| path | what it is |
|---|---|
| `prep/download.py` | Stage 0: the Kaggle download, SHA-256-checked |
| `prep/run_preflight.py`, `prep/preflight_static.py` | Stages 1a and 1c |
| `prep/prepare_pump_events.py` | Stage 1b |
| `prep/build_roles.py`, `prep/preflight_roles.py` | Stages 2 and 3 |
| `red_api.py`, `fit/atai.py` | stdlib platform helpers: requests, uploads, polling, resume state |
| `fit/optimize.py` | Stage 4 |
| `fit/test.py` | Stage 5 |
| `fit/deliver.py` | Stage 6, then Stage 7's scoring |
| `fit/evaluate_events.py` | Stage 7 |
| `data/prepared/` | Stage 1's output: training files, slices and label sidecars, z-score stats, `prep_report.json` (Git LFS) |
| `data/roles/` | Stage 2's output: the role files and labels Stages 3–7 read (Git LFS) |
| `fit/out/`, `eval_out/delivery/` | this repo's run: state and results |

## Licence

The code is under the [Apache License 2.0](LICENSE). The data is not covered by
it: see [Data attribution](#data-attribution).

## Data attribution

The sensor data comes from the Kaggle dataset **`pump_sensor_data`**, "Pump
sensor data for predictive maintenance", published by the Kaggle user
[`nphantawee`](https://www.kaggle.com/nphantawee) on 2019-03-04:
https://www.kaggle.com/datasets/nphantawee/pump-sensor-data. The uploader
credits a friend's operations team, who look after the water pump of a small,
remote area and shared the data so its failures could be understood.

| | |
|---|---|
| Title | `pump_sensor_data` |
| Publisher | Kaggle user `nphantawee` |
| Published | 2019-03-04 |
| Contents | 220,320 rows, 52 raw sensor channels, 1-minute cadence, `machine_status` label |
| Licence | none declared on the Kaggle dataset page |

**What is in this repo:** not the raw file, which `prep/download.py` fetches
from Kaggle with your own account. `data/prepared/` and `data/roles/` are
derived from it: 10 of the 52 channels, gaps of up to 16 readings interpolated,
z-scored with April's normal readings, cut into the files above, with a
`label` from `machine_status` (`BROKEN` and `RECOVERING` as `pump_breakdown`).
`eval_out/` and `fit/out/` hold this repo's run on them.
