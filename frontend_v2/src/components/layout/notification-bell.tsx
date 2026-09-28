import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import * as Popover from '@radix-ui/react-popover'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { Bell, CheckCheck, Trash2 } from 'lucide-react'
import { apiJson } from '@/api/client'
import type { Notification } from '@/api/types'
import { cn } from '@/lib/utils'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: unread } = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () => apiJson<{ unread: number }>('/api/notifications/unread-count'),
    refetchInterval: 30_000
  })
  const { data: items = [] } = useQuery({
    queryKey: ['notifications', 'list'],
    queryFn: () => apiJson<Notification[]>('/api/notifications'),
    enabled: open
  })

  const readAll = useMutation({
    mutationFn: () => apiJson('/api/notifications/read', { method: 'POST', body: '{}' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] })
  })
  const clearAll = useMutation({
    mutationFn: () => apiJson('/api/notifications/clear', { method: 'POST', body: '{}' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] })
  })

  const count = unread?.unread ?? 0

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          className="relative flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer"
          aria-label="通知"
        >
          <Bell className="h-4 w-4" />
          <AnimatePresence>
            {count > 0 && (
              <motion.span
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
                className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-foreground tnum"
              >
                {count > 99 ? '99+' : count}
              </motion.span>
            )}
          </AnimatePresence>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="z-50 w-[min(380px,92vw)] rounded-lg border border-border bg-card shadow-xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:slide-in-from-top-2"
        >
          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <span className="text-sm font-semibold">通知</span>
            {count > 0 && <Badge>{count} 未读</Badge>}
            <div className="flex-1" />
            <Button variant="ghost" size="sm" onClick={() => readAll.mutate()} disabled={!items.length}>
              <CheckCheck className="h-3.5 w-3.5" /> 全部已读
            </Button>
            <Button variant="ghost" size="sm" onClick={() => clearAll.mutate()} disabled={!items.length}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
          <ScrollArea className="max-h-[60vh]">
            {!items.length ? (
              <div className="px-4 py-10 text-center text-sm text-muted-foreground">暂无通知</div>
            ) : (
              <ul>
                <AnimatePresence initial={false}>
                  {items.map((n) => (
                    <motion.li
                      key={n.id}
                      layout
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, x: 12 }}
                    >
                      <button
                        onClick={() => {
                          setOpen(false)
                          if (n.target) navigate(n.target)
                        }}
                        className={cn(
                          'flex w-full flex-col gap-0.5 border-b border-border/60 px-4 py-3 text-left transition-colors hover:bg-muted cursor-pointer',
                          n.status === 'failed' && 'border-l-2 border-l-destructive'
                        )}
                      >
                        <span className="text-[13px] font-medium">{n.title}</span>
                        <span className="line-clamp-2 text-xs text-muted-foreground">{n.message}</span>
                      </button>
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </ScrollArea>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
