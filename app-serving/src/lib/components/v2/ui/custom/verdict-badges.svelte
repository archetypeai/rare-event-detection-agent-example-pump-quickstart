<script>
	import { cn } from '$lib/utils.js';
	import Badge from '$lib/components/v2/ui/primitives/badge/index.js';
	import { CADENCE_MS, CLASS_META, samplesToDuration, WINDOW_SIZE } from '$lib/red.js';

	// The demo's argument, and the RED counterpart of the rig's CURRENT / PREDICTED pair.
	// The shape is the same; the meaning of the left badge is NOT, and that is worth
	// stating because both apps ship in one ecosystem and a reader will carry the word
	// across.
	//
	//   OSM  CURRENT = ground truth, read off the recording's own ACTC activity code,
	//        set against PREDICTED, the agent's call. Two independent sources, so the
	//        pair is an eval you can watch.
	//
	//   RED  CURRENT = the AGENT'S VERDICT. There is no second source, by design: this
	//        UI shows only what a real control room would have, and a crew watching a
	//        live pump has no label track. Putting the dataset's label on screen would
	//        turn the demo into a scored test — and would quietly reveal incident #6 as
	//        a miss, which the app deliberately does not do.
	//
	// So the second badge cannot be PREDICTED either — RED detects, it does not predict,
	// and the Notion guide is emphatic that we never imply otherwise. What earns the
	// slot instead is the alarm clock: how long the agent has been asserting a
	// breakdown, which is the number an operator would actually act on.

	// `showAlarm` exists for a second caller that no longer exists: the Input panel
	// carried this badge briefly, and the verdict was moved back out when it became clear
	// the ask was for the MACHINE to show its state rather than to be labelled with it.
	// The prop is kept because it costs nothing and the distinction it encodes is real —
	// the alarm is a property of the agent's run, not of the pump, so it would not have
	// travelled to the Input side even if the verdict had stayed.
	let {
		latest = null,
		predictions = [],
		showAlarm = true,
		class: className,
		...restProps
	} = $props();

	let meta = $derived(latest ? (CLASS_META[latest.state] ?? CLASS_META.unknown) : null);

	// The alarm is computed HERE from the agent's own stream, not read off the store's
	// `assertedFor`. That getter has two faults, both visible on screen:
	//
	//  1. It goes NEGATIVE. It subtracts a prediction's timestamp from
	//     `status.timestamp_ms`, but the replayer only publishes pump/status every 25
	//     rows (replayer.js:303) while results arrive every row — so the status clock
	//     trails the agent by up to 24 minutes of data time and the subtraction inverts.
	//     "-8 MIN" is that, not a weird edge case.
	//  2. It used to LATCH on the first breakdown window of the epoch, so one false alarm
	//     — and this classifier is quoted at 0.8–4.3% of clean windows — left ALARM
	//     counting for the rest of the run while the verdict read Normal. main fixed that
	//     (assertedSinceTs now clears on a normal window), but fault 1 is untouched, and
	//     it alone is enough to keep the clock local.
	//
	// What an alarm clock should say is how long the CURRENT alarm has been standing, so
	// that is what this measures: the unbroken run of breakdown verdicts ending at the
	// newest one. It reads zero the moment the agent calls normal again.
	// `alarmRun`, not `alarm`: the snippet below already owns that name in this scope.
	let alarmRun = $derived.by(() => {
		if (!latest || latest.state !== 'pump_breakdown') return null;
		let i = predictions.length - 1;
		// The newest prediction IS `latest`; walk back while the run holds.
		while (i > 0 && predictions[i - 1]?.state === 'pump_breakdown') i--;
		const start = predictions[i];
		if (!start) return null;
		return {
			samples: (latest.timestamp_ms - start.timestamp_ms) / CADENCE_MS,
			// The buffer is capped at 500 windows. If the run reaches the oldest one we
			// held, the true alarm is at least this long — say so rather than quietly
			// under-reporting it.
			atLeast: i === 0 && predictions.length >= 500
		};
	});
	let alarming = $derived(alarmRun !== null);
</script>

{#snippet pair(label, children)}
	<div class="flex min-w-0 items-center gap-2">
		<!-- The rig's own label spec — `font-mono text-[11px] tracking-wider uppercase`, muted,
		     `gap-2` to its badge. It was 10px sans with tighter tracking, which read as a
		     different system to the one across the workbench for no reason.
		     Still a step under the badge it introduces: at matching sizes the two read as one
		     flat run of type with nothing saying which is label and which is value. -->
		<span
			class="shrink-0 font-mono text-[11px] tracking-wider text-muted-foreground uppercase"
			>{label}</span
		>
		{@render children()}
	</div>
{/snippet}

<div class={cn('flex min-w-0 items-center gap-3', className)} {...restProps}>
	{#snippet verdict()}
		{#if meta}
			<Badge
				variant="status"
				class="max-w-full text-xs"
				style="color: {meta.color}; border-color: {meta.color}"
				title="The agent's call for the latest {WINDOW_SIZE}-sample window. There is no ground truth in this UI — a live control room has none either."
			>
				<span class="truncate text-xs">{meta.label}</span>
			</Badge>
		{:else}
			<!-- Not a state: the agent needs a full window before it can say anything, so
			     the warm-up gets muted ink rather than a colour that implies a call. -->
			<Badge
				variant="status"
				class="border-border text-xs text-muted-foreground"
				title="Waiting for the first full {WINDOW_SIZE}-sample window"
			>
				awaiting
			</Badge>
		{/if}
	{/snippet}
	{@render pair('Current', verdict)}

	{#snippet alarm()}
		<Badge
			variant="status"
			class="text-xs"
			style={alarming
				? `color: ${CLASS_META.pump_breakdown.color}; border-color: ${CLASS_META.pump_breakdown.color}`
				: undefined}
			title={alarming
				? 'How long the agent has been calling breakdown without a break'
				: 'The agent is not currently calling a breakdown'}
		>
			<!-- Data time, not wall time: at 500x the replay a 2h50m alarm has been on
			     screen for about twenty seconds, and the pump's clock is the one that
			     means anything. -->
			<span class="text-xs {alarming ? '' : 'text-muted-foreground'}">
				{alarming ? `${alarmRun.atLeast ? '≥' : ''}${samplesToDuration(alarmRun.samples)}` : '—'}
			</span>
		</Badge>
	{/snippet}
	{#if showAlarm}
		{@render pair('Alarm', alarm)}
	{/if}
</div>
