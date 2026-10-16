<script>
	import { cn } from '$lib/utils.js';
	import * as Dialog from '$lib/components/v2/ui/primitives/dialog/index.js';
	import { Button } from '$lib/components/v2/ui/primitives/button/index.js';
	import { Slider } from '$lib/components/v2/ui/primitives/slider/index.js';
	import Badge from '$lib/components/v2/ui/primitives/badge/index.js';
	import WaypointsIcon from '@lucide/svelte/icons/waypoints';
	import ObservabilityPanel from './observability-panel.svelte';
	import CircleArrowRightIcon from '@lucide/svelte/icons/circle-arrow-right';
	import CircleGaugeIcon from '@lucide/svelte/icons/circle-gauge';
	import LayersIcon from '@lucide/svelte/icons/layers';
	import RotateCcwIcon from '@lucide/svelte/icons/rotate-ccw';
	import CrosshairIcon from '@lucide/svelte/icons/crosshair';
	import WifiIcon from '@lucide/svelte/icons/wifi';
	import WifiOffIcon from '@lucide/svelte/icons/wifi-off';

	// Everything the old full-width playback bar and incident row carried, plus the
	// counters that used to sit under the verdict banner, behind the gear beside Run
	// Agent — following the rig monitor, where the two live controls of the demo (start
	// it, configure it) read as one cluster.
	//
	// Run/pause deliberately stays OUT here: it is pressed constantly, these are set
	// occasionally.
	let { pump, open = $bindable(false) } = $props();

	// RED's own ladder, not the rig's 1–60×. The pump samples once a MINUTE, so even
	// 60× is one row a second; the demo needs hundreds to reach a fault in a meeting.
	const SPEEDS = [60, 120, 250, 500];

	let current = $derived(pump.status.row);
	let formattedTime = $derived.by(() => {
		if (!pump.status.timestamp_ms) return '';
		return new Date(pump.status.timestamp_ms).toLocaleString('en-US', {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit',
			hour12: false
		});
	});

	// While a drag is in flight the thumb follows the pointer rather than the replayer's
	// row count. A seek bumps the epoch, which is the signal the authoritative row has
	// caught up and the thumb can let go.
	let scrub = $state(null);
	let scrubValue = $derived(scrub ?? Math.max(0, current));
	let seekMax = $derived(Math.max(1, pump.status.totalRows - 1));
	// bits-ui materialises one entry per step, so a step of 1 over ~16 k rows rebuilds a
	// 16 k array on every replayer heartbeat. Half a pixel of track is all it can resolve.
	let seekStep = $derived(Math.max(1, Math.ceil(seekMax / 2000)));
	$effect(() => {
		pump.status.epoch;
		scrub = null;
	});

</script>

{#snippet caption(icon, text)}
	{@const Icon = icon}
	<span
		class="flex items-center gap-1.5 font-mono text-[11px] tracking-wider text-muted-foreground uppercase"
	>
		<Icon class="size-4" strokeWidth={1.25} aria-hidden="true" />
		{text}
	</span>
{/snippet}

{#snippet segmented(items, isActive, onpick, label)}
	<!-- The rig monitor's segmented treatment: a `bg-muted` track with the active chip
	     filled `primary`. Its long note on why the active item is filled rather than
	     lifted onto `background` applies verbatim here — same near-black page, same
	     1.4:1 problem, same WCAG 1.4.11 threshold for a state indicator's boundary. -->
	<div class="flex h-8 items-center rounded-lg bg-muted p-[3px]" role="group" aria-label={label}>
		{#each items as it (it.value)}
			<Button
				variant="ghost"
				size="sm"
				aria-pressed={isActive(it.value)}
				class={cn(
					'h-full flex-1 rounded-md px-2.5 font-mono text-[11px] uppercase',
					isActive(it.value)
						? 'bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground dark:hover:bg-primary'
						: 'text-muted-foreground'
				)}
				onclick={() => onpick(it.value)}
			>
				{it.label}
			</Button>
		{/each}
	</div>
{/snippet}

<Dialog.Root bind:open>
	<Dialog.Content class="max-h-[90vh] gap-4 overflow-y-auto bg-card p-4 sm:max-w-4xl">
		<Dialog.Header class="gap-1">
			<Dialog.Title class="font-mono text-sm font-normal tracking-wider uppercase">
				Settings
			</Dialog.Title>
			<Dialog.Description class="text-[11px]">
				Where in the recording the replayer is, how fast it runs, and what is moving over MQTT.
				Seeking clears the buffered rows and detections, and restarts the agent's window. Which
				incident is replayed is chosen in the Pump Input panel.
			</Dialog.Description>
		</Dialog.Header>

		<div class="flex flex-col gap-4">
			<div class="flex flex-col items-start gap-1.5">
				{@render caption(pump.connected ? WifiIcon : WifiOffIcon, 'Broker')}
				<Badge
					variant="status"
					class={cn(
						'text-xs',
						pump.connected
							? 'border-atai-good text-atai-good'
							: 'border-atai-critical text-atai-critical'
					)}
				>
					{pump.connected ? 'connected' : 'disconnected'}
				</Badge>
			</div>

			<!-- No incident control here any more. It is a Select in the Input panel's caption
			     row, which is where the reference keeps the equivalent (its well selector) and
			     where it belongs: choosing the recording is a statement about the INPUT, not a
			     setting on the run. What is left in this dialog all acts on the recording that
			     is already playing — position, speed, and the counters.
			     The restraint that governed the old segmented control still governs the Select:
			     no fault length beside an incident, ever. This UI shows only what a control
			     room would have, and printing "42 rows" next to #6 would announce the miss the
			     demo asks you to narrate. -->

			<div class="flex flex-col gap-1.5">
				<!-- The PUMP's clock rides the caption row opposite the label. It reads as a
				     date in 2018 because that is when the pump was logged; it belongs with
				     position, both answering "where in the recording are we". -->
				<div class="flex items-center justify-between gap-3">
					{@render caption(CircleArrowRightIcon, 'Position')}
					<span class="font-mono text-[11px] text-muted-foreground tabular-nums">
						{formattedTime || 'awaiting first row'}
					</span>
				</div>
				<div class="flex h-9 items-center gap-4 rounded-xs bg-muted px-4">
					<span class="font-mono text-xs whitespace-nowrap text-muted-foreground tabular-nums">
						{current.toLocaleString()} <span class="text-xs opacity-50">/</span>
						{pump.status.totalRows.toLocaleString()}
					</span>
					<Slider
						type="single"
						aria-label="Seek"
						class="min-w-24 flex-1"
						min={0}
						max={seekMax}
						step={seekStep}
						value={scrubValue}
						onValueChange={(v) => (scrub = v)}
						onValueCommit={(v) => {
							scrub = v;
							pump.seek(v);
						}}
					/>
				</div>
			</div>

			<div class="flex flex-col gap-1.5">
				{@render caption(CircleGaugeIcon, 'Speed')}
				{@render segmented(
					SPEEDS.map((s) => ({ value: s, label: `${s}×` })),
					(v) => pump.status.speed === v,
					(v) => pump.setSpeed(v),
					'Speed'
				)}
				<!-- The speed buttons are an upper bound, not a setting: the replayer stops
				     publishing when too many windows are outstanding, so a slow agent simply
				     makes the replay slower. Saying so here stops "500× but it's crawling"
				     reading as a bug. -->
				<p class="text-[11px] text-muted-foreground">
					An upper bound. The replayer paces itself against the agent, so a busy machine
					replays slower than the button says{pump.status.throttled ? ' — pacing right now' : ''}.
				</p>
			</div>

			<div class="flex flex-col gap-1.5 border-t border-separator pt-4">
				<!-- The three counters off the old verdict banner. They are a tally of the run,
				     not a live reading, so they belong where you go to inspect rather than in
				     the header you watch. -->
				{@render caption(LayersIcon, 'Windows this epoch')}
				<div class="grid grid-cols-3 gap-px overflow-hidden rounded-xs bg-separator">
					{#each [{ label: 'Read', value: pump.validCount + pump.invalidCount }, { label: 'Called breakdown', value: pump.flaggedCount }, { label: 'Unusable', value: pump.invalidCount }] as c (c.label)}
						<div class="flex flex-col gap-0.5 bg-card p-3">
							<span class="font-mono text-lg tabular-nums">{c.value.toLocaleString()}</span>
							<span class="text-[10px] tracking-wide text-muted-foreground uppercase">{c.label}</span>
						</div>
					{/each}
				</div>
			</div>

			<div class="flex flex-col gap-1.5 border-t border-separator pt-4">
				{@render caption(WaypointsIcon, 'Live data flow')}
				<!-- The diagram, not the per-topic table it replaced. The table said which
				     topics were ticking; it could not say what talks to what, which is the
				     thing worth showing a prospect — that the whole pipeline is on this
				     machine. Per-topic cumulative counts go with the table, but the epoch
				     counters directly above already carry the totals that matter. Matches
				     the rig monitor, which keeps its diagram under this same caption. -->
				<ObservabilityPanel {pump} />
			</div>
		</div>

		<Dialog.Footer>
			<!-- Two repositioning actions, both secondary: the settings above apply as you
			     touch them, so the dialog has nothing to submit and Close is simply how you
			     finish. Onset is RED's own — it jumps to the row the fault begins, which is
			     the one seek anybody performs by hand. -->
			<Button
				variant="outline"
				size="sm"
				disabled={pump.status.onsetRow === null}
				onclick={() => {
					pump.toOnset();
					open = false;
				}}
			>
				<CrosshairIcon />
				Jump to onset
			</Button>
			<Button
				variant="outline"
				size="sm"
				onclick={() => {
					pump.reset();
					open = false;
				}}
			>
				<RotateCcwIcon />
				Reset replay
			</Button>
			<Button variant="default" size="sm" onclick={() => (open = false)}>Close</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
