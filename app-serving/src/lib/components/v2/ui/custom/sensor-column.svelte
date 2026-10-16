<script>
	import { cn } from '$lib/utils.js';
	import { CHANNELS, CLASS_META, WINDOW_SIZE } from '$lib/red.js';
	import {
		latestValue,
		formatValue,
		sparklinePath,
		windowRange,
		windowBands,
		mergeRanges
	} from '$lib/samples.js';
	import { hover } from '$lib/stores/hover.svelte.js';

	// The ten channels the classifier reads, as one continuous list. Renders bare
	// content: the pane and its caption belong to input-panel.svelte.
	//
	// Order is red.js's CHANNELS — Drive, Current, Thermal — which is the reading
	// order of the old three-column panel flattened into one column. Group headings
	// are gone: nine of the ten labels already say which instrument they are
	// ("Phase Current B", "NDE Bearing Temp 1"), so the headings were restating the
	// label a row below them.
	//
	// No units, unlike the rig's. The Kaggle dataset ships no data dictionary, so
	// every unit here would be a guess printed as a fact — see channels.json.

	let { rows = [], predictions = [], class: className, ...restProps } = $props();

	// What the pointer is over in the Output panel, resolved to timestamp ranges once
	// for the whole column: the ranges are the same ten times over, only the
	// x-projection is per channel.
	//
	// Windows overlap heavily here — step 1 over a 64-sample window means consecutive
	// windows share 63 samples — so a run of one verdict merges into a single band
	// rather than a picket fence.
	let hoverRanges = $derived.by(() => {
		if (!rows.length || !hover.state) return [];
		const out = [];
		for (const p of predictions) {
			if (p.state !== hover.state) continue;
			const r = windowRange(rows, p.timestamp_ms, WINDOW_SIZE);
			if (r) out.push(r);
		}
		return mergeRanges(out);
	});
	let hoverColor = $derived(
		hover.state ? (CLASS_META[hover.state] ?? CLASS_META.unknown).color : null
	);
</script>

{#snippet sensorRow(ch)}
	<!-- No border of its own: the column's divide-y is the only rule, so the ten
	     readouts read as one continuous list rather than ten cards. -->
	<div class="flex min-h-0 flex-1 flex-col justify-center gap-1 py-1.5">
		<div class="flex items-baseline justify-between">
			<span class="text-xs text-muted-foreground">{ch.label}</span>
			<!-- Foreground tone, not the channel colour: read as a number, a coloured
			     value is indistinguishable from a verdict chip on the output side. -->
			<span class="font-mono text-sm">{formatValue(latestValue(rows, ch.key))}</span>
		</div>
		<!-- capped rather than filling: in a tall row an uncapped chart drifts to the
		     bottom and reads as belonging to the NEXT label instead of its own -->
		<svg class="max-h-14 min-h-3 w-full flex-1" viewBox="0 0 120 24" preserveAspectRatio="none">
			<!-- Where the hovered verdict's windows fall on this channel. Drawn before the
			     trace so the signal stays on top of its own highlight, and full-height so
			     the band marks a span of TIME rather than appearing to bound a range of
			     values. -->
			{#if hoverColor}
				{#each windowBands(rows, ch.key, 120, hoverRanges) as b, i (i)}
					<rect x={b.x} y="0" width={b.w} height="24" fill={hoverColor} opacity="0.28" />
				{/each}
			{/if}
			<!-- The viewBox stretches to whatever height the row gets, so the stroke opts
			     out of that scaling or it thickens as the panel grows. -->
			<path
				d={sparklinePath(rows, ch.key, 120, 24)}
				fill="none"
				stroke="var(--color-foreground)"
				stroke-width="1.5"
				stroke-linecap="round"
				stroke-linejoin="round"
				vector-effect="non-scaling-stroke"
				opacity="0.8"
			/>
		</svg>
	</div>
{/snippet}

<div class={cn('flex min-h-0 flex-1 flex-col divide-y divide-separator', className)} {...restProps}>
	{#each CHANNELS as ch (ch.key)}
		{@render sensorRow(ch)}
	{/each}
</div>
