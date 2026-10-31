import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { Plus, Trash2, PenLine, LoaderCircle } from 'lucide-react'
import { apiJson } from '@/api/client'
import { fmtDate, fmtNum } from '@/lib/format'
import { listVariants, itemVariants } from '@/lib/motion'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toaster'
import { DraftAiStatus } from './draft-ai-status'
import { EMPTY_DRAFT, type DraftEditState } from './edit-state'
import { modelInfo, srcLabel, srcTitle, type Draft } from './types'

// R-243：编辑器（tiptap/markdown ~600KB chunk）按需加载——列表页首屏不再静态 import edit-drawer；
// 用户点「新建草稿」/点卡片时才加载，页面挂载后用空闲时间预取，点开仍秒开。
const DraftEditDrawer = lazy(() => import('./edit-drawer').then((m) => ({ default: m.DraftEditDrawer })))

const STATUS_TABS = [
  { key: 'draft', label: '草稿' },
  { key: 'used', label: '待制作' },
  { key: 'done', label: '完成' },
  { key: 'archived', label: '废稿' }
] as const

type Status = (typeof STATUS_TABS)[number]['key']

/** R-211：「记反馈」行内展开状态（每篇草稿一份） */
interface FeedbackUI {
  open: boolean
  text: string
  saving: boolean
}

/** 卡片上的操作回调（R-173：DraftTile/Actions 提到模块作用域，靠 handlers 传参） */
interface TileHandlers {
  open: (d: Draft) => void
  setStatus: (d: Draft, status: Status, msg: string) => void
  remove: (d: Draft) => void
  toggleFeedback: (d: Draft) => void
  setFeedbackText: (id: number, text: string) => void
  submitFeedback: (d: Draft) => void
}

const PLATFORM_LABEL: Record<string, string> = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }

function Actions({ d, busy, h }: { d: Draft; busy: boolean; h: TileHandlers }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
      {busy && <LoaderCircle className="h-3.5 w-3.5 animate-spin text-accent" />}
      {d.status === 'draft' && (
        <>
          <Button variant="secondary" size="sm" className="h-7 text-xs" onClick={() => h.setStatus(d, 'used', '已采用，移入待制作')}>✅ 采用</Button>
          <Button variant="secondary" size="sm" className="h-7 text-xs" onClick={() => h.setStatus(d, 'archived', '已移入废稿')}>不采用</Button>
        </>
      )}
      {d.status === 'used' && (
        <>
          <Button size="sm" className="h-7 text-xs" onClick={() => h.setStatus(d, 'done', '已完成')}>完成</Button>
          <Button variant="secondary" size="sm" className="h-7 text-xs" onClick={() => h.setStatus(d, 'draft', '已退回草稿')}>退回草稿</Button>
          <Button variant="secondary" size="sm" className="h-7 text-xs" onClick={() => h.setStatus(d, 'archived', '已移入废稿')}>移入废稿</Button>
        </>
      )}
      {d.status === 'done' && (
        <Button variant="secondary" size="sm" className="h-7 text-xs" onClick={() => h.setStatus(d, 'used', '已退回待制作')}>退回待制作</Button>
      )}
      {d.status === 'archived' && (
        <Button variant="secondary" size="sm" className="h-7 text-xs" onClick={() => h.setStatus(d, 'draft', '已恢复为草稿')}>恢复为草稿</Button>
      )}
      <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => h.remove(d)}>
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

function DraftTile({
  d,
  index,
  busy,
  fb,
  h
}: {
  d: Draft
  index: number
  busy: boolean
  fb: FeedbackUI | undefined
  h: TileHandlers
}) {
  const info = modelInfo(d)
  // R-207：红线才是硬问题（标红）；口癖/高频词覆盖率只做诊断（微标，不阻断）
  const redlineHit = d.quality?.passed === false && !d.quality?.mock && !!d.quality?.issues?.length
  const coverage = d.quality?.diagnostics?.style_coverage
  return (
    <motion.article
      layout
      variants={itemVariants}
      initial="initial"
      animate="animate"
      exit={{ opacity: 0, scale: 0.94 }}
      transition={{ delay: Math.min(index, 12) * 0.03 }}
      onClick={() => h.open(d)}
      className="group cursor-pointer rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)] transition-all hover:-translate-y-0.5 hover:border-accent/40"
    >
      <div className="flex items-start gap-2">
        <h3 className="line-clamp-2 min-h-10 flex-1 text-[14px] font-semibold leading-snug">{d.title || '（无标题）'}</h3>
        {/* R-210：纯手写（AI 从未参与）标 */}
        {!!d.pure_manual && (
          <Badge variant="success" className="mt-0.5 shrink-0 text-[10px]">纯手写</Badge>
        )}
      </div>
      <p className="mt-1 truncate text-xs text-muted-foreground">
        {srcLabel(d)}
        {srcTitle(d) ? ` · ${srcTitle(d)}` : ''} · {fmtDate(d.updated_at)}
      </p>
      {!!d.publish_url && (
        <a
          href={d.publish_url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="mt-1 inline-block text-[11px] text-accent hover:underline"
        >
          已发布{d.publish_platform ? ` · ${PLATFORM_LABEL[d.publish_platform] || d.publish_platform}` : ''}
        </a>
      )}
      {!!d.performance?.totals && (
        <p className="tnum mt-0.5 text-[11px] text-muted-foreground">
          表现：播放 {fmtNum(d.performance.totals.plays || 0)} · 赞 {fmtNum(d.performance.totals.likes || 0)} · 藏{' '}
          {fmtNum(d.performance.totals.favorites || 0)} · 评 {fmtNum(d.performance.totals.comments || 0)}
        </p>
      )}

      {/* R-173：AI 长任务进行中/中断的状态条 */}
      {!!d.debate?.state && (
        <div className="mt-2" onClick={(e) => e.stopPropagation()}>
          <DraftAiStatus debate={d.debate} />
        </div>
      )}

      {!!info && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          <Badge variant="secondary" className="text-[10px]">{info}</Badge>
          {!!d.quality?.fallback && <Badge variant="warning" className="text-[10px]">由备用模型生成</Badge>}
        </div>
      )}
      {(redlineHit || coverage != null) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {redlineHit && <Badge variant="destructive" className="text-[10px]">踩红线</Badge>}
          {coverage != null && (
            <Badge
              variant="secondary"
              className="text-[10px] font-normal text-muted-foreground"
              title="口癖/高频词覆盖率（仅诊断，不作为重写依据）"
            >
              像作者 {Math.round(coverage * 100)}%
            </Badge>
          )}
        </div>
      )}
      <div className="mt-3">
        <Actions d={d} busy={busy} h={h} />
      </div>
      {/* R-211：记反馈（文本评价，AI 在完成/不采用时结合评价学习）；星级/四维/快速反馈已下线 */}
      <div className="mt-2 border-t border-border pt-2" onClick={(e) => e.stopPropagation()}>
        <button
          className="flex cursor-pointer items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
          onClick={() => h.toggleFeedback(d)}
        >
          <PenLine className="h-3 w-3" />
          记反馈
          {!fb?.open && !!d.feedback_comment && <span className="text-accent">· 已写</span>}
        </button>
        <AnimatePresence initial={false}>
          {fb?.open && (
            <motion.div
              key="fb"
              initial={{ height: 0, opacity: 0.4, y: -4 }}
              animate={{ height: 'auto', opacity: 1, y: 0 }}
              exit={{ height: 0, opacity: 0.4, y: -4 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              className="overflow-hidden"
            >
              <textarea
                value={fb.text}
                onChange={(e) => h.setFeedbackText(d.id, e.target.value)}
                placeholder="写下你的评价：好在哪 / 差在哪（完成或不采用时，AI 会结合评价复盘学习）"
                rows={3}
                className="mt-1.5 w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-xs outline-none focus:border-accent"
              />
              <div className="mt-1 flex items-center gap-2">
                <Button
                  size="sm"
                  className="h-6 px-2 text-[11px]"
                  disabled={fb.saving || !fb.text.trim()}
                  onClick={() => h.submitFeedback(d)}
                >
                  {fb.saving && <LoaderCircle className="h-3 w-3 animate-spin" />}
                  提交评价
                </Button>
                <span className="text-[10px] text-muted-foreground">完成 = 好 / 不采用 = 差，会触发 AI 复盘</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.article>
  )
}

export default function DraftsPage() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<Status>('draft')
  const [editState, setEditState] = useState<DraftEditState | null>(null)
  // R-243：编辑器 lazy 组件只有「第一次打开」后才挂载（否则 React.lazy 在页面首帧就会拉 chunk）；
  // 挂载后常驻（open=false 时仍保留），关闭动画与原来一致。
  const [drawerMounted, setDrawerMounted] = useState(false)
  const [editDraft, setEditDraft] = useState<Draft | null>(null)
  const [deleteDraft, setDeleteDraft] = useState<Draft | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [fbMap, setFbMap] = useState<Record<number, FeedbackUI>>({})
  const [busyId, setBusyId] = useState(0)

  // R-243：空闲预取编辑器 chunk（不支持 requestIdleCallback 则 1.2s 后 setTimeout）。
  // 只预取模块、不挂载组件；未打开编辑器前不阻塞首屏。
  useEffect(() => {
    const idleWindow = window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number
      cancelIdleCallback?: (id: number) => void
    }
    if (typeof idleWindow.requestIdleCallback === 'function') {
      const idleId = idleWindow.requestIdleCallback(() => void import('./edit-drawer'), { timeout: 2000 })
      return () => idleWindow.cancelIdleCallback?.(idleId)
    }
    const timer = window.setTimeout(() => void import('./edit-drawer'), 1200)
    return () => window.clearTimeout(timer)
  }, [])

  const draftsQ = useQuery({
    queryKey: ['drafts'],
    queryFn: () => apiJson<Draft[]>('/api/drafts?limit=500'),
    // R-173：只在「确实有草稿在跑 AI 任务」时轮询（讨论/洗稿/回炉/生成），否则不打扰后端
    refetchInterval: (query) => {
      const rows = query.state.data as Draft[] | undefined
      return rows?.some((d) => d.debate?.state === 'running') ? 3000 : false
    }
  })

  const drafts = useMemo(() => draftsQ.data ?? [], [draftsQ.data])
  const listOf = (s: Status) => drafts.filter((d) => d.status === s)

  // 深链 ?id=
  useEffect(() => {
    const idParam = params.get('id')
    if (!idParam || draftsQ.isLoading) return
    const d = drafts.find((x) => x.id === Number(idParam))
    setParams({}, { replace: true })
    if (d) open(d)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, draftsQ.isLoading])

  function open(d: Draft) {
    setDrawerMounted(true)
    setEditDraft(d)
    setEditState({
      id: d.id,
      title: d.title,
      cover_text: d.cover_text,
      script: d.script,
      video_id: d.video_id ?? null,
      tagsText: (d.tags || []).join(', '),
      publish_platform: d.publish_platform || '',
      publish_url: d.publish_url || '',
      published_at: d.published_at || ''
    })
  }

  function createDraft() {
    setDrawerMounted(true)
    setEditDraft(null)
    setEditState({ ...EMPTY_DRAFT })
  }

  async function setStatus(d: Draft, status: Status, msg: string) {
    setBusyId(d.id)
    try {
      await apiJson(`/api/drafts/${d.id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
      toast.success(msg)
      qc.invalidateQueries({ queryKey: ['drafts'] })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusyId(0)
    }
  }

  async function doDelete() {
    if (!deleteDraft) return
    setDeleting(true)
    try {
      await apiJson(`/api/drafts/${deleteDraft.id}`, { method: 'PATCH', body: JSON.stringify({ status: 'deleted' }) })
      toast.success('已删除')
      setDeleteDraft(null)
      qc.invalidateQueries({ queryKey: ['drafts'] })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setDeleting(false)
    }
  }

  /** R-212：自动保存建出的稿被清空并关闭抽屉 → 逻辑删除它（与卡片【删除】同口径），不留空卡片 */
  function discardAutoDraft(id: number) {
    qc.setQueryData<Draft[]>(['drafts'], (rows) => (rows ?? []).filter((d) => d.id !== id))
    apiJson(`/api/drafts/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'deleted' }) })
      .catch(() => {
        /* 删不掉就不删（列表刷新后还能看到，作者可手动删） */
      })
      .finally(() => qc.invalidateQueries({ queryKey: ['drafts'] }))
  }

  // R-211：记反馈——行内展开（预填已写评价）；提交只存文本，学习在「完成/不采用」时触发
  function toggleFeedback(d: Draft) {
    const cur = fbMap[d.id]
    setFbMap({
      ...fbMap,
      [d.id]: cur
        ? { ...cur, open: !cur.open }
        : { open: true, text: d.feedback_comment || '', saving: false }
    })
  }

  function setFeedbackText(id: number, text: string) {
    const cur = fbMap[id]
    if (cur) setFbMap({ ...fbMap, [id]: { ...cur, text } })
  }

  async function submitFeedback(d: Draft) {
    const cur = fbMap[d.id]
    if (!cur || !cur.text.trim()) return
    setFbMap({ ...fbMap, [d.id]: { ...cur, saving: true } })
    try {
      await apiJson(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ comment: cur.text.trim() }) })
      toast.success('评价已记录，完成/不采用时会一起复盘')
      setFbMap((m) => ({ ...m, [d.id]: { ...m[d.id], saving: false, open: false } }))
      qc.invalidateQueries({ queryKey: ['drafts'] })
    } catch (e) {
      toast.error((e as Error).message)
      setFbMap((m) => ({ ...m, [d.id]: { ...m[d.id], saving: false } }))
    }
  }

  // 稳定的 handlers：DraftTile 在模块作用域，回调走这里（R-173 顺手去掉每渲染新建函数）
  const handlers: TileHandlers = {
    open,
    setStatus,
    remove: setDeleteDraft,
    toggleFeedback,
    setFeedbackText,
    submitFeedback
  }

  return (
    <motion.div variants={listVariants} initial="initial" animate="animate" className="space-y-4">
      <motion.div variants={itemVariants} className="flex items-center gap-2">
        <Button size="sm" onClick={createDraft}>
          <Plus className="h-3.5 w-3.5" /> 新建草稿
        </Button>
        <span className="text-xs text-muted-foreground">完成 = 好 / 不采用 = 差，会触发 AI 复盘学习；记反馈可写下你的评价</span>
      </motion.div>

      <motion.div variants={itemVariants}>
        <Tabs value={tab} onValueChange={(v) => setTab(v as Status)}>
          <TabsList>
            {STATUS_TABS.map((t) => (
              <TabsTrigger key={t.key} value={t.key}>
                {t.label} ({listOf(t.key).length})
              </TabsTrigger>
            ))}
          </TabsList>

          {STATUS_TABS.map((t) => (
            <TabsContent key={t.key} value={t.key}>
              {draftsQ.isLoading ? (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <Skeleton key={i} className="h-36 w-full" />
                  ))}
                </div>
              ) : !listOf(t.key).length ? (
                <div className="flex h-36 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
                  {{ draft: '暂无草稿，新建或从主页灵感生成', used: '暂无待制作（点草稿的「采用」会进这里）', done: '暂无完成', archived: '废稿箱是空的' }[t.key]}
                </div>
              ) : (
                <motion.div layout className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <AnimatePresence>
                    {listOf(t.key).map((d, i) => (
                      <DraftTile
                        key={d.id}
                        d={d}
                        index={i}
                        busy={busyId === d.id}
                        fb={fbMap[d.id]}
                        h={handlers}
                      />
                    ))}
                  </AnimatePresence>
                </motion.div>
              )}
            </TabsContent>
          ))}
        </Tabs>
      </motion.div>

      {drawerMounted && (
        <Suspense fallback={null}>
          <DraftEditDrawer
            draft={editDraft}
            state={editState ?? EMPTY_DRAFT}
            setState={(s) => setEditState(s)}
            sourceRef={editDraft?.source_ref}
            open={editState !== null}
            onClose={() => {
              setEditState(null)
              setEditDraft(null)
              qc.invalidateQueries({ queryKey: ['drafts'] })
            }}
            onSaved={() => qc.invalidateQueries({ queryKey: ['drafts'] })}
            onCreated={(id) => {
              qc.invalidateQueries({ queryKey: ['drafts'] })
              setEditState((prev) => (prev ? { ...prev, id } : prev))
            }}
            onDiscardEmpty={discardAutoDraft}
          />
        </Suspense>
      )}

      <ConfirmDialog
        open={deleteDraft !== null}
        onOpenChange={(v) => !v && setDeleteDraft(null)}
        title={`删除草稿「${deleteDraft?.title || '（无标题）'}」？`}
        description="逻辑删除后任何 tab 都不可见"
        confirmText="删除"
        destructive
        loading={deleting}
        onConfirm={doDelete}
      />
    </motion.div>
  )
}
