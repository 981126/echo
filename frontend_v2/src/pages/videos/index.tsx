import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Upload,
  LoaderCircle,
  Merge,
  RefreshCw,
  Trash2,
  X,
  CheckSquare,
  Layers
} from 'lucide-react'
import { apiJson, uploadFile } from '@/api/client'
import { listVariants } from '@/lib/motion'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectValue, SelectTrigger, SelectContent, SelectItem } from '@/components/ui/select'
import { MultiSelect } from '@/components/ui/multi-select'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { toast } from '@/components/ui/toaster'
import {
  buildCards,
  applyFiltersTo,
  loadFilters,
  saveFilters,
  type CardItem,
  type VideoItem,
  type WorkItem,
  type Filters
} from './types'
import { useCardTasks } from './use-card-tasks'
import { MaterialCard } from './material-card'
import { EditDrawer } from './edit-drawer'
import { CloudDrawer } from './cloud-drawer'
import { PlayerDialog } from './player-dialog'

interface Creator {
  id: number
  name: string
  kind: string
  is_current?: boolean
}

export default function VideosPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const qc = useQueryClient()

  const [filters, setFilters] = useState<Filters>(loadFilters)
  const [applied, setApplied] = useState<Filters>(loadFilters)
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [batchBusy, setBatchBusy] = useState('')
  const [uploading, setUploading] = useState(false)
  const [busy, setBusy] = useState<Record<string, boolean>>({})  // 单卡操作（拆分/删除/同步）即时反馈

  const [editId, setEditId] = useState<number | null>(null)
  const [cloudItem, setCloudItem] = useState<CardItem | null>(null)
  const [player, setPlayer] = useState<{ id: number; title: string } | null>(null)
  const [deleteItem, setDeleteItem] = useState<CardItem | null>(null)
  const [splitItem, setSplitItem] = useState<CardItem | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [rewriting, setRewriting] = useState(false)
  const uploadInputRef = useRef<HTMLInputElement>(null)

  // ---------- 数据 ----------
  const creatorsQ = useQuery({ queryKey: ['creators'], queryFn: () => apiJson<Creator[]>('/api/creators') })
  const currentQ = useQuery({
    queryKey: ['creators', 'current'],
    queryFn: () => apiJson<Creator>('/api/creators/current')
  })
  const currentCreatorId = currentQ.data?.id ?? 0
  const effectiveCreator = filters.creatorId || 0

  const videosQ = useQuery({
    queryKey: ['videos', 'list', effectiveCreator],
    queryFn: () => apiJson<{ items: VideoItem[] }>(`/api/videos?limit=500${effectiveCreator ? `&creator_id=${effectiveCreator}` : ''}`)
  })
  const worksQ = useQuery({
    queryKey: ['works', 'list', effectiveCreator],
    queryFn: () => apiJson<{ items: WorkItem[] }>(`/api/works${effectiveCreator ? `?creator_id=${effectiveCreator}` : ''}`)
  })

  const cards = useMemo(
    () => buildCards(videosQ.data?.items ?? [], worksQ.data?.items ?? []),
    [videosQ.data, worksQ.data]
  )
  const filtered = useMemo(() => applyFiltersTo(cards, applied), [cards, applied])
  const allTags = useMemo(() => {
    const set = new Set<string>()
    cards.forEach((c) => c.tags.forEach((t) => set.add(t)))
    return [...set].sort()
  }, [cards])

  const reload = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['videos'] })
    qc.invalidateQueries({ queryKey: ['works'] })
     
  }, [qc])

  const { tasks, begin, claim, finish, refreshActive, hasTask } = useCardTasks(cards, reload)

  // 筛选持久化
  useEffect(() => saveFilters(filters), [filters])

  // 深链 ?edit=
  useEffect(() => {
    const edit = params.get('edit')
    if (edit && !videosQ.isLoading) {
      setEditId(Number(edit))
      setParams({}, { replace: true })
    }
  }, [params, setParams, videosQ.isLoading])

  // ---------- 动作 ----------
  async function doUpload(file: File) {
    setUploading(true)
    try {
      const v = await uploadFile<VideoItem>('/api/videos/upload', file)
      toast.success('上传成功，可在编辑页转写')
      reload()
      setEditId(v.id)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  const openItem = useCallback((it: CardItem) => {
    if (it.kind === 'cloud') {
      if (it.local_video_id) setEditId(it.local_video_id)
      else setCloudItem(it)
    } else {
      setEditId(it.id)
    }
  }, [])

  const onPlay = useCallback(async (it: CardItem) => {
    const vid = it.kind === 'local' ? it.id : it.local_video_id
    if (it.kind === 'cloud' && (!it.local_video_id || !it.hasVideo)) {
      openItem(it)
      return
    }
    if (!vid) {
      openItem(it)
      return
    }
    setPlayer({ id: vid, title: it.title })
  }, [openItem])

  const onDeleteCb = useCallback((it: CardItem) => setDeleteItem(it), [])
  const onSplitCb = useCallback((it: CardItem) => setSplitItem(it), [])

  const onSyncCb = useCallback(async (it: CardItem) => {
    if (hasTask(it.key)) return
    begin(it.key) // 本地即时过渡动画，不等服务端任务注册
    try {
      let r: { media?: { task_id?: number; status?: string }; message?: string } | null = null
      if (it.kind === 'local') {
        r = await apiJson(`/api/platform/videos/${it.id}/sync`, { method: 'POST' })
      } else if (it.type === 'work') {
        r = await apiJson(`/api/platform/works/${it.id}/sync`, { method: 'POST' })
      } else if (it.cloudPosts[0]) {
        r = await apiJson(`/api/platform/posts/${it.cloudPosts[0].id}/sync`, { method: 'POST' })
      }
      const taskId = r?.media?.task_id
      if (taskId) {
        claim(it.key, taskId) // 服务端媒体补齐任务接管进度
      } else if (r?.media?.status === 'skip') {
        finish(it.key, true, '已是最新，无需补齐')
      } else {
        await refreshActive() // 兜底：扫描认领
        if (!hasTask(it.key)) finish(it.key, true, r?.message || '同步完成')
      }
      reload()
    } catch (e) {
      finish(it.key, false)
      toast.error((e as Error).message)
    }
  }, [begin, claim, finish, refreshActive, reload, hasTask])

  const onConfirmTags = useCallback(async (it: CardItem) => {
    try {
      await apiJson(`/api/videos/${it.id}/confirm-tags`, { method: 'POST', body: JSON.stringify({ tags_confirmed: true }) })
      toast.success('标签已确认')
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }, [reload])

  async function doDelete() {
    if (!deleteItem) return
    setDeleting(true)
    setBusy((b) => ({ ...b, [deleteItem.key]: true }))
    try {
      if (deleteItem.kind === 'local') {
        await apiJson(`/api/videos/${deleteItem.id}`, { method: 'DELETE' })
      } else {
        await apiJson(`/api/works/${deleteItem.id}?kind=${deleteItem.type === 'work' ? 'work' : 'post'}`, { method: 'DELETE' })
      }
      toast.success('已删除')
      setDeleteItem(null)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setDeleting(false)
      setBusy((b) => {
        const n = { ...b }
        delete n[deleteItem.key]
        return n
      })
    }
  }

  async function doSplit() {
    if (!splitItem) return
    const key = splitItem.key
    setBusy((b) => ({ ...b, [key]: true }))  // 拆分即时反馈（卡片 spinner）
    try {
      await apiJson(`/api/works/${splitItem.id}/split`, { method: 'POST', body: JSON.stringify({ platform_post_ids: [] }) })
      toast.success('已拆分')
      setSplitItem(null)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy((b) => {
        const n = { ...b }
        delete n[key]
        return n
      })
    }
  }

  async function autoMergeAll() {
    try {
      const r = await apiJson<{ merged?: number; message?: string }>('/api/works/auto-merge', { method: 'POST', body: '{}' })
      toast.success(r.message || `自动合并完成（${r.merged ?? 0} 组）`)
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const toggleSel = useCallback((it: CardItem) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(it.key)) next.delete(it.key)
      else next.add(it.key)
      return next
    })
  }, [])

  const selectedCards = cards.filter((c) => selected.has(c.key))
  const cloudCount = selectedCards.filter((c) => c.kind === 'cloud').length

  async function batch(action: 'merge' | 'sync' | 'delete') {
    setBatchBusy(action)
    try {
      if (action === 'merge') {
        const ids = [...new Set(selectedCards.filter((c) => c.kind === 'cloud').flatMap((c) => c.cloudPosts.map((p) => p.id)))]
        await apiJson('/api/works/merge', { method: 'POST', body: JSON.stringify({ platform_post_ids: ids }) })
        toast.success('已合并所选')
      } else if (action === 'sync') {
        for (const c of selectedCards) {
           
          await onSyncCb(c).catch(() => undefined)
        }
      } else {
        for (const c of selectedCards) {
           
          await apiJson(c.kind === 'local' ? `/api/videos/${c.id}` : `/api/works/${c.id}?kind=${c.type === 'work' ? 'work' : 'post'}`, { method: 'DELETE' })
        }
        toast.success(`已删除 ${selectedCards.length} 项`)
      }
      setSelectMode(false)
      setSelected(new Set())
      reload()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBatchBusy('')
    }
  }

  async function onRewrite(videoId: number) {
    if (rewriting) return
    setRewriting(true)
    try {
      const d = await apiJson<{ task_id: number }>('/api/benchmark/rewrite-source', {
        method: 'POST',
        body: JSON.stringify({ video_id: videoId })
      })
      toast.info('洗稿进行中（双模型讨论）…')
      const poll = async () => {
        for (;;) {
          await new Promise((r) => setTimeout(r, 2000))
          const t = await apiJson<{ status: string; result?: string; error?: string }>(`/api/tasks/${d.task_id}`)
          if (t.status === 'done') {
            let draftId = 0
            try {
              draftId = Number(JSON.parse(t.result || '{}').draft_id || 0)
            } catch {
              /* ignore */
            }
            toast.success(`洗稿完成${draftId ? `，已存草稿 #${draftId}` : ''}`)
            setRewriting(false)
            navigate(draftId ? `/drafts?id=${draftId}` : '/drafts')
            return
          }
          if (t.status === 'failed') {
            toast.error(t.error || '洗稿失败')
            setRewriting(false)
            return
          }
        }
      }
      void poll()
    } catch (e) {
      setRewriting(false)
      toast.error((e as Error).message)
    }
  }

  // ---------- 渲染 ----------
  const creatorOptions = creatorsQ.data ?? []
  const loading = videosQ.isLoading || worksQ.isLoading

  return (
    <motion.div variants={listVariants} initial="initial" animate="animate" className="space-y-4">
      {/* 上传 + 工具栏 */}
      <motion.div variants={listVariants} className="flex flex-wrap items-center gap-2">
        <input
          ref={uploadInputRef}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && doUpload(e.target.files[0])}
        />
        <Button size="sm" onClick={() => uploadInputRef.current?.click()} disabled={uploading}>
          {uploading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          {uploading ? '上传中…' : '上传视频'}
        </Button>

        <Select
          value={String(filters.creatorId)}
          onValueChange={(v) => setFilters({ ...filters, creatorId: Number(v) })}
        >
          <SelectTrigger className="h-9 w-44"><SelectValue placeholder="博主（默认当前主博主）" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="0">当前主博主</SelectItem>
            {creatorOptions.map((c) => (
              <SelectItem key={c.id} value={String(c.id)}>
                {c.name}{c.kind === 'benchmark' ? '（对标）' : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <MultiSelect
          options={['douyin', 'xiaohongshu', 'bilibili']}
          value={filters.platforms}
          onChange={(v) => setFilters({ ...filters, platforms: v })}
          placeholder="平台"
          className="w-32"
        />
        <Select value={filters.status || 'all'} onValueChange={(v) => setFilters({ ...filters, status: v === 'all' ? '' : v })}>
          <SelectTrigger className="h-9 w-28"><SelectValue placeholder="状态" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value="planned">待发布</SelectItem>
            <SelectItem value="published">已发布</SelectItem>
          </SelectContent>
        </Select>
        <Select value={filters.video || 'all'} onValueChange={(v) => setFilters({ ...filters, video: v === 'all' ? '' : v })}>
          <SelectTrigger className="h-9 w-28"><SelectValue placeholder="视频" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">有无视频</SelectItem>
            <SelectItem value="yes">有视频</SelectItem>
            <SelectItem value="no">无视频</SelectItem>
          </SelectContent>
        </Select>
        <Select value={filters.ad || 'all'} onValueChange={(v) => setFilters({ ...filters, ad: v === 'all' ? '' : v })}>
          <SelectTrigger className="h-9 w-24"><SelectValue placeholder="广告" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">广告</SelectItem>
            <SelectItem value="ad">仅广告</SelectItem>
            <SelectItem value="no">非广告</SelectItem>
          </SelectContent>
        </Select>
        <Input
          value={filters.kw}
          onChange={(e) => setFilters({ ...filters, kw: e.target.value })}
          placeholder="搜索标题…"
          className="h-9 w-36"
          onKeyDown={(e) => e.key === 'Enter' && setApplied({ ...filters })}
        />
        <MultiSelect options={allTags} value={filters.tags} onChange={(v) => setFilters({ ...filters, tags: v })} placeholder="标签" className="w-32" />
        <Input
          type="number"
          min={0}
          value={filters.likesMin ?? ''}
          onChange={(e) => setFilters({ ...filters, likesMin: e.target.value === '' ? null : Number(e.target.value) })}
          placeholder="≥ 点赞"
          className="h-9 w-24"
        />
        <Input
          type="number"
          min={0}
          value={filters.likesMax ?? ''}
          onChange={(e) => setFilters({ ...filters, likesMax: e.target.value === '' ? null : Number(e.target.value) })}
          placeholder="≤ 点赞"
          className="h-9 w-24"
        />
        <Button size="sm" onClick={() => setApplied({ ...filters })}>查询</Button>
        <Button variant="outline" size="sm" onClick={autoMergeAll}>
          <Merge className="h-3.5 w-3.5" /> 自动合并
        </Button>
      </motion.div>

      {/* 多选栏 */}
      <div className="flex items-center gap-2">
        {!selectMode ? (
          <Button variant="secondary" size="sm" onClick={() => setSelectMode(true)}>
            <CheckSquare className="h-3.5 w-3.5" /> 多选
          </Button>
        ) : (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-accent/40 bg-accent-soft px-3 py-1.5"
          >
            <span className="text-xs text-muted-foreground">已选 {selected.size} 项</span>
            <Button size="sm" disabled={!!batchBusy || cloudCount < 2} onClick={() => batch('merge')}>
              {batchBusy === 'merge' ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Layers className="h-3.5 w-3.5" />}
              合并所选
            </Button>
            <Button variant="secondary" size="sm" disabled={!!batchBusy || !selected.size} onClick={() => batch('sync')}>
              {batchBusy === 'sync' ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              同步所选
            </Button>
            <Button variant="destructive" size="sm" disabled={!!batchBusy || !selected.size} onClick={() => batch('delete')}>
              {batchBusy === 'delete' ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              删除所选
            </Button>
            <Button variant="ghost" size="sm" disabled={!!batchBusy} onClick={() => { setSelectMode(false); setSelected(new Set()) }}>
              <X className="h-3.5 w-3.5" /> 取消
            </Button>
          </motion.div>
        )}
        <span className="text-xs text-muted-foreground">共 {filtered.length} 个素材 · 点赞筛选任一平台命中即可</span>
      </div>

      {/* 卡片墙 */}
      {loading ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="aspect-[4/5] w-full" />
          ))}
        </div>
      ) : !filtered.length ? (
        <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-sm text-muted-foreground">
          没有匹配的素材（换个关键词/标签，或去「博主管理」同步）
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <AnimatePresence mode="popLayout">
            {filtered.map((it, i) => (
              <MaterialCard
                key={it.key}
                item={it}
                index={i}
                selectMode={selectMode}
                selected={selected.has(it.key)}
                task={tasks[it.key]}
                busy={!!busy[it.key]}
                onOpen={openItem}
                onToggle={toggleSel}
                onPlay={onPlay}
                onSync={onSyncCb}
                onConfirmTags={onConfirmTags}
                onDelete={onDeleteCb}
                onSplit={onSplitCb}
              />
            ))}
          </AnimatePresence>
        </div>
      )}

      {/* 抽屉与弹窗 */}
      <EditDrawer
        videoId={editId}
        open={editId !== null}
        onClose={() => setEditId(null)}
        onSaved={reload}
        currentCreatorId={currentCreatorId}
        onPlay={(id, title) => setPlayer({ id, title })}
        onRewrite={onRewrite}
        rewriting={rewriting}
      />
      <CloudDrawer
        item={cloudItem}
        open={cloudItem !== null}
        onClose={() => setCloudItem(null)}
        onConverted={(videoId, transcribe) => {
          reload()
          if (videoId) {
            setEditId(videoId)
            if (transcribe) toast.info('已转入编辑页，可点「语音转文字」')
          }
        }}
      />
      <PlayerDialog
        videoId={player?.id ?? null}
        title={player?.title ?? ''}
        open={player !== null}
        onOpenChange={(v) => !v && setPlayer(null)}
      />
      <ConfirmDialog
        open={deleteItem !== null}
        onOpenChange={(v) => !v && setDeleteItem(null)}
        title={deleteItem?.kind === 'local' ? '删除本地素材？' : '删除云端作品记录？'}
        description={deleteItem?.kind === 'local' ? '将删除素材记录与本地文件，不可恢复' : '仅从素材库移除该记录'}
        confirmText="删除"
        destructive
        loading={deleting}
        onConfirm={doDelete}
      />
      <ConfirmDialog
        open={splitItem !== null}
        onOpenChange={(v) => !v && setSplitItem(null)}
        title="拆分合并作品？"
        description="将拆分为各平台独立作品"
        confirmText="拆分"
        onConfirm={doSplit}
      />

      {/* 底部计数 */}
      <div className="pt-1 text-right">
        <Badge variant="secondary" className="tnum">{filtered.length} / {cards.length}</Badge>
      </div>
    </motion.div>
  )
}
