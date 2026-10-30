<script>
	import { cn } from '$lib/utils.js';
	import { contourDensity } from 'd3-contour';
	import { CLASSES, CLASS_META } from '$lib/red.js';
	import { hover } from '$lib/stores/hover.svelte.js';

	// The same embedding space as Archetype AI's OSM rig monitor, so both workbenches read as
	// one product. The construction is theirs verbatim — density contours per class,
	// pills on the cores, a fading trail of live windows. What differs is RED's data:
	// two classes instead of six.
	//
	// The asset also ships the two fitted PROTOTYPES (the per-class mean embeddings the
	// nearest-prototype head compares against). They were drawn here as crosses and are
	// deliberately not: on a two-class streak each prototype lands inside its own cluster,
	// so the mark read as a stray glyph beside the pill that already names the territory.
	// `landscape.prototypes` is still in the asset if it is ever wanted back.

	let { pump, class: className, ...restProps } = $props();

	let containerRef = $state(null);
	let W = $state(800);
	let H = $state(420);
	const PAD = 24;

	$effect(() => {
		if (!containerRef) return;
		const ro = new ResizeObserver((entries) => {
			const { width, height } = entries[0].contentRect;
			if (width > 0 && height > 0) {
				W = width;
				H = height;
			}
		});
		ro.observe(containerRef);
		return () => ro.disconnect();
	});

	let landscape = $derived(pump.landscape);

	// data extent (fixed per asset)
	let extent = $derived.by(() => {
		if (!landscape) return null;
		let minX = Infinity,
			maxX = -Infinity,
			minY = Infinity,
			maxY = -Infinity;
		for (const s of landscape.shots) {
			if (s.x < minX) minX = s.x;
			if (s.x > maxX) maxX = s.x;
			if (s.y < minY) minY = s.y;
			if (s.y > maxY) maxY = s.y;
		}
		return { minX, maxX, minY, maxY };
	});

	// Uniform scale preserving the data's aspect ratio, letterboxed and centred.
	//
	// This matters more here than on the rig. PC1 carries 33% of the variance and PC2
	// only 4%, so the library really is a nearly flat horizontal streak — normal at one
	// end, breakdown at the other. Stretching y to fill the panel would manufacture a
	// vertical spread the data does not have, and the vertical axis is exactly the one
	// the guide tells people not to read.
	let view = $derived.by(() => {
		if (!extent) return null;
		const rx = extent.maxX - extent.minX;
		const ry = extent.maxY - extent.minY;
		const k = Math.min((W - 2 * PAD) / rx, (H - 2 * PAD) / ry);
		return { k, ox: (W - k * rx) / 2, oy: (H - k * ry) / 2 };
	});
	function sx(x) {
		return view.ox + (x - extent.minX) * view.k;
	}
	function sy(y) {
		return H - view.oy - (y - extent.minY) * view.k;
	}

	// Dot lattice behind the plot, ported from the interactive workbench's EmbeddingScatter
	// (archetypeai/design-agents-interactive-workbench, refactor/r3-ui) so the two embedding
	// views read as the same surface. Constants and the pixel-snapping are theirs.
	//
	// It is ONE path of circle subpaths rather than ~2000 <circle> elements: the lattice is
	// inert backdrop, and a node each would be that many more things for the browser to lay
	// out on every resize tick, for no gain.
	//
	// The snapping is the part worth keeping honest. Steps are fractional — the lattice is
	// fitted to the panel by dividing the span into whole columns — so centres are rounded
	// to whole pixels. Left unrounded, a 2px dot straddles the device grid unevenly and
	// smears across three columns of pixels, which is what stops a fine lattice reading as
	// crisp. This works here only because the SVG is 1 unit = 1 px (viewBox 0 0 W H at
	// width W height H); if the plate is ever given a fixed viewBox, the rounding becomes
	// meaningless and should go.
	const GRID_INSET = 16;
	const GRID_STEP = 13;
	const GRID_DOT_R = 1;
	let gridDots = $derived.by(() => {
		const w = W - GRID_INSET * 2;
		const h = H - GRID_INSET * 2;
		if (w <= 0 || h <= 0) return '';
		const cols = Math.max(1, Math.round(w / GRID_STEP));
		const rows = Math.max(1, Math.round(h / GRID_STEP));
		const stepX = w / cols;
		const stepY = h / rows;
		const r = GRID_DOT_R;
		let d = '';
		for (let row = 0; row <= rows; row++) {
			const y = Math.round(GRID_INSET + row * stepY);
			for (let col = 0; col <= cols; col++) {
				const x = Math.round(GRID_INSET + col * stepX) - r;
				d += `M${x} ${y}a${r} ${r} 0 1 0 ${r * 2} 0a${r} ${r} 0 1 0 ${-r * 2} 0`;
			}
		}
		return d;
	});

	// The reference's constants, kept verbatim — see the long note in the rig's copy on
	// why they are not re-derived from the data.
	const BLOB_BANDWIDTH = 22;
	const BLOB_THRESHOLDS = 8;
	const MIN_BLOB_POINTS = 5;

	function contourToPath(contour) {
		let d = '';
		for (const polygon of contour.coordinates) {
			for (const ring of polygon) {
				let first = true;
				for (const [x, y] of ring) {
					d += `${first ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
					first = false;
				}
				d += 'Z';
			}
		}
		return d;
	}

	// `s.c`, not `s.s`: RED's landscape keys its shots by CLASS index. Same schema
	// otherwise, so build_embedding_landscape.py output drops straight in.
	let blobGroups = $derived.by(() => {
		if (!landscape || !extent || !view || W <= 0 || H <= 0) return [];
		const out = [];
		for (let i = 0; i < CLASSES.length; i++) {
			const pts = landscape.shots.filter((s) => s.c === i);
			if (pts.length < MIN_BLOB_POINTS) continue;
			let density;
			try {
				density = contourDensity()
					.x((d) => sx(d.x))
					.y((d) => sy(d.y))
					.size([W, H])
					.bandwidth(BLOB_BANDWIDTH)
					.thresholds(BLOB_THRESHOLDS)(pts);
			} catch {
				continue;
			}
			if (!density.length) continue;
			const maxVal = Math.max(...density.map((c) => c.value));
			out.push({
				state: CLASSES[i],
				color: CLASS_META[CLASSES[i]].color,
				paths: density.map((c) => ({
					d: contourToPath(c),
					opacity: 0.06 + 0.22 * (maxVal > 0 ? c.value / maxVal : 0)
				}))
			});
		}
		return out;
	});

	// Pills anchored at the MEDIAN rather than the mean — with a streak-shaped cluster
	// the mean drifts into the sparse middle while the median stays where the contour
	// maths puts the darkest band.
	const PILL_H = 18;
	const PILL_PAD_X = 7;
	const MONO_CH = 6.02;
	let clusterPills = $derived.by(() => {
		if (!landscape || !extent || !view) return [];
		return CLASSES.map((st, i) => {
			const pts = landscape.shots.filter((s) => s.c === i);
			if (!pts.length) return null;
			const xs = pts.map((s) => s.x).sort((a, b) => a - b);
			const ys = pts.map((s) => s.y).sort((a, b) => a - b);
			const label = CLASS_META[st].short;
			const w = label.length * MONO_CH + PILL_PAD_X * 2;
			const cx = sx(xs[xs.length >> 1]);
			const cy = sy(ys[ys.length >> 1]);
			return {
				label,
				color: CLASS_META[st].color,
				w,
				x: Math.min(W - w - 4, Math.max(4, cx - w / 2)),
				y: Math.min(H - PILL_H - 4, Math.max(4, cy - PILL_H / 2))
			};
		}).filter(Boolean);
	});

	// live projected windows (only predictions that carried embeddings)
	const LIVE = 150;
	let live = $derived(pump.predictions.filter((p) => p.ex !== undefined).slice(-LIVE));
</script>

<div
	class={cn('relative flex max-h-full min-h-0 flex-col gap-2 overflow-hidden', className)}
	{...restProps}
>
	<div bind:this={containerRef} class="relative min-h-0 w-full flex-1">
		{#if pump.landscapeError}
			<!-- A mismatched asset is not an empty one, and the store already knows why:
			     say so instead of rendering a blank plate. -->
			<p class="py-8 text-center text-sm text-muted-foreground">{pump.landscapeError}</p>
		{:else if !landscape}
			<p class="py-8 text-center text-sm text-muted-foreground">
				No landscape asset — run fit/build_embedding_landscape.py
			</p>
		{:else}
			<svg
				viewBox="0 0 {W} {H}"
				width={W}
				height={H}
				class="absolute inset-0"
				font-family="var(--font-mono, ui-monospace, monospace)"
			>
				<!-- Lattice first: it is the ground everything else is drawn on.
				     The reference paints this with Tailwind's `fill-border`; here it is the token
				     directly, which is what every other colour in this file does and what the
				     pump plate does. Same pixels — `--color-border` is `--border`, zinc-200 on
				     light and zinc-800 on dark — with no dependency on that utility having been
				     generated. -->
				<path d={gridDots} fill="var(--color-border)" class="pointer-events-none" />

				<!-- Density first, so everything else sits on top of it. Only the innermost
				     band of each group takes the pointer — outer bands overlap where the two
				     clusters approach, so a hit there resolves to whichever painted last. -->
				{#each blobGroups as g (g.state)}
					{@const dim = hover.state && hover.state !== g.state}
					{#each g.paths as p, i (i)}
						<path
							d={p.d}
							fill={g.color}
							fill-opacity={dim ? p.opacity * 0.25 : p.opacity}
							class={i === g.paths.length - 1 ? 'cursor-pointer' : 'pointer-events-none'}
							role={i === g.paths.length - 1 ? 'presentation' : undefined}
							onpointerenter={i === g.paths.length - 1 ? () => hover.setState(g.state) : undefined}
							onpointerleave={i === g.paths.length - 1 ? () => hover.clear() : undefined}
						/>
					{/each}
				{/each}

				<!-- Scatter only, no connecting trail. The rig's polyline joined the windows in
				     time order, but RED's cluster is a dense knot rather than a path: 150 chords
				     inside one blob read as a mesh, not a trajectory. Recency still reads off the
				     opacity ramp and the ring on the newest window. -->
				{#each live as p, i (p.id)}
					<circle
						cx={sx(p.ex)}
						cy={sy(p.ey)}
						r={i === live.length - 1 ? 5 : 2.5}
						fill={(CLASS_META[p.state] ?? CLASS_META.unknown).color}
						opacity={i === live.length - 1 ? 1 : 0.35 + (0.55 * i) / live.length}
					/>
				{/each}
				{#if live.length}
					{@const last = live[live.length - 1]}
					<circle
						cx={sx(last.ex)}
						cy={sy(last.ey)}
						r="9"
						fill="none"
						stroke={(CLASS_META[last.state] ?? CLASS_META.unknown).color}
						stroke-width="1.5"
						opacity="0.8"
					/>
				{/if}

				<!-- Pills last: they name the territory, so nothing draws over them. -->
				{#each clusterPills as c (c.label)}
					<rect
						x={c.x}
						y={c.y}
						width={c.w}
						height={PILL_H}
						rx="3"
						fill="var(--color-background)"
						fill-opacity="0.72"
						stroke={c.color}
						stroke-width="1"
						class="pointer-events-none"
					/>
					<text
						x={c.x + c.w / 2}
						y={c.y + PILL_H / 2}
						font-size="10"
						fill={c.color}
						text-anchor="middle"
						dominant-baseline="central"
						class="pointer-events-none"
					>
						{c.label}
					</text>
				{/each}
			</svg>
		{/if}
	</div>

	{#if !pump.embeddingsSeen}
		<p class="shrink-0 pt-1 text-center text-xs text-muted-foreground">
			waiting for embeddings (agent must enable output_embeddings)
		</p>
	{/if}
</div>
