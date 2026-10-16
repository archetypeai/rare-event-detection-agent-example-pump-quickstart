<script>
	import { cn } from '$lib/utils.js';
	import { latestValue, formatValue } from '$lib/samples.js';

	// The pump as a draughtsman's plate — hairline outlines, almost no fills, parts
	// called out by reference numeral. The RED counterpart of the rig monitor's
	// rig-diagram.svelte, drawn to the same rules.
	//
	// TWO TONES, NO HUES. The previous version tinted the casing and impeller with the
	// verdict; the rig plate removed exactly that treatment, and for the reason that
	// applies here too — it puts a second colour system on screen competing with the one
	// that carries meaning (the verdict badge and the timeline), and it leaves the
	// drawing looking like a wiring diagram rather than a section.
	//
	//  * INK       the four called-out parts and the pump's own outline
	//  * INK_SOFT  context and section hatching: pipework, baseplate, ground, the cut
	//              faces of the casing and motor
	//
	// So the plate no longer states the verdict. It does not need to: the badge above
	// writes it in words, and the drawing still shows what is physically happening —
	// because when this pump breaks, motor speed and every phase current collapse to
	// zero, and the impeller simply stops turning. That is a truer cue than a red
	// outline, and it comes from the data rather than from the classifier.
	//
	// SECTIONED, after the `Querschnitt` figures in the Meyers plate: the volute is cut
	// so the impeller is visible inside it, rather than vanes drawn on the face of a
	// disc. That is the one thing worth taking from an engraving — its rendering
	// technique (dense tonal hatching) would turn to mud at this size and fights the
	// hairline system everything else here is drawn in.

	let { rows = [], latest = null, class: className, ...restProps } = $props();

	const INK = 'var(--color-plate-ink)';
	const INK_SOFT = 'var(--color-plate-ink-soft)';

	// --- plate geometry ---------------------------------------------------------
	// A pump is a squat machine, so the box is landscape where the derrick's was
	// portrait. Reference numerals are SVG so they scale with the plate the way
	// engraved callouts would; the key beside it is HTML, so the live values stay at a
	// fixed readable size however the panel is sized.
	const VB_W = 170;
	const VB_H = 120;

	const CX = 46; // impeller / volute centre
	const CY = 54;
	const R_IMPELLER = 19;
	const R_BORE = 25; // inner wall of the volute
	const R_CASE = 29; // outer wall — the gap between the two is the cut casing
	const SHAFT_Y = CY;

	// Where the context pipework and the legs MEET the casing circle, computed rather than
	// eyeballed. Every one of these was off by a few units, and a round body makes both
	// failure modes look like mistakes: stop short and the part floats away from the pump,
	// overshoot and a soft grey line runs through the hatched cut face and muddles the
	// outline. On a circle the meeting point is not a round number, so it has to be solved.
	// Rounded like the vane and arrow geometry above, so the emitted path data stays legible.
	const onCase = (off) => Number(Math.sqrt(R_CASE * R_CASE - off * off).toFixed(2));
	const SUCTION_X = CX - onCase(7); // suction walls sit ±7 off the axis
	const DISCHARGE_Y = CY - onCase(7); // riser walls sit ±7 off the centre
	const LEG_Y = CY + onCase(14); // legs stand under x = CX∓14

	// Backward-curved vanes, generated rather than hand-placed so the sweep stays
	// consistent. Six of them, the count on the machine in the old drawing.
	const VANES = [0, 60, 120, 180, 240, 300].map((a) => {
		const r = (d) => (d * Math.PI) / 180;
		const x1 = CX + 6.5 * Math.cos(r(a));
		const y1 = CY + 6.5 * Math.sin(r(a));
		const cx = CX + 14 * Math.cos(r(a + 16));
		const cy = CY + 14 * Math.sin(r(a + 16));
		const x2 = CX + R_IMPELLER * Math.cos(r(a + 38));
		const y2 = CY + R_IMPELLER * Math.sin(r(a + 38));
		return `M${x1.toFixed(2)},${y1.toFixed(2)} Q${cx.toFixed(2)},${cy.toFixed(2)} ${x2.toFixed(2)},${y2.toFixed(2)}`;
	});

	// Rotation notation — the convention the rope-pump reference uses: a curved arrow on
	// the wheel saying which way it turns. Without it the direction is only legible while
	// the animation runs, so a still screenshot, a paused demo or a reduced-motion viewer
	// gets nothing — and this is the one property of the drawing that is an outright
	// engineering error if it reads the wrong way.
	//
	// The arc sweeps 150° → 112°: DECREASING angle, which in SVG's y-down space is
	// counter-clockwise, matching the backward-curved vanes. Hence sweep-flag 0 too.
	// Computed here rather than inline because `{@const}` is only legal as the direct
	// child of a block, not loose in markup.
	const ROT = (() => {
		const rad = (d) => (d * Math.PI) / 180;
		const r = (R_IMPELLER + R_BORE) / 2;
		const from = 150;
		const to = 112;
		const p = (deg) => [CX + r * Math.cos(rad(deg)), CY + r * Math.sin(rad(deg))];
		const [x1, y1] = p(from);
		const [hx, hy] = p(to);
		// Tangent for a decreasing angle at θ is (sin θ, −cos θ).
		const tx = Math.sin(rad(to));
		const ty = -Math.cos(rad(to));
		const f = (n) => n.toFixed(2);
		return {
			arc: `M${f(x1)},${f(y1)} A${r},${r} 0 0 0 ${f(hx)},${f(hy)}`,
			head:
				`M${f(hx - 2.4 * tx + 1.5 * ty)},${f(hy - 2.4 * ty - 1.5 * tx)} ` +
				`L${f(hx)},${f(hy)} ` +
				`L${f(hx - 2.4 * tx - 1.5 * ty)},${f(hy - 2.4 * ty + 1.5 * tx)}`
		};
	})();

	// Section hatching for a cut face: parallel 45° lines clipped to the shape. Sparse
	// (3.5 units apart) and soft — the rig plate lists hatching under INK_SOFT for the
	// same reason, it should read as "this is a cut" and never as tone.
	function hatch(x, y, w, h, step = 3.5) {
		const out = [];
		for (let i = -h; i < w; i += step) out.push(`M${(x + i).toFixed(1)},${(y + h).toFixed(1)} l${h},-${h}`);
		return out;
	}

	// --- motion -----------------------------------------------------------------
	// The impeller turns while the machine turns, at a rate read off the machine.
	// `sensor_04` is motor speed: it runs around 200–650 on this pump and collapses to
	// low single digits when the incident hits, so the drawing slows and then stops on
	// its own — from the sensors, with no reference to the verdict.
	//
	// STOPPED is `< 5`, not `<= 0`. Measured on incident #4 the fault floor is ~3.3
	// rather than a clean zero, so a threshold of 1 leaves the impeller turning at full
	// tilt through a breakdown, which is exactly the thing this cue is supposed not to
	// do. Anything under 5 is a stopped machine's noise on a channel that reads in the
	// hundreds when it is running.
	const STOPPED_BELOW = 5;
	let speed = $derived(latestValue(rows, 'sensor_04'));
	let spinning = $derived(Number.isFinite(speed) && speed >= STOPPED_BELOW);
	// Period from the reading, clamped so it neither strobes nor looks frozen while
	// running. 1200/speed puts a typical 250 at ~4.8s and a hard-run 650 at ~1.8s.
	let spinPeriod = $derived(spinning ? Math.min(8, Math.max(0.9, 1200 / speed)) : 0);

	// Flow is gated on CURRENT rather than on speed, deliberately. A pump can be turning
	// and still move nothing — that is what a dead-headed or dry-run pump is — and the
	// motor draws almost no current when it has no water to work against. On incident #4
	// the currents collapse to 0.0 while motor speed still reads a few units, so current
	// is the earlier and more truthful witness of "is this thing actually pumping".
	let motorCurrent = $derived(latestValue(rows, 'sensor_05'));
	let flowing = $derived(Number.isFinite(motorCurrent) && motorCurrent > 1);
	// The water itself, as marching dashes along the fluid path. Period from current, so
	// the stream visibly slows as the pump loses its load and stops dead when it stops —
	// the machine BEHAVING differently in each state rather than being labelled with it.
	// Current runs ~70 here, which puts a healthy pump at a brisk ~0.9s march.
	let flowPeriod = $derived(flowing ? Math.min(3, Math.max(0.45, 60 / motorCurrent)) : 0);

	// --- distress ----------------------------------------------------------------
	// THE PLATE DELIBERATELY CARRIES ALMOST NO BREAKDOWN CUE. What it shows is the impeller
	// slowing with motor speed and the flow dashes stopping with motor current — nothing
	// more. Read the two states side by side and they are close to identical. That is a
	// known, chosen cost, not an oversight.
	//
	// Four attempts at more were removed, in this order:
	//   heat off the housing   read as steam; a machine venting vapour is another failure
	//   judder on the housing  read as a rendering glitch
	//   water in the volute    worked — full casing vs empty was unmistakable — but the
	//                          stipple was speckle inside the machine and cost more in
	//                          drawing quality than the cue was worth
	// The first two were driven by a rolling median of the NDE bearing channel with a
	// hysteresis band, which took real tuning: that channel sits at a median of 35 while
	// healthy but spikes to 219, so a plain threshold flashes "damage" during normal running.
	// All of that machinery went with them.
	//
	// Before adding a fifth, note the honest limit. `pump_breakdown` is 99.95% `RECOVERING`
	// rows: the label means the pump is DOWN and never says which part failed or why, so any
	// glyph naming a failure mode asserts more than the data contains. The verdict badge and
	// the timeline carry the state; this drawing shows the machine, and a stopped machine
	// mostly looks like a running one.
	//
	// The one channel that would support a cue outright is motor current. It is exact: across
	// incident #4 it never drops below 24.4 while the pump is healthy and reads a flat 0.00
	// for every fault row. `flowing` already gates the dashes on it.

	// RATE, not duration — and this is the whole reason the impeller used to jump.
	//
	// Both cues read their period off a sensor, and those sensors change on EVERY replayed
	// row. The period used to be pushed into `animation-duration` via a custom property,
	// which looks like it should just re-time the spin. It does not: per CSS Animations,
	// changing `animation-duration` leaves the animation's start time alone, so the phase
	// it displays becomes `elapsed / newDuration`. Once `elapsed` is minutes deep, a 2%
	// duration change moves the wheel most of a turn — at 60s in, 1.92s → 1.88s takes it
	// from 31.25 to 31.91 revolutions, a ~240° snap. Every row. That is the "starts over".
	//
	// `playbackRate` is defined to hold `currentTime` while it changes, so the wheel keeps
	// the angle it is at and only its rate changes. The CSS period is now a fixed base and
	// these constants must match it.
	const SPIN_BASE = 3;
	const FLOW_BASE = 1;

	let impellerRef = $state(null);
	let flowInRef = $state(null);
	let flowOutRef = $state(null);

	function drive(node, base, period, running) {
		// Svelte scopes the @keyframes NAME, so match loosely rather than by equality.
		// Nothing to drive under prefers-reduced-motion — that rule sets `animation: none`,
		// so getAnimations() is empty and the cue stays a still drawing, as intended.
		const anim = node
			?.getAnimations?.()
			.find((a) => /pd-(rotate|march)/.test(a.animationName ?? ''));
		if (!anim) return;
		if (!running || !(period > 0)) {
			anim.pause();
			return;
		}
		anim.playbackRate = base / period;
		// Pausing leaves the wheel mid-turn, which is what a coasting machine looks like;
		// resuming carries on from that angle rather than snapping back to 0°.
		if (anim.playState !== 'running') anim.play();
	}

	$effect(() => {
		drive(impellerRef, SPIN_BASE, spinPeriod, spinning);
	});
	$effect(() => {
		drive(flowInRef, FLOW_BASE, flowPeriod, flowing);
		drive(flowOutRef, FLOW_BASE, flowPeriod, flowing);
	});

	// --- callouts ---------------------------------------------------------------
	// Four numerals, each pointing at the part whose channel it names. Same bargain the
	// rig plate makes: the numeral is on the drawing, the value is in the key.
	// Each numeral must land on the part its channel measures, not merely near it — a
	// leader that stops at the nearest outline reads as labelling that outline.
	//   1 speed   → the impeller itself, so the numeral clears the casing to the left
	//               rather than sitting on the discharge pipe, which it appeared to name
	//   2 current → the terminal box, where the three phase leads enter
	//   3 bearing → a bearing, not the sump edge below it
	//   4 oil     → the return line itself
	//
	// EVERY NUMERAL SITS IN CLEAR GROUND, and 3 and 4 moved to get there. 3 was at (108,88)
	// on the motor's near leg, and its leader reached the bearing by cutting through the
	// sump's right wall; it now stands above the housing and drops in through the housing's
	// own roof, crossing nothing else. 4 was at (62,94) directly on top of the casing's
	// right leg; it now sits in the open bay between the casing and the sump.
	//
	// They are not banished to the plate margin, which is the other way to read "out of the
	// illustration". On a SECTIONED machine that trade goes the wrong way: three of these
	// four parts are interior, so margin numerals mean long leaders raking across the casing
	// and the baseplate to reach them, and crossing lines are the thing that actually makes
	// a shape hard to read. Short leaders from clear ground cross least.
	//
	// 1 is the one leader that must cross a cut face — the impeller is inside the casing, so
	// there is no approach that does not pass through the hatched annulus. That is ordinary
	// draughting practice and it stays.
	const CALLOUTS = [
		{ n: 1, key: 'sensor_04', label: 'Motor speed', x: 12, y: 26, lx: CX - 13, ly: CY - 11 },
		{ n: 2, key: 'sensor_05', label: 'Motor current', x: 148, y: 22, lx: 138, ly: 29 },
		{ n: 3, key: 'sensor_41', label: 'NDE bearing', x: 95, y: 28, lx: 97, ly: 50 },
		{ n: 4, key: 'sensor_38', label: 'Lube oil return', x: 66, y: 92, lx: 76, ly: 84 }
	];

	function value(key) {
		return formatValue(latestValue(rows, key));
	}

	// --- plate sizing -----------------------------------------------------------
	// Aspect-fit inside the region, then CAPPED — and the cap is the part the rig plate
	// does not have.
	//
	// Measured off the live reference rather than guessed: its box is set in px from a
	// measured region (`height: 396px; width: 264px` in a 688×427 region), and forcing that
	// region to 1068px moves the plate to 760px with no ceiling — 1.32 → 4.22 px per user
	// unit as the panel grows. A plain fit is all its drawing needs, because 2:3 PORTRAIT
	// art in a landscape region is limited by height, so it lands at 264px wide — a third
	// of the region, with generous margin either side.
	//
	// This plate is LANDSCAPE (170:120), so the same rule inverts: it fills the width and
	// renders at 5.65 px per unit. That is what turned the shared 0.6-unit strokes into
	// 3.4px cables and the callout discs into buttons — the geometry was already drawn to
	// the rig's numbers, it was only ever being scaled four times too far. Strokes here
	// scale with the plate (no `vector-effect`, same as the reference), so matching the
	// reference's WEIGHT means matching its SCALE.
	//
	// 2.2 px per user unit is the rig's own figure at the demo's default window, and it is the
	// number the strokes in this file are authored against: 0.6 → 1.32px, matching the rig's
	// line for line.
	const REF_PX_PER_UNIT = 2.2;

	// ...but the plate is DRAWN larger than that, because at 2.2 a landscape drawing uses about
	// two-thirds of the width it is given and reads small in the region. Geometry scales with
	// this figure — the body, the callout discs (r=4 → 10.8px), the numerals (5 → 13.5px) —
	// which is what "bigger illustration" means.
	//
	// Line weight does NOT. Strokes here scale with the plate (no `vector-effect`, same as the
	// reference), so drawing 23% larger would render every stroke 23% heavier and undo the
	// whole point of matching the rig's weight. `sw()` below gives the difference back.
	const PLATE_PX_PER_UNIT = 2.7;

	// The box measured is the one the plate is centred in — everything the key does not take.
	// It is sized by the flex column that owns it, never by what is inside it, so measuring
	// here cannot feed back into the plate it sizes. No key arithmetic either: the key is a
	// sibling that takes its own height off the top of this box before it is measured, so a
	// key that wraps to two lines simply leaves less and the plate follows.
	let fitW = $state(0);
	let fitH = $state(0);
	// Capped by the measured box as well as by the reference scale, so the px-sized plate can
	// never exceed the parent it was measured from — a child that outgrows its container grows
	// the container, and the measurement oscillates.
	let scale = $derived(Math.min(fitW / VB_W, fitH / VB_H, PLATE_PX_PER_UNIT));
	let plateW = $derived(Math.max(0, VB_W * scale));
	let plateH = $derived(Math.max(0, VB_H * scale));

	// Stroke widths are written in user units against REF_PX_PER_UNIT, so every one of them
	// goes through here: at the reference scale `sw` is the identity, and at any other scale it
	// divides out the difference so the rendered width in CSS px never moves. That keeps the
	// numbers in the markup meaningful — 0.3 hatching, 0.6 outline, 0.9 casing, the hierarchy
	// stays legible as authored — instead of the alternative, which is `vector-effect:
	// non-scaling-stroke` everywhere with every literal pre-multiplied into px.
	//
	// It also holds the weight when the plate is SQUEEZED below the reference scale (a short
	// panel, or the log opening), where strokes would otherwise thin to hairlines and the
	// hatching would drop out entirely.
	let strokeK = $derived(scale > 0 ? REF_PX_PER_UNIT / scale : 1);
	const sw = (w) => +(w * strokeK).toFixed(3);
</script>

<!-- Two rows: everything-but-the-key, then the key. No `justify-center` on the column — the
     first row is `flex-1` and centres the drawing inside itself, so the plate lands in the
     middle of the region while the key stays pinned to its bottom edge. Centring the column
     as one group instead welds the key to the drawing and floats the pair, which is right
     when the drawing fills the region (the reference's does) and wrong when it cannot (ours
     is capped at the reference's scale, so it never fills a tall panel). -->
<div class={cn('flex min-h-0 flex-1 flex-col items-center', className)} {...restProps}>
	<!-- The measured box: what the key leaves. -->
	<div
		bind:clientWidth={fitW}
		bind:clientHeight={fitH}
		class="flex min-h-0 w-full flex-1 items-center justify-center"
	>
		<!-- The plate box, sized in px like the reference's, with the drawing filling it. -->
		<div style="width: {plateW}px; height: {plateH}px">
			<svg
				viewBox="0 0 {VB_W} {VB_H}"
				class="h-full w-full"
				preserveAspectRatio="xMidYMid meet"
				font-family="var(--font-mono, ui-monospace, monospace)"
				role="img"
				aria-label="Sectioned elevation of the motor-driven centrifugal pump"
			>
				<defs>
					<!-- The cut faces of the casing: the annulus between bore and outer wall. -->
					<clipPath id="pd-case">
						<path
							d="M{CX},{CY} m-{R_CASE},0 a{R_CASE},{R_CASE} 0 1,0 {R_CASE * 2},0 a{R_CASE},{R_CASE} 0 1,0 -{R_CASE * 2},0 Z
							   M{CX},{CY} m-{R_BORE},0 a{R_BORE},{R_BORE} 0 1,1 {R_BORE * 2},0 a{R_BORE},{R_BORE} 0 1,1 -{R_BORE * 2},0 Z"
							clip-rule="evenodd"
						/>
					</clipPath>
					<!-- ONLY the end shield is a cut face, not the whole frame. Clipping to the
					     full motor rect hatched the entire block, which reads as a motor sectioned
					     through its middle — and a sectioned motor would have to show a rotor and
					     stator, not blank tone. Twelve units is the shield. -->
					<clipPath id="pd-motor"><rect x="104" y="38" width="12" height="32" /></clipPath>
				</defs>

				<!-- ---------------- context, all INK_SOFT ---------------- -->
				<!-- ground and baseplate -->
				<line x1="6" y1="104" x2="164" y2="104" stroke={INK_SOFT} stroke-width={sw(0.6)} />
				{#each hatch(6, 104, 158, 5, 6) as d, i (i)}
					<path {d} stroke={INK_SOFT} stroke-width={sw(0.3)} opacity="0.55" fill="none" />
				{/each}
				<rect x="18" y="98" width="134" height="6" fill="none" stroke={INK_SOFT} stroke-width={sw(0.6)} />
				<!-- pedestals under casing and motor -->
				<path d="M32,{LEG_Y} L32,98 M60,{LEG_Y} L60,98" stroke={INK_SOFT} stroke-width={sw(0.5)} />
				<path d="M110,70 L110,98 M144,70 L144,98" stroke={INK_SOFT} stroke-width={sw(0.5)} />

				<!-- suction pipe, axial into the eye, with a flange -->
				<path d="M6,{SHAFT_Y - 7} L{SUCTION_X},{SHAFT_Y - 7} M6,{SHAFT_Y + 7} L{SUCTION_X},{SHAFT_Y + 7}"
					stroke={INK_SOFT} stroke-width={sw(0.7)} fill="none" />
				<path d="M6,{SHAFT_Y - 10} L6,{SHAFT_Y + 10}" stroke={INK_SOFT} stroke-width={sw(0.9)} />
				<!-- Flow arrows are drawn ONLY while the machine is actually moving water — the
				     reference drawing's one piece of notation worth keeping, and the rig plate's
				     rule for its mud run (INK while circulating, dropped to context when not).
				     Permanent arrows were a small lie: when the impeller stops, nothing is being
				     pumped, and the drawing said otherwise. Now a breakdown reads on the plate as
				     the wheel stopping AND the flow ceasing, both off the sensors. -->
				{#if flowing}
					<!-- The stream, marching into the eye. Drawn left-to-right so a negative
					     dashoffset carries it along the path in the direction water travels. -->
					<path
						bind:this={flowInRef}
						class="pd-flow"
						d="M8,{SHAFT_Y} L32,{SHAFT_Y}"
						stroke={INK}
						stroke-width={sw(1)}
						stroke-dasharray="2.5 3"
						fill="none"
					/>
				{/if}

				<!-- discharge, tangential off the volute top, with a flange -->
				<path d="M{CX - 7},{DISCHARGE_Y} L{CX - 7},14 M{CX + 7},{DISCHARGE_Y} L{CX + 7},14"
					stroke={INK_SOFT} stroke-width={sw(0.7)} fill="none" />
				<path d="M{CX - 10},14 L{CX + 10},14" stroke={INK_SOFT} stroke-width={sw(0.9)} />
				{#if flowing}
					<!-- Discharge: path runs bottom-to-top, so the same negative offset carries the
					     dashes up the riser. -->
					<path
						bind:this={flowOutRef}
						class="pd-flow"
						d="M{CX},27 L{CX},16"
						stroke={INK}
						stroke-width={sw(1)}
						stroke-dasharray="2.5 3"
						fill="none"
					/>
				{/if}

				<!-- ---------------- the machine, INK ---------------- -->
				<!-- casing: outer wall and bore, with the annulus hatched as a cut face -->
				<circle cx={CX} cy={CY} r={R_CASE} fill="none" stroke={INK} stroke-width={sw(0.9)} />
				<circle cx={CX} cy={CY} r={R_BORE} fill="none" stroke={INK} stroke-width={sw(0.6)} />
				<g clip-path="url(#pd-case)">
					{#each hatch(CX - R_CASE, CY - R_CASE, R_CASE * 2, R_CASE * 2) as d, i (i)}
						<path {d} stroke={INK_SOFT} stroke-width={sw(0.3)} opacity="0.7" fill="none" />
					{/each}
				</g>

				<!-- impeller, inside the cut casing. Turns only while the machine turns. -->
				<!-- The class is permanent and `drive()` pauses it, rather than the class toggling on
				     `spinning`. Removing the animation would drop the wheel back to 0° the instant
				     the pump stops; pausing holds the angle it stopped at. -->
				<g
					bind:this={impellerRef}
					class="pd-spin"
					style="transform-origin: {CX}px {CY}px; transform-box: view-box;"
				>
					{#each VANES as d, i (i)}
						<path {d} fill="none" stroke={INK} stroke-width={sw(0.7)} stroke-linecap="round" />
					{/each}
					<circle cx={CX} cy={CY} r="6.5" fill="none" stroke={INK} stroke-width={sw(0.7)} />
					<!-- No keyway stub. It was here to make rotation legible on a symmetric part, but
					     the vanes are a backward-curved spiral and already read as turning, so the mark
					     was just a stray hairline in the bore. -->
				</g>
				<!-- Rotation notation. Sits between the vane tips and the bore, on the wheel it
				     describes. Geometry in the script — see ROT. -->
				<g class="pointer-events-none" stroke={INK_SOFT} stroke-width={sw(0.55)} fill="none" opacity="0.95">
					<path d={ROT.arc} />
					<path d={ROT.head} />
				</g>

				<!-- Shaft from impeller through the bearing housing into the motor.
				     OPAQUE, not two hairlines. It used to be a pair of edge lines over `fill="none"`,
				     so the turning vanes swept visibly THROUGH the shaft body — the shaft is in front
				     of the wheel in this section, so it has to occlude what passes behind it. The
				     background-filled body does that; the edge lines then draw on top of it, which is
				     why the outline is unchanged. -->
				<!-- It STOPS at the motor face (104), where it used to run on to 110. The motor's end
				     shield is hatched, and that hatch draws after the shaft, so the last six units of
				     shaft had grey 45° lines crossing it — the one place in the drawing where you
				     could not tell which part you were looking at. A shaft that meets the frame reads
				     as entering the motor; one that stops six units inside a hatched face reads as
				     broken off. -->
				<rect
					x={CX}
					y={SHAFT_Y - 2.2}
					width={104 - CX}
					height="4.4"
					fill="var(--color-background)"
					stroke="none"
				/>
				<path d="M{CX},{SHAFT_Y - 2.2} L104,{SHAFT_Y - 2.2} M{CX},{SHAFT_Y + 2.2} L104,{SHAFT_Y + 2.2}"
					stroke={INK} stroke-width={sw(0.6)} fill="none" />
				<!-- Shaft axis mark, after the shaft body so the fill does not bury it. -->
				<circle cx={CX} cy={CY} r="1.6" fill={INK} />

				<!-- Bearing housing at the non-drive end: two bearings, which is what the two NDE
				     temperature channels are reading. -->
				<g>
					<rect x="78" y="42" width="26" height="24" fill="none" stroke={INK} stroke-width={sw(0.8)} />
					<!-- Balls at ±3.4, not ±3.2: a ball of r=1.1 at 3.2 spans 2.1–4.3 from the axis, so its
					     inner edge crossed the shaft edge at 2.2 and collided with it. 3.4 spans 2.3–4.5,
					     which clears the shaft and still sits inside the 4.6 outer race — the ball rides
					     between the two, which is where a bearing ball actually is. -->
					{#each [85, 97] as bx (bx)}
						<circle cx={bx} cy={SHAFT_Y} r="4.6" fill="none" stroke={INK} stroke-width={sw(0.6)} />
						<circle cx={bx} cy={SHAFT_Y - 3.4} r="1.1" fill="none" stroke={INK} stroke-width={sw(0.45)} />
						<circle cx={bx} cy={SHAFT_Y + 3.4} r="1.1" fill="none" stroke={INK} stroke-width={sw(0.45)} />
					{/each}
					<!-- lube oil sump below the bearings, with its return line and a sight level -->
					<path d="M80,66 L80,76 L102,76 L102,66" fill="none" stroke={INK} stroke-width={sw(0.7)} />
					<path d="M81,72 L101,72" stroke={INK_SOFT} stroke-width={sw(0.4)} opacity="0.9" />
				</g>

				<!-- The return line now runs BETWEEN two parts instead of floating. Both ends used to
				     stop in open space — it began at (71,76) beside the sump rather than on it, and
				     ended at (102,84) under nothing. It leaves the sump's bottom-left corner and
				     lands on the motor's near leg, which is a route a return line can actually take. -->
				<path d="M80,76 L71,76 L71,84 L110,84" fill="none" stroke={INK} stroke-width={sw(0.6)} />

				<!-- motor: frame, cooling fins, end shield hatched as a cut, terminal box -->
				<rect x="104" y="38" width="46" height="32" fill="none" stroke={INK} stroke-width={sw(0.9)} />
				<g clip-path="url(#pd-motor)">
					{#each hatch(104, 38, 12, 32) as d, i (i)}
						<path {d} stroke={INK_SOFT} stroke-width={sw(0.3)} opacity="0.7" fill="none" />
					{/each}
				</g>
				{#each [116, 121, 126, 131, 136, 141] as fx (fx)}
					<path d="M{fx},38 L{fx},70" stroke={INK_SOFT} stroke-width={sw(0.35)} opacity="0.75" />
				{/each}
				<rect x="126" y="30" width="16" height="8" fill="none" stroke={INK} stroke-width={sw(0.7)} />
				<!-- three leads into the terminal box: the three phase currents -->
				{#each [130, 134, 138] as lx (lx)}
					<path d="M{lx},30 L{lx},24" stroke={INK} stroke-width={sw(0.5)} />
				{/each}

				<!-- ---------------- reference numerals ---------------- -->
				{#each CALLOUTS as c (c.n)}
					<path d="M{c.x},{c.y > c.ly ? c.y - 4 : c.y + 4} L{c.lx},{c.ly}"
						stroke={INK_SOFT} stroke-width={sw(0.4)} opacity="0.9" />
					<!-- knocked out of whatever it sits over, exactly as the rig plate does -->
					<circle cx={c.x} cy={c.y} r="4" fill="var(--color-background)" stroke={INK} stroke-width={sw(0.5)} />
					<text x={c.x} y={c.y} font-size="5" fill={INK} text-anchor="middle" dominant-baseline="central">
						{c.n}
					</text>
				{/each}
			</svg>
		</div>
	</div>

	<!-- The key in HTML, not SVG: the numerals should scale with the drawing, the live
	     values should stay at a readable size whatever the panel does. -->
	<!-- Value sits directly after its label rather than being pushed to the cell's right
	     edge with `ml-auto`. The columns were wide enough that a right-aligned figure
	     ended up a long way from the name it belongs to, and the eye had to bridge the
	     gap four times; a value and its label read as one unit when they touch. -->
	<!-- Read off the reference's own key, class for class:
	       row     `flex-wrap items-baseline justify-center gap-x-5 gap-y-1`
	       numeral `text-[13px] text-plate-ink tabular-nums`, and it carries a PERIOD
	       label   `text-[13px] whitespace-nowrap text-plate-ink`
	       value   `font-mono text-[13px] whitespace-nowrap`, plain foreground
	     Three things change from what this had. 13px, not 12 — and the whole row is one size
	     now instead of a 10px numeral beside 12px text. `text-plate-ink` on the numeral and
	     the label rather than `text-muted-foreground`: the key is part of the DRAWING, so it
	     is set in the drawing's own ink, while the value stays plain foreground so the live
	     figure is the brightest thing in the row. And `whitespace-nowrap` in place of
	     `truncate` — a row that wraps as whole entries reads; one that clips its labels does
	     not.
	     No `px-4`: the Pane block around this already insets by 4. -->
	<dl class="flex w-full shrink-0 flex-wrap items-baseline justify-center gap-x-5 gap-y-1">
		{#each CALLOUTS as c (c.n)}
			<div class="flex items-baseline gap-1.5">
				<span class="text-[13px] text-plate-ink tabular-nums">{c.n}.</span>
				<dt class="text-[13px] whitespace-nowrap text-plate-ink">{c.label}</dt>
				<dd class="font-mono text-[13px] whitespace-nowrap">{value(c.key)}</dd>
			</div>
		{/each}
	</dl>
</div>

<style>
	/* FIXED period — must stay in step with SPIN_BASE. The impeller still visibly slows as
	   the machine winds down and stops when it stops, but that is done by scaling
	   `playbackRate` in the script, not by rewriting this duration. See the long note at
	   `drive()` for why re-timing a running animation through its duration makes it jump. */
	.pd-spin {
		animation: pd-rotate 3s linear infinite;
	}
	/* COUNTER-clockwise, and it is the vanes that decide it, not taste.
	   They are drawn backward-curved — each vane's outer tip sits 38° clockwise of its
	   root (see VANES) — which is the standard geometry for a centrifugal water pump:
	   the tip must TRAIL the direction of rotation. A tip clockwise of the root only
	   trails if the wheel turns counter-clockwise. Spinning it clockwise instead makes
	   the tips lead, which draws a FORWARD-curved impeller — a fan geometry, not a pump.
	   In SVG's y-down space a positive angle is clockwise, hence -360deg. */
	@keyframes pd-rotate {
		to {
			transform: rotate(-360deg);
		}
	}
	/* The stream. dasharray is 2.5 + 3, so one full cycle is 5.5 units — offsetting by
	   exactly that makes the march seamless instead of jumping at the loop. */
	/* Fixed period, in step with FLOW_BASE — same reasoning as .pd-spin. */
	.pd-flow {
		animation: pd-march 1s linear infinite;
	}
	@keyframes pd-march {
		to {
			stroke-dashoffset: -5.5;
		}
	}


	/* The motion cues are decoration over information that is already on screen as numbers,
	   so they go away entirely rather than degrading. Nothing is lost by stopping them: the
	   breakdown cue is the casing emptying, which is a state change, not an animation. */
	@media (prefers-reduced-motion: reduce) {
		.pd-spin,
		.pd-flow {
			animation: none;
		}
	}
</style>
