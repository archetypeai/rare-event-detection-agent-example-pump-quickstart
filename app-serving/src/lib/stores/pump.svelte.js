// MQTT-backed live pump state (Svelte 5 runes).
//
// Subscribes (over WebSockets — endpoint from PUBLIC_MQTT_* env, see brokerUrl):
//   pump/raw      raw sensor rows (from the replayer)
//   pump/status   replayer playback status (retained)
//   red/results   the RED agent's per-window classifications
// Publishes:
//   pump/control  { action: play|pause|seek|speed|slice|reset|onset, value? }
//
// This store deliberately derives NOTHING from ground truth. A deployment
// watching a real pump has no label to compare against, so anything computed
// from one — precision, false-alarm rate, "missed" — would be a readout the
// operator could never actually have. Everything here comes from the agent's own
// output or from the replayer's playback state.
//
// The rows on pump/raw still carry the dataset's `label` column, because the
// replayer is also the harness the offline scorer feeds from. The UI ignores it.
import mqtt from 'mqtt';
import { base } from '$app/paths';
import { env } from '$env/dynamic/public';
import { CLASSES, CADENCE_MS, EMB_ORDER } from '$lib/red.js';

// Broker endpoint, built at RUNTIME from PUBLIC_* env the web server injects —
// read per-request by adapter-node, so the SAME pre-built kit image serves any
// host/port without a rebuild (see app/demo-kit/BUILDING.md). Two shapes, one
// env flag:
//   direct (default): ws(s)://<page-host>:<PUBLIC_MQTT_WS_PORT|9009>  (open ports)
//   proxy:            ws(s)://<page-host><PUBLIC_MQTT_WS_PATH|/mqtt>  (one port, same origin)
// Scheme follows the page: an https page can't open a ws:// socket, so -> wss.
export const WS_PORT = () => env.PUBLIC_MQTT_WS_PORT ?? '9009';
export const TCP_PORT = () => env.PUBLIC_MQTT_TCP_PORT ?? '1891';
export const MQTT_MODE = () => env.PUBLIC_MQTT_MODE ?? 'direct';
export const WS_PATH = () => env.PUBLIC_MQTT_WS_PATH ?? '/mqtt';

function brokerUrl() {
	const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
	if (MQTT_MODE() === 'proxy') return `${scheme}://${location.host}${WS_PATH()}`;
	return `${scheme}://${location.hostname}:${WS_PORT()}`;
}

const RAW_BUFFER = 900; // rows kept for the sparklines
const LOG_BUFFER = 500; // classifications kept for the log/timeline

export class PumpStore {
	connected = $state(false);
	status = $state({
		playing: false, loading: false, throttled: false, speed: 250,
		row: 0, totalRows: 0, demoStart: 0, demoEnd: 0, onsetRow: null,
		timestamp_ms: 0, slice: 'inc04', slices: [], channels: [], epoch: 0
	});
	rows = $state([]);        // [{ timestamp_ms, row, channels }]
	predictions = $state([]); // [{ id, timestamp_ms, state, probs, invalid }] — capped
	latest = $state(null);
	resultsStalled = $state(false);

	// Running totals since the last discontinuity. These are counted as results
	// arrive rather than derived from `predictions`, which is a capped ring buffer —
	// deriving them there silently pins the total at the buffer size.
	validCount = $state(0);     // windows the agent classified
	flaggedCount = $state(0);   // ...of which it called pump_breakdown
	invalidCount = $state(0);   // windows that failed validation, so were not classified

	/** First window this epoch the agent called a breakdown (agent-derived). */
	assertedSinceTs = $state(null);

	landscape = $state(null);        // PCA basis + library coords + prototypes
	landscapeError = $state(null);   // set when the asset does not match this model
	embeddingsSeen = $state(false);  // whether the agent is emitting embedding_*

	flows = $state({
		'sensors/red': { count: 0, rate: 0, last: 0 },
		'pump/raw': { count: 0, rate: 0, last: 0 },
		'pump/status': { count: 0, rate: 0, last: 0 },
		'red/results': { count: 0, rate: 0, last: 0 },
		'pump/control': { count: 0, rate: 0, last: 0 }
	});

	#client = null;
	#nextId = 1;
	#rateTimer = null;
	#lastResultWall = 0;
	#pcaMean = null;
	#pcaComponents = null;  // [Float32Array, Float32Array]

	async loadLandscape() {
		if (this.landscape) return;
		try {
			// base-relative so the asset still resolves if the app is built to be
			// served under a subpath (kit.paths.base — a BUILD-time setting).
			const res = await fetch(`${base}/red-embedding-landscape.json`);
			const data = await res.json();
			// Refuse an asset that does not match THIS classifier's geometry. Without
			// this the views render someone else's library and an empty trail, because
			// #concat quietly rejects every window on the per-variate length check —
			// which looks like "embeddings are broken" rather than "wrong asset".
			const want = EMB_ORDER.length * 768;
			if (data.dim !== want) {
				this.landscapeError =
					`asset is ${data.dim}-dim but this classifier is ${want} ` +
					`(${EMB_ORDER.length} channels x 768) — rebuild it with fit/build_embedding_landscape.py`;
				return;
			}
			this.#pcaMean = Float32Array.from(data.mean);
			this.#pcaComponents = data.components.map((c) => Float32Array.from(c));
			this.landscape = data;
		} catch {
			/* both embedding views degrade to an empty state */
		}
	}

	/** Concatenate per-variate embeddings in the classifier's declared order. */
	#concat(msg) {
		const dim = this.#pcaMean?.length ?? 0;
		if (!dim) return null;
		const per = dim / EMB_ORDER.length;
		const out = new Float32Array(dim);
		let off = 0;
		for (const c of EMB_ORDER) {
			const v = msg[`embedding_${c}`];
			if (!Array.isArray(v) || v.length !== per) return null;
			out.set(v, off);
			off += per;
		}
		return out;
	}

	/** 2-D PCA projection of a full embedding vector. */
	#project(x) {
		if (!this.#pcaMean) return null;
		const [c0, c1] = this.#pcaComponents;
		let px = 0;
		let py = 0;
		for (let i = 0; i < x.length; i++) {
			const d = x[i] - this.#pcaMean[i];
			px += d * c0[i];
			py += d * c1[i];
		}
		return { x: px, y: py };
	}

	connect(url = brokerUrl()) {
		if (this.#client) return;
		const client = mqtt.connect(url, {
			clientId: `red-demo-web-${Math.random().toString(16).slice(2, 8)}`
		});
		this.#client = client;
		client.on('connect', () => {
			this.connected = true;
			// sensors/red is subscribed only to observe the agent-feed flow rate
			client.subscribe(['pump/raw', 'pump/status', 'red/results', 'sensors/red']);
		});
		client.on('close', () => (this.connected = false));
		this.#rateTimer = setInterval(() => {
			const flows = { ...this.flows };
			for (const t of Object.keys(flows)) {
				flows[t] = { ...flows[t], rate: flows[t].count - flows[t].last, last: flows[t].count };
			}
			this.flows = flows;
			// throttling is expected and is not a stall — it means the replayer is
			// deliberately waiting for the agent.
			this.resultsStalled =
				this.status.playing && !this.status.throttled &&
				this.#lastResultWall > 0 && Date.now() - this.#lastResultWall > 12000;
		}, 1000);
		client.on('message', (topic, payload) => {
			if (this.flows[topic]) this.flows[topic].count += 1;
			if (topic === 'sensors/red') return; // observed for rate only
			try {
				const msg = JSON.parse(payload.toString());
				if (topic === 'pump/raw') this.#onRaw(msg);
				else if (topic === 'pump/status') this.#onStatus(msg);
				else if (topic === 'red/results') this.#onResult(msg);
			} catch {
				/* ignore malformed */
			}
		});
	}

	#onStatus(msg) {
		// Any discontinuity (seek / reset / slice switch) bumps the replayer's
		// epoch — clear local buffers so the charts never splice two sections.
		if (msg.epoch !== undefined && msg.epoch !== this.status.epoch) this.#clearBuffers();
		this.status = { ...this.status, ...msg };
	}

	#clearBuffers() {
		this.rows = [];
		this.predictions = [];
		this.latest = null;
		this.validCount = 0;
		this.flaggedCount = 0;
		this.invalidCount = 0;
		this.assertedSinceTs = null;
	}

	#onRaw(msg) {
		this.rows.push(msg);
		if (this.rows.length > RAW_BUFFER) this.rows.splice(0, this.rows.length - RAW_BUFFER);
	}

	#onResult(msg) {
		this.#lastResultWall = Date.now();
		// Window end = the moment this verdict is about. Runtime 1.1.9 renamed the
		// sink's time fields to start_/finish_timestamp; older aer-* builds emitted
		// `timestamp`. Read both, newest first, because run-agent.sh may still pick
		// up an old binary for a native run. Getting this wrong is not cosmetic: a
		// NaN here reaches the detection log and timeline as "Invalid Date" AND
		// makes assertedFor NaN, which breaks the banner's "ALARM FOR ..." readout.
		const ts = Number(
			msg.finish_timestamp ?? msg.timestamp ?? msg.timestamp_ms ?? msg.start_timestamp
		);
		const state = msg.predicted_state;
		const invalid = state === 'INVALID_STATE' || msg.invalid === 'true';

		const probs = {};
		for (const c of CLASSES) probs[c] = Number(msg[`p_${c}`] ?? 0);

		if (invalid) {
			this.invalidCount += 1;
		} else {
			this.validCount += 1;
			if (state === 'pump_breakdown') this.flaggedCount += 1;
		}
		// Start of the CURRENT alarm, not the first one ever. This used to latch on
		// the first breakdown and clear only on a stream discontinuity, so after the
		// agent flapped back to normal the banner read "NORMAL" and "ALARM FOR 13h
		// 34m" side by side — the duration since the first breakdown of the replay,
		// which is not a thing an operator would ever want.
		//
		// An INVALID window does not clear it: a window the agent could not use is
		// not evidence the pump recovered, and dropping the alarm on one would make
		// the duration restart at every unusable window mid-fault.
		if (!invalid) {
			if (state === 'pump_breakdown') {
				if (this.assertedSinceTs === null) this.assertedSinceTs = ts;
			} else {
				this.assertedSinceTs = null;
			}
		}

		const pred = { id: this.#nextId++, timestamp_ms: ts, state, probs, invalid };

		if (msg[`embedding_${EMB_ORDER[0]}`]) {
			this.embeddingsSeen = true;
			// Invalid windows carry embeddings too, but plotting them just smears
			// meaningless points across the map.
			if (!invalid) {
				const x = this.#concat(msg);
				if (x) {
					const pt = this.#project(x);
					if (pt) { pred.ex = pt.x; pred.ey = pt.y; }
				}
			}
		}

		this.predictions.push(pred);
		if (this.predictions.length > LOG_BUFFER) {
			this.predictions.splice(0, this.predictions.length - LOG_BUFFER);
		}
		this.latest = pred;
	}

	/**
	 * Samples of data time the agent has been asserting the CURRENT breakdown, or
	 * null when it is not asserting one. Drives the banner's "ALARM FOR ..." badge,
	 * so a null here is what hides the badge once the pump reads normal again.
	 */
	get assertedFor() {
		if (this.assertedSinceTs === null || !this.status.timestamp_ms) return null;
		return (this.status.timestamp_ms - this.assertedSinceTs) / CADENCE_MS;
	}

	get currentSlice() {
		return this.status.slices?.find((s) => s.id === this.status.slice) ?? null;
	}

	// --- playback control ----------------------------------------------------
	#control(action, value) {
		this.#client?.publish('pump/control', JSON.stringify({ action, value }));
		this.flows['pump/control'].count += 1;
	}
	play() { this.#control('play'); }
	pause() { this.#control('pause'); }
	reset() { this.#control('reset'); }
	toOnset() { this.#control('onset'); }
	setSpeed(v) { this.#control('speed', v); }
	seek(row) { this.#control('seek', row); }
	setSlice(id) { this.#control('slice', id); }
}

export const pump = new PumpStore();
