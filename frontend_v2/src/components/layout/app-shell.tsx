import { useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Search } from 'lucide-react'
import { Sidebar } from './sidebar'
import { ThemeToggle } from './theme-toggle'
import { NotificationBell } from './notification-bell'
import { ActiveWorkIndicator } from './active-work-indicator'
import { MobileTabBar } from './mobile-tab-bar'
import { MoreSheet } from './more-sheet'
import { useEventStream } from '@/hooks/use-events'
import { ActiveWorkProvider } from '@/hooks/use-active-work'
import { useMainScrollRestore } from '@/hooks/use-main-scroll-restore'
import { useMediaQuery } from '@/hooks/use-media-query'
import { pageTransition, pageVariants, pageVariantsMobile } from '@/lib/motion'

const TITLES: Record<string, string> = {
  '/home': '主页',
  '/dashboard': '数据看板',
  '/videos': '素材库',
  '/video-review': '视频复盘',
  '/drafts': '脚本工作台',
  '/inspiration': '灵感随手记',
  '/benchmark': '博主对标',
  '/creators': '博主管理',
  '/persona': '人设档案',
  '/prompts': 'AI 设置',
  '/chat': 'AI 对话'
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const mainRef = useRef<HTMLElement | null>(null)
  const reduce = useReducedMotion()
  const isMobile = useMediaQuery('(max-width: 767px)')
  useEventStream()
  useMainScrollRestore(location.pathname, mainRef)

  const title = TITLES[location.pathname] ?? 'echo'
  const variants = isMobile ? pageVariantsMobile : pageVariants

  return (
    <ActiveWorkProvider>
      <div className="flex h-full">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />

        <div className="flex min-w-0 flex-1 flex-col">
          {/* R-218：移动端顶栏瘦身——移除汉堡（底部 Tab 取代），标题单行截断，按钮热区 ≥44 */}
          <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border bg-card px-3 md:gap-3 md:bg-card/60 md:px-4 md:backdrop-blur">
            <AnimatePresence mode="wait" initial={false}>
              <motion.h1
                key={title}
                initial={reduce ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduce ? undefined : { opacity: 0, y: -6 }}
                transition={{ duration: reduce ? 0 : 0.2 }}
                className="min-w-0 flex-1 truncate text-[15px] font-semibold tracking-tight"
              >
                {title}
              </motion.h1>
            </AnimatePresence>

            <div className="relative hidden sm:block">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                placeholder="搜索（即将上线）"
                aria-label="搜索（即将上线）"
                className="h-9 w-52 rounded-md border border-input bg-card pl-8 pr-3 text-sm outline-none placeholder:text-muted-foreground/70 focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') navigate('/videos')
                }}
              />
            </div>

            <NotificationBell />
            <ActiveWorkIndicator />
            <ThemeToggle />
          </header>

          <main
            ref={mainRef}
            className="min-h-0 flex-1 overflow-y-auto pb-[calc(56px+env(safe-area-inset-bottom))] md:pb-0"
          >
            {/* 页面转场：仅入场动画（key 随 pathname 变化才重挂载）。
                不用 AnimatePresence mode=wait —— 它与 React 19 Outlet 组合会在页内 setState 时误触发整页卸载重挂载（R-164 实测）。
                R-218：<md 去掉大面积 blur 保流畅；首帧 0.85 不再全透明；reduce 用户不动。 */}
            <motion.div
              key={location.pathname}
              variants={variants}
              initial={reduce ? false : 'initial'}
              animate="animate"
              transition={reduce ? { duration: 0 } : pageTransition}
              className="mx-auto w-full max-w-6xl px-4 py-6 md:px-6"
            >
              <Outlet />
            </motion.div>
          </main>
        </div>

        <MobileTabBar moreOpen={moreOpen} onMore={() => setMoreOpen(true)} />
        <MoreSheet open={moreOpen} onOpenChange={setMoreOpen} />
      </div>
    </ActiveWorkProvider>
  )
}
