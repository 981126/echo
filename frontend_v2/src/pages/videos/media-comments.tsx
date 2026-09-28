import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { MessageSquare, RefreshCw, LoaderCircle, ThumbsUp } from 'lucide-react'
import { apiJson } from '@/api/client'
import { platformName, fmtNum } from '@/lib/format'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/toaster'

interface CommentItem {
  id?: number
  text: string
  likes?: number
  user_nick?: string
}

function PostComments({ postId, platform }: { postId: number; platform: string }) {
  const [refreshing, setRefreshing] = useState(false)
  const q = useQuery({
    queryKey: ['comments', postId],
    queryFn: () => apiJson<{ items: CommentItem[] }>(`/api/platform/posts/${postId}/comments`)
  })

  async function refresh() {
    setRefreshing(true)
    try {
      const r = await apiJson<{ added: number; updated: number }>(`/api/platform/posts/${postId}/comments/refresh`, {
        method: 'POST',
        body: '{}'
      })
      toast.success(`评论已更新（新增 ${r.added}）`)
      await q.refetch()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setRefreshing(false)
    }
  }

  const items = q.data?.items ?? []

  return (
    <div className="rounded-lg border border-border">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Badge variant="secondary">{platformName(platform)}</Badge>
        <span className="text-xs text-muted-foreground">{items.length} 条</span>
        <span className="flex-1" />
        <Button variant="ghost" size="sm" onClick={refresh} disabled={refreshing}>
          {refreshing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          加载评论
        </Button>
      </div>
      {q.isLoading ? (
        <div className="space-y-2 p-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      ) : !items.length ? (
        <div className="flex h-20 items-center justify-center text-xs text-muted-foreground">
          暂无评论，点「加载评论」从平台拉取
        </div>
      ) : (
        <ul className="max-h-72 overflow-y-auto p-2">
          {items.map((c, i) => (
            <motion.li
              key={c.id ?? i}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i, 20) * 0.02 }}
              className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
            >
              <span className="tnum mt-0.5 flex shrink-0 items-center gap-0.5 text-[11px] text-muted-foreground">
                <ThumbsUp className="h-3 w-3" /> {fmtNum(c.likes)}
              </span>
              <div className="min-w-0">
                {c.user_nick && <span className="mr-1.5 text-[11px] font-medium text-accent">{c.user_nick}</span>}
                <span className="text-xs leading-relaxed">{c.text}</span>
              </div>
            </motion.li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function MediaComments({ posts }: { posts: { id?: number | null; platform: string }[] }) {
  const valid = posts.filter((p) => p.id)
  if (!valid.length) {
    return (
      <div className="flex h-28 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
        <MessageSquare className="h-5 w-5" />
        还没有绑定平台作品，保存平台链接后即可查看评论
      </div>
    )
  }
  return (
    <div className="space-y-3">
      {valid.map((p) => (
        <PostComments key={p.id} postId={Number(p.id)} platform={p.platform} />
      ))}
    </div>
  )
}
