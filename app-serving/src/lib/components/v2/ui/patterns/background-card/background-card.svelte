<script>
	import { cn } from '$lib/utils.js';
	import {
		Card,
		CardHeader,
		CardTitle,
		CardAction,
		CardContent
	} from '$lib/components/v2/ui/primitives/card/index.js';

	/**
	 * Detail-panel card, composed the way the DS card usage contract prescribes:
	 * variant="info" + CardHeader (CardTitle + CardAction icon) + CardContent
	 * layout="stack". The variant owns the typography (sans, text-lg, capitalize)
	 * and the action icon (size-4, stroke-icon-default, muted) — don't restate
	 * either here, or the card stops matching every other DS surface.
	 *
	 * @typedef {Object} Props
	 * @property {string} [title=""] - card header label
	 * @property {import('svelte').Component} [icon] - lucide icon, rendered top-right
	 * @property {string} [class] - additional CSS classes
	 * @property {import('svelte').Snippet} [actions] - extra header controls, left of the icon
	 */

	/** @type {Props} */
	let {
		title = '',
		icon: Icon = undefined,
		class: className,
		actions,
		children,
		...restProps
	} = $props();
</script>

<Card variant="info" class={cn('gap-3', className)} {...restProps}>
	<CardHeader>
		<!-- lighter than the DS card's font-normal: at text-lg the sans face reads
		     heavier than the mono titles it replaced. The `!` is needed because the
		     variant sets the weight through a descendant selector, which outranks a
		     plain class on the element itself. -->
		<CardTitle class="font-light!">{title}</CardTitle>
		{#if Icon || actions}
			<CardAction class="flex items-center gap-2">
				{@render actions?.()}
				{#if Icon}
					<Icon aria-hidden="true" />
				{/if}
			</CardAction>
		{/if}
	</CardHeader>

	<CardContent layout="stack" class="min-h-0 flex-1">
		{@render children?.()}
	</CardContent>
</Card>
