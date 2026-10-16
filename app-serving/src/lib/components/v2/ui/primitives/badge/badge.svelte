<script module>
	import { tv } from 'tailwind-variants';

	export const badgeVariants = tv({
		base: 'cursor-default focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:ring-[3px] [&>svg]:pointer-events-none [&>svg]:size-3',
		variants: {
			variant: {
				default: 'bg-primary text-primary-foreground [a&]:hover:bg-primary/90 border-transparent',
				secondary:
					'bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90 border-transparent',
				destructive:
					'bg-destructive [a&]:hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/70 border-transparent text-white',
				outline: 'text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground',
				timestamp:
					'bg-foreground rounded-xs text-background [a&]:hover:bg-primary/90 border-transparent',
				// The console DS status badge, vendored verbatim from
				// @archetypeai/ds-ui-svelte-console `primitives/badge/types.ts`. Form only:
				// no fill and no colour of its own, because the CALLER supplies both the
				// text and border colour — upstream's own usage is
				// `<Badge variant="status" class="text-atai-good border-atai-good">`.
				// The negative margins are upstream's icon-group compensation and are kept
				// so this stays a faithful copy; with no icon inside they are inert.
				status:
					'-mr-1 h-auto gap-2 rounded-md border px-1.5 py-0.5 font-mono text-sm font-normal uppercase [&>svg]:-mx-1'
			}
		},
		defaultVariants: {
			variant: 'default'
		}
	});
</script>

<script>
	import { cn } from '$lib/utils.js';

	let {
		ref = $bindable(null),
		href,
		class: className,
		variant = 'default',
		children,
		...restProps
	} = $props();
</script>

<svelte:element
	this={href ? 'a' : 'span'}
	bind:this={ref}
	data-slot="badge"
	{href}
	class={cn(badgeVariants({ variant }), className)}
	{...restProps}
>
	{@render children?.()}
</svelte:element>
