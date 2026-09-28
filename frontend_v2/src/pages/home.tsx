import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { RefreshCw, Shuffle, Sparkles, LoaderCircle, Lightbulb } from 'lucide-react'
import { apiJson } from '@/api/client'
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
interface PackItem {
  title: string
  slot: string
  score: number
  reason: string
  demand?: number
  duplicate?: boolean
  samples?: string[]
}
interface Cluster {
  title: string
  count: number
  likes: number
  matched: boolean
  score: number
  samples: string[]
}
interface AttrTag {
  tag: string
  count: number
  avg_engagement: number
}
interface Attribution {
  by_tag: AttrTag[]
  good_tags: string[]
  draft_count: number
  avg_engagement?: number
}

// R-183 创作模式（空 = 自动，由人设+样本决定）
const GEN_MODES = [
  { key: '', label: '自动' },
  { key: 'sharp', label: '犀利干货' },
  { key: 'monologue', label: '个人独白' },
  { key: 'commentary', label: '热点评论' },
  { key: 'experiment', label: '实验复盘' }
]

const normTitle = (s: string) => (s || '').toLowerCase().replace(/[\s\W_]+/g, '')

export default function HomePage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [sourceTab, setSourceTab] = useState('all')
  const [batch, setBatch] = useState(0)
  const [angleOpen, setAngleOpen] = useState(false)
  const [angles, setAngles] = useState<Angle[]>([])
  const [mode, setMode] = useState('')
  const [pack, setPack] = useState<PackItem[]>([])
  const [packLoading, setPackLoading] = useState(false)
  const [clusters, setClusters] = useState<Cluster[]>([])
  const [clustersLoading, setClustersLoading] = useState(false)
  const [gap, setGap] = useState<PackItem[]>([])
  const [gapLoading, setGapLoading] = useState(false)
  const [gapNote, setGapNote] = useState('')
  const [attr, setAttr] = useState<Attribution | null>(null)
  const [attrLoading, setAttrLoading] = useState(false)
  const [pendingTopic, setPendingTopic] = useState('')
  const [angleLoading, setAngleLoading] = useState(false)
  const [generating, setGenerating] = useState<string | null>(null)

  const hotQ = useQuery({
    queryKey: ['topics', 'hot'],
    queryFn: () => apiJson<{ items: HotItem[] }>('/api/topics/hot')
  })
  const poolQ = useQuery({
    queryKey: ['topic-pool'],
    queryFn: () => apiJson<{ items: IdeaItem[] }>('/api/platform/topic-pool')
  })
  const coveredQ = useQuery({
    queryKey: ['opportunities', 'covered'],
    queryFn: () => apiJson<{ titles: string[] }>('/api/opportunities/covered?limit=300')
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

  const coveredNorm = useMemo(
    () => (coveredQ.data?.titles ?? []).map(normTitle).filter((t) => t.length >= 4),
    [coveredQ.data]
  )
  const isMaybeRepeated = (title: string) => {
    const n = normTitle(title)
    if (n.length < 4) return false
    return coveredNorm.some((c) => n.includes(c) || c.includes(n))
  }

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

  async function loadPack() {
    setPackLoading(true)
    try {
      const r = await apiJson<{ items: PackItem[] }>('/api/opportunities/weekly?limit=20')
      setPack(r.items || [])
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setPackLoading(false)
    }
  }

  async function loadClusters() {
    setClustersLoading(true)
    try {
      const r = await apiJson<{ clusters: Cluster[] }>('/api/opportunities/comments?limit=15')
      setClusters(r.clusters || [])
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setClustersLoading(false)
    }
  }

  async function loadGap() {
    setGapLoading(true)
    try {
      const r = await apiJson<{ items: PackItem[]; note?: string }>('/api/opportunities/gap?limit=6')
      setGap(r.items || [])
      setGapNote(r.note || '')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setGapLoading(false)
    }
  }

  async function loadAttr() {
    setAttrLoading(true)
    try {
      const r = await apiJson<Attribution>('/api/opportunities/attribution?limit=15')
      setAttr(r)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setAttrLoading(false)
    }
  }

  async function generate(topic: string) {
    setGenerating(topic)
    try {
      await apiJson('/api/drafts/generate-async', { method: 'POST', body: JSON.stringify({ topic, mode }) })
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
                    {isMaybeRepeated(it.title) && <Badge variant="warning" className="shrink-0">可能已讲</Badge>}
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

      {/* 内容机会（R-185）：观众提问榜 + 每周灵感包 */}
      <motion.section variants={itemVariants}>
        <Card>
          <CardHeader className="flex-row flex-wrap items-center gap-2">
            <Lightbulb className="h-4 w-4 text-accent" />
            <CardTitle>内容机会</CardTitle>
            <CardDescription>评论聚类「观众提问」+ 每周灵感包（自动去掉已讲过的话题）</CardDescription>
            <span className="flex-1" />
            <Button variant="outline" size="sm" onClick={loadClusters} disabled={clustersLoading}>
              {clustersLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Lightbulb className="h-3.5 w-3.5" />}
              观众提问榜
            </Button>
            <Button size="sm" onClick={loadPack} disabled={packLoading}>
              {packLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              生成本周灵感包
            </Button>
            <Button size="sm" variant="outline" onClick={loadGap} disabled={gapLoading}>
              {gapLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              找缺口选题
            </Button>
            <Button size="sm" variant="ghost" onClick={loadAttr} disabled={attrLoading}>
              {attrLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
              看表现归因
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {!!clusters.length && (
              <div>
                <span className="mb-1.5 block text-xs font-medium text-muted-foreground">观众提问榜（同一问题被问越多次越靠前）</span>
                <ul className="space-y-1.5">
                  {clusters.map((c, i) => (
                    <li key={i} className="flex items-start gap-2 rounded-lg border border-border px-3 py-2">
                      <span className="tnum mt-0.5 shrink-0 rounded bg-muted px-1.5 text-xs font-semibold">{c.count}人问</span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px]">{c.title}</span>
                        {!!c.samples?.length && <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">来自：{c.samples.join(' / ')}</span>}
                      </span>
                      {c.matched && <Badge variant="secondary" className="shrink-0">贴合人设</Badge>}
                      <Button size="sm" className="h-7 shrink-0 text-xs" onClick={() => generate(c.title)} disabled={generating !== null}>生成</Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!!pack.length && (
              <div>
                <span className="mb-1.5 block text-xs font-medium text-muted-foreground">本周灵感包（需求 × 人设 × 热度 × 缺口）</span>
                <ul className="space-y-1.5">
                  {pack.map((p, i) => (
                    <li key={i} className="flex items-start gap-2 rounded-lg border border-border px-3 py-2">
                      <span className="tnum mt-0.5 shrink-0 text-xs text-muted-foreground">#{i + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px]">{p.title}</span>
                        <span className="mt-0.5 block text-[11px] text-muted-foreground">{p.reason} · 分 {p.score}</span>
                      </span>
                      <Button size="sm" className="h-7 shrink-0 text-xs" onClick={() => generate(p.title)} disabled={generating !== null}>生成</Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!!gap.length && (
              <div>
                <span className="mb-1.5 block text-xs font-medium text-muted-foreground">缺口选题（该讲但还没讲过，AI 基于人设与已讲话题）</span>
                <ul className="space-y-1.5">
                  {gap.map((p, i) => (
                    <li key={i} className="flex items-start gap-2 rounded-lg border border-accent/30 bg-accent-soft/40 px-3 py-2">
                      <span className="tnum mt-0.5 shrink-0 text-xs text-muted-foreground">#{i + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px]">{p.title}</span>
                        {p.reason && <span className="mt-0.5 block text-[11px] text-muted-foreground">{p.reason}</span>}
                      </span>
                      <Button size="sm" className="h-7 shrink-0 text-xs" onClick={() => generate(p.title)} disabled={generating !== null}>生成</Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!!gapNote && !gap.length && (
              <p className="text-xs text-muted-foreground">{gapNote}</p>
            )}
            {attr && (
              <div>
                <span className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  表现归因（按标签聚合已发布稿件，越高越值得再做）
                </span>
                {attr.draft_count === 0 || !attr.by_tag.length ? (
                  <p className="text-xs text-muted-foreground">还没有已发布且回填了表现的稿件（先记录发布信息 + 每日自动回填）</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {attr.by_tag.map((t) => (
                      <Badge key={t.tag} variant={attr.good_tags.includes(t.tag) ? 'success' : 'secondary'} className="text-[11px]">
                        {t.tag} · {fmtNum(Math.round(t.avg_engagement))}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            )}
            {!clusters.length && !pack.length && !gap.length && !attr && (
              <p className="py-3 text-center text-sm text-muted-foreground">点上方按钮：看观众反复问什么、生成本周灵感包、让 AI 找缺口选题，或看表现归因</p>
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
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">创作模式</span>
            {GEN_MODES.map((m) => (
              <button
                key={m.key}
                onClick={() => setMode(m.key)}
                className={
                  'cursor-pointer rounded-md border px-2 py-0.5 text-xs transition-colors ' +
                  (mode === m.key ? 'border-accent bg-accent-soft text-accent' : 'border-border text-muted-foreground hover:text-foreground')
                }
              >
                {m.label}
              </button>
            ))}
          </div>
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
