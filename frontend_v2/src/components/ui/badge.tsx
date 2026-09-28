import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-accent-soft text-accent',
        secondary: 'border-border bg-muted text-muted-foreground',
        outline: 'border-border text-foreground',
        success: 'border-transparent bg-[rgba(16,185,129,0.12)] text-success',
        warning: 'border-transparent bg-[rgba(245,158,11,0.12)] text-warning',
        destructive: 'border-transparent bg-[rgba(239,68,68,0.12)] text-destructive'
      }
    },
    defaultVariants: { variant: 'default' }
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
