import { useCallback, useEffect, useState } from 'react'
import { Link2, Loader2, RefreshCw, Unlink } from 'lucide-react'
import { apiJson } from '@/api/client'
import { toast } from '@/components/ui/toaster'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Draft } from './types'

/** R-267：草稿发布区——绑定云端作品、回填效果。 */
type Candidate = {
  post_id: number
  platform: string
  title: string
  publish_time?: string | null
  plays?: number | null
  video_id?: number | null
  has_local_video?: boolean
}

type MetricItem = {
  value?: number | null
  baseline?: number | null
  percentile?: number | null
  sample_count?: number
  unit?: string
  missing?: boolean
}

type Performance = {
  post_id?: number
  platform?: string
  post_title?: string
  published_at?: string | null
  private_metrics?: boolean
  baseline_note?: string
  data_time?: string | null
  refreshed_at?: string
  metrics?: Record<string, MetricItem>
}

const METRIC_LABELS: Array<[string, string]> = [
  ['plays', '播放'],
  ['likes', '点赞'],
  ['favorites', '收藏'],
  ['comments', '评论'],
  ['shares', '转发'],
  ['finish_5s_rate', '5 秒完播'],
  ['bounce_2s_rate', '2 秒跳出'],
  ['finish_rate', '完整完播'],
  ['avg_view_proportion', '平均播放占比']
]

function fmt(value?: number | null, unit?: string): string {
  if (value === null || value === undefined) return '—'
  if (unit === 'ratio') return `${(value * 100).toFixed(1)}%`
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(1)}w`
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function fmtTime(iso?: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function PublishPanel({ draft, onChanged }: { draft: Draft; onChanged: () => void }) {
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<string>('')
  const [perf, setPerf] = useState<Performance | null>((draft.performance as Performance) || null)
  const [busy, setBusy] = useState(false)
  const [loadingList, setLoadingList] = useState(false)

  const loadCandidates = useCallback(async (keyword: string) => {
    setLoadingList(true)
    try {
      const data = await apiJson<{ items: Candidate[] }>(
        `/api/drafts/publish-candidates?limit=20&query=${encodeURIComponent(keyword)}`
      )
      setCandidates(data.items || [])
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setLoadingList(false)
    }
  }, [])

  useEffect(() => {
    if (draft.post_id) return
    void loadCandidates('')
  }, [draft.post_id, loadCandidates])

  const bind = useCallback(async () => {
    if (!selected) return
    setBusy(true)
    try {
      const data = await apiJson<{ performance: Performance }>(`/api/drafts/${draft.id}/publish`, {
        method: 'POST',
        body: JSON.stringify({ post_id: Number(selected) })
      })
      setPerf(data.performance)
      setSelected('')
      toast.success('已绑定作品，效果已回填')
      onChanged()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [draft.id, onChanged, selected])

  const unbind = useCallback(async () => {
    setBusy(true)
    try {
      await apiJson(`/api/drafts/${draft.id}/publish`, { method: 'DELETE' })
      setPerf(null)
      toast.success('已解除绑定')
      onChanged()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [draft.id, onChanged])

  const refresh = useCallback(async () => {
    setBusy(true)
    try {
      const data = await apiJson<{ performance: Performance | null }>(`/api/drafts/${draft.id}/publish?refresh=true`)
      setPerf(data.performance)
      toast.success('效果已刷新')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [draft.id])

  if (draft.post_id) {
    const metrics = perf?.metrics || {}
    return (
      <section className="rounded-xl border border-border bg-muted/40 p-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Link2 className="h-3.5 w-3.5 text-emerald-600" />
          <span className="font-medium">已绑定作品</span>
          <span className="truncate text-muted-foreground" title={perf?.post_title || ''}>
            {perf?.post_title || `#${draft.post_id}`}
          </span>
          <span className="rounded-full bg-background px-2 py-0.5">{perf?.platform || draft.publish_platform || '—'}</span>
          {perf?.published_at && <span className="text-muted-foreground">{fmtTime(perf.published_at)}</span>}
          <span className="flex-1" />
          <Button variant="ghost" size="sm" className="h-11 px-2 text-xs md:h-7" disabled={busy} onClick={() => void refresh()}>
            {busy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1 h-3.5 w-3.5" />}刷新
          </Button>
          <Button variant="ghost" size="sm" className="h-11 px-2 text-xs md:h-7" disabled={busy} onClick={() => void unbind()}>
            <Unlink className="mr-1 h-3.5 w-3.5" />解除绑定
          </Button>
        </div>
        {perf?.private_metrics === false && (
          <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">该作品没有创作者数据，只有公开互动。</p>
        )}
        <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-3">
          {METRIC_LABELS.filter(([key]) => !(metrics[key]?.missing ?? true)).map(([key, label]) => (
            <div key={key} className="rounded-lg bg-background px-2 py-1.5 text-xs">
              <div className="flex items-baseline justify-between gap-1">
                <span className="text-muted-foreground">{label}</span>
                <span className="tnum font-medium">{fmt(metrics[key]?.value, metrics[key]?.unit)}</span>
              </div>
              <div className="mt-0.5 text-[10px] text-muted-foreground">
                你平时 {fmt(metrics[key]?.baseline, metrics[key]?.unit)}
                {metrics[key]?.sample_count ? ` · 样本 ${metrics[key]?.sample_count} 条` : ''}
              </div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground">
          {perf?.baseline_note || ''}
          {perf?.data_time ? ` · 数据于 ${fmtTime(perf.data_time)}` : ''}
        </p>
      </section>
    )
  }

  return (
    <section className="rounded-xl border border-dashed border-border p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Link2 className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="font-medium">标记已发布</span>
        <span className="text-muted-foreground">选发布的作品，系统会回填播放/完播/留存</span>
      </div>
      <div className="mt-2 flex flex-col gap-2 md:flex-row">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="按标题搜索作品"
          className="h-9 md:max-w-[220px]"
          onKeyDown={(e) => {
            if (e.key === 'Enter') void loadCandidates(query)
          }}
        />
        <Select value={selected} onValueChange={setSelected}>
          <SelectTrigger className="h-9 flex-1">
            <SelectValue placeholder={loadingList ? '加载中…' : candidates.length ? '选择作品' : '没有找到作品'} />
          </SelectTrigger>
          <SelectContent>
            {candidates.map((item) => (
              <SelectItem key={item.post_id} value={String(item.post_id)}>
                {item.title || `#${item.post_id}`} · {item.publish_time?.slice(0, 10) || '未知日期'}
                {item.plays != null ? ` · 播放 ${item.plays}` : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button size="sm" className="h-9" disabled={!selected || busy} onClick={() => void bind()}>
          {busy && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}标记已发布
        </Button>
      </div>
    </section>
  )
}
