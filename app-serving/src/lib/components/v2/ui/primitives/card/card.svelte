<script>
	import { cn } from '$lib/utils.js';
	import { cardVariants } from './types.js';

	let {
		ref = $bindable(null),
		class: className,
		children,
		variant,
		href = undefined,
		...restProps
	} = $props();
</script>

{#if href}
	<a
		bind:this={ref}
		data-slot="card"
		data-variant={variant}
		{href}
		class={cn(cardVariants({ variant }), className)}
		{...restProps}
	>
		{@render children?.()}
	</a>
{:else}
	<div
		bind:this={ref}
		data-slot="card"
		data-variant={variant}
		class={cn(cardVariants({ variant }), className)}
		{...restProps}
	>
		{@render children?.()}
	</div>
{/if}
