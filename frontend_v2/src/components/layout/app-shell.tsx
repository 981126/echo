import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Menu, Search, X } from 'lucide-react'
import { Sidebar } from './sidebar'
import { ThemeToggle } from './theme-toggle'
import { NotificationBell } from './notification-bell'
import { ActiveWorkIndicator } from './active-work-indicator'
import { useEventStream } from '@/hooks/use-events'
import { ActiveWorkProvider } from '@/hooks/use-active-work'
import { pageVariants, pageTransition } from '@/lib/motion'

const TITLES: Record<string, string> = {
  '/home': '主页',
  '/videos': '素材库',
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
  const [mobileNav, setMobileNav] = useState(false)
  const [mobileNavMounted, setMobileNavMounted] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  useEventStream()

  // R-205：移动端抽屉导航退出动画——关闭后先保持挂载、animate 切到关闭态再卸载
  // （AnimatePresence 在本项目 React19+framer v12 下 exit 不触发）。
  useEffect(() => {
    if (mobileNav) {
      setMobileNavMounted(true)
      return
    }
    const timer = window.setTimeout(() => setMobileNavMounted(false), 340)
    return () => window.clearTimeout(timer)
  }, [mobileNav])

  const title = TITLES[location.pathname] ?? 'echo'

  return (
    <ActiveWorkProvider>
      <div className="flex h-full">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />

      {/* 移动端抽屉导航（R-205：受控 animate + 延迟卸载，保证退出动画） */}
      {mobileNavMounted && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: mobileNav ? 1 : 0 }}
            transition={{ duration: 0.2 }}
            style={{ pointerEvents: mobileNav ? 'auto' : 'none' }}
            className="fixed inset-0 z-40 bg-black/45 md:hidden"
            onClick={() => setMobileNav(false)}
          />
          <motion.div
            initial={{ x: -280 }}
            animate={{ x: mobileNav ? 0 : -280 }}
            transition={{ type: 'spring', stiffness: 360, damping: 36 }}
            style={{ pointerEvents: mobileNav ? 'auto' : 'none' }}
            className="fixed inset-y-0 left-0 z-50 w-64 md:hidden"
          >
            <div className="relative h-full">
              <Sidebar collapsed={false} onToggle={() => setMobileNav(false)} />
              <button
                onClick={() => setMobileNav(false)}
                className="absolute right-2 top-4 rounded-md p-1.5 text-muted-foreground hover:bg-muted cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </motion.div>
        </>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card/60 px-4 backdrop-blur">
          <button
            className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted md:hidden cursor-pointer"
            onClick={() => setMobileNav(true)}
            aria-label="打开导航"
          >
            <Menu className="h-4 w-4" />
          </button>
          <AnimatePresence mode="wait" initial={false}>
            <motion.h1
              key={title}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.2 }}
              className="text-[15px] font-semibold tracking-tight"
            >
              {title}
            </motion.h1>
          </AnimatePresence>

          <div className="flex-1" />

          <div className="relative hidden sm:block">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder="搜索（即将上线）"
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

        <main className="min-h-0 flex-1 overflow-y-auto">
          {/* 页面转场：仅入场动画（key 随 pathname 变化才重挂载）。
              不用 AnimatePresence mode=wait —— 它与 React 19 Outlet 组合会在页内 setState 时误触发整页卸载重挂载（R-164 实测）。 */}
          <motion.div
            key={location.pathname}
            variants={pageVariants}
            initial="initial"
            animate="animate"
            transition={pageTransition}
            className="mx-auto w-full max-w-6xl px-4 py-6 md:px-6"
          >
            <Outlet />
          </motion.div>
        </main>
      </div>
      </div>
    </ActiveWorkProvider>
  )
}
