<script>
	import { cn } from '$lib/utils.js';
	import { cardContentVariants } from './types.js';

	let { ref = $bindable(null), class: className, layout, children, ...restProps } = $props();
</script>

<div
	bind:this={ref}
	data-slot="card-content"
	data-layout={layout}
	class={cn(cardContentVariants({ layout }), className)}
	{...restProps}
>
	{@render children?.()}
</div>
