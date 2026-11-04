import * as React from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'framer-motion'
import { X } from 'lucide-react'
import { useBackToClose } from '@/hooks/use-back-to-close'
import { cn } from '@/lib/utils'

// 右侧抽屉（弹簧物理曲线）：素材编辑/详情主容器
// R-205：退出动画改为「受控 animate + 延迟卸载」——本项目 React 19 + framer-motion v12 下
// AnimatePresence 的 exit 不触发（实测抽屉/移动端导航关闭时元素直接消失），
// 因此关闭后先保持挂载、把 animate 切到关闭态，动画跑完（约 340ms）再卸载。
// R-218：<md 抽屉全屏（100vw）；footer 避让安全区；延迟卸载 400ms（覆盖 spring 收口）；返回键先关抽屉。
export function Drawer({
  open,
  onOpenChange,
  children,
  className,
  width = 'min(680px, 96vw)'
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  children: React.ReactNode
  className?: string
  width?: string
}) {
  const [mounted, setMounted] = React.useState(open)

  useBackToClose(open, () => onOpenChange(false))

  React.useEffect(() => {
    if (open) {
      setMounted(true)
      return
    }
    const timer = window.setTimeout(() => setMounted(false), 400)
    return () => window.clearTimeout(timer)
  }, [open])

  React.useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onOpenChange])

  if (!mounted) return null

  // 必须 portal 到 body：页面容器有 framer-motion 的 transform/filter（pageVariants 的 y/blur），
  // 它们会让 position:fixed 相对祖先而非视口定位 → 抽屉被限制在内容区、滚动不到底（R-164 实测 bug）。
  return createPortal(
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: open ? 1 : 0 }}
        transition={{ duration: 0.2 }}
        style={{ pointerEvents: open ? 'auto' : 'none' }}
        className="fixed inset-0 z-50 bg-black/45 md:backdrop-blur-[2px]"
        onClick={() => onOpenChange(false)}
      />
      <motion.div
        initial={{ x: '100%' }}
        animate={{ x: open ? 0 : '100%' }}
        transition={{ type: 'spring', stiffness: 340, damping: 36 }}
        style={{ ['--drawer-w' as string]: width, pointerEvents: open ? 'auto' : 'none' } as React.CSSProperties}
        className={cn(
          // R-218：<md 全屏；md+ 维持桌面右侧抽屉宽度（由调用方 width 决定）
          'fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-border bg-card shadow-2xl md:w-[var(--drawer-w)]',
          className
        )}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
      >
        <button
          onClick={() => onOpenChange(false)}
          className="pressable absolute right-2 top-2 z-10 flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:right-3 md:top-3 md:h-auto md:w-auto md:p-1.5 cursor-pointer"
          aria-label="关闭"
        >
          <X className="h-4 w-4" />
        </button>
        {children}
      </motion.div>
    </>,
    document.body
  )
}

export function DrawerHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('border-b border-border px-5 py-4 pr-12', className)} {...props} />
}

export function DrawerTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn('truncate text-base font-semibold tracking-tight', className)} {...props} />
}

export function DrawerBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('min-h-0 flex-1 overflow-y-auto px-5 py-4', className)} {...props} />
}

export function DrawerFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 border-t border-border px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] md:flex-nowrap md:px-5 md:pb-3',
        className
      )}
      {...props}
    />
  )
}
