import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Save,
  BadgeCheck,
  X,
  LoaderCircle,
  Stethoscope,
  Recycle,
  Eye,
  Pencil,
  MessageSquare,
  RotateCcw,

} from 'lucide-react'
import MarkdownIt from 'markdown-it'
import { apiJson } from '@/api/client'
import { cn } from '@/lib/utils'
import { fmtDate } from '@/lib/format'
import { Drawer, DrawerHeader, DrawerTitle, DrawerBody, DrawerFooter } from '@/components/ui/drawer'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Select, SelectValue, SelectTrigger, SelectContent, SelectItem } from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { toast } from '@/components/ui/toaster'
import { ScriptEditor } from './script-editor'
import { buildDiff } from './diff'
import {
  VERSION_SOURCE,
  modelInfo,
  type Draft,
  type DraftVersion,
  type Discussion
} from './types'

const md = new MarkdownIt({ html: false, linkify: true })

export interface DraftEditState {
  id: number
  title: string
  cover_text: string
  script: string
  video_id: number | null
  tagsText: string
}

export const EMPTY_DRAFT: DraftEditState = { id: 0, title: '', cover_text: '', script: '', video_id: null, tagsText: '' }

interface CheckInfo {
  ok: boolean
  issues: string[]
}

interface VideoOpt {
  id: number
  title: string
  filename: string
}

export function DraftEditDrawer({
  draft,
  state,
  setState,
  sourceRef,
  open,
  onClose,
  onSaved,
  onCreated
}: {
  draft: Draft | null // null = 新建（本地空白稿）
  state: DraftEditState
  setState: (s: DraftEditState) => void
  sourceRef?: Draft['source_ref']
  open: boolean
  onClose: () => void
  onSaved: () => void
  onCreated: (id: number) => void
}) {
  const [saving, setSaving] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  const [preview, setPreview] = useState(false)
  const [checkInfo, setCheckInfo] = useState<CheckInfo | null>(null)
  const [reworking, setReworking] = useState(false)
  const [discussions, setDiscussions] = useState<Discussion[]>([])
  const [discussing, setDiscussing] = useState(false)
  const [debateStatus, setDebateStatus] = useState('')
  const [versions, setVersions] = useState<DraftVersion[]>([])
  const [cmpLeft, setCmpLeft] = useState('')
  const [cmpRight, setCmpRight] = useState('')
  const [viewVer, setViewVer] = useState<DraftVersion | null>(null)
  const [rollingBack, setRollingBack] = useState(0)
  const [videos, setVideos] = useState<VideoOpt[]>([])

  const id = state.id

  // 关联素材选项
  useEffect(() => {
    if (!open) return
    apiJson<{ items: VideoOpt[] }>('/api/videos?limit=500')
      .then((r) => setVideos(r.items ?? []))
      .catch(() => setVideos([]))
  }, [open])

  // 讨论/版本随 id 加载
  useEffect(() => {
    if (!open || !id) {
      setDiscussions([])
      setVersions([])
      setCheckInfo(null)
      return
    }
    apiJson<Discussion[]>(`/api/drafts/${id}/discussions`).then(setDiscussions).catch(() => setDiscussions([]))
    apiJson<DraftVersion[]>(`/api/drafts/${id}/versions`).then((vs) => {
      setVersions(vs)
      if (vs.length >= 2 && !cmpLeft) {
        setCmpLeft(String(vs[vs.length - 2].id))
        setCmpRight(String(vs[vs.length - 1].id))
      }
    }).catch(() => setVersions([]))
    apiJson<CheckInfo>(`/api/drafts/${id}/check`).then(setCheckInfo).catch(() => setCheckInfo(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, id])

  // 讨论轮询
  useEffect(() => {
    if (!discussing || !id) return
    const timer = setInterval(async () => {
      try {
        const st = await apiJson<{ status?: string; note?: string }>(`/api/drafts/${id}/debate-status`)
        setDebateStatus(st.note || st.status || '')
        const rows = await apiJson<Discussion[]>(`/api/drafts/${id}/discussions`)
        setDiscussions(rows)
        if (st.status === 'done' || st.status === 'idle' || st.status === 'failed') {
          setDiscussing(false)
          setDebateStatus('')
          if (st.status === 'done') {
            toast.success('讨论完成，正文已更新')
            onSaved()
            const d = await apiJson<Draft>(`/api/drafts/${id}`)
            setState({
              id: d.id,
              title: d.title,
              cover_text: d.cover_text,
              script: d.script,
              video_id: d.video_id ?? null,
              tagsText: (d.tags || []).join(', ')
            })
          }
        }
      } catch {
        /* 抖动继续 */
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [discussing, id, onSaved, setState])

  const versionsDesc = useMemo(() => [...versions].sort((a, b) => b.id - a.id), [versions])
  const bodyDiff = useMemo(() => {
    const l = versions.find((v) => String(v.id) === cmpLeft)
    const r = versions.find((v) => String(v.id) === cmpRight)
    if (!l || !r) return null
    return buildDiff(l.script || '', r.script || '')
  }, [cmpLeft, cmpRight, versions])

  const canDiscuss = !!(state.script.trim() || draft?.original_script?.trim())

  if (!open) return null

  async function ensureSaved(): Promise<number> {
    const body = {
      title: state.title,
      cover_text: state.cover_text,
      script: state.script,
      video_id: state.video_id,
      tags: state.tagsText.split(/[,，]/).map((x) => x.trim()).filter(Boolean)
    }
    if (id) {
      await apiJson(`/api/drafts/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
      return id
    }
    const created = await apiJson<Draft>('/api/drafts', { method: 'POST', body: JSON.stringify(body) })
    setState({ ...state, id: created.id })
    onCreated(created.id)
    return created.id
  }

  async function save() {
    if (!state.title.trim() && !state.script.trim() && !state.cover_text.trim()) {
      toast.warning('内容为空，未保存')
      return
    }
    setSaving(true)
    try {
      await ensureSaved()
      toast.success('已保存')
      onSaved()
      onClose()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function finalize() {
    setFinalizing(true)
    try {
      const did = await ensureSaved()
      await apiJson(`/api/drafts/${did}/finalize`, {
        method: 'POST',
        body: JSON.stringify({
          title: state.title,
          cover_text: state.cover_text,
          script: state.script,
          tags: state.tagsText.split(/[,，]/).map((x) => x.trim()).filter(Boolean),
          video_id: state.video_id
        })
      })
      toast.success('已定稿并留存版本')
      const vs = await apiJson<DraftVersion[]>(`/api/drafts/${did}/versions`)
      setVersions(vs)
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setFinalizing(false)
    }
  }

  async function runCheck() {
    if (!id) return
    try {
      const r = await apiJson<CheckInfo>(`/api/drafts/${id}/check`)
      setCheckInfo(r)
      toast.success(r.ok ? '体检通过' : '体检完成：建议回炉')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function rework() {
    if (!id || reworking) return
    setReworking(true)
    try {
      await apiJson(`/api/drafts/${id}/rework`, { method: 'POST', body: '{}' })
      toast.success('已回炉重写')
      const d = await apiJson<Draft>(`/api/drafts/${id}`)
      setState({ ...state, title: d.title, cover_text: d.cover_text, script: d.script })
      setCheckInfo(null)
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setReworking(false)
    }
  }

  async function startDiscussion() {
    if (!id) return
    try {
      await apiJson(`/api/drafts/${id}/discuss`, { method: 'POST', body: '{}' })
      setDiscussing(true)
      setDebateStatus('模型讨论中…')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function rollback(ver: DraftVersion) {
    setRollingBack(ver.id)
    try {
      await apiJson(`/api/drafts/${id}/versions/${ver.id}/rollback`, { method: 'POST', body: '{}' })
      setState({ ...state, title: ver.title, cover_text: ver.cover_text, script: ver.script, tagsText: (ver.tags || []).join(', ') })
      toast.success(`已回滚到版本 #${ver.id}`)
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setRollingBack(0)
    }
  }

  const info = draft ? modelInfo(draft) : ''
  const q = draft?.quality || {}

  return (
    <Drawer open={open} onOpenChange={(v) => !v && onClose()} width="min(860px, 96vw)">
      <DrawerHeader>
        <DrawerTitle>{id ? `草稿 #${id}` : '新建草稿'}</DrawerTitle>
        {sourceRef?.source_title && (
          <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
            来源素材：
            {sourceRef.post_id ? (
              <a href={`#/videos?post=${sourceRef.post_id}`} className="text-accent hover:underline">
                {sourceRef.source_title}
              </a>
            ) : (
              sourceRef.source_title
            )}
            {sourceRef.benchmark_name ? ` · 对标「${sourceRef.benchmark_name}」` : ''}
          </p>
        )}
      </DrawerHeader>

      <DrawerBody>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">标题</label>
              <Input value={state.title} onChange={(e) => setState({ ...state, title: e.target.value })} placeholder="视频标题" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">封面字（3-8 字）</label>
              <Input value={state.cover_text} onChange={(e) => setState({ ...state, cover_text: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">关联素材视频（可选）</label>
              <Select
                value={state.video_id ? String(state.video_id) : 'none'}
                onValueChange={(v) => setState({ ...state, video_id: v === 'none' ? null : Number(v) })}
              >
                <SelectTrigger className="h-9"><SelectValue placeholder="选择一个素材视频" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">不关联</SelectItem>
                  {videos.map((v) => (
                    <SelectItem key={v.id} value={String(v.id)}>
                      #{v.id} {v.title || v.filename}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">素材标签（逗号分隔）</label>
              <Input value={state.tagsText} onChange={(e) => setState({ ...state, tagsText: e.target.value })} placeholder="如：求职, 面试, 赚钱" />
            </div>
          </div>
        </div>

        <Tabs defaultValue="edit" className="mt-4">
          <TabsList>
            <TabsTrigger value="edit">编辑</TabsTrigger>
            <TabsTrigger value="discuss">讨论（双模型留痕）</TabsTrigger>
            <TabsTrigger value="compare">正文对比</TabsTrigger>
            <TabsTrigger value="versions">版本{versions.length ? ` (${versions.length})` : ''}</TabsTrigger>
          </TabsList>

          {/* 编辑 */}
          <TabsContent value="edit" className="space-y-3">
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-muted-foreground">口播脚本（Markdown，可插图）</label>
              <span className="flex-1" />
              <Button variant="ghost" size="sm" onClick={() => setPreview(!preview)}>
                {preview ? <Pencil className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                {preview ? '返回编辑' : '预览'}
              </Button>
            </div>
            {preview ? (
              <div
                className="prose-echo min-h-72 rounded-lg border border-border px-4 py-3 text-sm"
                dangerouslySetInnerHTML={{ __html: md.render(state.script || '') }}
              />
            ) : (
              <ScriptEditor value={state.script} onChange={(v) => setState({ ...state, script: v })} />
            )}

            {!!id && checkInfo && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-lg border border-border p-3"
              >
                <div className="flex items-center gap-2">
                  <Stethoscope className="h-4 w-4 text-accent" />
                  <span className="text-xs font-medium">脚本体检</span>
                  {checkInfo.ok ? <Badge variant="success">通过</Badge> : <Badge variant="warning">建议回炉</Badge>}
                  <span className="flex-1" />
                  {!checkInfo.ok && (
                    <Button variant="secondary" size="sm" onClick={rework} disabled={reworking}>
                      {reworking ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Recycle className="h-3.5 w-3.5" />}
                      一键回炉重写
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={runCheck}>重新体检</Button>
                </div>
                {!!checkInfo.issues?.length && (
                  <ul className="mt-2 list-inside list-disc space-y-0.5 text-xs text-warning">
                    {checkInfo.issues.map((iss, i) => (
                      <li key={i}>{iss}</li>
                    ))}
                  </ul>
                )}
              </motion.div>
            )}

            {!!info && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                本篇生成模型：{info}
                {!!q.fallback && <Badge variant="warning">由备用模型生成</Badge>}
                {!!q.rounds && <Badge variant="secondary">讨论 {Number(q.rounds_done ?? q.rounds)}/{q.rounds} 轮</Badge>}
                {!!q.mock && <Badge variant="destructive">mock 稿（模型不可用）</Badge>}
              </div>
            )}
          </TabsContent>

          {/* 讨论 */}
          <TabsContent value="discuss">
            {!id ? (
              <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">先保存草稿，再让双模型基于原文讨论</div>
            ) : (
              <div className="space-y-3">
                {!discussions.length && !discussing && (
                  <div className="flex h-32 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
                    <MessageSquare className="h-5 w-5" />
                    暂无讨论记录
                    <Button size="sm" disabled={!canDiscuss} onClick={startDiscussion}>讨论</Button>
                    {!canDiscuss && <span className="text-xs">这篇草稿没有可讨论的原文或正文</span>}
                  </div>
                )}
                <ScrollArea className="max-h-[52vh]">
                  <div className="space-y-2.5 pr-2">
                    <AnimatePresence initial={false}>
                      {discussions.map((m) => (
                        <motion.div
                          key={m.id}
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          className={cn(
                            'rounded-lg border px-3 py-2.5',
                            m.actor === 'referee' ? 'border-accent/30 bg-accent-soft/40' : 'border-border bg-muted/40'
                          )}
                        >
                          <div className="mb-1 flex items-center gap-2 text-xs">
                            <b>{m.actor === 'referee' ? '评审方' : m.actor === 'generator' ? '生成方' : m.actor}</b>
                            <span className="text-muted-foreground">
                              {{ draft: '初稿', critique: '评审', revise: '修订', note: '说明' }[m.kind as string] || m.kind} · 第{m.round}轮
                            </span>
                          </div>
                          <p className="whitespace-pre-wrap text-xs leading-relaxed">{m.content}</p>
                        </motion.div>
                      ))}
                    </AnimatePresence>
                    {discussing && (
                      <div className="flex items-center gap-2 py-3 text-xs text-warning">
                        <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                        {debateStatus || '模型讨论中…'}
                      </div>
                    )}
                  </div>
                </ScrollArea>
                {!!discussions.length && !discussing && (
                  <div className="pt-1 text-center">
                    <Button variant="secondary" size="sm" disabled={!canDiscuss} onClick={startDiscussion}>重新讨论</Button>
                  </div>
                )}
              </div>
            )}
          </TabsContent>

          {/* 正文对比 */}
          <TabsContent value="compare">
            {!id ? (
              <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">先保存草稿，再进行正文对比</div>
            ) : versions.length < 2 ? (
              <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
                至少要有两个版本才能对比（先【定稿】，或让洗稿 / 讨论 / AI 生成自动留版）
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {(['left', 'right'] as const).map((side) => {
                  const val = side === 'left' ? cmpLeft : cmpRight
                  const setVal = side === 'left' ? setCmpLeft : setCmpRight
                  return (
                    <div key={side}>
                      <Select value={val} onValueChange={setVal}>
                        <SelectTrigger className="mb-2 h-8 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {versionsDesc.map((v) => (
                            <SelectItem key={v.id} value={String(v.id)}>
                              #{v.id} {VERSION_SOURCE[v.source]?.label || v.source} · {fmtDate(v.created_at)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <div className="diff-body">
                        {(side === 'left' ? bodyDiff?.left : bodyDiff?.right)?.map((seg, i) => (
                          <span key={i} className={seg.type}>{seg.text}</span>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </TabsContent>

          {/* 版本 */}
          <TabsContent value="versions">
            {!id ? (
              <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">先保存草稿，再进行定稿</div>
            ) : !versions.length ? (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                还没有版本，点编辑区下方的【定稿】保存一版
              </div>
            ) : (
              <ul className="space-y-2">
                <AnimatePresence initial={false}>
                  {versionsDesc.map((ver) => (
                    <motion.li
                      key={ver.id}
                      layout
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2.5"
                    >
                      <Badge variant={VERSION_SOURCE[ver.source]?.variant || 'secondary'}>
                        {VERSION_SOURCE[ver.source]?.label || ver.source}
                      </Badge>
                      <span className="min-w-0 flex-1 truncate text-[13px]">
                        {ver.title || '（无标题）'}
                        {ver.note && <span className="ml-1 text-xs text-muted-foreground">· {ver.note}</span>}
                      </span>
                      <span className="text-xs text-muted-foreground">{fmtDate(ver.created_at)}</span>
                      <Button variant="outline" size="sm" className="h-7 text-xs" disabled={rollingBack === ver.id} onClick={() => rollback(ver)}>
                        {rollingBack === ver.id ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                        回滚到此版本
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setViewVer(ver)}>查看</Button>
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </TabsContent>
        </Tabs>
      </DrawerBody>

      <DrawerFooter>
        <Button size="sm" onClick={save} disabled={saving}>
          {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          保存
        </Button>
        <Button variant="secondary" size="sm" onClick={finalize} disabled={finalizing}>
          {finalizing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <BadgeCheck className="h-3.5 w-3.5" />}
          定稿
        </Button>
        <span className="flex-1" />
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="h-3.5 w-3.5" /> 取消
        </Button>
      </DrawerFooter>

      {/* 版本查看 */}
      <Dialog open={viewVer !== null} onOpenChange={(v) => !v && setViewVer(null)}>
        <DialogContent className="w-[min(760px,94vw)]">
          <DialogHeader>
            <DialogTitle>
              版本 #{viewVer?.id} · {viewVer ? VERSION_SOURCE[viewVer.source]?.label || viewVer.source : ''}
            </DialogTitle>
          </DialogHeader>
          {viewVer && (
            <div className="space-y-3 text-sm">
              <p className="text-xs text-muted-foreground">
                {fmtDate(viewVer.created_at)}{viewVer.note ? ` · ${viewVer.note}` : ''}
              </p>
              <div><span className="text-xs text-muted-foreground">标题：</span>{viewVer.title || '（无标题）'}</div>
              <div><span className="text-xs text-muted-foreground">封面字：</span>{viewVer.cover_text || '（无）'}</div>
              <div><span className="text-xs text-muted-foreground">标签：</span>{(viewVer.tags || []).join('、') || '（无）'}</div>
              <div>
                <span className="text-xs text-muted-foreground">正文：</span>
                <div className="diff-body mt-1 max-h-[46vh]">{viewVer.script || '（空）'}</div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Drawer>
  )
}
