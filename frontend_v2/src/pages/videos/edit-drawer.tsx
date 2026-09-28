import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ImagePlus,
  Trash2,
  Play,
  Upload,
  RefreshCw,
  LoaderCircle,
  Mic,
  Sparkles,
  FileText,
  Save,
  X
} from 'lucide-react'
import { apiJson, uploadFile } from '@/api/client'
import { platformName } from '@/lib/format'
import { Drawer, DrawerHeader, DrawerTitle, DrawerBody, DrawerFooter } from '@/components/ui/drawer'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectValue, SelectTrigger, SelectContent, SelectItem } from '@/components/ui/select'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toaster'
import { MediaComments } from './media-comments'
import { hasRealFile, type VideoItem } from './types'

const LINK_PLATFORMS = ['douyin', 'bilibili', 'xiaohongshu'] as const
const MAIN_TOPICS = ['求职', '面试', '赚钱', '知识', '其他']
const PLATFORMS = ['douyin', 'xiaohongshu', 'bilibili']

interface Transcript {
  source_text: string
  transcript_text: string
  corrected_text: string
  asr_status: string
  asr_provider: string
  asr_model: string
}

interface PlatformLink {
  platform: string
  platform_post_id: string
  post_id?: number | null
  url: string
  publish_time?: string | null
}

interface VideoDetail extends VideoItem {
  transcript?: Transcript | null
  platform_links: PlatformLink[]
}

interface DraftLink {
  id: number
  title?: string
}

export interface EditState {
  title: string
  platforms: string[]
  status: string
  is_ad: boolean
  adPrice: number | null
  plannedTs: string
  publishedTs: string
  tagsText: string
  sourceText: string
  links: Record<string, string>
}

function toLocalTs(s?: string | null): string {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fromLocalTs(s: string): string | null {
  return s ? new Date(s).toISOString() : null
}

export function EditDrawer({
  videoId,
  open,
  onClose,
  onSaved,
  currentCreatorId,
  onPlay,
  onRewrite,
  rewriting
}: {
  videoId: number | null
  open: boolean
  onClose: () => void
  onSaved: () => void
  currentCreatorId: number
  onPlay: (videoId: number, title: string) => void
  onRewrite: (videoId: number) => void
  rewriting: boolean
}) {
  const navigate = useNavigate()
  const [detail, setDetail] = useState<VideoDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [drafts, setDrafts] = useState<DraftLink[]>([])
  const [state, setState] = useState<EditState | null>(null)
  const [orig, setOrig] = useState<EditState | null>(null)
  const [saving, setSaving] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [videoUploading, setVideoUploading] = useState(false)
  const [confirmRemoveVideo, setConfirmRemoveVideo] = useState(false)
  const [confirmRemoveCover, setConfirmRemoveCover] = useState(false)

  const isNonMain = !!currentCreatorId && !!detail?.creator_id && detail.creator_id !== currentCreatorId

  useEffect(() => {
    if (!open || !videoId) return
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const d = await apiJson<VideoDetail>(`/api/videos/${videoId}`)
        if (cancelled) return
        setDetail(d)
        const links: Record<string, string> = { douyin: '', bilibili: '', xiaohongshu: '' }
        ;(d.platform_links || []).forEach((x) => {
          if (x.platform in links && x.url) links[x.platform] = x.url
        })
        const st: EditState = {
          title: d.title || '',
          platforms: [...(d.platforms || [])],
          status: d.status || 'planned',
          is_ad: !!d.is_ad,
          adPrice: d.ad_price == null ? null : Number(d.ad_price),
          plannedTs: toLocalTs(d.planned_publish_at),
          publishedTs: toLocalTs(d.published_at),
          tagsText: [...new Set([...(d.main_topics || []), ...(d.tags || [])])].join(', '),
          sourceText: d.transcript?.source_text || '',
          links
        }
        setState(st)
        setOrig(JSON.parse(JSON.stringify(st)))
      } catch (e) {
        toast.error((e as Error).message)
      } finally {
        if (!cancelled) setLoading(false)
      }
      try {
        const ds = await apiJson<DraftLink[]>(`/api/drafts?video_id=${videoId}&limit=20`)
        if (!cancelled) setDrafts(Array.isArray(ds) ? ds : [])
      } catch {
        /* 忽略 */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open, videoId])

  // 转写轮询
  useEffect(() => {
    if (!transcribing || !videoId) return
    let tries = 0
    const timer = setInterval(async () => {
      tries += 1
      try {
        const d = await apiJson<VideoDetail>(`/api/videos/${videoId}`)
        const t = d.transcript
        if (t?.transcript_text) {
          setDetail(d)
          setTranscribing(false)
          toast.success('语音转文字完成')
        } else if (t?.asr_status === 'failed') {
          setTranscribing(false)
          toast.error('语音转文字失败，请重试')
        } else if (tries > 120) {
          setTranscribing(false)
          toast.info('仍在识别中，完成后会在通知里提醒')
        }
      } catch {
        /* 抖动继续 */
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [transcribing, videoId])

  const commentPosts = useMemo(
    () => (detail?.platform_links || []).map((x) => ({ id: x.post_id, platform: x.platform })),
    [detail]
  )

  if (!open) return null

  async function applyLinks(): Promise<void> {
    if (!state || !orig || !videoId) return
    const links: Record<string, string> = {}
    for (const p of LINK_PLATFORMS) {
      const v = (state.links[p] || '').trim()
      const prev = (orig.links[p] || '').trim()
      if (v && v !== prev) links[p] = v
    }
    if (!Object.keys(links).length) return
    const r = await apiJson<{ errors?: string[] }>(`/api/platform/videos/${videoId}/bind-links`, {
      method: 'POST',
      body: JSON.stringify({ links })
    })
    if (r?.errors?.length) toast.warning('部分链接未绑定：' + r.errors.join('；'))
    setOrig({ ...orig, links: { ...orig.links } })
  }

  async function save() {
    if (!state || !orig || !videoId) return
    setSaving(true)
    try {
      const body: Record<string, unknown> = {}
      if (state.title !== orig.title) body.title = state.title
      if (state.platforms.join() !== orig.platforms.join()) body.platforms = state.platforms
      if (state.status !== orig.status) body.status = state.status
      if (state.is_ad !== orig.is_ad) body.is_ad = state.is_ad
      if (state.plannedTs !== orig.plannedTs) body.planned_publish_at = fromLocalTs(state.plannedTs)
      if (state.publishedTs !== orig.publishedTs) body.published_at = fromLocalTs(state.publishedTs)
      if (state.tagsText !== orig.tagsText) {
        const parts = state.tagsText.split(/[,，]/).map((x) => x.trim()).filter(Boolean)
        body.main_topics = parts.filter((x) => MAIN_TOPICS.includes(x))
        body.tags = parts.filter((x) => !MAIN_TOPICS.includes(x))
      }
      if (state.sourceText !== orig.sourceText) body.source_text = state.sourceText || null
      if ((state.adPrice ?? null) !== (orig.adPrice ?? null))
        body.ad_price = state.adPrice == null ? null : Number(state.adPrice)
      await apiJson(`/api/videos/${videoId}`, { method: 'PATCH', body: JSON.stringify(body) })
      try {
        await applyLinks()
      } catch (e) {
        toast.warning('已保存，但平台链接绑定失败：' + (e as Error).message)
      }
      toast.success('已保存')
      onSaved()
      onClose()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function syncNow() {
    if (!videoId || syncing) return
    setSyncing(true)
    try {
      await applyLinks()
      const r = await apiJson<{ message?: string }>(`/api/platform/videos/${videoId}/sync`, { method: 'POST' })
      toast.success(r?.message || '同步完成')
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSyncing(false)
    }
  }

  async function startTranscribe() {
    if (!videoId || transcribing) return
    try {
      await apiJson(`/api/videos/${videoId}/transcribe`, { method: 'POST' })
      setTranscribing(true)
      toast.success('已开始语音转文字')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function attachVideo(file: File) {
    if (!videoId) return
    setVideoUploading(true)
    try {
      const d = await uploadFile<VideoDetail>(`/api/videos/${videoId}/video`, file)
      setDetail((prev) => (prev ? { ...prev, filename: d.filename } : prev))
      toast.success('视频已上传')
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setVideoUploading(false)
    }
  }

  async function removeVideo() {
    if (!videoId) return
    try {
      await apiJson(`/api/videos/${videoId}/video`, { method: 'DELETE' })
      setDetail((prev) => (prev ? { ...prev, filename: '' } : prev))
      toast.success('已移除视频文件')
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setConfirmRemoveVideo(false)
    }
  }

  async function onCoverFile(file: File) {
    if (!videoId) return
    try {
      const d = await uploadFile<VideoDetail>(`/api/videos/${videoId}/cover`, file)
      setDetail((prev) => (prev ? { ...prev, cover_url: d.cover_url } : prev))
      toast.success('封面已更新')
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function removeCover() {
    if (!videoId) return
    try {
      await apiJson(`/api/videos/${videoId}/cover`, { method: 'DELETE' })
      setDetail((prev) => (prev ? { ...prev, cover_url: null } : prev))
      toast.success('封面已移除')
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setConfirmRemoveCover(false)
    }
  }

  const transcript = detail?.transcript
  const asrLabel = transcript?.asr_provider
    ? { aliyun: '阿里云', siliconflow: '硅基流动', mock: 'mock' }[transcript.asr_provider] || transcript.asr_provider
    : ''

  return (
    <Drawer open={open} onOpenChange={(v) => !v && onClose()}>
      <DrawerHeader>
        <DrawerTitle>{state?.title || detail?.filename || '编辑素材'}</DrawerTitle>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {detail?.creator_id && isNonMain ? '对标博主素材' : '本地素材'}
          {detail?.created_at ? ` · 创建于 ${String(detail.created_at).slice(0, 10)}` : ''}
        </p>
      </DrawerHeader>

      <DrawerBody>
        {loading || !state || !detail ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : (
          <Tabs defaultValue="edit">
            <TabsList>
              <TabsTrigger value="edit">编辑信息</TabsTrigger>
              <TabsTrigger value="comments">评论数据</TabsTrigger>
            </TabsList>

            <TabsContent value="edit" className="space-y-4">
              {/* 标题 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">标题</label>
                <Input value={state.title} onChange={(e) => setState({ ...state, title: e.target.value })} placeholder="视频标题（选题标题）" />
              </div>

              {/* 平台链接 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">平台链接（绑定后同步数据/评论）</label>
                <div className="space-y-2">
                  {LINK_PLATFORMS.map((p) => (
                    <div key={p} className="flex items-center gap-2">
                      <span className="w-14 shrink-0 text-xs text-muted-foreground">{platformName(p)}</span>
                      <Input
                        value={state.links[p] || ''}
                        onChange={(e) => setState({ ...state, links: { ...state.links, [p]: e.target.value } })}
                        placeholder={`粘贴${platformName(p)}作品链接`}
                        className="h-8 text-xs"
                      />
                    </div>
                  ))}
                </div>
              </div>

              {/* 封面 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">封面</label>
                <div className="flex items-start gap-3">
                  <div className="relative h-24 w-32 overflow-hidden rounded-md border border-border bg-muted">
                    {detail.cover_url ? (
                      <img src={detail.cover_url} alt="封面" className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full items-center justify-center text-[10px] text-muted-foreground">无封面</div>
                    )}
                    {hasRealFile(detail.filename) && (
                      <button
                        onClick={() => onPlay(detail.id, state.title)}
                        className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition-all hover:bg-black/30 hover:opacity-100 cursor-pointer"
                      >
                        <Play className="h-6 w-6 text-white" fill="currentColor" />
                      </button>
                    )}
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <label className="cursor-pointer">
                      <input type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && onCoverFile(e.target.files[0])} />
                      <Button variant="outline" size="sm" asChild>
                        <span><ImagePlus className="h-3.5 w-3.5" /> 上传封面</span>
                      </Button>
                    </label>
                    {detail.cover_url && (
                      <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setConfirmRemoveCover(true)}>
                        <Trash2 className="h-3.5 w-3.5" /> 移除
                      </Button>
                    )}
                  </div>
                </div>
              </div>

              {/* 视频文件 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">视频文件</label>
                {hasRealFile(detail.filename) ? (
                  <div className="flex items-center gap-2 rounded-md border border-border bg-muted/50 px-3 py-2">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate text-xs">{detail.filename}</span>
                    <Button variant="ghost" size="sm" onClick={() => onPlay(detail.id, state.title)}>
                      <Play className="h-3.5 w-3.5" />
                    </Button>
                    <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setConfirmRemoveVideo(true)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ) : (
                  <label className="cursor-pointer">
                    <input type="file" accept="video/*" className="hidden" onChange={(e) => e.target.files?.[0] && attachVideo(e.target.files[0])} />
                    <Button variant="outline" size="sm" disabled={videoUploading} asChild>
                      <span>
                        {videoUploading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                        {videoUploading ? '上传中…' : '上传视频'}
                      </span>
                    </Button>
                  </label>
                )}
              </div>

              {/* 关联脚本 */}
              {!!drafts.length && (
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">已关联脚本</label>
                  <div className="flex flex-wrap gap-1.5">
                    {drafts.map((d) => (
                      <Button key={d.id} variant="outline" size="sm" onClick={() => { onClose(); navigate(`/drafts?id=${d.id}`) }}>
                        #{d.id} {d.title || '（无标题）'}
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              {/* 元信息 */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">平台</label>
                  <div className="flex gap-3 pt-1.5">
                    {PLATFORMS.map((p) => (
                      <label key={p} className="flex cursor-pointer items-center gap-1.5 text-xs">
                        <Checkbox
                          checked={state.platforms.includes(p)}
                          onCheckedChange={(v) =>
                            setState({
                              ...state,
                              platforms: v ? [...state.platforms, p] : state.platforms.filter((x) => x !== p)
                            })
                          }
                        />
                        {platformName(p)}
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">状态</label>
                  <Select value={state.status} onValueChange={(v) => setState({ ...state, status: v })}>
                    <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="planned">待发布</SelectItem>
                      <SelectItem value="published">已发布</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">计划发布</label>
                  <Input type="datetime-local" className="h-8 text-xs" value={state.plannedTs} onChange={(e) => setState({ ...state, plannedTs: e.target.value })} />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">实际发布</label>
                  <Input type="datetime-local" className="h-8 text-xs" value={state.publishedTs} onChange={(e) => setState({ ...state, publishedTs: e.target.value })} />
                </div>
                <div className="flex items-end gap-2 pb-1">
                  <label className="flex cursor-pointer items-center gap-2 text-xs">
                    <Checkbox checked={state.is_ad} onCheckedChange={(v) => setState({ ...state, is_ad: !!v })} />
                    商务广告（不参与人设学习）
                  </label>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">广告价格（元）</label>
                  <Input
                    type="number"
                    min={0}
                    className="h-8 text-xs"
                    value={state.adPrice ?? ''}
                    onChange={(e) => setState({ ...state, adPrice: e.target.value === '' ? null : Number(e.target.value) })}
                  />
                </div>
              </div>

              {/* 标签 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">标签（逗号分隔；{MAIN_TOPICS.join('/')} 为主赛道）</label>
                <Input value={state.tagsText} onChange={(e) => setState({ ...state, tagsText: e.target.value })} placeholder="如：求职, 简历, 应届生" />
              </div>

              {/* 转写 */}
              {hasRealFile(detail.filename) && (
                <div className="rounded-lg border border-border p-3">
                  <div className="flex items-center gap-2">
                    <Mic className="h-4 w-4 text-accent" />
                    <span className="text-xs font-medium">语音转文字</span>
                    {transcript?.transcript_text ? (
                      <Badge variant="success">已转写{asrLabel ? ` · ${asrLabel}` : ''}{transcript.asr_model ? ` · ${transcript.asr_model.split('/').pop()}` : ''}</Badge>
                    ) : (
                      <Badge variant="secondary">未转写</Badge>
                    )}
                    <span className="flex-1" />
                    <Button variant="outline" size="sm" onClick={startTranscribe} disabled={transcribing}>
                      {transcribing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Mic className="h-3.5 w-3.5" />}
                      {transcribing ? '识别中…' : transcript?.transcript_text ? '重新转写' : '语音转文字'}
                    </Button>
                    {isNonMain && transcript?.transcript_text && (
                      <Button variant="secondary" size="sm" onClick={() => onRewrite(detail.id)} disabled={rewriting}>
                        {rewriting ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                        洗稿
                      </Button>
                    )}
                  </div>
                </div>
              )}

              {/* 文稿 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  文稿（转写稿/原文；保存后用于人设与生成）
                </label>
                {transcript?.transcript_text && (
                  <details className="mb-2 rounded-md border border-border bg-muted/40 px-3 py-2">
                    <summary className="cursor-pointer text-xs text-muted-foreground">查看 ASR 转写稿（只读）</summary>
                    <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed">{transcript.transcript_text}</p>
                  </details>
                )}
                <Textarea
                  rows={7}
                  value={state.sourceText}
                  onChange={(e) => setState({ ...state, sourceText: e.target.value })}
                  placeholder="可在此粘贴/修改文稿"
                />
              </div>
            </TabsContent>

            <TabsContent value="comments">
              <MediaComments posts={commentPosts} />
            </TabsContent>
          </Tabs>
        )}
      </DrawerBody>

      <DrawerFooter>
        <Button variant="outline" size="sm" onClick={syncNow} disabled={syncing || loading}>
          {syncing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          同步数据
        </Button>
        <span className="flex-1" />
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="h-3.5 w-3.5" /> 取消
        </Button>
        <Button size="sm" onClick={save} disabled={saving || loading}>
          {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          保存
        </Button>
      </DrawerFooter>

      <ConfirmDialog
        open={confirmRemoveVideo}
        onOpenChange={setConfirmRemoveVideo}
        title="移除视频文件？"
        description="仅删除本地文件与转写，素材记录保留"
        confirmText="移除"
        destructive
        onConfirm={removeVideo}
      />
      <ConfirmDialog
        open={confirmRemoveCover}
        onOpenChange={setConfirmRemoveCover}
        title="移除封面？"
        confirmText="移除"
        destructive
        onConfirm={removeCover}
      />
    </Drawer>
  )
}
