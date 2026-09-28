import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ExternalLink, RefreshCw, PackagePlus } from 'lucide-react'
import { apiJson } from '@/api/client'
import { platformName, fmtNum, fmtDate } from '@/lib/format'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/toaster'
import { listVariants, itemVariants } from '@/lib/motion'
import type { AccountMeta, PlatformPostItem } from './types'

export function PostsDialog({
  account,
  open,
  onOpenChange
}: {
  account: AccountMeta | null
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['account-posts', account?.id],
    queryFn: () => apiJson<{ items: PlatformPostItem[]; total: number }>(`/api/platform/posts?account_id=${account!.id}&limit=200`),
    enabled: open && !!account
  })

  async function syncPost(p: PlatformPostItem) {
    try {
      await apiJson(`/api/platform/posts/${p.id}/sync`, { method: 'POST' })
      toast.success('已开始同步')
      qc.invalidateQueries({ queryKey: ['account-posts', account?.id] })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function toMaterial(p: PlatformPostItem) {
    try {
      await apiJson(`/api/platform/posts/${p.id}/to-material`, { method: 'POST' })
      toast.success('已转入素材库')
      qc.invalidateQueries({ queryKey: ['account-posts', account?.id] })
      qc.invalidateQueries({ queryKey: ['works'] })
      qc.invalidateQueries({ queryKey: ['videos'] })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const items = q.data?.items ?? []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(860px,96vw)]">
        <DialogHeader>
          <DialogTitle>
            {account?.nickname || platformName(account?.platform || '')} 的作品
            <span className="ml-2 text-xs font-normal text-muted-foreground">{q.data?.total ?? items.length} 条</span>
          </DialogTitle>
        </DialogHeader>
        <div className="max-h-[70vh] overflow-y-auto">
          {q.isLoading ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="aspect-[3/4] w-full" />
              ))}
            </div>
          ) : !items.length ? (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              暂无作品（先点「同步」拉取）
            </div>
          ) : (
            <motion.ul variants={listVariants} initial="initial" animate="animate" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {items.map((p) => (
                <motion.li key={p.id} variants={itemVariants} className="overflow-hidden rounded-lg border border-border bg-card">
                  <div className="relative aspect-[4/3] bg-muted">
                    {p.cover ? (
                      <img src={p.cover} alt="" loading="lazy" className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full items-center justify-center text-[10px] font-semibold text-muted-foreground/60">ECHO</div>
                    )}
                    {p.page_url && (
                      <a
                        href={p.page_url}
                        target="_blank"
                        rel="noreferrer"
                        className="absolute right-1.5 top-1.5 rounded-md bg-black/45 p-1 text-white backdrop-blur-sm hover:bg-black/65"
                      >
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                  <div className="p-2.5">
                    <p className="line-clamp-2 min-h-8 text-xs font-medium leading-snug">{p.title || '（无标题）'}</p>
                    <div className="tnum mt-1.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                      <span>👍 {fmtNum(p.latest_stat?.likes)}</span>
                      <span>💬 {fmtNum(p.latest_stat?.comments)}</span>
                      <span>⭐ {fmtNum(p.latest_stat?.favorites)}</span>
                      <span className="flex-1" />
                      <span>{fmtDate(p.publish_time)}</span>
                    </div>
                    <div className="mt-2 flex items-center gap-1">
                      {p.local_video_id ? (
                        <Badge variant="success" className="text-[10px]">已转素材</Badge>
                      ) : (
                        <Button variant="outline" size="sm" className="h-7 text-[11px]" onClick={() => toMaterial(p)}>
                          <PackagePlus className="h-3 w-3" /> 转素材
                        </Button>
                      )}
                      <span className="flex-1" />
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => syncPost(p)}>
                        <RefreshCw className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                </motion.li>
              ))}
            </motion.ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
