<script>
	import { Tabs as TabsPrimitive } from 'bits-ui';
	import { cn } from '$lib/utils.js';
	import { tabsTriggerVariants } from './types.js';

	let {
		ref = $bindable(null),
		variant = 'text',
		size = 'default',
		typography = 'default',
		class: className,
		...restProps
	} = $props();
</script>

<TabsPrimitive.Trigger
	bind:ref
	data-slot="tabs-trigger"
	data-variant={variant}
	data-size={size}
	data-typography={typography}
	class={cn(tabsTriggerVariants({ variant, size, typography }), className)}
	{...restProps}
/>
