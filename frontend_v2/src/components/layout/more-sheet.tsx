import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { X } from 'lucide-react'
import { MORE_NAV, isNavActive } from '@/lib/nav'
import { useBackToClose } from '@/hooks/use-back-to-close'
import { cn } from '@/lib/utils'

interface MoreSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * R-218：移动端「更多」底部 Sheet（博主对标 / 博主管理 / 人设档案 / AI 设置）。
 * - 复用 R-205 的「受控 animate + 延迟卸载」，保证退出动画真的播放（AnimatePresence exit 在本项目不触发）。
 * - 底部安全区 padding；条目热区 ≥44；返回键先关 Sheet（useBackToClose）。
 */
export function MoreSheet({ open, onOpenChange }: MoreSheetProps) {
  const [mounted, setMounted] = useState(open)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const close = useCallback(() => onOpenChange(false), [onOpenChange])

  useBackToClose(open, close)

  useEffect(() => {
    if (open) {
      setMounted(true)
      return
    }
    if (!mounted) return
    const timer = window.setTimeout(() => setMounted(false), 320)
    return () => window.clearTimeout(timer)
  }, [open, mounted])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, close])

  if (!mounted) return null

  return createPortal(
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: open ? 1 : 0 }}
        transition={{ duration: 0.2 }}
        style={{ pointerEvents: open ? 'auto' : 'none' }}
        className="fixed inset-0 z-50 bg-black/45"
        onClick={close}
      />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label="更多"
        initial={{ y: '100%' }}
        animate={{ y: open ? 0 : '100%' }}
        transition={{ type: 'spring', stiffness: 360, damping: 36 }}
        style={{ pointerEvents: open ? 'auto' : 'none' }}
        className="fixed inset-x-0 bottom-0 z-50 rounded-t-2xl border-t border-border bg-card shadow-2xl"
      >
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-border" aria-hidden />
        <div className="flex items-center justify-between px-5 pb-2 pt-3">
          <h2 className="text-sm font-semibold">更多</h2>
          <button
            type="button"
            onClick={close}
            aria-label="关闭"
            className="pressable -m-2 flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground hover:bg-muted cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2 px-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
          {MORE_NAV.map((item) => {
            const active = isNavActive(pathname, item.to)
            return (
              <button
                key={item.to}
                type="button"
                aria-current={active ? 'page' : undefined}
                onClick={() => {
                  close()
                  navigate(item.to)
                }}
                className={cn(
                  'pressable flex min-h-14 items-center gap-2.5 rounded-xl border px-3 text-left text-[13px] cursor-pointer',
                  active
                    ? 'border-accent/40 bg-accent-soft text-accent'
                    : 'border-border bg-card text-foreground hover:bg-muted'
                )}
              >
                <item.icon className="h-5 w-5 shrink-0" />
                <span className="min-w-0 flex-1 truncate">{item.label}</span>
                {active && <span className="shrink-0 text-xs md:text-[11px] opacity-70">当前</span>}
              </button>
            )
          })}
        </div>
      </motion.div>
    </>,
    document.body
  )
}
