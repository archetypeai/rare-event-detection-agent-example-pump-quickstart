<script>
	import { cn } from '$lib/utils.js';
	import { Button } from '$lib/components/v2/ui/primitives/button/index.js';
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
</script>

<div class={cn('flex items-center', className)} {...restProps}>
	{#if pump.status.playing}
		<Button variant="runAgent" onclick={() => pump.pause()}>
			<PauseIcon class="size-4.5" />
			Pause Agent
		</Button>
	{:else}
		<Button variant="runAgent" onclick={() => pump.play()}>
			<PlayIcon class="size-4.5" />
			Run Agent
		</Button>
	{/if}
</div>
