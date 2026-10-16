// Reading the replayer's buffered raw rows. Shared because the sensor column and
// the rig diagram surface the same channel values — the column as a list, the rig
// as readouts pinned to the part that measures them — and they must never
// disagree about what "current" means.

// Most recent finite sample of a channel. Bounded to the last `depth` rows so a
// channel that stopped reporting reads as stale ('--') instead of showing a value
// from minutes ago; the replayer's rows are ~1 s apart at 1×.
export function latestValue(rows, key, depth = 50) {
	for (let i = rows.length - 1; i >= Math.max(0, rows.length - depth); i--) {
		const v = rows[i]?.channels?.[key];
		if (Number.isFinite(v)) return v;
	}
	return null;
}

// Engineering units, so the magnitude decides the precision: hole depth in the
// thousands doesn't need a decimal, block position in the tens does.
export function formatValue(v) {
	if (v === null) return '--';
	return Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(1);
}

// The rows a classified window covers, as a timestamp range. A prediction carries only
// the window's END (`finish_timestamp`), so the start is found by walking back
// `windowSize - 1` rows from there — by ROW, not by clock, because the replayer's
// spacing varies with the recording and subtracting a fixed duration would drift.
export function windowRange(rows, endTimestampMs, windowSize = 16) {
	let end = -1;
	for (let i = rows.length - 1; i >= 0; i--) {
		if (rows[i].timestamp_ms <= endTimestampMs) {
			end = i;
			break;
		}
	}
	if (end < 0) return null;
	const start = Math.max(0, end - (windowSize - 1));
	return [rows[start].timestamp_ms, rows[end].timestamp_ms];
}

// Collapse overlapping/adjacent ranges into runs. Essential for the state hover: the
// agent steps one row per window, so 16-sample windows share 15 of their samples and a
// stretch of one state emits a range per row. Unmerged, hovering a common state drew ~200
// near-identical rects per channel — 1,800 nodes across the column, painting a solid wash
// that said "this state, everywhere" rather than showing WHERE its runs were. Merged, the
// same hover resolves to a handful of bands that match the runs a reader can see.
export function mergeRanges(ranges) {
	if (ranges.length < 2) return ranges;
	const sorted = [...ranges].sort((a, b) => a[0] - b[0]);
	const out = [sorted[0].slice()];
	for (let i = 1; i < sorted.length; i++) {
		const prev = out[out.length - 1];
		const [s, e] = sorted[i];
		if (s <= prev[1]) prev[1] = Math.max(prev[1], e);
		else out.push([s, e]);
	}
	return out;
}

// Where those ranges land on a channel's sparkline, in the same x-space `sparklinePath`
// draws in. It has to repeat that function's filtering rather than index the raw slice:
// the path drops non-finite samples BEFORE laying points out, so on a channel with gaps
// the nth drawn point is not the nth row, and a band placed by row index would sit
// beside the feature it is supposed to mark instead of on it.
export function windowBands(rows, key, w, ranges, tail = 200) {
	if (!ranges?.length) return [];
	const kept = rows.slice(-tail).filter((r) => Number.isFinite(r.channels?.[key]));
	if (kept.length < 2) return [];
	const n = kept.length;
	const out = [];
	for (const [t0, t1] of ranges) {
		let i0 = -1;
		let i1 = -1;
		for (let i = 0; i < n; i++) {
			const t = kept[i].timestamp_ms;
			if (t >= t0 && t <= t1) {
				if (i0 < 0) i0 = i;
				i1 = i;
			}
		}
		if (i0 < 0) continue; // window has already scrolled off this channel's tail
		const x0 = (i0 / (n - 1)) * w;
		const x1 = (i1 / (n - 1)) * w;
		// a single-sample hit would be zero-wide and invisible
		out.push({ x: x0, w: Math.max(1.5, x1 - x0) });
	}
	return out;
}

// SVG path for a sparkline over the last `tail` rows, self-scaled to the window's
// own min/max — these are trend shapes, not comparable charts.
//
// PAD keeps the trace off the viewBox edges. Mapping min -> y=h and max -> y=0 put
// those points exactly on the boundary, and an <svg> clips to its viewport, so half
// the stroke width fell outside: a flat channel sitting at its minimum rendered as a
// row of disconnected dashes rather than a line. The strokes here are
// non-scaling, so the pad is in viewBox units against a stretched height — 2 of 24
// clears the 1.5px stroke at every row height this column gives a chart.
const PAD = 2;

export function sparklinePath(rows, key, w, h, tail = 200) {
	const vals = rows
		.slice(-tail)
		.map((r) => r.channels?.[key])
		.filter(Number.isFinite);
	if (vals.length < 2) return '';
	const min = Math.min(...vals);
	const max = Math.max(...vals);
	const range = max - min || 1;
	const span = Math.max(1, h - PAD * 2);
	return (
		'M' +
		vals
			.map(
				(v, i) =>
					`${((i / (vals.length - 1)) * w).toFixed(1)},${(PAD + span - ((v - min) / range) * span).toFixed(1)}`
			)
			.join(' L')
	);
}
