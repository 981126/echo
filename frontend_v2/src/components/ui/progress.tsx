import * as React from 'react'
import * as ProgressPrimitive from '@radix-ui/react-progress'
import { cn } from '@/lib/utils'

// 支持不确定态（indeterminate）：不传 value 时显示流光动画
const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> & { indeterminate?: boolean }
>(({ className, value, indeterminate, ...props }, ref) => (
  <ProgressPrimitive.Root
    ref={ref}
    className={cn('relative h-1.5 w-full overflow-hidden rounded-full bg-muted', className)}
    {...props}
  >
    {indeterminate ? (
      <div className="absolute inset-y-0 w-1/3 rounded-full bg-accent progress-indeterminate" />
    ) : (
      <ProgressPrimitive.Indicator
        className="h-full rounded-full bg-accent transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
      />
    )}
  </ProgressPrimitive.Root>
))
Progress.displayName = ProgressPrimitive.Root.displayName

export { Progress }
