/**
 * The agent, on the Archetype AI platform: a bridge between the local broker
 * and a serving agent of the promoted RED classifier.
 *
 * In app/ the agent is `agent_edge_runtime` on this laptop, subscribed to the
 * broker. Here the agent runs on the platform (agent serving), and this
 * process stands where the runtime stood:
 *
 *   sensors/red ──► bridge: the latest 64 rows ──POST /query──► serving agent
 *                     ▲                                             │
 *                     └─────────── red/results ◄── one record per window ┘
 *
 * - THE BROWSER NEVER HOLDS THE API KEY. The bridge reads it from the repo's
 *   .env and is the only thing that talks to the platform.
 * - A QUERY CARRIES THE WHOLE WINDOW. A served agent keeps nothing between
 *   queries (fit/serve.py, Stage 8), so the bridge keeps the buffer and sends
 *   the latest `window_size` rows on every row: step 1, as Stage 7 delivered.
 * - THE SAME MESSAGE AS THE EDGE RUNTIME. `red/results` gets the record the
 *   agent answered (predicted_state, invalid, p_*, embedding_<channel>), with
 *   the window's timestamps put back: the served agent numbers rows 0..63
 *   within the query, the bridge knows which rows it sent.
 * - THE SAME ADMIN API AS THE EDGE RUNTIME, so the replayer is app/'s:
 *   GET /status reports `Running` once the serving agent is, POST /reset drops
 *   the buffer and anything queued (a seek or incident switch), POST /start is
 *   a no-op, POST /shutdown cleans up and exits (scripts/stop.sh calls it).
 * - ONE SERVING WORKER, HELD WHILE THIS RUNS. The blueprint is packaged, the
 *   package deployed as `serving` (the agent placed on a worker and loaded), and
 *   a session opened on the deployment; queries go to the session. On exit the
 *   session is cancelled, the deployment stopped, and all three deleted; the ids
 *   sit in fit/out/app_serving_state.json until then, so `python3 fit/cleanup.py`
 *   finds them after a hard kill. A session that stops taking queries (cancelled
 *   elsewhere, or its deployment ended) is replaced on the next window, with a
 *   new deployment if the old one is gone. Starting retries while all the serving
 *   workers are taken (15 s, doubling to 2 min).
 * - EMBEDDINGS NEED THEIR OWN BLUEPRINT. A package carries no values, so it can't
 *   turn `output_embeddings` on: the bridge serves fit/library_embeddings.py's
 *   embeddings blueprint (Stage 5's configuration with embeddings on) when it was
 *   made from the current Stage 5 blueprint, else Stage 5's, without the point.
 *
 * Env (repo .env): ATAI_API_ENDPOINT, ATAI_API_KEY.
 * Env (app-serving/.env): MQTT_PORT, AGENT_PORT.
 */
import mqtt from 'mqtt';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { REPO, loadEnv, readJson } from './common.js';

loadEnv();

// The deployment root, with any /api or /vX.Y suffix removed, then /api appended:
// every platform surface lives under it, and one .env works whichever form you have.
// Keeping /api on ENDPOINT also matches what fit/ writes into the state files.
const ROOT = (process.env.ATAI_API_ENDPOINT ?? '')
	.replace(/\/+$/, '')
	.replace(/\/api$/, '')
	.replace(/\/v\d+(\.\d+)*$/, '');
const ENDPOINT = ROOT ? `${ROOT}/api` : '';
const KEY = process.env.ATAI_API_KEY;
if (!ENDPOINT || !KEY) {
	console.error('bridge: set ATAI_API_ENDPOINT and ATAI_API_KEY in the repo .env');
	process.exit(1);
}
const MQTT_PORT = Number(process.env.MQTT_PORT ?? 1891);
const BROKER_URL = process.env.BROKER ?? `mqtt://127.0.0.1:${MQTT_PORT}`;
const ADMIN_PORT = Number(process.env.AGENT_PORT ?? 9101);
const MODEL = 'red-pump';
const STATE = path.join(REPO, 'fit', 'out', 'app_serving_state.json');

if (fs.existsSync(STATE)) {
	console.error(`bridge: ${path.relative(REPO, STATE)} holds an earlier bridge's deployment: run python3 fit/cleanup.py --yes`);
	process.exit(1);
}
const test = readJson(path.join(REPO, 'fit', 'out', 'test_state.json'));
if (!test?.blueprint?.key) {
	console.error('bridge: no fit/out/test_state.json: run fit/test.py (Stage 5) first');
	process.exit(1);
}
/** The deployment an endpoint addresses, whatever hostname it arrives under (as red_api.py). */
const deployment = (e) =>
	e.trim().replace(/^[a-z]+:\/\//, '').split('/')[0].split(':')[0].replace(/^(api|platform)\./, '').toLowerCase();
if (test.endpoint && deployment(test.endpoint) !== deployment(ENDPOINT)) {
	console.error(
		`bridge: fit/out/test_state.json is from ${test.endpoint}, a different deployment from ${ENDPOINT}`
	);
	process.exit(1);
}
/** fit/library_embeddings.py's embeddings blueprint, if it was made from this Stage 5 blueprint here. */
const library = readJson(path.join(REPO, 'fit', 'out', 'library_state.json'));
const served =
	library?.embeddings_blueprint &&
	library.blueprint === test.blueprint.key &&
	library.endpoint &&
	deployment(library.endpoint) === deployment(ENDPOINT)
		? library.embeddings_blueprint
		: test.blueprint;
if (served === test.blueprint)
	console.warn('bridge: no embeddings blueprint for this Stage 5 blueprint (python3 fit/library_embeddings.py makes one): serving it without embeddings');
const PROMOTED = served.key;
const PROMOTED_ID = served.id;
const WINDOW = test.blueprint.values.window_size;
// The classifier's channel order: the role files', which the replayer publishes in.
const CHANNELS = readJson(path.join(REPO, 'data', 'roles', 'manifest.json'))?.channels;
if (!CHANNELS) {
	console.error('bridge: no data/roles/manifest.json: build the role files (Stage 2) first');
	process.exit(1);
}

// ------------------------------------------------------------------ the platform

async function api(method, p, body) {
	const r = await fetch(`${ENDPOINT}/agents${p}`, {
		method,
		headers: { Authorization: `Bearer ${KEY}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
		body: body ? JSON.stringify(body) : undefined,
		signal: AbortSignal.timeout(120_000)
	});
	const text = await r.text();
	if (!r.ok) {
		const e = new Error(`${method} ${p} → ${r.status}: ${text.slice(0, 300)}`);
		e.status = r.status;
		throw e;
	}
	return text ? JSON.parse(text) : {};
}

/** `sessions`: every session not yet deleted, the current one last. `agent` is the current
 *  session, under the name the page and the replayer read. */
const live = { package: null, deployment: null, agent: null, sessions: [], running: false };
const save = () => fs.writeFileSync(STATE, JSON.stringify({ endpoint: ENDPOINT, package: live.package,
	deployment: live.deployment, session: live.agent, sessions: live.sessions }, null, 1));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Poll `p` while its status is `waiting`; throw unless it then reaches `want`. */
async function until(p, want, waiting) {
	const t0 = Date.now();
	for (;;) {
		const o = await api('GET', p);
		if (o.status === want) return o;
		if (o.status !== waiting || Date.now() - t0 > 600_000)
			throw new Error(`${p} is ${o.status}${o.error ? `: ${o.error}` : ''}`);
		await sleep(2000);
	}
}

async function startAgent() {
	if (!live.package) {
		// The blueprint as it is (step 1, and embeddings on for the embeddings blueprint):
		// the platform supplies the serving connectors for a serving deployment.
		live.package = (await api('POST', '/packages', { blueprint_ids: [PROMOTED_ID],
			target: { kind: 'platform' }, name: 'RED app-serving' })).id;
		save();
		await until(`/packages/${live.package}`, 'ready', 'building');
	}
	if (!live.deployment) {
		live.deployment = (await api('POST', '/deployments', { package_id: live.package, kind: 'serving' })).id;
		save();
		await until(`/deployments/${live.deployment}`, 'ready', 'deploying');
	}
	live.agent = (await api('POST', '/sessions', { deployment_id: live.deployment })).id;
	live.sessions.push(live.agent);
	save();
	await until(`/sessions/${live.agent}`, 'running', 'pending');
	live.running = true;
	console.log(`bridge: session ${live.agent} running (deployment ${live.deployment}, package ${live.package}, ${PROMOTED})`);
}

/** Delete `p`, after `prep` (cancel or stop) where that still applies; true once it is gone (404 counts). */
async function drop(p, prep) {
	if (prep) await api('POST', `${p}/${prep}`, {}).catch(() => {});   // already ended: nothing to do
	try {
		await api('DELETE', p);
		return true;
	} catch (e) {
		if (e.status === 404) return true;
		console.error(`bridge: ${e.message}`);
		return false;
	}
}

async function dropSession(id) {
	if (!(await drop(`/sessions/${id}`, 'cancel'))) return false;
	live.sessions = live.sessions.filter((s) => s !== id);
	if (live.agent === id) live.agent = null;
	save();
	return true;
}

async function dropDeployment() {
	if (!live.deployment) return true;
	if (!(await drop(`/deployments/${live.deployment}`, 'stop'))) return false;
	live.deployment = null;
	save();
	return true;
}

/** True when the current deployment is still up. */
async function deploymentReady() {
	if (!live.deployment) return false;
	return (await api('GET', `/deployments/${live.deployment}`).catch(() => ({}))).status === 'ready';
}

let stopping = false;
async function shutdown(sig) {
	if (stopping) return;
	stopping = true;
	console.log(`bridge: ${sig}, cleaning up`);
	let left = 0;
	try {
		for (const id of [...live.sessions]) if (!(await dropSession(id))) left++;
		if (!left && !(await dropDeployment())) left++;
		if (!left && live.package && !(await drop(`/packages/${live.package}`))) left++;
		if (left) {
			// Keep the ids for fit/cleanup.py rather than leaving them on the platform unrecorded.
			console.error(`bridge: not everything was deleted; run python3 fit/cleanup.py --yes (ids in ${path.relative(REPO, STATE)})`);
		} else {
			fs.rmSync(STATE, { force: true });
			console.log(`bridge: deleted its session(s), deployment and package ${live.package ?? '(none)'}`);
		}
	} finally {
		process.exit(left ? 1 : 0);
	}
}
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(sig, () => shutdown(sig));
// Anything unexpected still cleans up: an exit without it would hold a serving worker.
process.on('uncaughtException', (e) => { console.error('bridge:', e); shutdown('error'); });
process.on('unhandledRejection', (e) => { console.error('bridge:', e); shutdown('error'); });

/** Open a session (deploying first if needed), retrying while the serving workers are all
 *  taken: at startup, and to replace one that stopped taking queries. */
async function startWithRetry() {
	live.running = false;
	for (let wait = 15_000; !stopping; wait = Math.min(wait * 2, 120_000)) {
		try {
			await startAgent();
			return;
		} catch (e) {
			console.error(`bridge: could not start serving (${e.message}); retrying in ${wait / 1000} s`);
			if (live.agent) await dropSession(live.agent);
			if (live.deployment && !(await deploymentReady())) await dropDeployment();
			await sleep(wait);
		}
	}
}

// ------------------------------------------------------------------ the windows

/** Rows of the current section, oldest first: {t, values[10]}. */
let buffer = [];
/** Bumped on every reset, so an answer to a query sent before it is dropped. */
let generation = 0;
const queue = [];
let busy = false;
const latencies = [];

function onRow(payload) {
	const kv = Object.fromEntries(payload.toString().split(',').map((p) => p.split('=')));
	buffer.push({ t: Number(kv.timestamp_ms), values: CHANNELS.map((c) => Number(kv[c])) });
	if (buffer.length > WINDOW + 64) buffer.splice(0, buffer.length - WINDOW);
	if (buffer.length >= WINDOW) {
		queue.push({ gen: generation, rows: buffer.slice(-WINDOW) });
		drain().catch((e) => console.error(`bridge: ${e.message}`));
	}
}

async function drain() {
	if (busy) return;
	busy = true;
	try {
		while (queue.length && !stopping) {
			// The replayer starts before the agent is up (or while a released one is
			// replaced): hold the windows until it runs. Its flow control waits too.
			while (!live.running && !stopping) await sleep(500);
			const job = queue.shift();
			if (!job || job.gen !== generation) continue;
			const body = { model: MODEL, query: '', events: [{ type: 'data.numeric_array',
				event_data: { contents: CHANNELS.map((_, c) => job.rows.map((r) => r.values[c])) } }] };
			let answer;
			const t = Date.now();
			try {
				answer = await api('POST', `/sessions/${live.agent}/query`, body);
			} catch (e) {
				if (e.status === 409) {
					// The session was cancelled elsewhere, or its deployment ended.
					console.warn(`bridge: session ${live.agent} no longer taking queries; replacing it`);
					live.running = false;
					if (live.agent) await dropSession(live.agent);
					if (!(await deploymentReady())) await dropDeployment();
					await startWithRetry();
					queue.unshift(job);
					continue;
				}
				console.error(`bridge: query failed: ${e.message}`);
				publish({ predicted_state: 'INVALID_STATE', invalid: 'true',
					start_timestamp: job.rows[0].t, finish_timestamp: job.rows.at(-1).t });
				continue;
			}
			latencies.push(Date.now() - t);
			if (latencies.length > 200) latencies.shift();
			if (job.gen !== generation) continue;
			const rec = (answer.response ?? answer).data?.[0];
			if (!rec) {
				console.error(`bridge: no record in ${JSON.stringify(answer).slice(0, 200)}`);
				continue;
			}
			// The record as the agent answered it (predicted_state, invalid, p_*,
			// embedding_<channel>), with the window's own timestamps in ms.
			publish({ ...rec, start_timestamp: job.rows[0].t, finish_timestamp: job.rows.at(-1).t,
				latency_ms: Date.now() - t });
		}
	} finally {
		busy = false;
	}
}

const client = mqtt.connect(BROKER_URL, { clientId: `red-serving-bridge-${Date.now()}` });
const publish = (msg) => client.publish('red/results', JSON.stringify(msg));

client.on('connect', () => {
	client.subscribe('sensors/red', { qos: 1 });
	console.log(`bridge: connected to ${BROKER_URL}`);
});
client.on('message', (_topic, payload) => onRow(payload));
client.on('error', (e) => console.error('bridge mqtt error:', e.message));

// ------------------------------------------------- the edge runtime's admin API

function reset() {
	generation++;
	buffer = [];
	queue.length = 0;
}

http.createServer((req, res) => {
	const reply = (code, body) => {
		res.writeHead(code, { 'Content-Type': 'application/json' });
		res.end(JSON.stringify(body));
	};
	if (req.method === 'GET' && req.url === '/status') {
		const ms = [...latencies].sort((a, b) => a - b);
		return reply(live.running ? 200 : 503, { state: live.running ? 'Running' : 'Starting', agent: live.agent,
			deployment: live.deployment, package: live.package, blueprint: PROMOTED, queued: queue.length, medianLatencyMs: ms[Math.floor(ms.length / 2)] ?? null });
	}
	if (req.method === 'POST' && req.url === '/reset') {
		reset();
		return reply(200, { reset: true });
	}
	if (req.method === 'POST' && req.url === '/start') return reply(200, { started: true });
	if (req.method === 'POST' && req.url === '/shutdown') {
		reply(200, { shutting_down: true });
		return shutdown('POST /shutdown');
	}
	reply(404, { error: 'not found' });
}).listen(ADMIN_PORT, '127.0.0.1', () => console.log(`bridge: admin API on http://127.0.0.1:${ADMIN_PORT}`));

// ------------------------------------------------------------------------ start

try {
	await startWithRetry();
} catch (e) {
	console.error(`bridge: ${e.message}`);
	await shutdown('startup failure');
}
