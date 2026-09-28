import { Moon, Sun, Monitor } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTheme } from '@/hooks/use-theme'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const LABEL = { light: '浅色', dark: '深色', system: '跟随系统' } as const

export function ThemeToggle() {
  const { theme, cycle } = useTheme()
  const Icon = theme === 'dark' ? Moon : theme === 'light' ? Sun : Monitor
  return (
    <Tooltip delayDuration={0}>
      <TooltipTrigger asChild>
        <button
          onClick={cycle}
          className="relative flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer"
          aria-label="切换主题"
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={theme}
              initial={{ opacity: 0, rotate: -40, scale: 0.7 }}
              animate={{ opacity: 1, rotate: 0, scale: 1 }}
              exit={{ opacity: 0, rotate: 40, scale: 0.7 }}
              transition={{ duration: 0.18 }}
              className="flex"
            >
              <Icon className="h-4 w-4" />
            </motion.span>
          </AnimatePresence>
        </button>
      </TooltipTrigger>
      <TooltipContent>主题：{LABEL[theme]}（点击切换）</TooltipContent>
    </Tooltip>
  )
}
