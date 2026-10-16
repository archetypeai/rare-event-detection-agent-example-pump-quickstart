import { tv } from 'tailwind-variants';

// --- List variants ---
export const tabsListVariants = tv({
	base: 'rounded-lg p-[3px] group-data-horizontal/tabs:h-8 data-[variant=line]:rounded-none data-[variant=toggle]:rounded-interactive group/tabs-list text-muted-foreground inline-flex w-fit items-center justify-center group-data-[orientation=vertical]/tabs:h-fit group-data-[orientation=vertical]/tabs:flex-col',
	variants: {
		variant: {
			default: 'bg-muted',
			line: 'border-border w-full justify-start gap-5 border-b bg-transparent p-0 group-data-horizontal/tabs:h-auto',
			toggle: 'border-border h-[34px] gap-0 border bg-transparent p-1 px-0.5'
		}
	},
	defaultVariants: {
		variant: 'default'
	}
});

// --- Trigger variants ---
export const tabsTriggerVariants = tv({
	base: "has-data-[icon=inline-end]:pr-1 has-data-[icon=inline-start]:pl-1 group-data-[variant=default]/tabs-list:data-[state=active]:shadow-sm group-data-[variant=line]/tabs-list:data-[state=active]:shadow-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:outline-ring text-foreground/60 hover:text-foreground dark:text-muted-foreground dark:hover:text-foreground relative inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-transparent px-1.5 py-0.5 text-sm transition-all group-data-[variant=default]/tabs-list:h-[calc(100%-1px)] group-data-[variant=default]/tabs-list:flex-1 focus-visible:outline-1 focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50 group-data-[orientation=vertical]/tabs:w-full group-data-[orientation=vertical]/tabs:justify-start [&_svg:not([class*='size-'])]:size-4 [&_svg]:pointer-events-none [&_svg]:shrink-0 group-data-[variant=line]/tabs-list:cursor-pointer group-data-[variant=line]/tabs-list:px-0 group-data-[variant=line]/tabs-list:py-0 group-data-[variant=line]/tabs-list:pb-2 group-data-[variant=line]/tabs-list:text-muted-foreground group-data-[variant=line]/tabs-list:data-[state=active]:text-foreground group-data-[variant=line]/tabs-list:data-[state=active]:bg-transparent dark:group-data-[variant=line]/tabs-list:data-[state=active]:border-transparent dark:group-data-[variant=line]/tabs-list:data-[state=active]:bg-transparent group-data-[variant=line]/tabs-list:bg-transparent group-data-[variant=default]/tabs-list:data-[state=active]:bg-background dark:group-data-[variant=default]/tabs-list:data-[state=active]:text-foreground dark:group-data-[variant=default]/tabs-list:data-[state=active]:border-input dark:group-data-[variant=default]/tabs-list:data-[state=active]:bg-input/30 group-data-[variant=default]/tabs-list:data-[state=active]:text-foreground group-data-[variant=toggle]/tabs-list:rounded-interactive group-data-[variant=toggle]/tabs-list:text-muted-foreground group-data-[variant=toggle]/tabs-list:hover:text-foreground group-data-[variant=toggle]/tabs-list:data-[state=active]:bg-accent group-data-[variant=toggle]/tabs-list:data-[state=active]:text-accent-foreground group-data-[variant=toggle]/tabs-list:data-[state=active]:shadow-none group-data-[variant=toggle]/tabs-list:data-[state=active]:border-transparent group-data-[variant=toggle]/tabs-list:cursor-pointer group-data-[variant=toggle]/tabs-list:bg-transparent after:bg-foreground group-data-[variant=line]/tabs-list:data-[state=active]:after:opacity-100 after:absolute after:opacity-0 after:transition-opacity group-data-[orientation=horizontal]/tabs:after:inset-x-0 group-data-[orientation=vertical]/tabs:after:inset-y-0 group-data-[orientation=horizontal]/tabs:after:bottom-[-1px] group-data-[orientation=vertical]/tabs:after:-right-1 group-data-[orientation=horizontal]/tabs:after:h-0.5 group-data-[orientation=vertical]/tabs:after:w-0.5",
	variants: {
		variant: {
			text: '',
			icon: 'size-7 flex-none p-0'
		},
		size: {
			default: '',
			pill: 'px-3 py-1'
		},
		typography: {
			default: '',
			mono: 'font-mono text-xs uppercase'
		}
	},
	defaultVariants: {
		variant: 'text',
		size: 'default',
		typography: 'default'
	}
});
