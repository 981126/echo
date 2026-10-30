import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { BarChart3, Check, ChevronDown, ExternalLink, Lightbulb, Loader2, Play, RefreshCw, Settings2, Sparkles, UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import { apiJson } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Progress } from '@/components/ui/progress'
import { BaselineBars, MetricCards, PlanComparisonCharts, SimpleBars, WatchTrendChart } from './charts'
import { waitForReviewTask } from './use-review-task'
import type { Credential, FailedReview, ReferenceItem, Review, Topic, VideoItem } from './types'

const judgementLabels = { fact: '数据直接显示', hypothesis: '结合内容推测', unknown: '目前无法判断' }

export default function VideoReviewPage() {
  const [videos, setVideos] = useState<VideoItem[]>([])
  const [account, setAccount] = useState<{ id: number; nickname: string; avatar?: string } | null>(null)
  const [postId, setPostId] = useState<number>(0)
  const [review, setReview] = useState<Review | null>(null)
  const [failedReview, setFailedReview] = useState<FailedReview | null>(null)
  const [loading, setLoading] = useState(true)
  const [task, setTask] = useState<{ id: number; progress: number; note: string } | null>(null)
  const [credential, setCredential] = useState<Credential | null>(null)
  const [cookieOpen, setCookieOpen] = useState(false)
  const [cookie, setCookie] = useState('')
  const [savingCookie, setSavingCookie] = useState(false)
  const [kind, setKind] = useState<'peer' | 'low_fan'>('peer')
  const [references, setReferences] = useState<ReferenceItem[]>([])
  const [referenceLoading, setReferenceLoading] = useState(false)
  const [keptText, setKeptText] = useState('')
  const [changeOne, setChangeOne] = useState('')
  const [changeTwo, setChangeTwo] = useState('')
  const [linkPostId, setLinkPostId] = useState(0)
  const [bio, setBio] = useState('')
  const [direction, setDirection] = useState('')
  const controller = useRef<AbortController | null>(null)
  const activePost = useRef(0)

  const loadReview = useCallback(async (id: number) => {
    const data = await apiJson<{ review: Review | null; running_task_id?: number | null; failed_review?: FailedReview | null }>(`/api/douyin-review/posts/${id}/latest-review`)
    if (activePost.current !== id) return
    setReview(data.review)
    setFailedReview(data.failed_review ?? null)
    if (data.review?.improvement_plan) {
      setKeptText(data.review.improvement_plan.kept_text)
      setChangeOne(data.review.improvement_plan.changes[0] ?? '')
      setChangeTwo(data.review.improvement_plan.changes[1] ?? '')
      setLinkPostId(data.review.improvement_plan.published_post_id ?? 0)
    }
    if (data.review?.follower_analysis.homepage) {
      setBio(data.review.follower_analysis.homepage.bio ?? '')
      setDirection(data.review.follower_analysis.homepage.direction_note ?? '')
    }
    if (data.running_task_id) setTask((old) => old?.id === data.running_task_id ? old : { id: data.running_task_id!, progress: 5, note: '正在恢复分析进度' })
  }, [])

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
        const data = await apiJson<{ account: { id: number; nickname: string; avatar?: string }; items: VideoItem[]; credential_status: string }>('/api/douyin-review/videos?limit=50')
        setAccount(data.account)
        setVideos(data.items)
        const selected = wanted && data.items.some((x) => x.post_id === wanted) ? wanted : data.items[0]?.post_id ?? 0
        activePost.current = selected
        setPostId(selected)
        if (selected) await loadReview(selected)
        const cred = await apiJson<Credential>(`/api/douyin-review/credentials?account_id=${data.account.id}`)
        setCredential(cred)
        await loadReferences('peer')
      } catch (error) {
        toast.error(error instanceof Error ? error.message : '视频复盘加载失败')
      } finally {
        setLoading(false)
      }
    })()
    return () => controller.current?.abort()
  }, [loadReferences, loadReview])

  async function selectVideo(id: number) {
    activePost.current = id
    setPostId(id)
    setReview(null)
    setFailedReview(null)
    setTask(null)
    await loadReview(id)
  }

  async function analyze(refresh: boolean) {
    if (!postId) return
    try {
      const data = await apiJson<{ task_id: number; review?: Review }>(`/api/douyin-review/analyze`, { method: 'POST', body: JSON.stringify({ post_id: postId, refresh, force: true }) })
      if (data.review) setReview(data.review)
      if (data.task_id) await followTask(data.task_id)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '分析失败')
    }
  }

  async function saveCookie() {
    if (!account || !cookie.trim()) return
    setSavingCookie(true)
    try {
      const result = await apiJson<Credential>('/api/douyin-review/credentials', { method: 'PUT', body: JSON.stringify({ account_id: account.id, cookie }) })
      setCredential(result)
      setCookie('')
      setCookieOpen(false)
      toast.success('抖音创作者数据验证成功')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Cookie验证失败')
    } finally {
      setSavingCookie(false)
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

  async function adopt(topic: Topic) {
    if (!topic.id) return
    const changes = [changeOne.trim(), changeTwo.trim()].filter(Boolean)
    if (!changes.length) {
      toast.error('请先填写这次准备重点修改的1项内容')
      return
    }
    try {
      await apiJson(`/api/douyin-review/recommendations/${topic.id}/adopt`, { method: 'POST', body: JSON.stringify({ kept_text: keptText, changes, target_metrics: [topic.target_metric || 'plays'] }) })
      toast.success('已保存主题和本次修改')
      await loadReview(postId)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败')
    }
  }

  async function savePlan() {
    if (!review?.improvement_plan) return
    const changes = [changeOne.trim(), changeTwo.trim()].filter(Boolean)
    try {
      await apiJson(`/api/douyin-review/plans/${review.improvement_plan.id}`, { method: 'PATCH', body: JSON.stringify({ kept_text: keptText, changes, target_metrics: review.improvement_plan.target_metrics }) })
      toast.success('修改内容已保存')
      await loadReview(postId)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败')
    }
  }

  async function linkPlan() {
    if (!review?.improvement_plan || !linkPostId) return
    try {
      await apiJson(`/api/douyin-review/plans/${review.improvement_plan.id}/link`, { method: 'POST', body: JSON.stringify({ published_post_id: linkPostId, replace: true }) })
      toast.success('已关联新发布视频')
      await loadReview(postId)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '关联失败')
    }
  }

  async function checkPlan() {
    if (!review?.improvement_plan) return
    try {
      const data = await apiJson<{ task_id: number }>(`/api/douyin-review/plans/${review.improvement_plan.id}/check`, { method: 'POST', body: JSON.stringify({ refresh: true }) })
      await waitForReviewTask(data.task_id)
      await loadReview(postId)
      toast.success('修改效果已更新')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '检查失败')
    }
  }

  async function saveHomepage() {
    if (!account || !review) return
    try {
      await apiJson('/api/douyin-review/homepage', { method: 'PUT', body: JSON.stringify({ account_id: account.id, bio, direction_note: direction, pinned_post_ids: review.follower_analysis.homepage.pinned_post_ids ?? [] }) })
      toast.success('主页信息已保存，重新分析后会使用')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败')
    }
  }

  const charts = review?.charts
  const planItems = review?.improvement_plan?.check_result.items ?? charts?.plan ?? []
  const primary = review?.recommendations.primary

  if (loading) return <div className="flex h-64 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  return (
    <motion.div initial={{ opacity: 0.7, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-5 pb-10">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-sm text-muted-foreground">先看懂为什么，再决定下一条拍什么</p>
          <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground"><span className="h-2 w-2 rounded-full bg-indigo-500" />{account?.nickname || '当前抖音账号'} · 只分析抖音</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setCookieOpen(true)}><Settings2 className="mr-2 h-4 w-4" />抖音数据设置</Button>
          <Button variant="outline" disabled={!postId || !!task} onClick={() => void analyze(false)}><BarChart3 className="mr-2 h-4 w-4" />{review ? '重新分析' : '开始分析'}</Button>
          <Button disabled={!postId || !!task} onClick={() => void analyze(true)}><RefreshCw className="mr-2 h-4 w-4" />更新数据并分析</Button>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <label className="text-xs font-medium text-muted-foreground" htmlFor="review-video">选择要复盘的视频</label>
        <div className="mt-2 flex flex-col gap-3 md:flex-row md:items-center">
          <select id="review-video" value={postId} onChange={(e) => void selectVideo(Number(e.target.value))} className="h-10 min-w-0 flex-1 rounded-md border border-input bg-card px-3 text-sm">
            {videos.map((video) => <option key={video.post_id} value={video.post_id}>{video.title || `视频 ${video.post_id}`}</option>)}
          </select>
          {review?.post.video_url && <a href={review.post.video_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-indigo-500 hover:underline">查看原视频<ExternalLink className="h-3 w-3" /></a>}
        </div>
        <div className="mt-2 text-xs text-muted-foreground">最近成功数据时间：{review?.data_time ? new Date(review.data_time).toLocaleString('zh-CN') : '尚未分析'} · {credential?.status === 'valid' ? '创作者数据可用' : '需要检查创作者数据设置'}</div>
      </div>

      {task && <div className="rounded-xl border border-indigo-200 bg-indigo-50/60 p-4 dark:border-indigo-900 dark:bg-indigo-950/30"><div className="mb-2 flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" />{task.note}</div><Progress value={task.progress} /></div>}
      {failedReview && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
        最近一次刷新分析失败：{failedReview.error || '未知错误'}。当前展示的是上一次成功的复盘，旧数据没有被清空。
      </div>}
      {review?.warnings.map((warning) => <div key={warning} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">{warning}</div>)}

      {review ? (
        <>
          <section className="rounded-2xl border border-border bg-gradient-to-br from-indigo-50/70 to-card p-5 shadow-card dark:from-indigo-950/30">
            <div className="flex items-start gap-3"><div className="rounded-lg bg-indigo-100 p-2 text-indigo-600 dark:bg-indigo-900"><Sparkles className="h-5 w-5" /></div><div><h2 className="text-lg font-semibold">{review.summary}</h2><p className="mt-1 text-xs text-muted-foreground">{review.comparison.sample_note} · 实际比较 {review.comparison.count} 条</p></div></div>
          </section>

          <MetricCards metrics={review.metrics} />

          {primary && <section className="rounded-2xl border border-indigo-200 bg-card p-5 shadow-card dark:border-indigo-900">
            <div className="flex items-center gap-2 text-xs font-medium text-indigo-500"><Lightbulb className="h-4 w-4" />下一条最推荐拍这个</div>
            <h2 className="mt-3 text-xl font-semibold">{primary.topic}</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{primary.reason}</p>
            <div className="mt-3 rounded-lg bg-muted/70 p-3 text-sm leading-6"><span className="font-medium">为什么适合你：</span>{primary.fit_reason}</div>
            {primary.opening_line && <div className="mt-3 text-sm"><span className="font-medium">开头第一句：</span>{primary.opening_line}</div>}
            <Button className="mt-4" onClick={() => void adopt(primary)}><Check className="mr-2 h-4 w-4" />采用首选主题</Button>
          </section>}

          {!primary && <section className="rounded-2xl border border-dashed border-border bg-card p-5"><div className="flex items-center gap-2 text-sm font-medium"><Lightbulb className="h-4 w-4 text-muted-foreground" />暂时没有足够依据给出可靠首选</div><p className="mt-2 text-xs leading-5 text-muted-foreground">不会为了凑主题而乱推荐。可以更新低粉爆款、补充视频转写和评论，或先同步更多同行数据。</p></section>}

          {review.findings.length > 0 && <section className="space-y-3">
            <div><h2 className="text-base font-semibold">这条视频为什么好或差？</h2><p className="mt-1 text-xs text-muted-foreground">每条结论都能展开看依据，事实和推测分开写。</p></div>
            <div className="grid gap-3 lg:grid-cols-2">{review.findings.map((finding) => <details key={finding.id} className="group rounded-xl border border-border bg-card p-4 shadow-card"><summary className="cursor-pointer list-none"><div className="flex items-start justify-between gap-3"><h3 className="text-sm font-medium leading-6">{finding.title}</h3><ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" /></div><span className="mt-2 inline-block rounded-full bg-muted px-2 py-1 text-[10px] text-muted-foreground">{judgementLabels[finding.judgement_type]}</span></summary><div className="mt-3 space-y-3 border-t border-border pt-3 text-sm leading-6"><p>{finding.conclusion}</p><p className="rounded-lg bg-indigo-50 p-3 text-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-100"><span className="font-medium">下一条怎么改：</span>{finding.suggestion}</p>{finding.metric_evidence.length > 0 && <div className="text-xs text-muted-foreground"><span className="font-medium">数据依据：</span><pre className="mt-1 max-h-36 overflow-auto whitespace-pre-wrap rounded bg-muted p-2">{JSON.stringify(finding.metric_evidence, null, 2)}</pre></div>}{finding.content_evidence.length > 0 && <div className="text-xs text-muted-foreground"><span className="font-medium">内容依据：</span>{finding.content_evidence.map((x, i) => <blockquote key={i} className="mt-1 border-l-2 border-indigo-300 pl-2">{String(x.text ?? '')}</blockquote>)}</div>}</div></details>)}</div>
          </section>}

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

          {review.recommendations.backups.length > 0 && <section className="rounded-xl border border-border bg-card p-4"><h2 className="text-sm font-semibold">两个备选主题</h2><div className="mt-3 grid gap-3 md:grid-cols-2">{review.recommendations.backups.map((topic) => <div key={topic.id ?? topic.topic} className="rounded-lg border border-border p-3"><h3 className="text-sm font-medium">{topic.topic}</h3><p className="mt-2 text-xs leading-5 text-muted-foreground">{topic.reason}</p>{topic.id && <Button variant="outline" size="sm" className="mt-3" onClick={() => void adopt(topic)}>采用这个备选</Button>}</div>)}</div></section>}

          {review.recommendations.follow_ups.length > 0 && <section className="rounded-xl border border-border bg-card p-4"><h2 className="text-sm font-semibold">首选之后，可以连续讲这3条</h2><div className="mt-3 space-y-3">{review.recommendations.follow_ups.map((topic, index) => <div key={topic.id ?? index} className="flex gap-3 rounded-lg bg-muted/60 p-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-600 dark:bg-indigo-900">{index + 1}</span><div><h3 className="text-sm font-medium">{topic.topic}</h3><p className="mt-1 text-xs text-muted-foreground">{topic.follow_up_role} · {topic.reason}</p></div></div>)}</div></section>}

          <section className="rounded-xl border border-border bg-card p-4 shadow-card"><div className="flex items-center gap-2"><UserPlus className="h-4 w-4 text-indigo-500" /><h2 className="text-sm font-semibold">怎样让观众愿意关注？</h2></div><p className="mt-2 text-sm text-muted-foreground">{review.follower_analysis.homepage.message}</p><div className="mt-3 grid gap-3 md:grid-cols-2"><Textarea value={bio} onChange={(e) => setBio(e.target.value)} placeholder="主页简介：关注你以后能持续看到什么" /><Textarea value={direction} onChange={(e) => setDirection(e.target.value)} placeholder="你的主要内容方向，例如：求职、面试和转行" /></div><Button variant="outline" size="sm" className="mt-3" onClick={() => void saveHomepage()}>保存主页信息</Button></section>

          <section className="rounded-xl border border-border bg-card p-4 shadow-card"><h2 className="text-sm font-semibold">这次准备重点改什么？</h2><p className="mt-1 text-xs text-muted-foreground">最多两项，改太多就无法判断哪项有效。</p><div className="mt-3 grid gap-3"><Input value={keptText} onChange={(e) => setKeptText(e.target.value)} placeholder="这次保留什么？例如：保留这个主题" /><Input value={changeOne} onChange={(e) => setChangeOne(e.target.value)} placeholder="重点修改第1项（必填），例如：开头先给结果" /><Input value={changeTwo} onChange={(e) => setChangeTwo(e.target.value)} placeholder="重点修改第2项（可选）" /></div>{review.improvement_plan && <div className="mt-3 flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => void savePlan()}>保存修改</Button><select value={linkPostId} onChange={(e) => setLinkPostId(Number(e.target.value))} className="h-9 rounded-md border border-input bg-card px-2 text-xs"><option value={0}>选择执行后发布的新视频</option>{videos.filter((x) => x.post_id !== postId).map((x) => <option key={x.post_id} value={x.post_id}>{x.title}</option>)}</select><Button variant="outline" size="sm" disabled={!linkPostId} onClick={() => void linkPlan()}>关联新视频</Button>{review.improvement_plan.published_post_id && <Button size="sm" onClick={() => void checkPlan()}>更新检查结果</Button>}</div>}</section>

          {planItems.length > 0 && <PlanComparisonCharts items={planItems} />}

          {review.new_topics.length > 0 && <section className="rounded-xl border border-border bg-card p-4"><h2 className="text-sm font-semibold">账号可以尝试的新话题</h2><div className="mt-3 grid gap-3 md:grid-cols-3">{review.new_topics.map((topic) => <div key={topic.topic} className="rounded-lg border border-border p-3"><h3 className="text-sm font-medium">{topic.topic}</h3><p className="mt-2 text-xs leading-5 text-muted-foreground">{topic.fit_reason}</p><p className="mt-2 text-xs">{topic.first_step}</p></div>)}</div></section>}
        </>
      ) : !task && <div className="rounded-2xl border border-dashed border-border py-16 text-center"><Play className="mx-auto h-8 w-8 text-muted-foreground" /><h2 className="mt-4 font-medium">选择一条视频，开始第一次复盘</h2><p className="mt-2 text-sm text-muted-foreground">会先保存数据，再给出有依据的原因和下一条主题。</p></div>}

      <section className="space-y-3 border-t border-border pt-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-semibold">同行爆款与低粉爆款</h2><p className="mt-1 text-xs text-muted-foreground">同行只来自你手动添加的对标账号；低粉爆款来自抖音官方标签。</p></div><div className="flex gap-2"><Button variant={kind === 'peer' ? 'default' : 'outline'} size="sm" onClick={() => { setKind('peer'); void loadReferences('peer') }}>同行爆款</Button><Button variant={kind === 'low_fan' ? 'default' : 'outline'} size="sm" onClick={() => { setKind('low_fan'); void loadReferences('low_fan') }}>低粉爆款</Button>{kind === 'low_fan' && <Button variant="outline" size="sm" onClick={() => void refreshLowFan()}><RefreshCw className="mr-1 h-3.5 w-3.5" />更新</Button>}</div></div>
        {referenceLoading ? <div className="py-8 text-center"><Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" /></div> : <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{references.map((item) => <article key={item.id} className="rounded-xl border border-border bg-card p-4 shadow-card"><div className="flex items-start justify-between gap-2"><h3 className="text-sm font-medium leading-6">{item.title}</h3><span className="shrink-0 rounded-full bg-indigo-50 px-2 py-1 text-[10px] text-indigo-600 dark:bg-indigo-950">{item.verdict}</span></div><p className="mt-2 text-xs text-muted-foreground">{item.author_nickname}{item.author_followers !== null && item.author_followers !== undefined ? ` · ${item.author_followers}粉丝` : ''}</p><div className="tnum mt-3 text-xs">播放 {item.plays ?? '暂无'} · 点赞 {item.likes ?? '暂无'} · 评论 {item.comments ?? '暂无'}</div>{item.verdict_evidence.play_multiple && <p className="mt-2 text-xs text-emerald-600">是该同行平时播放的 {item.verdict_evidence.play_multiple} 倍（{item.verdict_evidence.sample_count}条样本）</p>}{item.video_url && <a href={item.video_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs text-indigo-500">查看原视频<ExternalLink className="h-3 w-3" /></a>}</article>)}</div>}
        {!referenceLoading && !references.length && <div className="rounded-lg border border-dashed border-border py-8 text-center text-sm text-muted-foreground">{kind === 'peer' ? '暂无符合规则的同行爆款，请先在博主管理添加抖音同行并同步数据。' : '当前条件下暂无低粉爆款，点击更新获取。'}</div>}
      </section>

      {cookieOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4" onMouseDown={() => setCookieOpen(false)}><motion.div initial={{ opacity: 0.7, y: 10 }} animate={{ opacity: 1, y: 0 }} onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-lg rounded-2xl border border-border bg-card p-5 shadow-xl"><h2 className="text-lg font-semibold">抖音创作者数据设置</h2><p className="mt-2 text-xs leading-5 text-muted-foreground">只用于你本人或已授权账号。Cookie加密保存，不会回显，也不会写入日志、任务或AI分析。</p><div className="mt-4 text-xs">当前状态：{credential?.status === 'valid' ? '可用' : '未设置或已失效'}<br />最近成功：{credential?.last_success_at ? new Date(credential.last_success_at).toLocaleString('zh-CN') : '暂无'}</div><Textarea className="mt-4 min-h-28 font-mono text-xs" value={cookie} onChange={(e) => setCookie(e.target.value)} placeholder="粘贴本人抖音创作者平台 Cookie" /><div className="mt-4 flex justify-end gap-2"><Button variant="outline" onClick={() => setCookieOpen(false)}>关闭</Button><Button disabled={!cookie.trim() || savingCookie} onClick={() => void saveCookie()}>{savingCookie && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}保存并验证</Button></div></motion.div></div>}
    </motion.div>
  )
}
