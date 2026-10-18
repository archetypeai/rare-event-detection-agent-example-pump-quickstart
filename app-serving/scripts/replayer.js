#!/usr/bin/env node
/**
 * Replay a held-out pump incident as a live sensor stream over MQTT.
 *
 * Publishes every row twice, because the agent and the browser need different
 * things from it:
 *
 *   sensors/red   z-scored, key=value, canonical channel order — the
 *                 classifier's contract. Normalised with the very same
 *                 pump_zscore_stats.json the prototypes were built from; using
 *                 different stats silently degrades accuracy.
 *   pump/raw      raw engineering units + the ground-truth label, as JSON —
 *                 what the dashboard charts. Never seen by the agent.
 *
 * Pacing follows the data's own timestamps divided by a speed factor, and the
 * published timestamps stay original. The agent therefore validates *data time*,
 * so results are identical at any replay speed — 1-minute pump cadence at 250x
 * is one sample per 240 ms.
 *
 * SPEED is an upper bound, not a promise. The on-device agent encodes only a few
 * windows per second on CPU (10 variates x 64 samples is 10 encoder passes per
 * window, and it already pegs 11 cores), and publishing faster than it can encode
 * grows the broker queue without bound — results drift further behind the chart
 * the longer it runs. So the replayer watches `red/results` and holds off whenever
 * more than MAX_INFLIGHT windows are outstanding. That self-tunes to whatever
 * hardware the demo runs on instead of trusting a speed measured on one laptop.
 *
 * At a sustainable speed the full 8,798-row slice takes ~35 min and inc04's fault
 * does not start until row 4,096, so the replay defaults to a *demo window*
 * anchored on the incident: LEAD_ROWS of normal, the fault, then TAIL_ROWS. The
 * whole slice stays loaded and seekable — only the default playhead and the loop
 * bounds are narrowed.
 *
 *   pump/status   retained; {playing, slice, row, totalRows, speed, epoch, ...}
 *   pump/control  subscribed; {action: play|pause|seek|speed|slice|reset|onset, value?}
 *
 * `epoch` bumps on every discontinuity (seek, reset, slice change) so the app can
 * clear its buffers. A discontinuity also makes the agent emit INVALID_STATE for
 * the windows that straddle it, which is correct behaviour — see resetAgent().
 */
import fs from 'node:fs';
import path from 'node:path';
import mqtt from 'mqtt';
import { REPO, loadEnv } from './common.js';

// SLICE, SPEED and the ports from app-serving/.env (.env.example lists them).
loadEnv();
// Repo-relative by default; overridable so the data can live elsewhere.
const PREPARED = process.env.PREPARED_DIR ?? path.join(REPO, 'data/prepared');
// The quickstart ships no raw file (it's a Kaggle download): the replay is
// Stage 6's delivery files, already z-scored, with their labels beside them.
const ROLES = process.env.ROLES_DIR ?? path.join(REPO, 'data/roles');

const BROKER = process.env.BROKER ?? `mqtt://127.0.0.1:${process.env.MQTT_PORT ?? 1891}`;
const AGENT_ADMIN = process.env.AGENT_ADMIN ?? `http://127.0.0.1:${process.env.AGENT_PORT ?? 9101}`;
const T_SENSORS = 'sensors/red';
const T_RAW = 'pump/raw';
const T_STATUS = 'pump/status';
const T_CONTROL = 'pump/control';
const T_RESULTS = 'red/results';   // subscribed only to count, for flow control

const manifest = JSON.parse(fs.readFileSync(path.join(ROLES, 'manifest.json'), 'utf8'));
const zstats = JSON.parse(fs.readFileSync(path.join(PREPARED, 'pump_zscore_stats.json'), 'utf8'));
const CHANNELS = manifest.channels;

/** Stage 6's delivery files, keyed by short name. */
const SLICES = manifest.delivery
  .map((d) => ({
    id: d.file.match(/inc\d+/)[0],
    incident: d.incident,
    file: path.join(ROLES, d.file),
    labels: path.join(ROLES, d.labels),
    from: d.rows[0],
    rows: d.n_rows,
    faultRows: d.fault_rows,
  }))
  .sort((a, b) => a.incident - b.incident);

/** Rows of context on each side of the fault in the default demo window. */
const LEAD_ROWS = Number(process.env.LEAD_ROWS ?? 240);
const TAIL_ROWS = Number(process.env.TAIL_ROWS ?? 240);
/** Windows the agent may owe us before the replayer stops publishing. */
const MAX_INFLIGHT = Number(process.env.MAX_INFLIGHT ?? 48);
const WINDOW_SIZE = 64;      // must match the blueprint; the warm-up owes no result
const STALL_MS = 20_000;     // give up waiting on the agent after this

const state = {
  playing: true,
  loading: false,
  slice: process.env.SLICE ?? 'inc04',
  speed: Number(process.env.SPEED ?? 250),
  throttled: false,    // true while waiting for the agent to catch up
  row: 0,
  totalRows: 0,
  demoStart: 0,        // loop bounds; the full slice stays seekable
  demoEnd: 0,
  onsetRow: null,      // first fault row, for the UI's ground-truth marker
  epoch: 0,
  timestamp_ms: 0,
};

let rows = [];              // the loaded slice, raw values + label
let timer = null;
const client = mqtt.connect(BROKER, { clientId: `red-replayer-${process.pid}` });

/**
 * Flow control. `published` counts samples sent since the last discontinuity;
 * `classified` counts windows the agent has returned. The first WINDOW_SIZE - 1
 * samples fill the window and produce nothing, so they are never "owed".
 */
let published = 0;
let classified = 0;
let throttledSince = 0;
let throttledAt = 0;
const inflight = () => Math.max(0, published - (WINDOW_SIZE - 1) - classified);

/**
 * The agent, as the bridge reports it on GET /status, polled. While the bridge is
 * starting its agent (or replacing a released one, or waiting for a free serving
 * worker, which can take minutes) the replay holds: rows published then would only
 * queue in the bridge. A new agent id means the bridge started over, and answers
 * owed by the old one may never come, so the debt is forgotten. A bridge that
 * doesn't answer at all is left to the STALL_MS timeout.
 */
const agent = { starting: false, id: null };
async function pollAgent() {
  try {
    const s = await (await fetch(`${AGENT_ADMIN}/status`, { signal: AbortSignal.timeout(2000) })).json();
    const id = s.agent ?? null;
    if (s.state === 'Running' && agent.id !== null && id !== agent.id) {
      console.log(`replayer: new agent ${id}; not waiting for the old one's answers`);
      classified = Math.max(classified, published - (WINDOW_SIZE - 1));
    }
    agent.starting = s.state !== 'Running';
    if (s.state === 'Running') agent.id = id;
  } catch {
    agent.starting = false;
  }
}
pollAgent();
setInterval(pollAgent, 2000);

const sliceById = (id) => SLICES.find((s) => s.id === id) ?? SLICES[0];

function publishStatus() {
  client.publish(
    T_STATUS,
    JSON.stringify({
      ...state,
      slices: SLICES.map(({ id, incident, rows, faultRows }) => ({ id, incident, rows, faultRows })),
      channels: CHANNELS,
    }),
    { qos: 1, retain: true },
  );
}

/**
 * Read one delivery file and its labels. The agent gets the file's z-values as
 * written (so every window matches Stage 6's); the charts get them back in
 * engineering units, through the same z-score stats.
 */
async function loadSlice(id) {
  const s = sliceById(id);
  state.loading = true;
  state.slice = s.id;
  publishStatus();

  const out = [];
  const lines = fs.readFileSync(s.file, 'utf8').trim().split('\n');
  const labels = fs.readFileSync(s.labels, 'utf8').trim().split('\n').slice(1).map((l) => l.split(',')[1]);
  const header = lines[0].split(',');
  lines.slice(1).forEach((line, i) => {
    const cells = line.split(',');
    const row = { row: s.from + i, z: {} };
    for (const c of CHANNELS) {
      const z = cells[header.indexOf(c)];
      const v = Number(z);
      row.z[c] = Number.isFinite(v) ? z : null;
      row[c] = Number.isFinite(v) ? v * (zstats[c].std || 1) + zstats[c].mean : null;
    }
    row.timestamp_ms = Number(cells[header.indexOf('timestamp')]) * 1000;
    row.label = labels[i] === 'normal' ? 'normal' : 'pump_breakdown';
    out.push(row);
  });

  // Carry forward the last finite value for the few short NaN runs prep would
  // have interpolated. The agent also repairs gaps up to 16 samples itself.
  const last = {};
  for (const row of out) {
    for (const c of CHANNELS) {
      if (row[c] === null) row[c] = last[c] ?? 0;
      else last[c] = row[c];
    }
  }

  rows = out;
  state.totalRows = out.length;

  // Anchor the demo window on the fault so the incident arrives in ~1 minute
  // rather than ~16. Seeking outside it is still allowed.
  const onset = out.findIndex((r) => r.label !== 'normal');
  let lastFault = -1;
  for (let i = out.length - 1; i >= 0; i--) if (out[i].label !== 'normal') { lastFault = i; break; }
  state.onsetRow = onset === -1 ? null : onset;
  state.demoStart = onset === -1 ? 0 : Math.max(0, onset - LEAD_ROWS);
  state.demoEnd = lastFault === -1 ? out.length - 1 : Math.min(out.length - 1, lastFault + TAIL_ROWS);
  state.row = state.demoStart;

  console.log(`loaded ${s.id}: ${out.length} rows (incident #${s.incident}, ${s.faultRows} fault)`);
  console.log(`  demo window rows ${state.demoStart}-${state.demoEnd}, onset at ${state.onsetRow}`);
  await bumpEpoch();
}

/**
 * Clear the agent's in-flight window across a discontinuity.
 *
 * Two calls, not one: a soft reset stops the graph and leaves it `Loaded`, so it
 * has to be started again. (`hard` would re-read the blueprint from disk, which
 * we don't want — it would also reload the 768-dim encoder.)
 *
 * Without this, the ~64 windows straddling the jump come back INVALID_STATE,
 * because the timestamp gap trips the sampling-rate validator. That's correct
 * behaviour, but it reads as a bug on a dashboard. Resetting trades those
 * invalid windows for a clean warm-up gap of the same length.
 *
 * The agent's MQTT source disconnects while this happens, and the broker drops
 * what it can't deliver, so callers must not be publishing during the await.
 */
async function resetAgent() {
  try {
    const r = await fetch(`${AGENT_ADMIN}/reset`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ mode: 'soft' }),
    });
    if (!r.ok) throw new Error(`reset ${r.status}: ${await r.text()}`);
    const s = await fetch(`${AGENT_ADMIN}/start`, { method: 'POST' });
    if (!s.ok) throw new Error(`start ${s.status}: ${await s.text()}`);
    await waitForSource();
  } catch (e) {
    // Not fatal: the replayer is useful on its own, and the dashboard just sees
    // the invalid windows the reset would have avoided.
    console.warn(`agent reset skipped (${e.message})`);
  }
}

/** Poll /status until the graph is Running again, so we don't publish into a gap. */
async function waitForSource(timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const s = await (await fetch(`${AGENT_ADMIN}/status`)).json();
      if (s.state === 'Running') return;
    } catch { /* keep waiting */ }
    await new Promise((r) => setTimeout(r, 150));
  }
  console.warn('agent did not report Running within 5s; continuing anyway');
}

/** Mark a discontinuity: tell the UI to clear, and clear the agent's window. */
async function bumpEpoch() {
  state.epoch += 1;
  state.loading = true;          // gates tick() so nothing is published mid-reset
  publishStatus();
  await resetAgent();
  published = 0;                 // the agent's window is empty again
  classified = 0;
  state.loading = false;
  state.throttled = false;
  publishStatus();
}

function publishRow(row) {
  const kv = [`timestamp_ms=${row.timestamp_ms}`];
  for (const c of CHANNELS) {
    const { mean, std } = zstats[c];
    kv.push(`${c}=${row.z?.[c] ?? ((row[c] - mean) / (std || 1)).toFixed(6)}`);
  }
  client.publish(T_SENSORS, kv.join(','), { qos: 1 });

  const channels = {};
  for (const c of CHANNELS) channels[c] = row[c];
  client.publish(
    T_RAW,
    JSON.stringify({ timestamp_ms: row.timestamp_ms, row: row.row, label: row.label, channels }),
    { qos: 1 },
  );
}

async function tick() {
  if (!state.playing || state.loading || rows.length === 0) return schedule(200);

  if (agent.starting) {
    if (!state.throttled) { state.throttled = true; publishStatus(); }
    throttledSince = Date.now();
    throttledAt = classified;
    return schedule(200);
  }

  // Hold off while the agent is behind, so the queue can't grow without bound.
  // Bounded wait: if no result arrives at all — agent stopped, or it is still
  // chewing an older backlog — publish anyway rather than freeze the demo.
  if (inflight() >= MAX_INFLIGHT) {
    if (!state.throttled) {
      state.throttled = true;
      throttledSince = Date.now();
      throttledAt = classified;
      publishStatus();
    }
    if (classified > throttledAt) { throttledSince = Date.now(); throttledAt = classified; }
    else if (Date.now() - throttledSince > STALL_MS) {
      console.warn(`no results for ${STALL_MS / 1000}s while ${inflight()} windows outstanding; ` +
                   'publishing anyway (is the agent running?)');
      throttledSince = Date.now();
      classified = published - (WINDOW_SIZE - 1);   // forget the debt, keep streaming
    }
    return schedule(100);
  }
  if (state.throttled) { state.throttled = false; publishStatus(); }

  const row = rows[state.row];
  publishRow(row);
  published += 1;
  state.timestamp_ms = row.timestamp_ms;
  state.row += 1;

  // Loop at the demo window's end (or the slice's, if seeked past it).
  if (state.row > state.demoEnd || state.row >= rows.length) {
    state.row = state.demoStart;
    await bumpEpoch();
    return schedule(1000);
  }
  if (state.row % 25 === 0) publishStatus();

  const dt = rows[state.row].timestamp_ms - row.timestamp_ms;
  schedule(Math.max(1, dt / state.speed));
}

function schedule(ms) { timer = setTimeout(tick, ms); }

client.on('connect', async () => {
  console.log(`replayer connected to ${BROKER}`);
  console.log(`slices: ${SLICES.map((s) => `${s.id}(#${s.incident})`).join(' ')}`);
  client.subscribe([T_CONTROL, T_RESULTS], { qos: 1 });
  await loadSlice(state.slice);
  schedule(0);
});

client.on('message', async (topic, buf) => {
  if (topic === T_RESULTS) { classified += 1; return; }   // flow-control feedback
  if (topic !== T_CONTROL) return;
  let msg;
  try { msg = JSON.parse(buf.toString()); } catch { return; }
  const { action, value } = msg;
  switch (action) {
    case 'play': state.playing = true; publishStatus(); break;
    case 'pause': state.playing = false; publishStatus(); break;
    case 'speed':
      // Not clamped: flow control already caps the effective rate, so a high
      // setting just means "as fast as the agent will go".
      state.speed = Math.max(1, Number(value) || 1);
      publishStatus();
      break;
    case 'onset': state.row = state.demoStart; await bumpEpoch(); break;
    case 'seek':
      state.row = Math.min(Math.max(0, Number(value) || 0), Math.max(0, rows.length - 1));
      await bumpEpoch();
      break;
    case 'reset': state.row = state.demoStart; await bumpEpoch(); break;
    case 'slice':
      if (sliceById(value).id !== state.slice) { clearTimeout(timer); await loadSlice(value); schedule(0); }
      break;
    default: break;
  }
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => { clearTimeout(timer); client.end(true, () => process.exit(0)); });
}
