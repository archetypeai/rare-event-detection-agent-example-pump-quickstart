<script>
	import { cn } from '$lib/utils.js';
	import Pane from '$lib/components/ui/patterns/pane/index.js';
	import * as Tabs from '@archetypeai/ds-ui-svelte-console/primitives/tabs';
	import VerdictBadges from './verdict-badges.svelte';
	import DetectionTimeline from './detection-timeline.svelte';
	import DetectionLog from './detection-log.svelte';
	import EmbeddingSpace from './embedding-space.svelte';
	import PumpDiagram from './pump-diagram.svelte';
	import PlaybackControls from './playback-controls.svelte';
	import { Button } from '@archetypeai/ds-ui-svelte-console/primitives/button';
	import CircleArrowDownIcon from '@lucide/svelte/icons/circle-arrow-down';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import ScatterChartIcon from '@lucide/svelte/icons/chart-scatter';
	// `fan`, not `cog` or `factory`: the blades radiating from a hub are the impeller
	// silhouette, which is the shape of the drawing this view opens. Same reasoning the rig
	// panel used to land on `pyramid` for a derrick — pick the icon that is a picture of the
	// asset, not a generic machine. It followed the plate over from the Input panel.
	import FanIcon from '@lucide/svelte/icons/fan';
	import Settings2Icon from '@lucide/svelte/icons/settings-2';

	// OUTPUT: everything derived from `red/results`, and only that. The pump plate stays on
	// the Input panel, where its data comes from.
	//
	// Composed after the rig monitor's agent panel: three stacked regions separated by
	// hairlines.
	//
	//   Detection State  the verdict and its alarm clock, over the per-window chip bar
	//   the body          switched — the embedding map or the pump plate
	//   Detection Log    a disclosure at the panel's foot, collapsed by default
	//
	// The caption-row toggle switches the BODY, which is what the reference's does: the two
	// views there are the rig drawing and the embedding map, and they sit under one panel
	// because both are readings of the same machine at the same instant — the plate is what
	// the verdict is about, the map is where the model put it. The plate moved here from the
	// Input panel to make that pairing possible, so the left panel is now one continuous
	// sensor list, exactly as the reference's is.
	//
	// The log is not one of the switched views: it is on screen at the same time as whichever
	// one is showing, so a switch position for it would be a control that cannot change
	// anything. It gets the disclosure at the foot instead.
	//
	// Why the state block leads rather than riding the subtitle row: the verdict is the
	// demo's whole argument, and compressed onto the subtitle it had to survive on two
	// 10px labels beside the window geometry. Given a block of its own it gets a heading,
	// the labels get room, and the chip bar sits directly under the badge it explains — a
	// flip shows up in both at the same moment, in the same hue.
	let { pump, settingsOpen = $bindable(false), class: className, ...restProps } = $props();

	// Collapsed on load. The log is 200 rows of tail; opening it costs the body the height,
	// so that is the operator's call to make, not ours.
	let logOpen = $state(false);

	// The plate on load, as the reference opens on its drawing. It is the view that needs no
	// explaining — a cold open on the machine says what is being watched before anyone has to
	// read an axis — and the map is what you switch to once the question becomes what the
	// model made of it. Flip to 'embedding' to open on the map instead.
	let view = $state('pump');
</script>

{#snippet viewToggle()}
	<!-- The same segmented icon switch the reference puts in this row, and the same one the
	     Input panel used to carry for these two views. -->
	<!-- Plate first, map second — the default view takes the leading position, as the
	     reference's selected view takes its. A switch whose lit segment is the right-hand one
	     on load reads as though something has already been changed. -->
	<Tabs.List variant="segmented">
		<Tabs.Trigger value="pump" variant="icon" title="Pump" aria-label="Pump">
			<FanIcon />
		</Tabs.Trigger>
		<Tabs.Trigger
			value="embedding"
			variant="icon"
			title="Embedding space"
			aria-label="Embedding space"
		>
			<ScatterChartIcon />
		</Tabs.Trigger>
	</Tabs.List>
{/snippet}

<!-- Named for the AGENT, mirroring the left panel being named for the pump: one side is
     the thing being watched, the other the thing watching it.
     The subtitle states the window geometry and the class count, both true whether the
     real agent or the mock is publishing — and deliberately claims no model, because a
     panel header is the last place to assert inference that may not be happening. -->
<!-- Switching views closes the log. Without it the toggle is a control with no visible
     effect whenever the log is open — the region it switches is collapsed, so both positions
     look identical. The reference has the same exclusivity: open its log, switch to its
     scatter view, and the log goes to zero height. -->
<Tabs.Root
	bind:value={view}
	onValueChange={() => (logOpen = false)}
	class={cn('flex min-h-0 flex-col', className)}
	{...restProps}
>
<Pane
	variant="panel"
	title="RED Agent"
	subtitle="Two states · 64-sample windows · step 1"
	icon={CircleArrowDownIcon}
	class="relative min-h-0 flex-1"
>
	{#snippet actions()}
		{@render viewToggle()}
	{/snippet}

	<!-- BODY FIRST, then the state block, then the log — the reference's own order, and the
	     order matters twice over. The picture is the subject and the verdict is a statement
	     about it, so the statement goes under the thing it is about; and it puts the verdict
	     badge directly above the log disclosure that details it, with the chip bar between
	     them as the bridge.
	     No `border-t` here: the reference runs no rule between its subtitle and its first
	     region either. The rules start below this one. -->
	<!-- Panels in the same order as their triggers. Only the active one is in the layout, so
	     this changes nothing on screen — it keeps source order from contradicting tab order
	     for anyone reading either. -->
	<!-- Both views get the whole region. It was capped to 324px for the plate view — the exact
	     height that drawing wants at the reference's scale — to keep it from floating in dead
	     air, and the cap is gone because the plate now handles that itself: it centres in this
	     region with its key pinned to the region's bottom edge, so the leftover height reads as
	     the drawing sitting in the middle of the panel rather than as a gap under it. The
	     leftover also stops pooling between the regions, which is what made the state block
	     look half empty. -->
	<!-- COLLAPSED while the log is open, which is what the reference does — measured on it:
	     opening its Classification Log takes the drawing's region out of the DOM entirely and
	     hands the height to the log, leaving the state block untouched. It shared before, and
	     sharing was the wrong call: a 260px slice of plate is a drawing you cannot read next
	     to a table you opened because you wanted to read it.
	     `hidden` rather than an `{#if}` around the region: that keeps both tab panels mounted,
	     so the triggers' `aria-controls` still resolve to something. Costs nothing — bits-ui
	     keeps the inactive panel mounted either way. -->
	<div class={cn('flex min-h-0 flex-1 flex-col', logOpen && 'hidden')}>
		<Tabs.Content value="pump" class="flex min-h-0 flex-1 flex-col">
			<!-- `rows`, not the verdict: the plate is two-tone and reads the SENSORS — its
			     callout values and whether the impeller is turning both come from the stream,
			     not from the classifier. Sitting beside the map does not change that. -->
			<PumpDiagram rows={pump.rows} latest={pump.latest} class="min-h-0 flex-1 p-4" />
		</Tabs.Content>

		<Tabs.Content value="embedding" class="flex min-h-0 flex-1 flex-col">
			<EmbeddingSpace {pump} class="min-h-0 flex-1 p-4" />
		</Tabs.Content>
	</div>

	<!-- ONE section for the verdict and its log, not two. Separate, they left the panel's spare
	     height as a band between the state block's last row and the log's rule — bounded above
	     by content and below by a rule, so it read as a half-empty panel rather than as spare
	     room. Folded together, the section carries verdict → chip bar → log, and the log is
	     where it belongs anyway: the rows are the detail behind the badge two lines above them.
	     `shrink-0` normally, `flex-1` when the log is open so the table has somewhere to grow.
	     No `mt-auto`: the body region above is `flex-1` and takes every spare pixel in both
	     states — visible, or collapsed with this section grown to `flex-1` — so there is never
	     free space in the column for a margin to claim. It was load-bearing only while the plate
	     view was capped to 324px and something had to hold this section against the foot.
	     `mt-3` when the body above is collapsed, because then THIS is the first region under
	     the subtitle and its rule would otherwise land 0px below the type — an underline on
	     the subtitle, clipping its descenders. With the body showing, the body's own `p-4`
	     already provides that air and a margin here would double it. -->
	<Pane
		title="Detection State"
		captionClass="font-sans text-sm normal-case tracking-normal text-foreground"
		class={cn('border-t border-separator', logOpen ? 'mt-3 min-h-0 flex-1' : 'shrink-0')}
	>
		<!-- The reference's own grid: one column until `sm`, two above it, with `gap-x-6
		     gap-y-2` so the pair that wraps to a second line gets a tighter gap than the one
		     that sits beside it. Halves rather than `justify-between`, which on a ~1000px
		     panel drops the alarm badge in the far corner reading as a stray control instead
		     of the second half of a pair.
		     `grid` beats the component's own `flex` through tailwind-merge — same display
		     group, later class wins. -->
		<VerdictBadges
			latest={pump.latest}
			predictions={pump.predictions}
			class="grid min-w-0 grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2"
		/>
		<!-- Directly under the badges: the bar is the shape of the run, the badge is where it
		     stands now, and the rows in the disclosure below are the detail. -->
		<DetectionTimeline predictions={pump.predictions} />

		<!-- The log, now the section's last element rather than a section of its own.
		     `-mx-4 -mb-4` cancels the section's padding on three sides so the disclosure's rule
		     still spans the panel edge to edge and the row still ends flush with the panel's
		     foot — full-bleed like the reference's, without needing its own section to be. -->
		<div
			class={cn(
				'-mx-4 -mb-4 flex flex-col border-t border-separator',
				logOpen ? 'min-h-0 flex-1' : 'shrink-0'
			)}
		>
			<!-- `aria-controls` only while open: the log is not in the DOM when collapsed, and a
			     dangling IDREF is a broken relationship rather than a harmless one. -->
			<!-- `pt-5` always, `pb-5` only while closed. The reference's `py-5` makes the row 60px,
			     which is exactly what the floating transport occupies (44px pill + its 16px
			     offset), so the pill sits WITHIN this row instead of standing proud of it into the
			     body above — but that only matters while the row IS the panel's foot. Open, the
			     pill has moved down over the table and the 20px underneath the label is just space
			     between a heading and the rows it heads. The top padding is unchanged either way,
			     so the label does not shift when you toggle; only the table moves up. -->
			<button
				type="button"
				class={cn(
					'flex shrink-0 cursor-pointer items-center gap-2 px-4 pt-5 text-left transition-colors hover:text-muted-foreground',
					logOpen ? 'pb-2' : 'pb-5'
				)}
				aria-expanded={logOpen}
				aria-controls={logOpen ? 'detection-log' : undefined}
				onclick={() => (logOpen = !logOpen)}
			>
				<!-- One icon rotated rather than two glyphs swapped, so the chevron animates
				     between the two states instead of cutting. -->
				<ChevronDownIcon
					class={cn(
						'size-4 shrink-0 text-muted-foreground transition-transform duration-200',
						!logOpen && '-rotate-90'
					)}
					strokeWidth={1.25}
					aria-hidden="true"
				/>
				<span class="text-sm">Detection Log</span>
			</button>
			{#if logOpen}
				<DetectionLog id="detection-log" predictions={pump.predictions} class="min-h-0 flex-1" />
			{/if}
		</div>
	</Pane>

	<!-- The transport as a floating CTA on the PANEL's lower-right corner — over the log row,
	     which is where the reference floats its own. It was anchored inside the body region,
	     which was fine while the body was only ever the map (whose one overlappable element
	     is a footnote the reference overlaps too) and wrong the moment the plate moved in:
	     with the log open the body shortens, and the pill came down over the plate's key —
	     live values, hidden behind a button.
	     Outside the switched region it also survives a view change untouched rather than
	     being torn down and rebuilt with the content.
	     `pointer-events-none` on the wrapper with it re-enabled on the controls: the wrapper
	     spans the corner, and without that it would swallow hover from whatever it sits over
	     — in the map's case the contours, which are the trigger for the sensor-trace
	     highlight on the other side of the workbench. -->
	<div class="pointer-events-none absolute right-4 bottom-4 z-10 flex items-center gap-2">
		<div class="pointer-events-auto">
			<PlaybackControls {pump} />
		</div>
		<Button
			variant="ghost"
			class="bottom-toolbar-surface shadow-bottom-toolbar pointer-events-auto size-11 rounded-full border border-transparent p-0 text-atai-always-black transition-colors hover:text-atai-always-black has-[>svg]:px-0"
			aria-label="Settings"
			onclick={() => (settingsOpen = !settingsOpen)}
		>
			<Settings2Icon />
		</Button>
	</div>
</Pane>
</Tabs.Root>
