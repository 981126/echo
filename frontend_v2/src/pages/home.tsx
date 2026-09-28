import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { RefreshCw, Shuffle, Sparkles, LoaderCircle, Lightbulb, CalendarDays } from 'lucide-react'
import { apiJson } from '@/api/client'
import { buildTimelineModel, type VideoLike, type WorkLike } from '@/lib/timeline'
import { platformName, fmtNum } from '@/lib/format'
import { listVariants, itemVariants } from '@/lib/motion'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { toast } from '@/components/ui/toaster'

interface HotItem {
  platform?: string
  title: string
  heat?: number | null
  url?: string
  matched?: boolean
  score?: number | null
}
interface IdeaItem {
  id: number
  source: 'hot' | 'comment'
  platform?: string
  title: string
  likes?: number
  matched?: boolean
  score?: number | null
}
interface Angle {
  title: string
  hook?: string
  reason?: string
}

export default function HomePage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [sourceTab, setSourceTab] = useState('all')
  const [batch, setBatch] = useState(0)
  const [angleOpen, setAngleOpen] = useState(false)
  const [angles, setAngles] = useState<Angle[]>([])
  const [pendingTopic, setPendingTopic] = useState('')
  const [angleLoading, setAngleLoading] = useState(false)
  const [generating, setGenerating] = useState<string | null>(null)

  const videosQ = useQuery({
    queryKey: ['videos', 'timeline'],
    queryFn: () => apiJson<{ items: VideoLike[] }>('/api/videos?limit=500')
  })
  const worksQ = useQuery({
    queryKey: ['works', 'timeline'],
    queryFn: () => apiJson<{ items: WorkLike[] }>('/api/works')
  })
  const hotQ = useQuery({
    queryKey: ['topics', 'hot'],
    queryFn: () => apiJson<{ items: HotItem[] }>('/api/topics/hot')
  })
  const poolQ = useQuery({
    queryKey: ['topic-pool'],
    queryFn: () => apiJson<{ items: IdeaItem[] }>('/api/platform/topic-pool')
  })

  const refreshHot = useMutation({
    mutationFn: () => apiJson<{ fetched: number }>('/api/topics/refresh', { method: 'POST', body: '{}' }),
    onSuccess: (r) => {
      toast.success(`已抓取 ${r.fetched} 条热点`)
      qc.invalidateQueries({ queryKey: ['topics'] })
      qc.invalidateQueries({ queryKey: ['topic-pool'] })
    },
    onError: (e) => toast.error(e.message)
  })

  const model = useMemo(
    () => buildTimelineModel(videosQ.data?.items ?? [], worksQ.data?.items ?? []),
    [videosQ.data, worksQ.data]
  )

  // 灵感池：评论（topic-pool）+ 热榜（hot），按来源过滤，「换一批」轮转
  const ideas = useMemo(() => {
    const comments: IdeaItem[] = (poolQ.data?.items ?? []).filter((i) => i.source === 'comment')
    const hots: IdeaItem[] = (hotQ.data?.items ?? []).map((h, i) => ({
      id: -(i + 1),
      source: 'hot' as const,
      platform: h.platform,
      title: h.title,
      matched: h.matched,
      score: h.score,
      likes: h.heat ? Number(h.heat) : 0
    }))
    // 相关度优先 + 评论/热榜交错
    const sortByScore = (a: IdeaItem[]) =>
      [...a].sort((x, y) => Number(y.matched) - Number(x.matched) || (y.score ?? 0) - (x.score ?? 0))
    const c = sortByScore(comments)
    const h = sortByScore(hots)
    const merged: IdeaItem[] = []
    const max = Math.max(c.length, h.length)
    for (let i = 0; i < max; i++) {
      if (c[i]) merged.push(c[i])
      if (h[i]) merged.push(h[i])
    }
    return merged
  }, [poolQ.data, hotQ.data])

  const shown = useMemo(() => {
    const filtered =
      sourceTab === 'all' ? ideas : ideas.filter((i) => (sourceTab === 'hot' ? i.source === 'hot' : i.source === 'comment'))
    const n = 10
    if (filtered.length <= n) return filtered
    const off = (batch * n) % filtered.length
    return [...filtered.slice(off), ...filtered.slice(0, off)].slice(0, n)
  }, [ideas, sourceTab, batch])

  async function pickAngle(topic: string) {
    setPendingTopic(topic)
    setAngleOpen(true)
    setAngleLoading(true)
    setAngles([])
    try {
      const r = await apiJson<{ items?: Angle[]; angles?: Angle[] }>('/api/drafts/angles', {
        method: 'POST',
        body: JSON.stringify({ topic })
      })
      setAngles(r.items ?? r.angles ?? [])
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setAngleLoading(false)
    }
  }

  async function generate(topic: string) {
    setGenerating(topic)
    try {
      await apiJson('/api/drafts/generate-async', { method: 'POST', body: JSON.stringify({ topic }) })
      toast.success('已开始生成，去脚本工作台查看')
      setAngleOpen(false)
      navigate('/drafts')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setGenerating(null)
    }
  }

  return (
    <motion.div variants={listVariants} initial="initial" animate="animate" className="space-y-6">
      {/* 时间线 */}
      <motion.section variants={itemVariants}>
        <Card>
          <CardHeader className="flex-row items-center gap-2">
            <CalendarDays className="h-4 w-4 text-accent" />
            <CardTitle>时间线</CardTitle>
            <CardDescription>本地素材与云端作品的发布轨迹</CardDescription>
          </CardHeader>
          <CardContent>
            {videosQ.isLoading || worksQ.isLoading ? (
              <Skeleton className="h-28 w-full" />
            ) : !model.events.length ? (
              <div className="flex h-28 items-center justify-center text-sm text-muted-foreground">
                暂无视频时间记录
              </div>
            ) : (
              <div className="overflow-x-auto pb-2">
                <div className="relative h-32" style={{ width: model.width }}>
                  <div className="absolute left-0 right-0 top-[52px] h-px bg-border" />
                  {model.todayLeft !== null && (
                    <div className="absolute top-2 bottom-2 w-px bg-accent/60" style={{ left: model.todayLeft }}>
                      <span className="absolute -top-1 left-1 text-[10px] font-medium text-accent">今天</span>
                    </div>
                  )}
                  {model.months.map((m) => (
                    <span key={m.key} className="absolute top-0 text-[11px] text-muted-foreground" style={{ left: m.left }}>
                      {m.label}
                    </span>
                  ))}
                  {model.events.map((e, i) => (
                    <motion.button
                      key={e.key}
                      initial={{ opacity: 0, y: 14 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.04 * Math.min(i, 14), duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                      whileHover={{ y: -4 }}
                      onClick={() => navigate(e.kind === 'video' ? `/videos?edit=${e.id}` : '/videos')}
                      className="group absolute flex w-20 cursor-pointer flex-col items-center gap-1"
                      style={{ left: e.left - 40, top: 24 }}
                    >
                      {e.coverUrl ? (
                        <img
                          src={e.coverUrl}
                          alt=""
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          className="h-12 w-12 rounded-md border border-border object-cover transition-transform duration-300 group-hover:scale-105"
                        />
                      ) : (
                        <span className="flex h-12 w-12 items-center justify-center rounded-md border border-border bg-muted text-[9px] font-semibold text-muted-foreground">
                          ECHO
                        </span>
                      )}
                      <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                      <span className="w-full truncate text-center text-[10px] text-muted-foreground">{e.title}</span>
                      {e.srcLabel && (
                        <span className="rounded-full bg-muted px-1.5 text-[9px] text-muted-foreground">{e.srcLabel}</span>
                      )}
                    </motion.button>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </motion.section>

      {/* 灵感池 */}
      <motion.section variants={itemVariants}>
        <Card>
          <CardHeader className="flex-row flex-wrap items-center gap-2">
            <Lightbulb className="h-4 w-4 text-accent" />
            <CardTitle>灵感池</CardTitle>
            <CardDescription>评论与热榜按人设相关度均衡展示 · 人工挑选</CardDescription>
            <div className="flex-1" />
            <Tabs value={sourceTab} onValueChange={setSourceTab}>
              <TabsList className="h-8">
                <TabsTrigger value="all" className="text-xs">全部</TabsTrigger>
                <TabsTrigger value="comment" className="text-xs">只看评论</TabsTrigger>
                <TabsTrigger value="hot" className="text-xs">只看热榜</TabsTrigger>
              </TabsList>
            </Tabs>
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={() => setBatch((b) => b + 1)}>
                  <Shuffle className="h-3.5 w-3.5" /> 换一批
                </Button>
              </TooltipTrigger>
              <TooltipContent>轮转展示其它灵感</TooltipContent>
            </Tooltip>
            <Button variant="secondary" size="sm" onClick={() => refreshHot.mutate()} disabled={refreshHot.isPending}>
              {refreshHot.isPending ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              抓取更新
            </Button>
          </CardHeader>
          <CardContent>
            {hotQ.isLoading || poolQ.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-9 w-full" />
                ))}
              </div>
            ) : !shown.length ? (
              <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
                暂无灵感（点「抓取更新」或等每日自动同步）
              </div>
            ) : (
              <motion.ul variants={listVariants} initial="initial" animate="animate" className="divide-y divide-border/60">
                {shown.map((it) => (
                  <motion.li key={`${it.source}-${it.id}`} variants={itemVariants} className="flex items-center gap-2 py-2.5">
                    <span className="w-12 shrink-0 text-xs text-muted-foreground">
                      {platformName(it.platform, '综合')}
                    </span>
                    <Badge variant={it.source === 'hot' ? 'secondary' : 'default'}>
                      {it.source === 'hot' ? '热榜' : '评论'}
                    </Badge>
                    {it.matched || (it.score ?? 0) > 0 ? (
                      <Badge variant="success">相关</Badge>
                    ) : it.source === 'hot' ? (
                      <Badge variant="secondary">低相关</Badge>
                    ) : null}
                    {it.source === 'comment' && it.likes ? (
                      <span className="tnum shrink-0 text-xs text-muted-foreground">👍 {fmtNum(it.likes)}</span>
                    ) : null}
                    <span className="min-w-0 flex-1 truncate text-[13px]">{it.title}</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-accent"
                      disabled={generating !== null}
                      onClick={() => pickAngle(it.title)}
                    >
                      {generating === it.title ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      生成文案
                    </Button>
                  </motion.li>
                ))}
              </motion.ul>
            )}
          </CardContent>
        </Card>
      </motion.section>

      {/* 角度选择 */}
      <Dialog open={angleOpen} onOpenChange={setAngleOpen}>
        <DialogContent className="w-[min(680px,94vw)]">
          <DialogHeader>
            <DialogTitle>选一个切入角度</DialogTitle>
          </DialogHeader>
          {angleLoading ? (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> 正在想 3 个角度…
            </div>
          ) : !angles.length ? (
            <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
              暂时没想出来，直接按原话题生成
            </div>
          ) : (
            <ul className="space-y-2">
              {angles.map((a, i) => (
                <motion.li
                  key={i}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.07, duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                >
                  <button
                    onClick={() => generate(a.title)}
                    disabled={generating !== null}
                    className="flex w-full items-start gap-3 rounded-lg border border-border p-3 text-left transition-all hover:border-accent/50 hover:bg-accent-soft cursor-pointer"
                  >
                    <span className="tnum flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-semibold">
                      {i + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-medium">{a.title}</span>
                      {a.hook && <span className="mt-1 block text-xs text-muted-foreground">钩子:{a.hook}</span>}
                      {a.reason && <span className="mt-0.5 block text-xs text-muted-foreground/80">{a.reason}</span>}
                    </span>
                    {generating === a.title && <LoaderCircle className="h-4 w-4 animate-spin text-accent" />}
                  </button>
                </motion.li>
              ))}
            </ul>
          )}
          {!angleLoading && (
            <div className="mt-2 flex gap-2">
              <Button variant="secondary" size="sm" onClick={() => generate(pendingTopic)} disabled={generating !== null}>
                不选角度，直接生成
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setAngleOpen(false)}>
                取消
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </motion.div>
  )
}
