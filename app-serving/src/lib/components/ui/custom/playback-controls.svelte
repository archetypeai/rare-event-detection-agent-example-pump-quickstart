<script>
	import { cn } from '$lib/utils.js';
	import { Button } from '@archetypeai/ds-ui-svelte-console/primitives/button';
	import PlayIcon from '@lucide/svelte/icons/play';
	import PauseIcon from '@lucide/svelte/icons/pause';

	// One call to action instead of a transport bar, after the rig monitor. The old RED
	// bar carried play/pause, reset, jump-to-onset, a scrubber, four speed buttons, a row
	// counter and a clock across the full width of the page; all of it except this button
	// has moved into the settings dialog, which is where you look for the things that
	// reposition a replay.
	//
	// It TOGGLES rather than only starting, because a run you cannot stop is not a
	// control. Play and pause share a glyph pair so the two states read as one button.
	//
	// Naming note: the button says "Agent" while it actually drives the REPLAYER — the
	// agent is a separate process that classifies whatever arrives. Kept anyway, because
	// it is the ecosystem's word for "start the demo" and because from the outside they
	// are one thing: no rows, no windows, no verdicts.
	let { pump, class: className, ...restProps } = $props();

	// The platform's Run Agent chip (its `.run-agent-surface` in layout.css), on the DS
	// Button: the DS ships no variant for it, so the ghost variant carries the classes.
	const runAgent =
		'run-agent-surface shadow-bottom-toolbar h-11 gap-2.5 rounded-full border border-transparent pr-5 pl-4 text-base text-atai-always-black transition-colors hover:text-atai-always-black has-[>svg]:pr-5 has-[>svg]:pl-4';
</script>

<div class={cn('flex items-center', className)} {...restProps}>
	{#if pump.status.playing}
		<Button variant="ghost" class={runAgent} onclick={() => pump.pause()}>
			<PauseIcon class="size-4.5" />
			Pause Agent
		</Button>
	{:else}
		<Button variant="ghost" class={runAgent} onclick={() => pump.play()}>
			<PlayIcon class="size-4.5" />
			Run Agent
		</Button>
	{/if}
</div>
