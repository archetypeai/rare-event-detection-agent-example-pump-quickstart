<script>
	import { cn } from '$lib/utils.js';
	import { CLASS_META } from '$lib/red.js';

	// Segmented chip bar, ported from the rig monitor's state-timeline: one chip per
	// classified window, right-anchored so the newest is always the rightmost and older
	// ones shift off the left.
	//
	// This replaces RED's full-width green-and-red band. The band drew one rect per RUN
	// rather than per window, which read as a continuous recording and hid how many
	// separate calls the agent had actually made — five scattered breakdown windows and
	// one five-window run looked identical. A chip per window cannot do that.
	//
	// Renders BARE content — no pane, no caption. It sits in the output panel's state
	// block, under the verdict badge it puts in context.
	let { predictions = [], class: className, ...restProps } = $props();

	const PITCH = 11; // chip + gap
	const GAP = 5;

	// Slot count comes from measured width, so the bar spans its block exactly with no
	// scrollbar. Chips are fixed-width inside a w-full parent, so count cannot feed back
	// into width.
	let barWidth = $state(0);
	let slotCount = $derived(Math.max(1, Math.floor((barWidth + GAP) / PITCH)));

	let recent = $derived(predictions.slice(-slotCount));
	let pending = $derived(Math.max(0, slotCount - recent.length));
</script>

<div class={cn('flex flex-col gap-2', className)} {...restProps}>
	<!-- justify-end so the run stays welded to the right edge even on a frame where a
	     resize changed the slot count before the padding caught up -->
	<div
		bind:clientWidth={barWidth}
		class="flex w-full min-w-0 items-center justify-end gap-[5px] overflow-hidden"
		role="list"
		aria-label="Detection timeline"
	>
		{#each Array.from({ length: pending }, (_, i) => i) as i (i)}
			<div
				role="listitem"
				class="h-8 w-1.5 shrink-0 rounded-[1px] bg-muted-foreground/20"
				title="pending"
			></div>
		{/each}
		{#each recent as p (p.id)}
			<div
				role="listitem"
				class="h-8 w-1.5 shrink-0 rounded-[1px]"
				style:background={(CLASS_META[p.state] ?? CLASS_META.unknown).color}
				title="{CLASS_META[p.state]?.label ?? p.state} @ {new Date(p.timestamp_ms).toLocaleString(
					'en-US',
					{ hour12: false }
				)}"
			></div>
		{/each}
	</div>

	<!-- No legend: two colours, and the verdict badge above teaches both as they happen —
	     a flip shows up in the badge and in the newest chip in the same hue at the same
	     moment. Every chip still names itself and its timestamp on hover. -->

	{#if recent.length === 0}
		<p class="text-center text-sm text-muted-foreground">Press play to see detections</p>
	{:else}
		<div class="flex justify-between text-[11px] text-muted-foreground tabular-nums">
			<span class="text-[11px]"
				>{new Date(recent[0].timestamp_ms).toLocaleTimeString('en-US', { hour12: false })}</span
			>
			<span class="text-[11px]">last {recent.length} windows</span>
			<span class="text-[11px]"
				>{new Date(recent[recent.length - 1].timestamp_ms).toLocaleTimeString('en-US', {
					hour12: false
				})}</span
			>
		</div>
	{/if}
</div>
