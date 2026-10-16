// The two classes the classifier was fitted on, plus the special outcome.
//
// Order matters in one place only: EMB_ORDER below must match the order the
// blueprint's `data_columns` declares, because per-variate embeddings are
// concatenated in that order.
export const CLASSES = ['normal', 'pump_breakdown'];

export const CLASS_META = {
	normal: { label: 'Normal', short: 'NORMAL', color: '#34d399' },
	pump_breakdown: { label: 'Pump Breakdown', short: 'BREAKDOWN', color: '#f43f5e' },
	INVALID_STATE: { label: 'Invalid', short: 'INVALID', color: '#64748b' },
	unknown: { label: 'Unknown', short: '—', color: '#475569' }
};

/** Canonical channel order — the classifier's `data_columns`. */
export const EMB_ORDER = [
	'sensor_02', 'sensor_03', 'sensor_04', 'sensor_05', 'sensor_10',
	'sensor_11', 'sensor_12', 'sensor_38', 'sensor_41', 'sensor_42'
];

// Display labels are community inference from Kaggle discussion 131429, not a
// vendor data dictionary — see src/lib/data/channels.json. Grouped by what they
// measure so the panel reads like an instrument rack rather than a list.
export const CHANNELS = [
	{ key: 'sensor_04', label: 'Motor Speed', group: 'Drive', color: '#22d3ee' },
	{ key: 'sensor_02', label: 'Motor Frequency B', group: 'Drive', color: '#38bdf8' },
	{ key: 'sensor_03', label: 'Motor Frequency C', group: 'Drive', color: '#818cf8' },
	{ key: 'sensor_05', label: 'Motor Current', group: 'Current', color: '#facc15' },
	{ key: 'sensor_10', label: 'Phase Current A', group: 'Current', color: '#fbbf24' },
	{ key: 'sensor_11', label: 'Phase Current B', group: 'Current', color: '#fb923c' },
	{ key: 'sensor_12', label: 'Phase Current C', group: 'Current', color: '#f97316' },
	{ key: 'sensor_38', label: 'Lube Oil Return Temp', group: 'Thermal', color: '#a78bfa' },
	{ key: 'sensor_41', label: 'NDE Bearing Temp 1', group: 'Thermal', color: '#c084fc' },
	{ key: 'sensor_42', label: 'NDE Bearing Temp 2', group: 'Thermal', color: '#e879f9' }
];

export const CADENCE_MS = 60_000; // the pump samples once a minute

/** Window length the blueprint declares; also the warm-up before any output. */
export const WINDOW_SIZE = 64;

/** "21 samples" reads better as "21 min" when the cadence is 1/min. */
export function samplesToDuration(n) {
	if (n === null || n === undefined) return '—';
	const m = Math.round(n);
	if (Math.abs(m) < 60) return `${m} min`;
	const h = Math.floor(Math.abs(m) / 60);
	const r = Math.abs(m) % 60;
	return `${m < 0 ? '-' : ''}${h}h ${r}m`;
}
