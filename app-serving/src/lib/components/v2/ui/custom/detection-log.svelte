<script>
	import { cn } from '$lib/utils.js';
	import { ScrollArea } from '$lib/components/v2/ui/primitives/scroll-area/index.js';
	import * as Table from '$lib/components/v2/ui/primitives/table/index.js';
	import Badge from '$lib/components/v2/ui/primitives/badge/index.js';
	import { CLASS_META, WINDOW_SIZE } from '$lib/red.js';

	// The body of the output panel's foot disclosure — ported from the rig monitor's
	// classification log, which sits in the same place. The verdict leads each row as a
	// badge, the metadata that identifies the window follows, and the one figure worth
	// comparing down the column is right-aligned at the end.
	//
	// Two things the badge column buys: a run of one verdict reads as a block of
	// identical chips so a flip breaks the pattern, and no colour lands in the body copy.
	//
	// Gone from RED's old log: the "only flagged windows" checkbox. It was a filter that
	// hid the majority of the evidence to make the rare thing easier to find — which is
	// the one edit that can turn this panel into a highlight reel. The chip bar up in the
	// state block already answers "where were the flags" at a glance, and it does it
	// without removing anything.
	let { predictions = [], class: className, ...restProps } = $props();

	// newest first, the way a log tails
	let rows = $derived([...predictions].reverse().slice(0, 200));

	function isInvalid(p) {
		return p.invalid || p.state === 'INVALID_STATE';
	}

	// Confidence in the verdict actually returned. An invalid window has no verdict to be
	// confident about, so it gets no figure rather than a zero that would scan as a real
	// measurement.
	function confidence(p) {
		if (isInvalid(p)) return null;
		const c = p.probs?.[p.state];
		return Number.isFinite(c) ? `${(c * 100).toFixed(0)}%` : null;
	}
</script>

{#snippet verdictBadge(state)}
	{@const meta = CLASS_META[state] ?? CLASS_META.unknown}
	<Badge
		variant="status"
		class="text-xs"
		style="color: {meta.color}; border-color: {meta.color}"
		title={state === 'INVALID_STATE'
			? 'Window failed validation (sampling rate or NaN) and was not classified'
			: `The agent's call for this ${WINDOW_SIZE}-sample window`}
	>
		<span class="truncate text-xs">{meta.label}</span>
	</Badge>
{/snippet}

<section class={cn('flex min-h-0 flex-col', className)} {...restProps}>
	<!-- No heading of its own: the disclosure that reveals this is the heading. And no top
	     padding for the same reason — the disclosure's own bottom padding is the gap between
	     that heading and these rows. `pt-4` here stacked a second 16px on top of it and left
	     the table floating away from the label it belongs to. -->
	<div class="flex min-h-0 flex-1 flex-col px-4 pt-0 pb-4">
		<ScrollArea class="min-h-0 flex-1">
			{#if predictions.length === 0}
				<!-- Not "press play" — the chip bar in the state block says that, and it is on
				     screen at the same time as this. Two panels asking for the same click read
				     as a rendering fault. This one states what the table has instead. -->
				<p class="py-8 text-center text-sm text-muted-foreground">No classified windows yet</p>
			{:else}
				<!-- table-fixed with a quarter to each column, so slack spreads across all
				     four instead of pooling in whichever one was left elastic. -->
				<Table.Root class="table-fixed text-xs">
					<Table.Header>
						<!-- sticky so the columns stay named while the log tails past them -->
						<Table.Row class="sticky top-0 z-10 border-separator bg-background hover:bg-transparent">
							<Table.Head
								class="h-8 w-1/4 px-3 text-[11px] font-normal tracking-wide text-muted-foreground uppercase"
								>Verdict</Table.Head
							>
							<Table.Head
								class="h-8 w-1/4 px-3 text-[11px] font-normal tracking-wide text-muted-foreground uppercase"
								>Timestamp</Table.Head
							>
							<Table.Head
								class="h-8 w-1/4 px-3 text-[11px] font-normal tracking-wide text-muted-foreground uppercase"
								>Window</Table.Head
							>
							<Table.Head
								class="h-8 w-1/4 px-3 text-right text-[11px] font-normal tracking-wide text-muted-foreground uppercase"
								>Confidence</Table.Head
							>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each rows as p (p.id)}
							<Table.Row class="border-separator">
								<Table.Cell class="px-3 py-2 align-middle">
									{@render verdictBadge(p.state)}
								</Table.Cell>
								<Table.Cell class="px-3 py-2 align-middle tabular-nums">
									{new Date(p.timestamp_ms).toLocaleTimeString('en-US', { hour12: false })}
								</Table.Cell>
								<Table.Cell class="px-3 py-2 align-middle text-muted-foreground tabular-nums"
									>#{p.id}</Table.Cell
								>
								<Table.Cell class="px-3 py-2 text-right align-middle tabular-nums">
									{confidence(p) ?? '—'}
								</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			{/if}
		</ScrollArea>
	</div>
</section>
