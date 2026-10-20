<script>
	import { resolve } from '$app/paths';
	import Logo from '$lib/components/ui/patterns/logo/index.js';
	import { Button } from '@archetypeai/ds-ui-svelte-console/primitives/button';
	import SunIcon from '@lucide/svelte/icons/sun';
	import MoonIcon from '@lucide/svelte/icons/moon';
	import { darkMode } from '@archetypeai/ds-ui-svelte-console/primitives/theme';

	// Identity and the theme switch, nothing else. Settings and Observability were icon
	// buttons here; both now sit behind the gear beside Run Agent in the output panel,
	// where the demo's other live control already is. The theme toggle stays because it is
	// a property of the page rather than of the run.
	let { children } = $props();

	function toggleDark() {
		if (document.startViewTransition) document.startViewTransition(() => darkMode.toggle());
		else darkMode.toggle();
	}
</script>

<header class="flex items-center justify-between border-b border-separator px-4 py-2">
	<div class="flex items-center gap-3">
		<!-- The DS's own top-nav logo treatment, same as the workbench: a Button in the
		     `topNavLogo` variant linking home. Safe as a link here even though this is a
		     single-route app — the rig store is a module-level singleton (`rig.svelte.js`),
		     so it lives outside the component tree and a same-route navigation cannot drop
		     the live MQTT buffer. -->
		<!-- `resolve()`, not a bare "/": the project's eslint enforces
		     `svelte/no-navigation-without-resolve`, which keeps links correct under a
		     non-empty base path. -->
		<!-- The lockup carries the whole identity — the Archetype AI wordmark, a rule,
		     then "Pump Monitor" over "Built by Archetype" — so nothing else up here
		     needs to name the app. -->
		<Button variant="topNavLogo" href={resolve('/')}>
			<Logo />
		</Button>
	</div>
	<div class="flex items-center gap-2">
		{@render children?.()}
		<Button variant="outline" size="icon" aria-label="Toggle dark mode" onclick={toggleDark}>
			{#if darkMode.current}<SunIcon class="size-4" />{:else}<MoonIcon class="size-4" />{/if}
		</Button>
	</div>
</header>
