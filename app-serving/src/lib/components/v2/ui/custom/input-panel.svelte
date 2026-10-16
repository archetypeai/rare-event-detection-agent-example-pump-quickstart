<script>
	import { cn } from '$lib/utils.js';
	import Pane from '$lib/components/v2/ui/patterns/pane/index.js';
	import * as Select from '$lib/components/v2/ui/primitives/select/index.js';
	import SensorColumn from './sensor-column.svelte';
	import CircleArrowUpIcon from '@lucide/svelte/icons/circle-arrow-up';

	// INPUT: what the agent is being fed — the ten channels as traces, and the control that
	// chooses WHICH recording feeds them.
	//
	// The pump plate used to be a second view here behind a toggle. It has moved to the
	// Output panel, where the reference keeps its rig: the plate is what the agent's verdict
	// is ABOUT, and switching it against the embedding map puts the machine and the model's
	// read of the machine in the same frame.
	//
	// The plate still reads the SENSORS rather than the verdict once it is over there; only
	// its home changed, not what drives it.

	let { pump, class: className, ...restProps } = $props();

	// --- the input selector ------------------------------------------------------
	// The rig monitor puts a Select in this caption row naming the WELL — one entry per
	// recording its replayer can feed the agent (14 of them: F-1, F-4, F-5, F-7, F-9, F-10,
	// F-12, F-14, F-15 and variants). The row is the demo's "what is going in", and the well
	// is the identity of that input.
	//
	// The RED equivalent is the INCIDENT. There is one asset here, not fourteen — a single
	// water pump logged over 2018 — so the thing that varies is which of the dataset's
	// labelled breakdowns the replayer is streaming. The replayer publishes the list on
	// `pump/status.slices` (inc03…inc07, five held-out incidents), which is the same list the
	// Settings dialog used to render as segmented buttons; it lives here now, and Settings
	// keeps only the controls that act on the current recording — position, speed, the flow
	// counters. The reference made exactly that move: its Settings has Broker, Position,
	// Speed and Live data flow, and no well selector.
	//
	// LABEL FORMAT: "Incident #4" and nothing else. No row count, no fault length, no hint of
	// which ones the classifier catches. That rule is the whole reason this UI is credible —
	// see the note in settings-dialog.svelte where the same restraint applied to the old
	// segmented control, and the app README on incident #6, which is never detected and must
	// look identical to a healthy pump until you narrate it.
	let slices = $derived(pump.status.slices ?? []);

	// `picked` is REAL state bound into the Select, not a `$derived` fed in one-way — and that
	// distinction is load-bearing. The wrapper in primitives/select does `bind:value` on the
	// bits-ui root, so the component writes back to whatever is passed. Hand it a derived
	// expression and every write is undone by the next render, which the root reads as a fresh
	// value and re-emits: mounting the control walked the replayer through inc05 → inc04 →
	// inc06 → inc07 → inc03 before settling, switching the demo's recording five times because
	// a dropdown had been rendered. A `$state` gives those writes somewhere to land.
	let picked = $state('');

	// The replayer stays the source of truth — it also changes slice on reset, and on its own
	// retained `pump/status` at connect — so follow it. Guarded on inequality, or this write
	// and the Select's would chase each other.
	$effect(() => {
		const id = pump.status.slice ?? '';
		if (id && id !== picked) picked = id;
	});

	// Ignore the echo: when the replayer confirms a switch, the Select emits the value it
	// already has, and re-publishing it would clear the buffers a second time.
	function pickSlice(id) {
		if (!id || id === pump.status.slice) return;
		pump.setSlice(id);
	}

	// The trigger shows the incident, not the slice id: `inc04` is a filename, `#4` is what the
	// dataset calls it and what the README and the offline scorer both refer to.
	let selectedLabel = $derived.by(() => {
		const s = slices.find((x) => x.id === picked);
		return s ? `Incident #${s.incident}` : '';
	});
</script>

{#snippet incidentSelect()}
	<!-- Trigger dressed as the caption row's own type — mono, 11px, wide tracking, uppercase,
	     transparent, 34px tall — which is the reference's trigger class for class, and the
	     same 34px the view toggle on the other panel is, so the two caption rows sit level. -->
	<Select.Root type="single" bind:value={picked} onValueChange={pickSlice}>
		<Select.Trigger
			class="w-fit gap-1.5 rounded-interactive border-border bg-transparent px-2.5 font-mono text-[11px] tracking-wider uppercase shadow-none hover:bg-accent/50 data-[size=default]:h-[34px] dark:bg-transparent dark:hover:bg-accent/50"
			aria-label="Incident"
			title="Switch incident — clears the buffered rows and detections, and restarts the agent's window"
		>
			{selectedLabel || 'Incident'}
		</Select.Trigger>
		<!-- Items carry NO class of their own, which is the point: the reference's options are
		     the bare `select-item` base — sans, `text-sm`, 32px rows — and only its TRIGGER is
		     dressed in the caption row's mono. An override here (mono, 11px, uppercase, wide
		     tracking, which this had) makes a menu that belongs to a different design system
		     than the one every other menu in both apps comes from. Verified against the live
		     reference: its option elements have exactly this base and nothing appended. -->
		<Select.Content>
			{#each slices as s (s.id)}
				<Select.Item value={s.id} label={`Incident #${s.incident}`}>
					Incident #{s.incident}
				</Select.Item>
			{/each}
		</Select.Content>
	</Select.Root>
{/snippet}

<Pane
	variant="panel"
	title="Pump Input"
	subtitle="10 of 52 channels · 1-min cadence"
	icon={CircleArrowUpIcon}
	class={cn('min-h-0', className)}
	{...restProps}
>
	<!-- Caption names the ROLE now — "Pump Input", after the reference's "Rig Input" — because
	     the asset's identity moved into the control beside it. The subtitle drops the incident
	     with it: repeating "Incident #4" a line under a control that says the same thing gave
	     the row two voices. What is left is the shape of the feed, which the selector does not
	     change. -->
	{#snippet actions()}
		{@render incidentSelect()}
	{/snippet}

	<!-- No title on the block: the panel caption already names the input, and a caption here
	     would be a heading over the only thing it could refer to. -->
	<Pane class="min-h-0 flex-1">
		<!-- `predictions` is only for the hover link: hovering a class in the embedding map
		     has to find every window of that class, which means reading the prediction
		     buffer here. -->
		<SensorColumn rows={pump.rows} predictions={pump.predictions} />
	</Pane>
</Pane>
