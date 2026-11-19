import { NavLink } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Waves } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SIDEBAR_NAV as NAV } from '@/lib/nav'

// R-256：取消展开/收起，固定宽度；R-269：85px → 68px（-20%），内边距/字号同步收紧保证汉字完整。
export function Sidebar() {
  return (
    <aside className="hidden h-full w-[68px] shrink-0 flex-col border-r border-border bg-card/60 backdrop-blur md:flex">
      <div className="flex h-14 shrink-0 items-center justify-center">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-foreground">
          <Waves className="h-4 w-4" />
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-1 py-2">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                'group relative flex flex-col items-center gap-1 rounded-md px-1 py-2 text-[10px] leading-none font-medium whitespace-nowrap text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
                isActive && 'text-foreground'
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
                <span className="relative z-10">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
