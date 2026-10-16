<script module>
	import { cn } from '$lib/utils.js';
	import { tv } from 'tailwind-variants';

	export const buttonVariants = tv({
		base: "cursor-pointer focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive inline-flex shrink-0 items-center justify-center gap-2 rounded-xs text-sm font-regular whitespace-nowrap transition-all outline-none focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
		variants: {
			variant: {
				default: 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-xs',
				destructive:
					'bg-destructive hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60 text-white shadow-xs',
				outline:
					'bg-background hover:bg-accent hover:text-accent-foreground dark:bg-input/30 dark:border-input dark:hover:bg-input/50 border border-border shadow-xs',
				secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80 shadow-xs',
				ghost: 'hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50',
				link: 'text-primary underline-offset-4 hover:underline',
				// Ported verbatim from the console DS (`ds-ui-svelte-console`, button
				// `types.js`), which is where the workbench's top-nav logo comes from.
				// `size-auto` is the load-bearing part: the base sets every unsized svg to
				// `size-4`, which would square the wordmark. The `-mb-px` is the DS's own
				// optical nudge for sitting a wordmark on a nav baseline. Its BOX comes from
				// the compoundVariants entry below, not from here — see the note there.
				topNavLogo:
					"bg-transparent text-foreground [&_svg:not([class*='size-'])]:size-auto [&_svg]:-mb-px",
				// Read off the LIVE platform, not the vendored DS. The DS package ships a
				// `runSession` variant that is a flat `bg-atai-brand-babyblue` fill; the
				// playground actually renders `data-variant="runAgent"` with a transparent
				// background and a layered gradient surface (`.run-agent-surface` in
				// layout.css) under a 0.5px border and the toolbar shadow stack. Copying the
				// DS gave a flat pill that did not match, which is what prompted this pass.
				runAgent:
					'run-agent-surface shadow-bottom-toolbar rounded-full border border-transparent text-atai-always-black font-normal transition-colors',
				// Its sibling: same construction, neutral surface instead of babyblue.
				agentSettings:
					'bottom-toolbar-surface shadow-bottom-toolbar rounded-full border border-transparent text-atai-always-black font-normal transition-colors'
			},
			size: {
				default: 'h-9 px-4 py-2 has-[>svg]:px-3',
				sm: 'h-8 gap-1.5 rounded-xs px-3 has-[>svg]:px-2.5',
				lg: 'h-10 rounded-xs px-6 has-[>svg]:px-4',
				icon: 'size-9',
				'icon-sm': 'size-8',
				'icon-lg': 'size-10'
			}
		},
		// The DS keeps each variant's BOX here rather than in the variant, and the
		// placement is load-bearing: `tv()` emits compound classes AFTER the size classes,
		// so `h-auto px-0 py-1.5` beats the `size: default` preset's `h-9 px-4 py-2`.
		// Folded into the variant string instead, it loses to size and the logo renders in
		// a 36px-tall button with 16px of side padding.
		compoundVariants: [
			{ variant: 'topNavLogo', class: 'h-auto px-0 py-1.5 has-[>svg]:px-0' },
			// Geometry measured on the platform: 44px tall (h-11), 16px type, 10px gap, and
			// asymmetric padding — pl-4 / pr-5, because the play glyph on the left already
			// carries optical space that the text on the right does not.
			{
				variant: 'runAgent',
				class: 'h-11 gap-2.5 pr-5 pl-4 text-base has-[>svg]:pr-5 has-[>svg]:pl-4'
			},
			// Square at the same 44px, so the two sit as one cluster.
			{ variant: 'agentSettings', class: 'size-11 p-0 has-[>svg]:px-0' }
		],
		defaultVariants: {
			variant: 'default',
			size: 'default'
		}
	});
</script>

<script>
	let {
		class: className,
		variant = 'default',
		size = 'default',
		ref = $bindable(null),
		href = undefined,
		type = 'button',
		disabled,
		children,
		...restProps
	} = $props();
</script>

{#if href}
	<a
		bind:this={ref}
		data-slot="button"
		class={cn(buttonVariants({ variant, size }), className)}
		href={disabled ? undefined : href}
		aria-disabled={disabled}
		role={disabled ? 'button' : undefined}
		tabindex={disabled ? -1 : undefined}
		{...restProps}
	>
		{@render children?.()}
	</a>
{:else}
	<button
		bind:this={ref}
		data-slot="button"
		class={cn(buttonVariants({ variant, size }), className)}
		{type}
		{disabled}
		{...restProps}
	>
		{@render children?.()}
	</button>
{/if}
