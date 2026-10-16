<script>
	import { Dialog as DialogPrimitive } from 'bits-ui';
	import { cn } from '$lib/utils.js';

	let { ref = $bindable(null), class: className, ...restProps } = $props();
</script>

<DialogPrimitive.Overlay
	bind:ref
	data-slot="dialog-overlay"
	class={cn(
		// The console DS overlay, vendored from @archetypeai/ds-ui-svelte-console
		// `primitives/dialog/types.ts`: a light `bg-background/30` scrim with
		// `backdrop-blur-xs` behind it, rather than the plain `bg-black/50` this copy had.
		// The blur is what does the work — it pushes the page back without dimming it to
		// mud, which matters here because the thing behind the dialog is a live drawing
		// that should still read as running.
		'fixed inset-0 z-50 bg-background/30 backdrop-blur-xs data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0',
		className
	)}
	{...restProps}
/>
