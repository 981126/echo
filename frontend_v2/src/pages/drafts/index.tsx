import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { Plus, Trash2, Star, LoaderCircle } from 'lucide-react'
import { apiJson } from '@/api/client'
import { cn } from '@/lib/utils'
import { fmtDate } from '@/lib/format'
import { listVariants, itemVariants } from '@/lib/motion'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toaster'
import { DraftAiStatus } from './draft-ai-status'
import { DraftEditDrawer, EMPTY_DRAFT, type DraftEditState } from './edit-drawer'
import { DIM_DEFS, DIM_OPTS, modelInfo, srcLabel, srcTitle, type Draft } from './types'

const STATUS_TABS = [
  { key: 'draft', label: '草稿' },
  { key: 'used', label: '待制作' },
  { key: 'done', label: '完成' },
  { key: 'archived', label: '废稿' }
] as const

type Status = (typeof STATUS_TABS)[number]['key']

/** 卡片上的操作回调（R-173：DraftTile/Actions 提到模块作用域，靠 handlers 传参） */
interface TileHandlers {
  open: (d: Draft) => void
  rate: (d: Draft, i: number) => void
  setDim: (id: number, key: string, v: number) => void
  submitDims: (d: Draft) => void
  setStatus: (d: Draft, status: Status, msg: string) => void
  remove: (d: Draft) => void
}

const dimOf = (dims: Record<number, Record<string, number | null>>, id: number) => dims[id] || {}

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
  rating,
  dims,
  h
}: {
  d: Draft
  index: number
  busy: boolean
  rating: number
  dims: Record<string, number | null>
  h: TileHandlers
}) {
  const info = modelInfo(d)
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
      <h3 className="line-clamp-2 min-h-10 text-[14px] font-semibold leading-snug">{d.title || '（无标题）'}</h3>
      <p className="mt-1 truncate text-xs text-muted-foreground">
        {srcLabel(d)}
        {srcTitle(d) ? ` · ${srcTitle(d)}` : ''} · {fmtDate(d.updated_at)}
      </p>

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
      <div className="mt-3">
        <Actions d={d} busy={busy} h={h} />
      </div>
      {d.status === 'draft' && (
        <div className="mt-3 space-y-1.5 border-t border-border pt-2.5" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center gap-0.5">
            <span className="mr-1 text-[11px] text-muted-foreground">打分</span>
            {[1, 2, 3, 4, 5].map((i) => (
              <button key={i} onClick={() => h.rate(d, i)} className="cursor-pointer p-0.5">
                <Star
                  className={cn('h-3.5 w-3.5 transition-colors', rating >= i ? 'fill-warning text-warning' : 'text-muted-foreground/40 hover:text-warning')}
                />
              </button>
            ))}
            <span className="ml-1 text-[10px] text-muted-foreground">
              {rating ? `${rating} 分` : '← 打分是 AI 学你偏好最强的信号'}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {DIM_DEFS.map((def) => (
              <span key={def.key} className="flex items-center gap-0.5 text-[11px]">
                <span className="text-muted-foreground">{def.label}</span>
                {DIM_OPTS.map((opt) => (
                  <button
                    key={def.key + opt.v}
                    onClick={() => h.setDim(d.id, def.key, opt.v)}
                    className={cn(
                      'cursor-pointer rounded px-1 transition-colors',
                      dims[def.key] === opt.v ? 'bg-accent-soft text-accent' : 'text-muted-foreground/50 hover:text-foreground'
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </span>
            ))}
            <Button variant="ghost" size="sm" className="h-6 px-1.5 text-[11px]" onClick={() => h.submitDims(d)}>记反馈</Button>
          </div>
        </div>
      )}
    </motion.article>
  )
}

export default function DraftsPage() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<Status>('draft')
  const [editState, setEditState] = useState<DraftEditState | null>(null)
  const [editDraft, setEditDraft] = useState<Draft | null>(null)
  const [deleteDraft, setDeleteDraft] = useState<Draft | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [ratings, setRatings] = useState<Record<number, number>>({})
  const [dims, setDims] = useState<Record<number, Record<string, number | null>>>({})
  const [busyId, setBusyId] = useState(0)

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
    setEditDraft(d)
    setEditState({
      id: d.id,
      title: d.title,
      cover_text: d.cover_text,
      script: d.script,
      video_id: d.video_id ?? null,
      tagsText: (d.tags || []).join(', ')
    })
  }

  function createDraft() {
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

  async function rate(d: Draft, i: number) {
    try {
      await apiJson(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked: null, rating: i }) })
      setRatings({ ...ratings, [d.id]: i })
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  function setDim(id: number, key: string, v: number) {
    const cur = dims[id] || {}
    setDims({ ...dims, [id]: { ...cur, [key]: cur[key] === v ? null : v } })
  }

  async function submitDims(d: Draft) {
    const sel = dims[d.id] || {}
    const body: Record<string, unknown> = { liked: null }
    for (const def of DIM_DEFS) {
      if (sel[def.key] != null) body[def.key] = sel[def.key]
    }
    try {
      await apiJson(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify(body) })
      setDims({ ...dims, [d.id]: {} })
      toast.success('已记录分节反馈')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  // 稳定的 handlers：DraftTile 在模块作用域，回调走这里（R-173 顺手去掉每渲染新建函数）
  const handlers: TileHandlers = {
    open,
    rate,
    setDim,
    submitDims,
    setStatus,
    remove: setDeleteDraft
  }

  return (
    <motion.div variants={listVariants} initial="initial" animate="animate" className="space-y-4">
      <motion.div variants={itemVariants} className="flex items-center gap-2">
        <Button size="sm" onClick={createDraft}>
          <Plus className="h-3.5 w-3.5" /> 新建草稿
        </Button>
        <span className="text-xs text-muted-foreground">打分与分节反馈会回流训练生成偏好</span>
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
                        rating={ratings[d.id] || 0}
                        dims={dimOf(dims, d.id)}
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
      />

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
