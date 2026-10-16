// Cross-panel hover link. The embedding map lives in the Output panel and the sensor
// traces in the Input panel; they are siblings under `+page.svelte` with no data path
// between them. Rather than lift hover state to the page and thread it down through two
// component trees, it sits here as a module singleton — the same shape `rig` already
// uses, and the same reason: this is app state, not a prop of either panel.
//
// STATE is the only granularity. A per-window mode existed briefly — hover one dot, mark
// its 16 samples — and was dropped: the dot is a 2.5px target in a 150-dot trail, and 16
// of 200 rows is a sliver about 9px wide on the traces. Hovering a whole state answers
// the question that view actually raises: where in the run did this happen?

let _state = $state(null);

export const hover = {
	get state() {
		return _state;
	},
	setState(s) {
		_state = s;
	},
	clear() {
		_state = null;
	}
};
