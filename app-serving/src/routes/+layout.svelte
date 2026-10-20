<script>
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';

	let { children } = $props();
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>
<!-- Dark by default: app.html starts <html> with the `dark` class, so there is no light
     flash before the page mounts. The menubar's toggle switches it (the DS `darkMode`). -->
{@render children()}
