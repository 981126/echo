import { Link, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Ellipsis } from 'lucide-react'
import { PRIMARY_NAV, isNavActive } from '@/lib/nav'
import { EASE_SPRING } from '@/lib/motion'
import { cn } from '@/lib/utils'

interface MobileTabBarProps {
  moreOpen: boolean
  onMore: () => void
}

/**
 * R-218：移动端底部 Tab（< md 显示）。
 * - 5 个一级入口 + 「更多」共 6 格，拇指可达；选中态用共享 layout 滑块（比照 R-204）。
 * - 高度 56 + env(safe-area-inset-bottom)；每格热区 ≥44；主内容由 AppShell 预留底部 padding。
 * - 只用 CSS 断点显隐（md:hidden），桌面侧栏不变。
 */
export function MobileTabBar({ moreOpen, onMore }: MobileTabBarProps) {
  const { pathname } = useLocation()

  return (
    <nav
      aria-label="底部导航"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card md:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <div className="grid grid-cols-6">
        {PRIMARY_NAV.map((item) => {
          const active = isNavActive(pathname, item.to)
          return (
            <Link
              key={item.to}
              to={item.to}
              aria-label={item.label}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'pressable relative flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-[12px]',
                active ? 'text-accent' : 'text-muted-foreground'
              )}
            >
              {active && (
                <motion.span
                  layoutId="mobile-tab-pill"
                  aria-hidden
                  transition={EASE_SPRING}
                  className="absolute inset-x-1.5 top-1 h-9 rounded-lg bg-accent-soft"
                />
              )}
              <item.icon className="relative z-[1] h-5 w-5" />
              <span className="relative z-[1] whitespace-nowrap leading-4">{item.shortLabel ?? item.label}</span>
            </Link>
          )
        })}
        <button
          type="button"
          onClick={onMore}
          aria-label="更多"
          aria-expanded={moreOpen}
          aria-haspopup="dialog"
          className={cn(
            'pressable relative flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-[12px] cursor-pointer',
            moreOpen ? 'text-accent' : 'text-muted-foreground'
          )}
        >
          <Ellipsis className="relative z-[1] h-5 w-5" />
          <span className="relative z-[1] whitespace-nowrap leading-4">更多</span>
        </button>
      </div>
    </nav>
  )
}
