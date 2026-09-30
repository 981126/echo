import * as React from 'react'
import * as TabsPrimitive from '@radix-ui/react-tabs'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { EASE_OUT_EXPO } from '@/lib/motion'

// R-204：选中态用一个共享 layout 的「滑块」在 tab 间平滑移动（原来只是瞬间换背景色，没过渡）。
// layoutId 每个 Tabs 实例唯一（useId），避免页面上多个 Tabs 的滑块互相串门。
interface TabsCtxValue {
  value?: string
  id: string
}
const TabsCtx = React.createContext<TabsCtxValue>({ id: '' })

const Tabs = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Root>
>(({ value, defaultValue, onValueChange, children, ...props }, ref) => {
  const id = React.useId()
  const [internal, setInternal] = React.useState(defaultValue)
  const current = value !== undefined ? value : internal
  return (
    <TabsPrimitive.Root
      ref={ref}
      value={value}
      defaultValue={defaultValue}
      onValueChange={(v) => {
        setInternal(v)
        onValueChange?.(v)
      }}
      {...props}
    >
      <TabsCtx.Provider value={{ value: current, id }}>{children}</TabsCtx.Provider>
    </TabsPrimitive.Root>
  )
})
Tabs.displayName = 'Tabs'

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      'inline-flex h-9 items-center gap-1 rounded-lg bg-muted p-1 text-muted-foreground',
      className
    )}
    {...props}
  />
))
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, children, value, ...props }, ref) => {
  const ctx = React.useContext(TabsCtx)
  const active = value !== undefined && value === ctx.value
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      value={value}
      className={cn(
        'relative inline-flex cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium text-muted-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-50 data-[state=active]:text-foreground',
        className
      )}
      {...props}
    >
      {active && (
        <motion.span
          aria-hidden
          layoutId={`tab-pill-${ctx.id}`}
          className="absolute inset-0 rounded-md bg-card shadow-sm"
          transition={{ type: 'spring', stiffness: 420, damping: 34 }}
        />
      )}
      <span className="relative z-[1] inline-flex items-center gap-1.5">{children}</span>
    </TabsPrimitive.Trigger>
  )
})
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

// R-174：切换 TAB 的入场动效全站统一。Radix 的 Presence 在未选中时会卸载 Content，
// 切回来是重新挂载 → `initial` 每次都会播。调用方的 className 挂在内层 motion 上，
// 避免破坏 `space-y-*`（它只作用于直接子元素）。
// R-175：**不能从 opacity:0 起步**——旧面板已卸载、新面板全透明会先闪出一帧空白（实测切
// AI 设置时整块卡片白闪一下）；改从 0.85 起步 + 8px 位移，0.22s 收口，既看得见动效又不闪。
const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <TabsPrimitive.Content ref={ref} className="mt-3 outline-none" {...props}>
    <motion.div
      initial={{ opacity: 0.85, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE_OUT_EXPO }}
      className={cn('outline-none', className)}
    >
      {children}
    </motion.div>
  </TabsPrimitive.Content>
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export { Tabs, TabsList, TabsTrigger, TabsContent }
