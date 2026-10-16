<script>
	import { cn } from '$lib/utils.js';

	/**
	 * Workbench pane: a captioned region of the page background, separated from its
	 * neighbours by a hairline rather than wrapped in a card. Panes carry no border,
	 * radius or surface of their own — the grid that lays them out owns the rules,
	 * so several panes read as one continuous workbench instead of floating cards.
	 *
	 * Two variants, because the layout nests one level:
	 *
	 * - `panel` — a top-level region (Input / Output). Caption is icon + foreground
	 *   text, and the content is FLUSH: no horizontal padding, so the hairlines
	 *   between the blocks inside reach the panel's own edges. The caption row has no
	 *   bottom padding — the block beneath supplies its own, and stacking the two put
	 *   28px between a panel's name and its content.
	 * - `block` — a section within a panel. Caption is muted and a step smaller with
	 *   no icon, which is what keeps the hierarchy readable when five captions are
	 *   on screen at once. Content is inset and gapped.
	 *
	 * @typedef {Object} Props
	 * @property {string} [title=""] - caption text, rendered uppercase. Omit it (with no
	 *   icon or actions either) and the caption row is not rendered at all.
	 * @property {'panel'|'block'} [variant="block"] - nesting level, see above
	 * @property {import('svelte').Component} [icon] - lucide icon, left of the caption
	 * @property {string} [class] - additional CSS classes
	 * @property {string} [captionClass] - classes for the caption text itself. The caption
	 *   is mono, uppercase and small by default, which is the workbench's voice for a
	 *   region label. Pass through here to override any of that per pane — the blocks that
	 *   read as headings rather than labels (Operational State, Classification Log) use
	 *   `font-sans normal-case text-sm` so they carry the weight of a title.
	 * @property {import('svelte').Snippet} [actions] - controls pinned to the caption row's right edge
	 * @property {string} [subtitle] - second line under the caption, for the standing facts
	 *   about what a panel is showing (which well, which model). Panel variant only: a block's
	 *   caption is a small label with no room beneath it before its content starts.
	 * @property {import('svelte').Snippet} [subtitleActions] - pinned to the SUBTITLE row's
	 *   right edge. For live readouts that would jostle the caption row's controls as they
	 *   change width. Renders the row even with no `subtitle` text.
	 */

	/** @type {Props} */
	let {
		title = '',
		subtitle = '',
		subtitleActions,
		variant = 'block',
		icon: Icon = undefined,
		class: className,
		captionClass,
		actions,
		children,
		...restProps
	} = $props();

	let isPanel = $derived(variant === 'panel');
</script>

<section class={cn('flex min-h-0 flex-col', isPanel ? '' : 'gap-2 p-4', className)} {...restProps}>
	<!-- No caption row at all when there is nothing to put in it: an empty title
	     would still reserve its min-height and the gap below it, which is dead space
	     for a block whose content is already named elsewhere (a view toggle, say). -->
	{#if title || Icon || actions}
		<!-- A panel's caption row is a fixed 34px of content — the height of the DS
		     toggle, the tallest thing that goes in `actions`. Fixed rather than
		     content-sized so two panels side by side start their content on the same
		     line whatever each one puts in the row (a view toggle in one, transport
		     buttons in the other, nothing at all in a third).
		     The floor lives on the CAPTION below, not on this header: the header is
		     border-box with `pt-4`, so a `min-h-[34px]` here leaves an 18px content box
		     and a 34px toggle overrides it to 50 — which aligned two panels only for as
		     long as both happened to carry a toggle. On the caption it is 34px either way. -->
		<header
			class={cn('flex items-center justify-between gap-2', isPanel ? 'px-4 pt-4 pb-0' : 'min-h-6')}
		>
			<span
				class={cn(
					'flex items-center gap-1.5 font-mono uppercase',
					isPanel
						? 'min-h-[34px] text-[11px] tracking-wider text-foreground'
						: 'text-[10px] tracking-wide text-muted-foreground',
					captionClass
				)}
			>
				{#if Icon}
					<Icon class="size-4" strokeWidth={1.25} aria-hidden="true" />
				{/if}
				{title}
			</span>
			{#if actions}
				<div class="flex items-center gap-2">
					{@render actions()}
				</div>
			{/if}
		</header>
	{/if}

	<!-- Subtitle on its own line under the caption, not appended to it: the caption row is a
	     fixed-height flex with the actions pinned right, so anything added inline competes
	     with the controls for width and truncates first on a narrow panel. A separate line
	     also lets the title stay the loud thing and the standing facts stay quiet.
	     `pt-1` rather than a gap on the header, because the header's `pb-0` is load-bearing
	     for the no-subtitle case — see the note on the caption row above. -->
	{#if isPanel && (subtitle || subtitleActions)}
		<!-- The subtitle line takes its own right-hand slot, mirroring the caption row's.
		     Anything live enough to change while you watch belongs here rather than up in the
		     caption: that row is a fixed 34px holding the title and the view switcher, and a
		     value that changes width as it changes — a state name, a count — makes the
		     switcher shift under the pointer. -->
		<div class="flex shrink-0 items-center justify-between gap-3 px-4 pt-1">
			<p class="min-w-0 truncate text-xs text-muted-foreground">{subtitle}</p>
			{#if subtitleActions}
				<div class="flex shrink-0 items-center gap-2">
					{@render subtitleActions()}
				</div>
			{/if}
		</div>
	{/if}

	<!-- blocks get gap-4, matching the DS card's `layout="stack"` content spacing
	     they used to inherit from CardContent; panels stay flush so the hairlines
	     between their blocks span the whole panel -->
	<div class={cn('flex min-h-0 flex-1 flex-col', !isPanel && 'gap-4')}>
		{@render children?.()}
	</div>
</section>
