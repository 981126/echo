import { NavLink } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  BarChart3,
  Clapperboard,
  PenLine,
  Target,
  Users,
  Fingerprint,
  Settings2,
  MessageSquare,
  NotebookPen,
  PanelLeftClose,
  PanelLeftOpen,
  Waves
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const NAV = [
  { to: '/home', label: '主页', icon: LayoutDashboard },
  { to: '/videos', label: '素材库', icon: Clapperboard },
  { to: '/video-review', label: '视频复盘', icon: BarChart3 },
  { to: '/drafts', label: '脚本工作台', icon: PenLine },
  { to: '/inspiration', label: '灵感随手记', icon: NotebookPen },
  { to: '/benchmark', label: '博主对标', icon: Target },
  { to: '/creators', label: '博主管理', icon: Users },
  { to: '/persona', label: '人设档案', icon: Fingerprint },
  { to: '/prompts', label: 'AI 设置', icon: Settings2 },
  { to: '/chat', label: 'AI 对话', icon: MessageSquare }
]

export function Sidebar({
  collapsed,
  onToggle
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  return (
    <motion.aside
      animate={{ width: collapsed ? 64 : 216 }}
      transition={{ type: 'spring', stiffness: 320, damping: 32 }}
      className="hidden md:flex h-full flex-col border-r border-border bg-card/60 backdrop-blur"
    >
      <div className="flex h-14 items-center gap-2.5 px-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
          <Waves className="h-4 w-4" />
        </div>
        {!collapsed && (
          <motion.span
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            className="text-[15px] font-semibold tracking-tight"
          >
            echo
          </motion.span>
        )}
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
        {NAV.map((item) => {
          const link = (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  'group relative flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
                  isActive && 'text-foreground',
                  collapsed && 'justify-center px-0'
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId="nav-active"
                      className="absolute inset-0 rounded-md bg-accent-soft"
                      transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                    />
                  )}
                  <item.icon className={cn('relative z-10 h-4 w-4 shrink-0', isActive && 'text-accent')} />
                  {!collapsed && <span className="relative z-10">{item.label}</span>}
                </>
              )}
            </NavLink>
          )
          return collapsed ? (
            <Tooltip key={item.to} delayDuration={0}>
              <TooltipTrigger asChild>{link}</TooltipTrigger>
              <TooltipContent side="right">{item.label}</TooltipContent>
            </Tooltip>
          ) : (
            link
          )
        })}
      </nav>

      <div className="border-t border-border p-2">
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer"
        >
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          {!collapsed && '收起'}
        </button>
      </div>
    </motion.aside>
  )
}
