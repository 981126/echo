import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Check, ChevronDown, ExternalLink, Layers, Lightbulb, Loader2, Play, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { apiJson } from '@/api/client'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { CoverImage } from '@/components/ui/cover-image'
import { Progress } from '@/components/ui/progress'
import { waitTaskResult } from '@/api/task'
import { PostAnalysis } from '@/pages/dashboard/post-analysis'
import type { PostDetail } from '@/pages/dashboard/types'
import { BaselineBars, SimpleBars, WatchTrendChart, formatMetric } from './charts'
import { waitForReviewTask } from './use-review-task'
import type { FailedReview, FindingContentEvidence, FindingMetricEvidence, ReferenceItem, Review, VideoItem } from './types'

const judgementLabels = { fact: '数据直接显示', hypothesis: '结合内容推测', unknown: '目前无法判断' }

/** R-248：归因方向徽标（verdict 由后端按真实指标判定，不交给 AI）。 */
const verdictMeta: Record<string, { label: string; cls: string }> = {
  strength: { label: '好在哪', cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' },
  weak: { label: '差在哪', cls: 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300' },
  neutral: { label: '影响有限', cls: 'bg-muted text-muted-foreground' },
  unknown: { label: '无法判断', cls: 'bg-muted text-muted-foreground' }
}

/** R-248：把结构化指标证据转成可读文字（新分析由程序构造；历史数据字段缺失时降级）。 */
function metricEvidenceText(evidence: FindingMetricEvidence): string {
  if (evidence.time) return `${evidence.time}：留存下降 ${(Number(evidence.drop ?? 0) * 100).toFixed(1)} 个百分点`
  const label = evidence.label || evidence.key || '指标'
  const value = typeof evidence.value === 'number' ? formatMetric(evidence.value, evidence.unit || '') : '暂无数据'
  const extra: string[] = []
  if (typeof evidence.baseline === 'number') extra.push(`自己平时 ${formatMetric(evidence.baseline, evidence.unit || '')}`)
  if (evidence.sample_count) extra.push(`样本 ${evidence.sample_count} 条`)
  return `${label}：${value}${extra.length ? `（${extra.join('，')}）` : ''}`
}

function contentSourceLabel(evidence: FindingContentEvidence): string {
  return evidence.source ? `（${evidence.source}）` : ''
}

/** R-247：采用主题时给生成链路的具体文本（「采用」→ 脚本工作台 AI 草稿）；空字段自动跳过。 */
type AdoptTopic = { topic: string; reason?: string; fit_reason?: string; opening_line?: string; first_step?: string }

function adoptQuerySource(topic: AdoptTopic): string {
  return [topic.topic, topic.reason, topic.fit_reason, topic.opening_line, topic.first_step]
    .map((x) => (x || '').trim())
    .filter(Boolean)
    .join('\n')
}

/** R-249：参考视频封面与抖音主页视频同比例（3:4 竖版），坏图按 CoverImage 兜底不裂图。 */
function ReferenceCover({ url }: { url?: string | null }) {
  return (
    <div className="relative aspect-[3/4] w-full overflow-hidden bg-muted">
      <CoverImage
        url={url}
        alt="参考视频封面"
        className="absolute inset-0 h-full w-full object-cover"
        placeholder={<div className="flex h-full items-center justify-center text-xs font-semibold text-muted-foreground/60">ECHO</div>}
      />
    </div>
  )
}

export default function VideoReviewPage() {
  const [videos, setVideos] = useState<VideoItem[]>([])
  const [account, setAccount] = useState<{ id: number; nickname: string; avatar?: string } | null>(null)
  const [postId, setPostId] = useState<number>(0)
  const [review, setReview] = useState<Review | null>(null)
  // v30：视频复盘第一块直接用数据看板的「视频总览」（趋势 + 指标）替代旧对比卡片
  const [overview, setOverview] = useState<PostDetail | null>(null)
  const [overviewLoading, setOverviewLoading] = useState(false)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [transcribing, setTranscribing] = useState(false)
  const [failedReview, setFailedReview] = useState<FailedReview | null>(null)
  const [loading, setLoading] = useState(true)
  const [task, setTask] = useState<{ id: number; progress: number; note: string } | null>(null)
  const [kind, setKind] = useState<'peer' | 'low_fan'>('peer')
  const [references, setReferences] = useState<ReferenceItem[]>([])
  const [referenceLoading, setReferenceLoading] = useState(false)
  // R-247：采用主题 → 生成草稿；adopting 为被点按钮 key（空=空闲，非空时禁用本页全部采用按钮）
  const [adopting, setAdopting] = useState('')
  const navigate = useNavigate()
  const controller = useRef<AbortController | null>(null)
  const activePost = useRef(0)

  const loadReview = useCallback(async (id: number) => {
    const data = await apiJson<{ review: Review | null; running_task_id?: number | null; failed_review?: FailedReview | null }>(`/api/douyin-review/posts/${id}/latest-review`)
    if (activePost.current !== id) return
    setReview(data.review)
    setFailedReview(data.failed_review ?? null)
    if (data.running_task_id) setTask((old) => old?.id === data.running_task_id ? old : { id: data.running_task_id!, progress: 5, note: '正在恢复分析进度' })
  }, [])

  const loadOverview = useCallback(async (id: number) => {
    if (!id) {
      setOverview(null)
      return
    }
    setOverviewLoading(true)
    try {
      const data = await apiJson<PostDetail>(`/api/douyin-dashboard/works/${id}`)
      if (activePost.current === id) {
        setOverview(data)
        setOverviewError(null)
      }
    } catch (error) {
      if (activePost.current === id) {
        setOverview(null)
        setOverviewError(error instanceof Error ? error.message : '作品数据加载失败')
      }
    } finally {
      setOverviewLoading(false)
    }
  }, [])

  /** v32：文案脚本为空时的 ASR 转写（复用素材库转写任务） */
  async function transcribeOverview() {
    if (!postId) return
    setTranscribing(true)
    try {
      const response = await apiJson<{ task_id?: number }>(`/api/douyin-dashboard/works/${postId}/transcribe`, { method: 'POST' })
      if (response.task_id) await waitTaskResult(response.task_id)
      await loadOverview(postId)
      toast.success('转写完成')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '转写失败')
    } finally {
      setTranscribing(false)
    }
  }

  /** v30：内嵌数据看板卡片上的「更新数据」= 触发该作品数据刷新并重载 */
  async function refreshOverviewData() {
    if (!postId) return
    try {
      const response = await apiJson<{ task_id?: number; skipped?: boolean; reason?: string }>(
        `/api/douyin-dashboard/works/${postId}/refresh`,
        { method: 'POST', body: JSON.stringify({ force: false }) }
      )
      if (response.skipped) toast.info(response.reason || '数据已是最新')
      else if (response.task_id) await waitTaskResult(response.task_id)
      await loadOverview(postId)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '数据更新失败')
    }
  }

  const followTask = useCallback(async (taskId: number) => {
    controller.current?.abort()
    const current = new AbortController()
    controller.current = current
    setTask({ id: taskId, progress: 5, note: '正在准备分析' })
    try {
      const result = await waitForReviewTask(taskId, current.signal)
      setTask(null)
      if (activePost.current) await loadReview(activePost.current)
      return result
    } catch (error) {
      setTask(null)
      if (!current.signal.aborted) toast.error(error instanceof Error ? error.message : '任务失败')
      throw error
    }
  }, [loadReview])

  const loadReferences = useCallback(async (selectedKind: 'peer' | 'low_fan') => {
    setReferenceLoading(true)
    try {
      const data = await apiJson<{ items: ReferenceItem[] }>(`/api/douyin-review/references?kind=${selectedKind}&limit=20`)
      setReferences(data.items)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '参考视频加载失败')
    } finally {
      setReferenceLoading(false)
    }
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        const params = new URLSearchParams(location.hash.split('?')[1] ?? '')
        const wanted = Number(params.get('post') || 0)
        const data = await apiJson<{ account: { id: number; nickname: string; avatar?: string }; items: VideoItem[]; credential_status: string; credential?: Credential | null }>('/api/douyin-review/videos?limit=50')
        setAccount(data.account)
        setVideos(data.items)
        const selected = wanted && data.items.some((x) => x.post_id === wanted) ? wanted : data.items[0]?.post_id ?? 0
        activePost.current = selected
        setPostId(selected)
        // R-243：review 与 references 无数据依赖 → 首屏并行请求（loadReferences 内部自行兜住错误，
        // loadReview 失败仍由外层 catch 统一提示，错误语义不变）。
        if (selected) {
          await Promise.all([loadReview(selected), loadReferences('peer'), loadOverview(selected)])
        } else {
          await loadReferences('peer')
        }
      } catch (error) {
        toast.error(error instanceof Error ? error.message : '视频复盘加载失败')
      } finally {
        setLoading(false)
      }
    })()
    return () => controller.current?.abort()
  }, [loadOverview, loadReferences, loadReview])

  async function selectVideo(id: number) {
    activePost.current = id
    setPostId(id)
    setReview(null)
    setFailedReview(null)
    setTask(null)
    await Promise.all([loadReview(id), loadOverview(id)])
  }

  async function analyze(refresh: boolean) {
    if (!postId) return
    try {
      const data = await apiJson<{ task_id: number; review?: Review }>(`/api/douyin-review/analyze`, {
        method: 'POST',
        body: JSON.stringify({ post_id: postId, refresh, force: true })
      })
      if (data.review) setReview(data.review)
      const analysisResult = data.task_id ? await followTask(data.task_id) : null
      let mediaTaskId = 0
      try {
        mediaTaskId = Number(JSON.parse(analysisResult?.result || '{}').media_task_id || 0)
      } catch {
        mediaTaskId = 0
      }
      await loadOverview(postId)
      // v35：刷新时后端已提交「视频下载 + ASR 转写」任务；等它完成后再用文案重新分析一次
      if (mediaTaskId) {
        setTask({ id: mediaTaskId, progress: 5, note: '正在下载视频并转写文案…' })
        try {
          await waitTaskResult(mediaTaskId)
          setTask(null)
          await loadOverview(postId)
          toast.info('视频与文案已补齐，正在用文案重新分析…')
          await analyze(false)
        } catch (mediaError) {
          setTask(null)
          toast.error(mediaError instanceof Error ? `视频/转写任务失败：${mediaError.message}` : '视频/转写任务失败')
        }
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '分析失败')
    }
  }

  async function refreshLowFan() {
    try {
      const data = await apiJson<{ task_id: number }>('/api/douyin-review/references/refresh', { method: 'POST', body: JSON.stringify({ date_window: 168, limit: 20, keyword: '' }) })
      await waitForReviewTask(data.task_id)
      await loadReferences('low_fan')
      toast.success('低粉爆款已更新')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新失败')
    }
  }

  /** R-247：「采用」= 在脚本工作台生成一篇 AI 草稿（占位稿立即创建，后台双模型讨论），成功后跳过去打开它。 */
  async function adoptTopic(topic: AdoptTopic, key: string) {
    const title = (topic.topic || '').trim()
    if (!title || adopting) return
    setAdopting(key)
    try {
      const data = await apiJson<{ task_id: number; draft_id: number }>('/api/drafts/generate-async', {
        method: 'POST',
        body: JSON.stringify({ topic: title, query_source: adoptQuerySource(topic) })
      })
      toast.success(`已开始生成《${title}》，去脚本工作台查看`)
      navigate(`/drafts?id=${data.draft_id}`)
    } catch (error) {
      setAdopting('')
      toast.error(error instanceof Error ? error.message : '生成失败，请重试')
    }
  }

  const charts = review?.charts
  const primary = review?.recommendations.primary
  const backups = review?.recommendations.backups ?? []
  // R-248：可比较样本 < 5 时提示「原因仅供参考，不能当成整体好坏结论」
  const metricSamples = (review?.metrics ?? []).filter((m) => !m.missing && m.value !== null && m.sample_count > 0).map((m) => m.sample_count)
  const dataThin = metricSamples.length > 0 && Math.min(...metricSamples) < 5
  const minMetricSample = metricSamples.length > 0 ? Math.min(...metricSamples) : 0

  if (loading) return <div className="flex h-64 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  return (
    <motion.div initial={{ opacity: 0.7, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-5 pb-10">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-sm text-muted-foreground">先看懂为什么，再决定下一条拍什么</p>
          <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground"><span className="h-2 w-2 rounded-full bg-indigo-500" />{account?.nickname || '当前抖音账号'} · 只分析抖音</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={!postId || !!task} onClick={() => void analyze(true)}><RefreshCw className="mr-2 h-4 w-4" />更新数据并分析</Button>
        </div>
      </div>

      {task && <div className="rounded-xl border border-indigo-200 bg-indigo-50/60 p-4 dark:border-indigo-900 dark:bg-indigo-950/30"><div className="mb-2 flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" />{task.note}</div><Progress value={task.progress} /></div>}
      {failedReview && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
        最近一次刷新分析失败：{failedReview.error || '未知错误'}。当前展示的是上一次成功的复盘，旧数据没有被清空。
      </div>}
      {/* v30：第一块直接用数据看板的「视频总览」（趋势 + 指标）替代旧对比卡片 */}
      {postId ? (
        overview ? (
          <PostAnalysis
            detail={overview}
            refreshing={overviewLoading}
            refreshError={null}
            onRefresh={() => void refreshOverviewData()}
            onRefreshComments={() => void refreshOverviewData()}
            onOpenVideoReview={() => {}}
            showVideoReviewLink={false}
            showRefreshButton={false}
            showTranscriptHint
            videoOptions={videos.map((video) => ({
              post_id: video.post_id,
              title: video.title,
              cover_url: video.cover_url ?? null,
              plays: video.plays ?? null,
              likes: video.likes ?? null,
              favorites: video.favorites ?? null,
              shares: video.shares ?? null,
              status_label: video.status_label ?? null
            }))}
            onSelectVideo={(id) => void selectVideo(id)}
            onTranscribe={() => void transcribeOverview()}
            transcribing={transcribing}
          />
        ) : overviewLoading ? (
          <div className="flex h-40 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">数据看板暂无这条作品的数据{overviewError ? `：${overviewError}` : ''}</p>
        )
      ) : null}

      {review ? (
        <>
          {review.findings.length > 0 && <section className="space-y-3">
            <div>
              <h2 className="text-base font-semibold">这条视频为什么好或差？</h2>
              <p className="mt-1 text-xs text-muted-foreground">每条结论都能展开看依据；方向由真实指标判定，事实和推测分开写。</p>
              {dataThin && <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">部分指标可比较样本仅 {minMetricSample} 条（较少），以下原因仅供参考，不能当成整体好坏结论。</p>}
            </div>
            <div className="grid gap-3 lg:grid-cols-2">{review.findings.map((finding) => (
              <details key={finding.id} className="group rounded-xl border border-border bg-card p-4 shadow-card">
                <summary className="cursor-pointer list-none">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="text-sm font-medium leading-6">{finding.title}</h3>
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {!!finding.verdict && verdictMeta[finding.verdict] && <span className={cn('rounded-full px-2 py-1 text-[10px]', verdictMeta[finding.verdict].cls)}>{verdictMeta[finding.verdict].label}</span>}
                    <span className="rounded-full bg-muted px-2 py-1 text-[10px] text-muted-foreground">{judgementLabels[finding.judgement_type]}</span>
                  </div>
                </summary>
                <div className="mt-3 space-y-3 border-t border-border pt-3 text-sm leading-6">
                  <p className="whitespace-pre-wrap">{finding.conclusion}</p>
                  <p className="rounded-lg bg-indigo-50 p-3 text-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-100"><span className="font-medium">下一条怎么改：</span>{finding.suggestion}</p>
                  {finding.metric_evidence.length > 0 && <div className="text-xs text-muted-foreground">
                    <span className="font-medium">数据依据：</span>
                    <ul className="mt-1 list-disc space-y-1 pl-5">{finding.metric_evidence.map((evidence, index) => <li key={evidence.evidence_id || index}>{metricEvidenceText(evidence)}</li>)}</ul>
                  </div>}
                  {finding.content_evidence.length > 0 && <div className="text-xs text-muted-foreground">
                    <span className="font-medium">内容依据：</span>
                    {finding.content_evidence.map((evidence, index) => <blockquote key={evidence.evidence_id || index} className="mt-1 border-l-2 border-indigo-300 pl-2">{evidence.text ?? ''}<span className="ml-1 opacity-70">{contentSourceLabel(evidence)}</span></blockquote>)}
                  </div>}
                </div>
              </details>
            ))}</div>
          </section>}

          {review.advices.length > 0 && <section className="space-y-3">
            <div><h2 className="text-base font-semibold">按指标优化建议</h2><p className="mt-1 text-xs text-muted-foreground">结合这条视频的指标差距和文案原句，按每个指标给出具体改法。</p></div>
            <div className="grid gap-3 lg:grid-cols-2">{review.advices.map((advice) => (
              <article key={advice.dimension} className="rounded-xl border border-border bg-card p-4 shadow-card">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-sm font-medium leading-6">{advice.title}</h3>
                  <span className="shrink-0 rounded-full bg-muted px-2 py-1 text-[10px] text-muted-foreground">{judgementLabels[advice.judgement_type]}</span>
                </div>
                <p className="mt-2 rounded-lg bg-muted/70 p-2 text-xs leading-5 text-muted-foreground">{advice.gap}</p>
                <div className="mt-3 space-y-3 text-sm leading-6">
                  <div>
                    <span className="font-medium">原因：</span>
                    <ul className="mt-1 list-disc space-y-1 pl-5">{advice.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                  </div>
                  <div>
                    <span className="font-medium">具体怎么做：</span>
                    <ol className="mt-1 list-decimal space-y-1 pl-5">{advice.actions.map((action) => <li key={action}>{action}</li>)}</ol>
                  </div>
                  {advice.copy_refs.length > 0 && <div className="text-xs text-muted-foreground">
                    <span className="font-medium">文案依据：</span>
                    {advice.copy_refs.map((ref) => <blockquote key={ref} className="mt-1 border-l-2 border-indigo-300 pl-2">{ref}</blockquote>)}
                  </div>}
                  {overview && !overview.transcript.available && <p className="text-xs text-amber-700 dark:text-amber-300">没有文案转写，本次建议只基于指标；转写后可结合文案分析。</p>}
                </div>
              </article>
            ))}</div>
          </section>}

          {/* R-248：首选与两个备选同排；两卡等高、标题行统一、底部对齐（缺一侧单列占整行，窄屏堆叠） */}
          <div className={cn('grid gap-4', primary && backups.length > 0 && 'lg:grid-cols-2')}>
            {primary ? (
              <section className="flex h-full flex-col rounded-2xl border border-indigo-200 bg-card p-5 shadow-card dark:border-indigo-900">
                <div className="flex h-6 items-center gap-2 text-xs font-medium text-indigo-500"><Lightbulb className="h-4 w-4" />下一条最推荐拍这个</div>
                <h2 className="mt-3 text-xl font-semibold">{primary.topic}</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{primary.reason}</p>
                <div className="mt-3 rounded-lg bg-muted/70 p-3 text-sm leading-6"><span className="font-medium">为什么适合你：</span>{primary.fit_reason}</div>
                {primary.opening_line && <div className="mt-3 text-sm"><span className="font-medium">开头第一句：</span>{primary.opening_line}</div>}
                <div className="mt-auto pt-4">
                  <Button disabled={!!adopting} onClick={() => void adoptTopic(primary, 'primary')}>
                    {adopting === 'primary' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}
                    {adopting === 'primary' ? '生成中…' : '采用'}
                  </Button>
                </div>
              </section>
            ) : (
              <section className="rounded-2xl border border-dashed border-border bg-card p-5"><div className="flex items-center gap-2 text-sm font-medium"><Lightbulb className="h-4 w-4 text-muted-foreground" />暂时没有足够依据给出可靠首选</div><p className="mt-2 text-xs leading-5 text-muted-foreground">不会为了凑主题而乱推荐。可以更新低粉爆款、补充视频转写和评论，或先同步更多同行数据。</p></section>
            )}

            {backups.length > 0 && (
              <section className="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-card">
                <div className="flex h-6 items-center gap-2 text-xs font-medium text-indigo-500"><Layers className="h-4 w-4" />两个备选主题</div>
                <div className="mt-3 flex flex-1 flex-col gap-3">
                  {backups.map((topic, index) => {
                    const key = `backup-${topic.id ?? index}`
                    return (
                      <div key={key} className="flex flex-1 flex-col rounded-lg border border-border p-3">
                        <h3 className="text-sm font-medium">{topic.topic}</h3>
                        <p className="mt-2 text-xs leading-5 text-muted-foreground">{topic.reason}</p>
                        <div className="mt-auto pt-3">
                          <Button variant="outline" size="sm" disabled={!!adopting} onClick={() => void adoptTopic(topic, key)}>
                            {adopting === key && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                            {adopting === key ? '生成中…' : '采用'}
                          </Button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>
            )}
          </div>

          {charts && <div className="grid gap-4 xl:grid-cols-2">
            <BaselineBars metrics={(charts.comparison ?? []).filter((x) => ['plays', 'like_rate', 'finish_rate', 'follower_per_1k'].includes(x.key))} />
            <WatchTrendChart data={charts.retention} />
          </div>}

          {(charts?.traffic?.length ?? 0) > 0 && <div className="grid gap-4 xl:grid-cols-2">
            <SimpleBars title="观众主要从哪里来？" unit="%" items={(charts?.traffic ?? []).map((x) => ({ label: x.name, value: Number((x.ratio * 100).toFixed(1)), detail: '占比' }))} />
            <SimpleBars title="哪些搜索词带来观看？" unit="%" items={(charts?.search_terms ?? []).map((x) => ({ label: x.term || x.keyword || '未知搜索词', value: x.value, detail: '占比' }))} />
          </div>}

          {(charts?.comment_questions?.length ?? 0) > 0 && <SimpleBars title="观众反复在问什么？" conclusion="点击数据表可查看问题人数；原评论保存在分析依据中。" items={(charts?.comment_questions ?? []).map((x) => ({ label: x.group_title, value: x.commenter_count, detail: `人 · ${x.likes}赞` }))} unit="" />}

          {(charts?.follower_topics?.length ?? 0) > 0 && <SimpleBars title="哪类内容更容易带来关注？" conclusion="同时看粉丝增量和样本数，不只看播放量。" unit="人" items={(charts?.follower_topics ?? []).map((x) => ({ label: x.topic, value: Number((x.follower_per_1k ?? 0).toFixed(1)), detail: `/千次播放 · 实际涨粉${x.follower_gain}人` }))} />}

          {review.recommendations.follow_ups.length > 0 && <section className="rounded-xl border border-border bg-card p-4"><h2 className="text-sm font-semibold">首选之后，可以连续讲这3条</h2><div className="mt-3 space-y-3">{review.recommendations.follow_ups.map((topic, index) => <div key={topic.id ?? index} className="flex gap-3 rounded-lg bg-muted/60 p-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-600 dark:bg-indigo-900">{index + 1}</span><div><h3 className="text-sm font-medium">{topic.topic}</h3><p className="mt-1 text-xs text-muted-foreground">{topic.follow_up_role} · {topic.reason}</p></div></div>)}</div></section>}

          {review.new_topics.length > 0 && <section className="rounded-xl border border-border bg-card p-4"><h2 className="text-sm font-semibold">账号可以尝试的新话题</h2><div className="mt-3 grid gap-3 md:grid-cols-3">{review.new_topics.map((topic, index) => {
            const key = `new-${index}`
            return <div key={key} className="rounded-lg border border-border p-3"><h3 className="text-sm font-medium">{topic.topic}</h3><p className="mt-2 text-xs leading-5 text-muted-foreground">{topic.fit_reason}</p><p className="mt-2 text-xs">{topic.first_step}</p><Button variant="outline" size="sm" className="mt-3" disabled={!!adopting} onClick={() => void adoptTopic(topic, key)}>{adopting === key && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}{adopting === key ? '生成中…' : '采用'}</Button></div>
          })}</div></section>}
        </>
      ) : !task && <div className="rounded-2xl border border-dashed border-border py-16 text-center"><Play className="mx-auto h-8 w-8 text-muted-foreground" /><h2 className="mt-4 font-medium">还没有这条视频的复盘分析</h2><p className="mt-2 text-sm text-muted-foreground">点右上角「更新数据并分析」，会先保存数据，再给出有依据的原因和下一条主题。</p></div>}

      <section className="space-y-3 border-t border-border pt-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-semibold">同行爆款与低粉爆款</h2><p className="mt-1 text-xs text-muted-foreground">同行只来自你手动添加的对标账号；低粉爆款只显示与你主赛道相关的视频，点「更新」重新抓取。</p></div><div className="flex gap-2"><Button variant={kind === 'peer' ? 'default' : 'outline'} size="sm" onClick={() => { setKind('peer'); void loadReferences('peer') }}>同行爆款</Button><Button variant={kind === 'low_fan' ? 'default' : 'outline'} size="sm" onClick={() => { setKind('low_fan'); void loadReferences('low_fan') }}>低粉爆款</Button>{kind === 'low_fan' && <Button variant="outline" size="sm" onClick={() => void refreshLowFan()}><RefreshCw className="mr-1 h-3.5 w-3.5" />更新</Button>}</div></div>
        {referenceLoading ? <div className="py-8 text-center"><Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" /></div> : <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{references.map((item) => <article key={item.id} className="overflow-hidden rounded-xl border border-border bg-card shadow-card"><ReferenceCover url={item.cover_url} /><div className="p-4"><div className="flex items-start justify-between gap-2"><h3 className="text-sm font-medium leading-6">{item.title}</h3><span className="shrink-0 rounded-full bg-indigo-50 px-2 py-1 text-[10px] text-indigo-600 dark:bg-indigo-950">{item.verdict}</span></div><p className="mt-2 text-xs text-muted-foreground">{item.author_nickname}{item.author_followers !== null && item.author_followers !== undefined ? ` · ${item.author_followers}粉丝` : ''}</p><div className="tnum mt-3 text-xs">播放 {item.plays ?? '暂无'} · 点赞 {item.likes ?? '暂无'} · 评论 {item.comments ?? '暂无'}</div>{item.verdict_evidence.play_multiple && <p className="mt-2 text-xs text-emerald-600">是该同行平时播放的 {item.verdict_evidence.play_multiple} 倍（{item.verdict_evidence.sample_count}条样本）</p>}{item.video_url && <a href={item.video_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs text-indigo-500">查看原视频<ExternalLink className="h-3 w-3" /></a>}</div></article>)}</div>}
        {!referenceLoading && !references.length && <div className="rounded-lg border border-dashed border-border py-8 text-center text-sm text-muted-foreground">{kind === 'peer' ? '暂无符合规则的同行爆款，请先在博主管理添加抖音同行并同步数据。' : '当前方向下暂无低粉爆款，点「更新」获取。'}</div>}
      </section>

    </motion.div>
  )
}
