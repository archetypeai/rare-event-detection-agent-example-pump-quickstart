<script>
	// A SECTION of the settings dialog, not a dialog of its own — the same shape the rig
	// monitor's panel takes, so the two demos answer "is data actually moving, and where"
	// the same way. It had its own menubar icon and full-screen overlay before the
	// workbench rebuild; both are gone, and what replaced it here was a table of per-topic
	// rates. The table says which topics tick; only the diagram says what talks to what,
	// which is the whole point of showing a prospect that this runs on one machine.
	//
	// No `open` prop and no Dialog wrapper: the host owns visibility. A component that
	// both hides itself and is hidden by its parent has two sources of truth.
	//
	// No local 1 s timer either. The store already re-computes `flows` on its own interval
	// (pump.svelte.js's #rateTimer), so the rates are reactive and a second clock here
	// would just re-render between updates.
	import { MQTT_MODE, TCP_PORT, WS_PORT, WS_PATH } from '$lib/stores/pump.svelte.js';
	import { WINDOW_SIZE } from '$lib/red.js';

	let { pump } = $props();

	let f = $derived(pump.flows);
	// Liveness from pump/raw, NOT from pump/status. The rig publishes status as a 1 Hz
	// heartbeat, so upstream that test works; this replayer publishes it every 25 rows
	// (replayer.js:303), which at demo speeds is ~0.16/s and rounds to 0 in a 1 s window.
	// Keying the dot off that rate showed the replayer GREY — dead — while it was visibly
	// streaming, and printed "pump/status 0/s" beside it. Raw rows are the thing the
	// replayer exists to emit, so they are what "alive" means; the retained-status count
	// covers the paused case, where nothing flows but the replayer is still up.
	let replayerAlive = $derived(f['pump/raw'].rate > 0 || f['pump/status'].count > 0);
	let agentAlive = $derived(
		f['red/results'].rate > 0 || (f['sensors/red'].rate === 0 && pump.latest !== null)
	);
	let streaming = $derived(f['pump/raw'].rate > 0);

	// The endpoints are deployment config (see app/demo-kit/BUILDING.md), so read them
	// rather than print the default ports — on EC2 or a custom-port run a hardcoded
	// ":1884 · ws :9002" would be a diagram that lies. Derived, not $derived: the values
	// are injected once per page load by adapter-node and cannot change under us.
	const brokerLabel =
		MQTT_MODE() === 'proxy'
			? `MQTT (mosquitto broker) · tcp :${TCP_PORT()} · ws via proxy ${WS_PATH()}`
			: `MQTT (mosquitto broker) · tcp :${TCP_PORT()} · ws :${WS_PORT()}`;

	const GOOD = 'var(--color-atai-good)';
	const MUTED = 'var(--color-muted-foreground)';

	function dot(active) {
		return active ? GOOD : MUTED;
	}
	function fmtRate(r, unit = 'msg/s') {
		return r > 0 ? `${r} ${unit}` : 'idle';
	}
</script>

<div class="flex flex-col gap-2">
	<p class="text-[11px] text-muted-foreground">
		Live rates measured by this browser tab (1 s window). A row = one sensor reading; a window =
		the trailing {WINDOW_SIZE} rows, sliding by one — so in steady state, classified windows/s ≈
		classifiable rows/s. Green pulses = data moving now. Everything below runs on this machine.
	</p>

	<svg viewBox="0 0 900 560" class="w-full" font-family="var(--font-mono, ui-monospace, monospace)">
		<defs>
			<marker
				id="obs-arr"
				viewBox="0 0 8 8"
				refX="7"
				refY="4"
				markerWidth="6"
				markerHeight="6"
				orient="auto"
			>
				<path d="M0,0 L8,4 L0,8 z" fill="var(--color-muted-foreground)" />
			</marker>
		</defs>

		{#snippet box(x, y, w, h, title, alive)}
			<rect
				{x}
				{y}
				width={w}
				height={h}
				rx="2"
				fill="var(--color-background)"
				stroke="var(--color-border)"
			/>
			<circle cx={x + 14} cy={y + 16} r="4" fill={dot(alive)} />
			<text x={x + 26} y={y + 20} font-size="13" fill="var(--color-foreground)" letter-spacing="1"
				>{title}</text
			>
		{/snippet}

		{#snippet flow(path, label, rate, lx, ly, unit = 'msg/s')}
			<path
				d={path}
				fill="none"
				stroke="var(--color-border)"
				stroke-width="1.5"
				marker-end="url(#obs-arr)"
			/>
			<text x={lx} y={ly} font-size="11" fill={rate > 0 ? GOOD : MUTED}>{label}</text>
			<text x={lx} y={ly + 13} font-size="10" fill={rate > 0 ? GOOD : MUTED}
				>{fmtRate(rate, unit)}</text
			>
			{#if rate > 0}
				<circle r="3.5" fill={GOOD}>
					<animateMotion dur="1.4s" repeatCount="indefinite" {path} />
				</circle>
			{/if}
		{/snippet}

		<!-- raw csv -->
		{@render box(280, 10, 340, 52, 'data/roles/delivery/', streaming)}
		<text x="306" y="44" font-size="10" fill={MUTED}>Stage 6's files · 10 channels · 1-min cadence</text
		>
		<!-- replayer -->
		{@render box(40, 130, 280, 110, 'replayer (node)', replayerAlive)}
		<text x="66" y="175" font-size="10" fill={MUTED}>incident row ranges · z-score</text>
		<text x="66" y="190" font-size="10" fill={MUTED}>flow control · data-time pacing</text>
		<text x="66" y="205" font-size="10" fill={MUTED}>epoch on discontinuity</text>
		<!-- agent -->
		{@render box(600, 130, 290, 110, 'Rare Event Detection Agent', agentAlive)}
		<text x="626" y="172" font-size="10" fill={MUTED}>agent serving · Archetype AI platform</text>
		<text x="626" y="190" font-size="10" fill={MUTED}>window {WINDOW_SIZE} · step 1 → validate</text>
		<text x="626" y="205" font-size="10" fill={MUTED}>Omega 1.5 → nearest prototype</text>
		<text x="626" y="220" font-size="10" fill={MUTED}>2 classes · per-variate embeddings</text>
		<!-- broker -->
		{@render box(200, 330, 500, 50, brokerLabel, pump.connected)}
		<!-- app -->
		{@render box(150, 470, 600, 60, 'web app (this browser tab, mqtt.js over ws)', pump.connected)}
		<text x="176" y="515" font-size="10" fill={MUTED}
			>pump input · embedding map · detection state · log · playback</text
		>

		<!-- raw csv -> replayer -->
		{@render flow(
			'M 320,62 C 240,84 190,100 182,128',
			'reads + paces',
			streaming ? f['pump/raw'].rate : 0,
			196,
			88,
			'rows/s'
		)}

		<!-- replayer -> broker: sensors/red + pump/raw + pump/status -->
		{@render flow(
			'M 120,240 C 120,285 215,312 278,328',
			'sensors/red',
			f['sensors/red'].rate,
			44,
			280,
			'rows/s'
		)}
		{@render flow(
			'M 215,240 C 235,275 290,302 330,328',
			'pump/raw',
			f['pump/raw'].rate,
			228,
			288,
			'rows/s'
		)}
		<!-- Count, not rate: this topic ticks every 25 rows, so a per-second rate is 0 at
		     every speed the demo runs at and "0/s" reads as a dead link. -->
		<text x="228" y="316" font-size="10" fill={f['pump/status'].count > 0 ? GOOD : MUTED}
			>pump/status ×{f['pump/status'].count} (every 25 rows)</text
		>

		<!-- broker -> agent: sensors/red -->
		{@render flow(
			'M 600,328 C 645,292 675,262 700,242',
			'sensors/red',
			f['sensors/red'].rate,
			620,
			300,
			'rows/s'
		)}
		<!-- agent -> broker: red/results -->
		{@render flow(
			'M 790,240 C 775,288 706,312 668,330',
			'red/results',
			f['red/results'].rate,
			726,
			288,
			'windows/s'
		)}
		<text x="726" y="314" font-size="10" fill={f['red/results'].rate > 0 ? GOOD : MUTED}
			>+ 10×768 embeddings</text
		>

		<!-- broker -> app: display topics -->
		{@render flow(
			'M 490,380 C 500,410 510,440 520,468',
			'pump/raw · red/results',
			f['red/results'].rate + f['pump/raw'].rate,
			500,
			424
		)}
		<text x="500" y="450" font-size="10" fill={f['pump/status'].count > 0 ? GOOD : MUTED}
			>pump/status → playback · incidents · epoch</text
		>
		<!-- app -> broker: pump/control -->
		{@render flow(
			'M 380,468 C 380,440 385,410 395,382',
			'pump/control',
			f['pump/control'].rate,
			258,
			424
		)}

		<!-- broker -> replayer: pump/control -->
		{@render flow(
			'M 278,328 C 215,310 172,282 162,242',
			'pump/control',
			f['pump/control'].rate,
			78,
			300
		)}
	</svg>
</div>
