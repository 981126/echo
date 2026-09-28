import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { RefreshCw, LoaderCircle, Sparkles, PenLine, Target, CircleCheck, CircleX, Wand2 } from 'lucide-react'
import { apiJson } from '@/api/client'
import { platformName, fmtNum } from '@/lib/format'
import { listVariants, itemVariants } from '@/lib/motion'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/toaster'
import { cn } from '@/lib/utils'
import { RewriteDiffDialog, type RewriteResult } from './rewrite-diff-dialog'

interface Analysis {
  can: boolean
  reason?: string
  [k: string]: unknown
}

interface BenchUnit {
  key: string
  post_id: number
  work_id?: number | null
  title: string
  cover?: string
  platforms: string[]
  likes: number
  favorites: number
  comments: number
  plays: number
  score: number
  has_text: boolean
  text: string
  tags: string[]
  analysis?: Analysis | null
}

interface Benchmark {
  benchmark_id: number
  name: string
  note: string
  items: BenchUnit[]
}

interface TaskRow {
  id: number
  status: string
  result?: string
  error?: string
}

async function waitTask(taskId: number, signal: { cancelled: boolean }): Promise<TaskRow> {
  for (;;) {
    if (signal.cancelled) throw new Error('已取消')
    await new Promise((r) => setTimeout(r, 2000))
    const t = await apiJson<TaskRow>(`/api/tasks/${taskId}`)
    if (t.status === 'done' || t.status === 'failed') return t
  }
}

export default function BenchmarkPage() {
  const qc = useQueryClient()
  const [analysisMap, setAnalysisMap] = useState<Record<string, Analysis>>({})
  const [busyKey, setBusyKey] = useState('')
  const [preparingId, setPreparingId] = useState(0)
  const [rerunning, setRerunning] = useState(false)
  const [rewrite, setRewrite] = useState<RewriteResult | null>(null)
  const seqRef = useRef(0)

  const topQ = useQuery({
    queryKey: ['benchmark', 'top'],
    queryFn: () => apiJson<{ owner_name: string; benchmarks: Benchmark[] }>('/api/benchmark/top')
  })

  // 首屏载入已落库的分析结果 + 恢复进行中任务
  useEffect(() => {
    const map: Record<string, Analysis> = {}
    for (const b of topQ.data?.benchmarks ?? []) {
      for (const it of b.items) {
        if (it.analysis) map[it.key] = it.analysis
      }
    }
    if (Object.keys(map).length) setAnalysisMap((prev) => ({ ...map, ...prev }))
  }, [topQ.data])

  useEffect(() => {
    ;(async () => {
      try {
        const running = await apiJson<{ id: number; kind: string; payload: string }[]>(
          '/api/tasks?status=running&kind=benchmark_analyze,benchmark_rewrite&limit=20'
        )
        void running
      } catch {
        /* 忽略 */
      }
    })()
  }, [])

  async function rerun() {
    setRerunning(true)
    const seq = ++seqRef.current
    try {
      const d = await apiJson<{ task_id: number }>('/api/benchmark/rerun', { method: 'POST', body: '{}' })
      toast.info('重新对标进行中（重捞+转写补齐）…')
      const t = await waitTask(d.task_id, { cancelled: false })
      if (seq !== seqRef.current) return
      if (t.status === 'done') {
        toast.success('重新对标完成')
        qc.invalidateQueries({ queryKey: ['benchmark'] })
      } else {
        toast.error(t.error || '重新对标失败')
      }
    } catch (e) {
      if ((e as Error).message !== '已取消') toast.error((e as Error).message)
    } finally {
      if (seq === seqRef.current) setRerunning(false)
    }
  }

  async function prepare(b: Benchmark) {
    setPreparingId(b.benchmark_id)
    try {
      await apiJson('/api/benchmark/prepare', { method: 'POST', body: JSON.stringify({ benchmark_id: b.benchmark_id }) })
      toast.success('文案补齐完成')
      qc.invalidateQueries({ queryKey: ['benchmark'] })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setPreparingId(0)
    }
  }

  async function analyze(it: BenchUnit) {
    const key = it.key
    setBusyKey('a' + key)
    try {
      const d = await apiJson<{ task_id: number }>('/api/benchmark/analyze', {
        method: 'POST',
        body: JSON.stringify({ title: it.title, text: it.text, key })
      })
      const t = await waitTask(d.task_id, { cancelled: false })
      if (t.status === 'done') {
        const res = JSON.parse(t.result || '{}') as Analysis
        setAnalysisMap((prev) => ({ ...prev, [key]: res }))
        toast.success(res.can ? '分析完成：能讲' : '分析完成：不建议')
      } else {
        toast.error(t.error || '分析失败')
      }
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusyKey('')
    }
  }

  async function doRewrite(b: Benchmark, it: BenchUnit) {
    const key = it.key
    setBusyKey('r' + key)
    try {
      const d = await apiJson<{ task_id: number }>('/api/benchmark/rewrite', {
        method: 'POST',
        body: JSON.stringify({
          title: it.title,
          text: it.text,
          key,
          benchmark_name: b.name,
          post_id: it.post_id,
          work_id: it.work_id ?? undefined,
          tags: it.tags || []
        })
      })
      toast.info('洗稿进行中（双模型讨论）…')
      const t = await waitTask(d.task_id, { cancelled: false })
      if (t.status === 'done') {
        const res = JSON.parse(t.result || '{}')
        if (res.script) {
          setRewrite({
            script: res.script,
            original_script: res.original_script || '',
            draft_id: res.draft_id || 0,
            source_title: res.source_ref?.source_title || res.title || '',
            benchmark_name: res.benchmark_name || b.name
          })
        }
        toast.success(`洗稿完成${res.draft_id ? `，已存草稿 #${res.draft_id}` : ''}`)
      } else {
        toast.error(t.error || '洗稿失败')
      }
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusyKey('')
    }
  }

  const benchmarks = topQ.data?.benchmarks ?? []

  return (
    <motion.div variants={listVariants} initial="initial" animate="animate" className="space-y-4">
      <motion.div variants={itemVariants} className="flex flex-wrap items-center gap-2">
        <Target className="h-4 w-4 text-accent" />
        <span className="text-sm text-muted-foreground">
          每个对标展示 <b className="text-foreground">前2 + 最新一篇</b>（按互动分，广告已过滤）
        </span>
        <span className="flex-1" />
        <Button size="sm" onClick={rerun} disabled={rerunning}>
          {rerunning ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {rerunning ? '重新对标中…' : '重新对标'}
        </Button>
      </motion.div>

      {topQ.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-56 w-full" />
          ))}
        </div>
      ) : !benchmarks.length ? (
        <Card>
          <CardContent className="flex h-40 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
            <Target className="h-6 w-6" />
            还没有对标博主，先去「博主管理」添加
          </CardContent>
        </Card>
      ) : (
        benchmarks.map((b) => (
          <motion.section key={b.benchmark_id} variants={itemVariants}>
            <Card>
              <CardHeader className="flex-row items-center gap-2">
                <CardTitle className="text-base">{b.name}</CardTitle>
                {b.note && <CardDescription className="truncate">{b.note}</CardDescription>}
                <span className="flex-1" />
                <Button variant="outline" size="sm" onClick={() => prepare(b)} disabled={preparingId === b.benchmark_id}>
                  {preparingId === b.benchmark_id ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
                  转写补齐（前2+最新）
                </Button>
              </CardHeader>
              <CardContent>
                {!b.items.length ? (
                  <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
                    暂无作品（先「重新对标」拉取）
                  </div>
                ) : (
                  <div className="grid gap-3 lg:grid-cols-3">
                    {b.items.map((it, idx) => {
                      const ana = analysisMap[it.key]
                      return (
                        <motion.article
                          key={it.key}
                          initial={{ opacity: 0, y: 14 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: idx * 0.07, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                          className="flex flex-col overflow-hidden rounded-lg border border-border bg-card"
                        >
                          {/* R-172：封面框必须固定比例——absolute 的 img 不参与 min-content 计算，
                              否则 flex item 的 min-height:auto 会被竖版封面的原始高度撑开（344×459） */}
                          <div className="relative aspect-[4/3] w-full shrink-0 overflow-hidden bg-muted">
                            {it.cover ? (
                              <img
                                src={it.cover}
                                alt=""
                                loading="lazy"
                                referrerPolicy="no-referrer"
                                className="absolute inset-0 h-full w-full object-cover"
                              />
                            ) : (
                              <div className="flex h-full items-center justify-center text-xs font-semibold text-muted-foreground/60">ECHO</div>
                            )}
                            <div className="absolute left-2 top-2 flex gap-1">
                              {it.platforms.map((p) => (
                                <Badge key={p} variant="secondary" className="bg-black/45 text-white border-transparent backdrop-blur-sm">
                                  {platformName(p)}
                                </Badge>
                              ))}
                            </div>
                            <span className="tnum absolute right-2 top-2 rounded-md bg-black/45 px-1.5 py-0.5 text-[10px] text-white backdrop-blur-sm">
                              互动分 {fmtNum(it.score)}
                            </span>
                          </div>
                          <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
                            <p className="line-clamp-2 text-[13px] font-medium leading-snug">{it.title || '（无标题）'}</p>
                            <div className="tnum flex items-center gap-2.5 text-[11px] text-muted-foreground">
                              <span>👍 {fmtNum(it.likes)}</span>
                              <span>⭐ {fmtNum(it.favorites)}</span>
                              <span>💬 {fmtNum(it.comments)}</span>
                              <span>▶ {fmtNum(it.plays)}</span>
                            </div>
                            {!!it.tags.length && (
                              <div className="flex flex-wrap gap-1">
                                {it.tags.slice(0, 3).map((t) => (
                                  <span key={t} className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{t}</span>
                                ))}
                              </div>
                            )}
                            {it.has_text ? (
                              <details className="rounded-md border border-border bg-muted/40 px-2.5 py-1.5">
                                <summary className="cursor-pointer text-xs text-muted-foreground">查看文案</summary>
                                <p className="mt-1.5 line-clamp-6 whitespace-pre-wrap text-xs leading-relaxed">{it.text}</p>
                              </details>
                            ) : (
                              <p className="text-xs text-muted-foreground/70">暂无文案（点「转写补齐」）</p>
                            )}

                            <AnimatePresence>
                              {ana && (
                                <motion.div
                                  initial={{ opacity: 0, height: 0 }}
                                  animate={{ opacity: 1, height: 'auto' }}
                                  exit={{ opacity: 0, height: 0 }}
                                  className={cn(
                                    'flex items-start gap-1.5 overflow-hidden rounded-md px-2.5 py-1.5 text-xs',
                                    ana.can ? 'bg-[rgba(16,185,129,0.1)] text-success' : 'bg-[rgba(239,68,68,0.08)] text-destructive'
                                  )}
                                >
                                  {ana.can ? <CircleCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <CircleX className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                                  <span className="leading-relaxed">{ana.can ? '能讲' : '不建议'}{ana.reason ? `：${ana.reason}` : ''}</span>
                                </motion.div>
                              )}
                            </AnimatePresence>

                            <div className="mt-auto flex items-center gap-1.5 pt-1">
                              <Button variant="outline" size="sm" className="h-7 text-xs" disabled={busyKey === 'a' + it.key || !it.has_text} onClick={() => analyze(it)}>
                                {busyKey === 'a' + it.key ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                                AI 分析
                              </Button>
                              {ana?.can && (
                                <Button size="sm" className="h-7 text-xs" disabled={busyKey === 'r' + it.key} onClick={() => doRewrite(b, it)}>
                                  {busyKey === 'r' + it.key ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <PenLine className="h-3 w-3" />}
                                  洗稿
                                </Button>
                              )}
                            </div>
                          </div>
                        </motion.article>
                      )
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.section>
        ))
      )}

      <RewriteDiffDialog result={rewrite} open={rewrite !== null} onOpenChange={(v) => !v && setRewrite(null)} />
    </motion.div>
  )
}
