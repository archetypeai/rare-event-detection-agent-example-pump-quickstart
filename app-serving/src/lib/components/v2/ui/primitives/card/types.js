import { tv } from 'tailwind-variants';

// --- Root variants ---
export const cardVariants = tv({
	base: 'ring-foreground/10 bg-card text-card-foreground gap-4 overflow-hidden rounded-interactive py-4 text-sm ring-1 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:border-ring has-data-[slot=card-footer]:pb-0 has-[>img:first-child]:pt-0 group/card flex flex-col',
	variants: {
		variant: {
			default: '',
			intro:
				'h-72 hover:bg-accent transition-all duration-200 hover:-translate-y-0.5 cursor-pointer [&_[data-slot=card-title]]:font-normal [&_[data-slot=card-title]]:text-2xl [&_[data-slot=card-description]]:max-w-prose',
			status:
				'hover:bg-accent ring-0 border border-border py-5 cursor-pointer transition-colors [&_[data-slot=card-title]]:truncate [&_[data-slot=card-title]]:text-lg [&_[data-slot=card-title]]:font-normal [&_[data-slot=card-title]]:capitalize [&_[data-slot=card-content]_span:not([data-slot=badge])]:text-muted-foreground [&_[data-slot=card-content]_span:not([data-slot=badge])]:font-sans [&_[data-slot=card-content]_span:not([data-slot=badge])]:text-xs',
			info: 'gap-2 ring-0 border border-border py-5 [&_[data-slot=card-header]]:px-5 [&_[data-slot=card-content]]:px-5 [&_[data-slot=card-title]]:text-foreground [&_[data-slot=card-title]]:font-sans [&_[data-slot=card-title]]:text-lg [&_[data-slot=card-title]]:font-normal [&_[data-slot=card-title]]:capitalize [&_[data-slot=card-action]]:row-span-1 [&_[data-slot=card-action]]:self-center [&_[data-slot=card-action]_svg]:-translate-y-px [&_[data-slot=card-action]_svg]:stroke-icon-default [&_[data-slot=card-action]_svg]:text-muted-foreground [&_[data-slot=card-action]_svg]:size-4'
		}
	},
	defaultVariants: { variant: 'default' }
});

// --- Content variants ---
export const cardContentVariants = tv({
	base: 'px-4',
	variants: {
		layout: {
			stack: 'flex flex-col gap-4',
			compact: 'space-y-2'
		}
	}
});
