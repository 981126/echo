import * as React from 'react'
import * as ScrollAreaPrimitive from '@radix-ui/react-scroll-area'
import { cn } from '@/lib/utils'

const ScrollArea = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root>
>(({ className, children, ...props }, ref) => (
  <ScrollAreaPrimitive.Root ref={ref} className={cn('relative overflow-hidden', className)} {...props}>
    {/* R-177：Viewport 必须有「定高」才能滚。调用方常只给 Root `max-h-*`（没有显式 height），
        此时 `h-full` 的百分比高度对 auto 高度父级解析为 auto → Viewport 高度=内容高度，
        自己没得滚，Root 又 overflow:hidden → 超出部分直接被裁掉（讨论 tab 实测 4215px 内容卡在 468px 内滚不动）。
        `max-h-[inherit]` 让 Viewport 继承 Root 的上限，只有 max-h 约束时也能成为滚动容器。 */}
    <ScrollAreaPrimitive.Viewport className="h-full max-h-[inherit] w-full rounded-[inherit]">
      {children}
    </ScrollAreaPrimitive.Viewport>
    <ScrollAreaPrimitive.Scrollbar
      orientation="vertical"
      className="flex w-2 touch-none select-none p-0.5"
    >
      <ScrollAreaPrimitive.Thumb className="flex-1 rounded-full bg-border" />
    </ScrollAreaPrimitive.Scrollbar>
    <ScrollAreaPrimitive.Corner />
  </ScrollAreaPrimitive.Root>
))
ScrollArea.displayName = ScrollAreaPrimitive.Root.displayName

export { ScrollArea }
