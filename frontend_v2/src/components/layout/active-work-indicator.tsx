import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import * as Popover from '@radix-ui/react-popover'
import { AnimatePresence, motion } from 'framer-motion'
import { LoaderCircle } from 'lucide-react'
import { useActiveWork, type ActiveItem } from '@/hooks/use-active-work'
import { softIn } from '@/lib/motion'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'

// R-202：顶栏全局「进行中 N」指示器——任何页面都能确认后台还有任务在跑，
// 避免「切页回来动画没了 → 误以为已完成」。
export function ActiveWorkIndicator() {
  const { items } = useActiveWork()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const count = items.length

  function go(item: ActiveItem) {
    setOpen(false)
    if (item.target) navigate(item.target)
  }

  return (
    <AnimatePresence>
      {count > 0 && (
        <motion.div
          initial={{ opacity: 0.85, x: 6 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 6 }}
          transition={softIn}
        >
          <Popover.Root open={open} onOpenChange={setOpen}>
            <Popover.Trigger asChild>
              <button
                className="flex h-9 items-center gap-1.5 rounded-md border border-accent/30 bg-accent-soft/50 px-2.5 text-xs font-medium text-accent transition-colors hover:bg-accent-soft cursor-pointer"
                aria-label={`进行中 ${count}`}
              >
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                <span className="tnum">进行中 {count}</span>
              </button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                align="end"
                sideOffset={8}
                className="z-50 w-[min(360px,92vw)] rounded-lg border border-border bg-card shadow-xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:slide-in-from-top-2 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=closed]:slide-out-to-top-2"
              >
                <div className="border-b border-border px-4 py-3 text-sm font-semibold">
                  进行中的任务（{count}）
                </div>
                <ScrollArea className="max-h-[50vh]">
                  <ul>
                    <AnimatePresence initial={false}>
                      {items.map((t) => (
                        <motion.li
                          key={t.key}
                          layout
                          initial={{ opacity: 0, y: 6 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, x: 12 }}
                        >
                          <button
                            onClick={() => go(t)}
                            className="flex w-full flex-col gap-1 border-b border-border/60 px-4 py-3 text-left transition-colors hover:bg-muted cursor-pointer"
                          >
                            <span className="flex items-center gap-2">
                              <span className="text-[13px] font-medium">{t.label || t.kind}</span>
                              <span className="tnum text-[11px] text-muted-foreground">{t.progress}%</span>
                            </span>
                            {t.note && <span className="line-clamp-1 text-xs text-muted-foreground">{t.note}</span>}
                            <Progress value={t.progress} />
                          </button>
                        </motion.li>
                      ))}
                    </AnimatePresence>
                  </ul>
                </ScrollArea>
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
