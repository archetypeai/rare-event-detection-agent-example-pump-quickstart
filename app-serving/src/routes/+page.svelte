<script>
	import { pump } from '$lib/stores/pump.svelte.js';
	import Menubar from '$lib/components/ui/patterns/menubar/index.js';
	import InputPanel from '$lib/components/ui/custom/input-panel.svelte';
	import OutputPanel from '$lib/components/ui/custom/output-panel.svelte';
	import SettingsDialog from '$lib/components/ui/custom/settings-dialog.svelte';

	// RED Pump Monitor on the same workbench as the OSM rig monitor, so the two demos read
	// as one product.
	//
	// One dialog. RED's observability was a full-screen panel behind a menubar icon and
	// its playback a full-width bar; both are sections of Settings now, and Settings is
	// reached from the gear beside Run Agent — the two things you do to this demo, start
	// it and configure it, sit together.
	let settingsOpen = $state(false);

	$effect(() => {
		pump.connect();
		pump.loadLandscape();
	});
</script>

<svelte:head><title>RED Pump Monitor — platform · serving</title></svelte:head>

<div class="grid h-dvh w-full grid-rows-[auto_1fr] overflow-hidden">
	<!-- The menubar carries nothing but identity: no status, no controls. -->
	<Menubar />

	<!-- Workbench: what goes into the agent on the left, what comes out on the right,
	     separated by a single hairline. The panels are full-bleed and carry no surface of
	     their own, so the grid's rule is the only thing between them.
	     grid-cols-2 is repeat(2, minmax(0, 1fr)) — the 0 minimum matters, or a wide row
	     inside a panel would push its track past half and shift the rule. -->
	<div class="grid min-h-0 grid-cols-1 lg:grid-cols-2">
		<InputPanel {pump} class="min-h-0 border-separator lg:border-r" />
		<OutputPanel {pump} bind:settingsOpen class="min-h-0 border-t border-separator lg:border-t-0" />
	</div>
</div>

<SettingsDialog {pump} bind:open={settingsOpen} />
