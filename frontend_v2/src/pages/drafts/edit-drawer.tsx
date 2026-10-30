import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
  Cpu,
  CloudCheck,
  CloudUpload,
  CloudOff,
  CircleAlert,
  Captions,
  Sparkles,
} from 'lucide-react'
import MarkdownIt from 'markdown-it'
import { apiJson } from '@/api/client'
import { EvidencePanel } from '@/components/evidence-panel'
import { cn } from '@/lib/utils'
import { fmtDate, fmtTime } from '@/lib/format'
import { Drawer, DrawerHeader, DrawerTitle, DrawerBody, DrawerFooter } from '@/components/ui/drawer'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Select, SelectValue, SelectTrigger, SelectContent, SelectItem } from '@/components/ui/select'
import { CreatableSelect } from '@/components/ui/creatable-select'
import { CreatableMultiSelect } from '@/components/ui/creatable-multi-select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { toast } from '@/components/ui/toaster'
import { ScriptEditor } from './script-editor'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import { DraftAiStatus } from './draft-ai-status'
import { createAutoSaver, draftFingerprint, type AutoSaveStatus } from './autosave'
import { clearLocalCopy, readLocalCopy, type LocalDraftCopy } from './local-copy'
import { countNewRows, isNearBottom, maxRowId } from './discuss-follow'
import { buildDiff } from './diff'
import { itemVariants, listVariants, softIn } from '@/lib/motion'
import {
  VERSION_SOURCE,
  aiKindLabel,
  discussionModelInfo,
  discussModelLabel,
  discussRoleLabel,
  isRunRow,
  latestRun,
  type DebateState,
  type Draft,
  type DraftVersion,
  type Discussion
} from './types'
import { ThinkingDots } from '@/components/ui/thinking-dots'

const md = new MarkdownIt({ html: false, linkify: true })

/** R-178：只有「模型真的说过话」的留痕才挂模型标签（note/run 是系统行） */
const TALK_KINDS = new Set(['draft', 'critique', 'revise'])

/** R-178：模型标签（`DeepSeek · deepseek-flash`），生成方/评审方用不同底色区分 */
export function ModelChip({ label, tone }: { label: string; tone: 'gen' | 'critic' }) {
  return (
    <span
      data-testid={`model-chip-${tone}`}
      className={cn(
        'rounded px-1 py-0.5 text-[10px] font-medium',
        tone === 'gen' ? 'bg-accent-soft text-accent' : 'bg-muted text-foreground'
      )}
    >
      {label}
    </span>
  )
}

export interface DraftEditState {
  id: number
  title: string
  cover_text: string
  script: string
  video_id: number | null
  tagsText: string
  publish_platform: string
  publish_url: string
  published_at: string
}

export const EMPTY_DRAFT: DraftEditState = {
  id: 0,
  title: '',
  cover_text: '',
  script: '',
  video_id: null,
  tagsText: '',
  publish_platform: '',
  publish_url: '',
  published_at: ''
}

interface CheckInfo {
  ok: boolean
  issues: string[]
}

interface VideoOpt {
  id: number
  title: string
  filename: string
}

/** R-173：`/api/drafts/{id}/debate-status` 返回（status 为老字段=人类可读文案） */
interface DebateStatusRow {
  status?: string | null
  state?: 'running' | 'failed' | null
  kind?: string
  note?: string
  actor?: string
  phase?: string
  round?: number | null
  rounds?: number | null
}

function toDebateState(row: DebateStatusRow): DebateState | null {
  if (!row.state) return null
  return {
    state: row.state,
    kind: row.kind || '',
    note: row.note || row.status || '',
    actor: row.actor || '',
    phase: row.phase || '',
    round: row.round ?? null,
    rounds: row.rounds ?? null
  }
}

export function DraftEditDrawer({
  draft,
  state,
  setState,
  sourceRef,
  open,
  onClose,
  onSaved,
  onCreated,
  onDiscardEmpty
}: {
  draft: Draft | null // null = 新建（本地空白稿）
  state: DraftEditState
  setState: (s: DraftEditState) => void
  sourceRef?: Draft['source_ref']
  open: boolean
  onClose: () => void
  onSaved: () => void
  onCreated: (id: number) => void
  /** R-212：自动保存建出的稿被清空 → 让页面把它逻辑删除（不留空卡片） */
  onDiscardEmpty: (id: number) => void
}) {
  const navigate = useNavigate()
  const [saving, setSaving] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  const [prompterOpening, setPrompterOpening] = useState(false)
  const [preview, setPreview] = useState(false)
  const [checkInfo, setCheckInfo] = useState<CheckInfo | null>(null)
  const [reworking, setReworking] = useState(false)
  const [discussions, setDiscussions] = useState<Discussion[]>([])
  // R-173：讨论状态来自服务端（谁都能发起：抽屉里的【讨论】、素材库洗稿、回炉、AI 生成）
  const [debate, setDebate] = useState<DebateState | null>(null)
  const sawRunningRef = useRef(false) // 轮询里确认过 running（用于收尾判定，避免启动瞬间的空状态误判完成）
  const startedAtRef = useRef(0) // 自己点【讨论】的时间（乐观 running 的兜底）
  // R-227：讨论进行中实时刷新的草稿 quality（证据/论点先落库，不必等跑完）
  const [liveQuality, setLiveQuality] = useState<Draft['quality'] | null>(null)
  const [versions, setVersions] = useState<DraftVersion[]>([])
  const [cmpLeft, setCmpLeft] = useState('')
  const [cmpRight, setCmpRight] = useState('')
  const [viewVer, setViewVer] = useState<DraftVersion | null>(null)
  const [rollingBack, setRollingBack] = useState(0)
  const [videos, setVideos] = useState<VideoOpt[]>([])
  // R-224：AI 生成标题/封面字/素材标签的候选列表与任务态
  const [titleOptions, setTitleOptions] = useState<string[]>([])
  const [coverTextOptions, setCoverTextOptions] = useState<string[]>([])
  const [tagOptions, setTagOptions] = useState<string[]>([])
  const [suggesting, setSuggesting] = useState(false)
  const [suggestTaskId, setSuggestTaskId] = useState<number | null>(null)
  // R-206：tab 受控——切进「讨论」tab 时才能把最新留痕滚进视野（Radix 切 tab 会重挂 Content）
  const [tab, setTab] = useState('edit')
  const viewportRef = useRef<HTMLDivElement>(null) // 讨论留痕的滚动视口（ScrollArea 的 Viewport）
  const atBottomRef = useRef(true) // 是否贴着最新（翻看历史时不抢滚动条）
  const lastSeenIdRef = useRef(0) // 已看到的留痕 id 游标
  const [pendingNew, setPendingNew] = useState(0) // 未看到的新留痕条数（浮出「N 条新留痕 ↓」）

  // R-212/R-224：新建与已有草稿都在有改动时实时保存
  const [autoStatus, setAutoStatus] = useState<AutoSaveStatus>('idle')
  const [autoSavedAt, setAutoSavedAt] = useState<Date | null>(null)
  const [autoAttempt, setAutoAttempt] = useState(0) // R-213：离线重试次数
  const [localCopy, setLocalCopy] = useState<LocalDraftCopy | null>(null) // R-213：未同步的本地副本（提示条）
  // 常驻挂载的组件：回调与最新内容都走 ref，保存器只建一次也不会读到陈旧闭包
  const latestRef = useRef(state)
  const onCreatedRef = useRef(onCreated)
  const onDiscardEmptyRef = useRef(onDiscardEmpty)
  const onCloseRef = useRef(onClose)
  const skipOpenScheduleRef = useRef(false) // R-213：本轮打开若确有未同步副本，别被打开动作覆盖
  useEffect(() => {
    latestRef.current = state
    onCreatedRef.current = onCreated
    onDiscardEmptyRef.current = onDiscardEmpty
    onCloseRef.current = onClose
  })
  const autoSaver = useMemo(
    () =>
      createAutoSaver({
        read: () => latestRef.current,
        create: (body) => apiJson<Draft>('/api/drafts', { method: 'POST', body: JSON.stringify(body) }),
        update: async (draftId, body) => {
          await apiJson(`/api/drafts/${draftId}`, { method: 'PATCH', body: JSON.stringify(body) })
        },
        onCreate: (newId) => onCreatedRef.current(newId),
        onDiscard: (deadId) => onDiscardEmptyRef.current(deadId),
        onStatus: (s, at, attempt) => {
          setAutoStatus(s)
          if (at) setAutoSavedAt(at)
          if (attempt != null) setAutoAttempt(attempt)
          // 服务器确认落库 → 本地副本已无意义（提示条跟着收掉）
          if (s === 'saved') setLocalCopy(null)
        }
      }),
    []
  )
  // 新一轮打开：清掉上一轮的 id/指纹（组件跨会话常驻）；这层必须排在下面 schedule 之前
  useEffect(() => {
    if (!open) return
    autoSaver.reset()
    setAutoStatus('idle')
    setAutoSavedAt(null)
    setAutoAttempt(0)
    // 打开本身不算改动：把服务端内容设为自动保存基线，避免「一打开就写库 / 留本地副本」。
    // 例外：浏览器里确有一份「属于本篇且内容不同」的未同步副本——不能覆盖它，也不能被打开动作清掉。
    const cur = latestRef.current
    const copy = readLocalCopy()
    const mine = !!copy && (copy.id ? copy.id === cur.id : draft === null)
    const genuine = mine && draftFingerprint(copy.state) !== draftFingerprint(cur)
    skipOpenScheduleRef.current = genuine
    if (!genuine) autoSaver.baseline(cur)
  }, [open, draft, autoSaver])
  // R-213：打开抽屉时读一次本地副本——只认「属于当前这篇」的那份（副本 id=0 ↔ 新建草稿会话）；
  // 与服务器内容一致的是「无用副本」（上次自动保存没跑完留下的），直接丢弃，别每次都弹提示。
  useEffect(() => {
    if (!open) return
    // R-227：AI（讨论/生成/洗稿）正在写这篇草稿时，服务端内容为准——本地副本一律不提示，避免误报
    if (debate?.state === 'running') {
      clearLocalCopy()
      setLocalCopy(null)
      return
    }
    const copy = readLocalCopy()
    const mine = !!copy && (copy.id ? copy.id === state.id : draft === null)
    const same = mine && draftFingerprint(copy.state) === draftFingerprint(state)
    // 服务端在这份副本之后又更新过（如 AI 讨论完成回填）→ 副本已过期，静默丢弃，不弹提示
    const superseded =
      mine && !!draft?.updated_at && !!copy.at && Date.parse(draft.updated_at) > Date.parse(copy.at)
    if (same || superseded) clearLocalCopy()
    setLocalCopy(mine && !same && !superseded ? copy : null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, draft, state.id, debate?.state])
  // R-213：浏览器恢复联网 → 立刻重试还没落库的内容（不用干等退避）
  useEffect(() => {
    const onOnline = () => autoSaver.retryNow()
    window.addEventListener('online', onOnline)
    return () => window.removeEventListener('online', onOnline)
  }, [autoSaver])
  useEffect(() => () => autoSaver.dispose(), [autoSaver])
  // 任何一处变动（标题/封面字/正文/关联素材/标签/发布信息）都排一次自动保存
  useEffect(() => {
    if (!open) return
    // R-227：AI（讨论/生成/洗稿）正在写这篇草稿时不自动保存——否则会把后端正在生成的内容 PATCH 回去，
    // 保存失败还会在该草稿上留下误报的「本地未同步内容」。等讨论完成后由轮询回填 + markSaved 落库。
    if (debate?.state === 'running') return
    // 本轮打开若存在未同步副本，跳过这次「打开触发」的保存，别把它覆盖掉（下一次真实改动再保存）
    if (skipOpenScheduleRef.current) {
      skipOpenScheduleRef.current = false
      return
    }
    autoSaver.schedule()
  }, [open, state, autoSaver, debate?.state])

  /** R-212：关抽屉（遮罩 / X / Esc /【关闭】）时立刻补一次保存——防抖窗口里最后几个字也不丢 */
  function handleClose() {
    autoSaver.closeOut()
    onCloseRef.current()
  }

  /** R-213：把本地副本回填编辑器（回填后由自动保存负责落库；成功前本地副本不动） */
  function restoreLocalCopy() {
    if (!localCopy) return
    setLocalCopy(null)
    setState(localCopy.state)
    setAutoStatus('dirty')
    toast.success('已恢复断网时暂存的内容，正在重新保存')
  }

  /** R-213：明确丢弃这份本地副本（作者确认不要了） */
  function dropLocalCopy() {
    clearLocalCopy()
    setLocalCopy(null)
  }

  const id = state.id
  const discussing = debate?.state === 'running'

  /** R-206：滚到最新。`auto` 用于切进 tab（不能慢悠悠地滚，否则新留痕的入场动画又跑掉了） */
  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const vp = viewportRef.current
    if (!vp) return
    vp.scrollTo({ top: vp.scrollHeight, behavior })
    atBottomRef.current = true
    setPendingNew(0)
  }, [])

  /** R-173：取一次服务端 AI 状态（打开抽屉、回炉后都用它同步） */
  async function refreshDebate(targetId = id) {
    if (!targetId) return
    try {
      const row = await apiJson<DebateStatusRow>(`/api/drafts/${targetId}/debate-status`)
      if (row.state === 'running') sawRunningRef.current = true
      setDebate(toDebateState(row))
    } catch {
      /* 抖动忽略 */
    }
  }

  // 关联素材选项
  useEffect(() => {
    if (!open) return
    apiJson<{ items: VideoOpt[] }>('/api/videos?limit=500')
      .then((r) => setVideos(r.items ?? []))
      .catch(() => setVideos([]))
  }, [open])

  // 讨论/版本随 id 加载
  useEffect(() => {
    // R-206：tab 改成受控后关闭抽屉不会连带卸载 Tabs，这里显式复位，保持「每次打开都从编辑 tab 开始」
    if (!open) setTab('edit')
    sawRunningRef.current = false
    startedAtRef.current = 0
    // R-206：换草稿要清掉「跟随最新」的游标，否则新稿的历史留痕会被当成新消息
    lastSeenIdRef.current = 0
    atBottomRef.current = true
    setPendingNew(0)
    setLiveQuality(null)
    if (!open || !id) {
      setDiscussions([])
      setVersions([])
      setCheckInfo(null)
      setDebate(null)
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
    // R-173：打开抽屉时先取一次 AI 状态——别人（素材库洗稿/回炉/生成）发起的任务也能看到进度
    void refreshDebate(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, id])

  // 讨论轮询（R-173：以服务端 state 为准；不再等 done/idle/failed 三个永远不出现的值）
  useEffect(() => {
    if (!discussing || !id) return
    const timer = setInterval(async () => {
      try {
        const row = await apiJson<DebateStatusRow>(`/api/drafts/${id}/debate-status`)
        const rows = await apiJson<Discussion[]>(`/api/drafts/${id}/discussions`)
        setDiscussions(rows)
        if (row.state === 'running') {
          sawRunningRef.current = true
          setDebate(toDebateState(row))
          // R-227：讨论进行中就把「豆包搜索词 / 论点 / 引用来源」拉出来展示
          try {
            const dq = await apiJson<Draft>(`/api/drafts/${id}`)
            setLiveQuality(dq.quality ?? null)
          } catch {
            /* 抖动继续 */
          }
          return
        }
        // 状态已消失/失败：还没确认「跑起来过」时容忍刚入队的空窗，避免误判完成
        const graceOver = startedAtRef.current > 0 && Date.now() - startedAtRef.current > 6000
        if (!sawRunningRef.current && !graceOver) return
        const next = toDebateState(row)
        setDebate(next)
        if (next && next.state === 'failed') toast.warning(next.note || '讨论中断')
        else toast.success('讨论完成，正文已更新')
        onSaved()
        const d = await apiJson<Draft>(`/api/drafts/${id}`)
        setLiveQuality(d.quality ?? null)
        const synced: DraftEditState = {
          id: d.id,
          title: d.title,
          cover_text: d.cover_text,
          script: d.script,
          video_id: d.video_id ?? null,
          tagsText: (d.tags || []).join(', '),
          publish_platform: d.publish_platform || '',
          publish_url: d.publish_url || '',
          published_at: d.published_at || ''
        }
        setState(synced)
        // R-212：这是服务端刚写回来的内容，标记已落库，别让自动保存再重复 PATCH 一遍
        autoSaver.markSaved(synced)
      } catch {
        /* 抖动继续 */
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [discussing, id, onSaved, setState, autoSaver])

  // R-178：最近一次讨论的运行头（配置的生成方/评审方）——必须在 early return 之前，遵守 hooks 规则
  const currentRun = useMemo(() => latestRun(discussions), [discussions])
  const versionsDesc = useMemo(() => [...versions].sort((a, b) => b.id - a.id), [versions])
  const bodyDiff = useMemo(() => {
    const l = versions.find((v) => String(v.id) === cmpLeft)
    const r = versions.find((v) => String(v.id) === cmpRight)
    if (!l || !r) return null
    return buildDiff(l.script || '', r.script || '')
  }, [cmpLeft, cmpRight, versions])

  // R-206：讨论留痕是「只往下长」的直播式列表——贴底时自动跟随最新，翻看历史时只累加提示。
  useEffect(() => {
    const maxId = maxRowId(discussions)
    if (!maxId) return
    const firstLoad = lastSeenIdRef.current === 0
    const added = countNewRows(discussions, lastSeenIdRef.current)
    lastSeenIdRef.current = maxId
    if (firstLoad) {
      // 首次加载：讨论在跑就直接贴底（最新在最下面）；已结束则从头看
      if (discussing) scrollToBottom('auto')
      return
    }
    if (!added) return
    if (atBottomRef.current) scrollToBottom()
    else setPendingNew((n) => n + added)
  }, [discussions, discussing, scrollToBottom])

  // R-206：「是否贴底」必须在**滚动视口挂载的那一刻**接管。实测 Radix 的 TabsContent 比这一层
  // 晚一个 commit 才把内容挂上（`[tab]` 的 effect 里 ref 与 DOM 都还是 null），所以用回调 ref。
  const detachScrollRef = useRef<(() => void) | null>(null)
  const attachViewport = useCallback((el: HTMLDivElement | null) => {
    detachScrollRef.current?.()
    detachScrollRef.current = null
    viewportRef.current = el
    if (!el) return
    const onScroll = () => {
      const near = isNearBottom(el)
      atBottomRef.current = near
      if (near) setPendingNew(0)
    }
    onScroll()
    el.addEventListener('scroll', onScroll, { passive: true })
    detachScrollRef.current = () => el.removeEventListener('scroll', onScroll)
  }, [])

  // R-206：切进「讨论」tab 时若讨论正在跑，直接落到底部——否则新留痕的入场动画又播在屏幕外
  useEffect(() => {
    if (tab !== 'discuss' || !discussing) return
    const raf = requestAnimationFrame(() => scrollToBottom('auto'))
    return () => cancelAnimationFrame(raf)
  }, [tab, discussing, scrollToBottom])

  const canDiscuss = !!(state.script.trim() || draft?.original_script?.trim())

  // R-224：打开/切换草稿时，用当前已有值作为候选列表首项。
  // 只填候选、**不写编辑态**——否则「打开抽屉」本身就算一次改动，会被实时保存当成新内容造出空稿。
  useEffect(() => {
    if (!open) return
    const tags = state.tagsText.split(/[,，]/).map((x) => x.trim()).filter(Boolean)
    setTitleOptions(state.title ? [state.title] : [])
    setCoverTextOptions(state.cover_text ? [state.cover_text] : [])
    setTagOptions(tags)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, state.id])

  // R-224：恢复页面刷新前未完成的生成任务
  useEffect(() => {
    if (!open || !id) return
    const saved = window.localStorage.getItem(`draft_suggest_meta:${id}`)
    if (saved) {
      setSuggestTaskId(Number(saved))
      setSuggesting(true)
    }
  }, [open, id])

  // R-224：轮询生成任务（只有任务到达终态才收尾；running/pending 必须继续轮询）
  useEffect(() => {
    if (!suggestTaskId || !id) return
    setSuggesting(true)
    function finish() {
      setSuggesting(false)
      setSuggestTaskId(null)
      window.localStorage.removeItem(`draft_suggest_meta:${id}`)
    }
    const timer = setInterval(async () => {
      try {
        const task = await apiJson<{ id: number; status: string; result: string; error: string }>(`/api/tasks/${suggestTaskId}`)
        if (task.status === 'running' || task.status === 'pending') return
        clearInterval(timer)
        if (task.status === 'done') {
          const data = JSON.parse(task.result || '{}') as {
            titles?: string[]
            cover_texts?: string[]
            tags?: string[]
          }
          const newTitles = data.titles || []
          const newCovers = data.cover_texts || []
          const newTags = data.tags || []
          setTitleOptions((prev) => [...new Set([...prev, ...newTitles])])
          setCoverTextOptions((prev) => [...new Set([...prev, ...newCovers])])
          setTagOptions((prev) => [...new Set([...prev, ...newTags])])
          const total = newTitles.length + newCovers.length + newTags.length
          toast.success(`已生成 ${total} 条候选，请从下拉框选择`)
        } else {
          toast.error(task.error || '生成失败')
        }
        finish()
      } catch (e) {
        clearInterval(timer)
        toast.error((e as Error).message)
        finish()
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [suggestTaskId, id])

  async function suggestMeta() {
    if (!id || suggesting) return
    setSuggesting(true)
    try {
      const res = await apiJson<{ task_id: number }>(`/api/drafts/${id}/suggest-meta`, { method: 'POST', body: '{}' })
      setSuggestTaskId(res.task_id)
      window.localStorage.setItem(`draft_suggest_meta:${id}`, String(res.task_id))
    } catch (e) {
      toast.error((e as Error).message)
      setSuggesting(false)
    }
  }

  // R-205：不再 `if (!open) return null` —— 否则父组件先卸载，抽屉的退出动画根本没机会播。
  async function ensureSaved(): Promise<number> {
    const body = {
      title: state.title,
      cover_text: state.cover_text,
      script: state.script,
      video_id: state.video_id,
      tags: state.tagsText.split(/[,，]/).map((x) => x.trim()).filter(Boolean),
      publish_platform: state.publish_platform,
      publish_url: state.publish_url,
      published_at: state.published_at || null
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

  /** R-214：进提词器前先把当前改动补存（提词页按 id 只读拉取，保证与眼前这版一致） */
  async function openPrompter() {
    if (!state.script.trim()) return
    setPrompterOpening(true)
    try {
      const did = await ensureSaved()
      autoSaver.markSaved(state)
      navigate(`/prompter/${did}`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setPrompterOpening(false)
    }
  }

  async function save() {
    if (!state.title.trim() && !state.script.trim() && !state.cover_text.trim()) {
      toast.warning('内容为空，未保存')
      return
    }
    setSaving(true)
    try {
      await ensureSaved()
      autoSaver.markSaved(state) // R-212：已手动落库，别再补一次自动保存
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
      void refreshDebate(id) // R-173：回炉期间也显示「正在回炉重写…」状态条
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
      // R-173：乐观进入 running（后端 worker 接手后会写入真实步骤）
      sawRunningRef.current = false
      startedAtRef.current = Date.now()
      setDebate({ state: 'running', kind: 'discuss', note: '讨论已入队，正在准备…', actor: '', phase: 'queued', round: null, rounds: null })
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

  // R-178：本篇生成模型优先用「最近一次讨论的运行头」（切模型后仍显示当时那次），quality 兜底
  const info = draft ? discussionModelInfo(discussions, draft) : ''
  const q = draft?.quality || {}
  // R-227：优先用讨论中实时拉到的 quality（证据先落库），否则用打开时的草稿
  const evi = liveQuality ?? draft?.quality

  return (
    <Drawer open={open} onOpenChange={(v) => !v && handleClose()} width="min(860px, 96vw)">
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
        {/* R-213：断网/后端不可达时留在浏览器里的那一次改动——不静默覆盖服务端内容，让作者选 */}
        <AnimatePresence>
          {!!localCopy && (
            <motion.div
              data-testid="draft-local-copy"
              initial={{ opacity: 0.85, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0.85, y: -6, transition: { duration: 0.15 } }}
              transition={softIn}
              className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs"
            >
              <CloudOff className="h-3.5 w-3.5 shrink-0 text-warning" />
              <span className="flex-1">
                发现一份<b>没同步到服务器</b>的本地内容
                {fmtTime(localCopy.at) ? `（${fmtTime(localCopy.at)} 暂存）` : ''}，要恢复到编辑器吗？
              </span>
              <Button size="sm" className="h-6 px-2 text-[11px]" onClick={restoreLocalCopy}>恢复</Button>
              <Button variant="ghost" size="sm" className="h-6 px-2 text-[11px]" onClick={dropLocalCopy}>丢弃</Button>
            </motion.div>
          )}
        </AnimatePresence>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">标题</label>
              <CreatableSelect
                value={state.title}
                options={titleOptions}
                onChange={(v) => setState({ ...state, title: v })}
                placeholder="视频标题"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">封面字（3-8 字）</label>
              <CreatableSelect
                value={state.cover_text}
                options={coverTextOptions}
                onChange={(v) => setState({ ...state, cover_text: v })}
                placeholder="封面字"
              />
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
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">素材标签</label>
              <CreatableMultiSelect
                options={tagOptions}
                value={state.tagsText.split(/[,，]/).map((x) => x.trim()).filter(Boolean)}
                onChange={(v) => setState({ ...state, tagsText: v.join(', ') })}
                placeholder="选择或输入标签"
              />
            </div>
          </div>
          {/* R-184 发布回填：记录发布链接/平台/时间，关联素材后可看表现 */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">发布平台（可选）</label>
              <Select value={state.publish_platform || 'none'} onValueChange={(v) => setState({ ...state, publish_platform: v === 'none' ? '' : v })}>
                <SelectTrigger className="h-9"><SelectValue placeholder="未发布" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">未发布</SelectItem>
                  <SelectItem value="douyin">抖音</SelectItem>
                  <SelectItem value="bilibili">B站</SelectItem>
                  <SelectItem value="xiaohongshu">小红书</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">发布链接（可选）</label>
              <Input value={state.publish_url} onChange={(e) => setState({ ...state, publish_url: e.target.value })} placeholder="粘贴作品链接" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">发布时间（可选）</label>
              <Input type="datetime-local" value={state.published_at ? state.published_at.slice(0, 16) : ''} onChange={(e) => setState({ ...state, published_at: e.target.value })} />
            </div>
          </div>
        </div>

        {/* R-206：受控 Tabs —— 切进讨论 tab 时要能把最新留痕滚进视野 */}
        <Tabs value={tab} onValueChange={setTab} className="mt-4">
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
              {/* R-224：AI 生成标题/封面字/素材标签 */}
              <Button
                variant="ghost"
                size="sm"
                data-testid="draft-suggest-meta"
                disabled={!id || !state.script.trim() || suggesting}
                title={!id ? '先保存草稿' : !state.script.trim() ? '正文为空，无法生成' : '基于正文和人设生成候选'}
                onClick={() => void suggestMeta()}
              >
                {suggesting ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                AI标题
              </Button>
              {/* R-214：一键进全屏提词器（先补存当前改动，提词页读到的一定是眼前这版；只读不回写） */}
              <Button
                variant="ghost"
                size="sm"
                data-testid="draft-prompter"
                disabled={!state.script.trim()}
                title={state.script.trim() ? '全屏提词 + 录像（先保存当前内容再进入）' : '正文为空，无法提词'}
                onClick={() => void openPrompter()}
              >
                {prompterOpening ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Captions className="h-3.5 w-3.5" />}
                提词器
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setPreview(!preview)}>
                {preview ? <Pencil className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                {preview ? '返回编辑' : '预览'}
              </Button>
            </div>
            {/* R-173/R-227：AI 讨论/生成进行中，正文置灰只读，中间浮出「哪个模型在干嘛」动画 */}
            <div className="relative">
              <div className={cn(discussing && 'pointer-events-none select-none opacity-50')}>
                {preview ? (
                  <div
                    className="prose-echo min-h-72 rounded-lg border border-border px-4 py-3 text-sm"
                    dangerouslySetInnerHTML={{ __html: md.render(state.script || '') }}
                  />
                ) : (
                  <ErrorBoundary
                    fallback={
                      <div className="space-y-2">
                        <p className="text-xs text-warning">块编辑器加载失败，已切换为纯文本编辑（内容不会丢）</p>
                        <Textarea
                          rows={14}
                          value={state.script}
                          disabled={discussing}
                          onChange={(e) => setState({ ...state, script: e.target.value })}
                        />
                      </div>
                    }
                  >
                    <ScriptEditor value={state.script} onChange={(v) => setState({ ...state, script: v })} />
                  </ErrorBoundary>
                )}
              </div>
              <AnimatePresence>
                {discussing && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-background/60 backdrop-blur-[2px]"
                  >
                    <motion.div
                      initial={{ opacity: 0.9, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={softIn}
                      className="mx-4 rounded-xl border border-accent/30 bg-card/95 px-6 py-5 text-center shadow-sm"
                    >
                      <div className="mx-auto mb-2 flex justify-center">
                        <ThinkingDots />
                      </div>
                      <div className="text-sm font-medium text-accent">
                        {aiKindLabel(debate?.kind)}进行中
                      </div>
                      <div className="mt-1 max-w-[16rem] text-xs leading-relaxed text-muted-foreground">
                        {debate?.note || 'AI 处理中…'}
                      </div>
                      {!!(debate?.round && debate?.rounds) && (
                        <div className="tnum mt-1 text-[11px] text-muted-foreground/80">
                          第 {debate.round}/{debate.rounds} 轮
                        </div>
                      )}
                    </motion.div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

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
                {/* R-173：顶部状态条——正在思考的模型 + 三点跳动 + 第 x/y 轮；中断时给出标记 */}
                {/* R-206：key 只跟 state（running↔failed）。原先 key 含 note，讨论每换一步就整条重挂：
                    三点动画被打断重来、状态区先空一下、下面的留痕列表被顶上顶下 */}
                {/* R-206：**不能**给这层 `initial={false}`——它会让子组件的 `initial` 变成 false，
                    三点跳动的关键帧动画（`opacity:[…]`/`y:[…]` 循环）会停在第一帧不再跑（生产包实测：98 帧里
                    `opacity` 恒 0.25、`transform` 恒 none、零个 WAAPI 动画）。草稿页卡片的同一组件没有这层就没问题。 */}
                <AnimatePresence>
                  {!!debate && <DraftAiStatus key={debate.state} debate={debate} />}
                </AnimatePresence>
                {!discussions.length && !discussing && (
                  <div className="flex h-32 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
                    <MessageSquare className="h-5 w-5" />
                    暂无讨论记录
                    <Button size="sm" disabled={!canDiscuss} onClick={startDiscussion}>讨论</Button>
                    {!canDiscuss && <span className="text-xs">这篇草稿没有可讨论的原文或正文</span>}
                  </div>
                )}
                {/* R-178：本次讨论用的是哪两个模型（最近一次运行头，切模型后仍显示历史那次） */}
                {!!currentRun && (
                  <motion.div
                    initial={{ opacity: 0.85, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={softIn}
                    className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-muted/40 px-2.5 py-2 text-[11px]"
                  >
                    <Cpu className="h-3.5 w-3.5 shrink-0 text-accent" />
                    <span className="text-muted-foreground">本次讨论：</span>
                    <ModelChip label={currentRun.gen} tone="gen" />
                    <span className="text-muted-foreground">×</span>
                    <ModelChip label={currentRun.critic} tone="critic" />
                    {!!currentRun.rounds && (
                      <span className="text-muted-foreground">
                        · 讨论 {currentRun.rounds_done ?? currentRun.rounds}/{currentRun.rounds} 轮
                      </span>
                    )}
                    {currentRun.degraded === true && <Badge variant="warning">存在降级</Badge>}
                  </motion.div>
                )}
                {/* R-207：生成自检（红线=硬问题；口癖/高频词覆盖率/AI 腔词=只诊断、不触发重写） */}
                {!!draft?.quality?.diagnostics && (
                  <div className="rounded-lg border border-border p-2.5">
                    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                      <Stethoscope className="h-3.5 w-3.5 shrink-0 text-accent" />
                      <span className="font-medium">生成自检</span>
                      {draft.quality.passed === false ? (
                        <Badge variant="destructive" className="text-[10px]">踩红线</Badge>
                      ) : (
                        <Badge variant="success" className="text-[10px]">无红线</Badge>
                      )}
                      <span className="tnum text-muted-foreground">
                        像作者 {Math.round((draft.quality.diagnostics.style_coverage ?? 0) * 100)}%
                      </span>
                      <span className="text-muted-foreground/70">（口癖/高频词覆盖率仅诊断，不作为重写依据）</span>
                    </div>
                    {!!draft.quality.issues?.length && (
                      <ul className="mt-1 list-inside list-disc text-[11px] text-destructive">
                        {draft.quality.issues.map((iss, i) => (
                          <li key={i}>{iss}</li>
                        ))}
                      </ul>
                    )}
                    {!!(draft.quality.diagnostics.style_matched?.length || draft.quality.diagnostics.style_missing?.length) && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-1">
                        {(draft.quality.diagnostics.style_matched || []).map((w) => (
                          <Badge key={w} variant="success" className="text-[10px]">{w}</Badge>
                        ))}
                        {(draft.quality.diagnostics.style_missing || []).map((w) => (
                          <span key={w} className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{w}</span>
                        ))}
                      </div>
                    )}
                    {!!draft.quality.diagnostics.ai_cliche?.length && (
                      <p className="mt-1 text-[11px] text-warning">
                        AI 腔词：{draft.quality.diagnostics.ai_cliche.join('、')}
                      </p>
                    )}
                  </div>
                )}
                {/* R-227：本篇论点 + 联网引用来源（可切换标签、右侧可收起） */}
                <EvidencePanel
                  outlines={evi?.outlines}
                  outline={evi?.outline}
                  sources={evi?.sources}
                  onlineSources={evi?.online_sources}
                  references={evi?.references}
                  queries={evi?.search_queries}
                  station={evi?.station}
                  outlineDrift={!!evi?.outline_drift}
                />
                <div className="relative">
                  <ScrollArea className="max-h-[52vh]" viewportRef={attachViewport}>
                    {/* R-206：用标准列表入场（`listVariants` + `itemVariants`，与草稿页卡片墙同一套观感）。
                        原先外层 `initial={false}` 把「切进 tab 时已经在的这批留痕」的入场动画整个吃掉（实测 110 帧 0 帧在动），
                        后来改成单条 `softIn`（0.85→1 + y10）又太轻——作者反馈「手动切到讨论 tab 没有动画」，逐帧截图确认肉眼分辨不出。
                        注意：这里**不能**再用 `initial={false}`，否则又变回「一进 tab 就全在」。 */}
                    <motion.div variants={listVariants} initial="initial" animate="animate" className="space-y-2.5 pr-2">
                      <AnimatePresence>
                        {discussions.filter((m) => !isRunRow(m)).map((m) => (
                          <motion.div
                            key={m.id}
                            variants={itemVariants}
                            className={cn(
                              'rounded-lg border px-3 py-2.5',
                              m.kind === 'critique' ? 'border-accent/30 bg-accent-soft/40' : 'border-border bg-muted/40'
                            )}
                          >
                            <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
                              <b>{discussRoleLabel(m)}</b>
                              {/* R-178：显示真实模型 + 版本，不再显示 model1/model2（系统说明行没有模型，不挂标签） */}
                              {TALK_KINDS.has(m.kind) && (
                                <motion.span
                                  initial={{ opacity: 0.85 }}
                                  animate={{ opacity: 1 }}
                                  transition={softIn}
                                  className={cn(
                                    'rounded px-1 py-0.5 text-[10px]',
                                    m.model_label ? 'bg-accent-soft text-accent' : 'bg-muted text-muted-foreground'
                                  )}
                                  title={m.model_id ? `${m.vendor}/${m.model_id}` : '这条留痕产生时还没有记录模型版本'}
                                >
                                  {discussModelLabel(m)}
                                </motion.span>
                              )}
                              <span className="text-muted-foreground">
                                {{ draft: '初稿', critique: '评审', revise: '修订', note: '说明' }[m.kind as string] || m.kind} · 第{m.round}轮
                              </span>
                              {!!m.created_at && (
                                <span className="text-muted-foreground/70">{fmtDate(m.created_at)}</span>
                              )}
                            </div>
                            <p className="whitespace-pre-wrap text-xs leading-relaxed">{m.content}</p>
                          </motion.div>
                        ))}
                      </AnimatePresence>
                    </motion.div>
                  </ScrollArea>
                  {/* R-206：作者向上翻看历史时不抢滚动条，改成可点的「N 条新留痕 ↓」。
                      钉在滚动区**右上角**（不是底部）：DrawerBody 本身可滚，tab 内容比可视区高
                      （标题/封面上方那半屏表单 + 列表 52vh），底部的浮层会被 body 裁掉一半；
                      顶端则始终在视野内，且作者翻历史时正好在看这一带。用实底 `bg-card` 才压得住正文。 */}
                  <div className="pointer-events-none absolute right-2 top-2 z-10">
                    <AnimatePresence initial={false}>
                      {pendingNew > 0 && (
                        <motion.button
                          key="pending-new"
                          data-testid="discuss-new-badge"
                          initial={{ opacity: 0.85, y: -6 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -6, transition: { duration: 0.15 } }}
                          transition={softIn}
                          onClick={() => scrollToBottom()}
                          className="pointer-events-auto cursor-pointer rounded-full border border-accent/40 bg-card px-3 py-1 text-[11px] font-medium text-accent shadow-[var(--shadow-card)]"
                        >
                          {pendingNew} 条新留痕 ↓
                        </motion.button>
                      )}
                    </AnimatePresence>
                  </div>
                </div>
                {!discussing && (!!discussions.length || debate?.state === 'failed') && (
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
        {/* R-212/R-224：新建与已有草稿的改动都会自动落库，这里常驻「保存中 / 已自动保存 HH:MM」状态位（R-202：进行中必须可见） */}
        <motion.span
          key={autoStatus}
          data-testid="draft-autosave"
          data-state={autoStatus}
          initial={{ opacity: 0.85, y: 3 }}
          animate={{ opacity: 1, y: 0 }}
          transition={softIn}
          className={cn(
            'flex items-center gap-1 text-[11px]',
            autoStatus === 'error' ? 'text-warning' : 'text-muted-foreground'
          )}
        >
          {autoStatus === 'offline' ? (
            <>
              <CloudOff className="h-3 w-3 text-warning" />
              连不上服务器，已本地暂存{autoAttempt > 1 ? `（重试 ${autoAttempt}）` : ''}
            </>
          ) : autoStatus === 'dirty' || autoStatus === 'saving' ? (
            <>
              <LoaderCircle className="h-3 w-3 animate-spin" />
              保存中…
            </>
          ) : autoStatus === 'saved' ? (
            <>
              <CloudCheck className="h-3 w-3 text-accent" />
              已自动保存{autoSavedAt ? ` ${fmtTime(autoSavedAt)}` : ''}
            </>
          ) : autoStatus === 'error' ? (
            <>
              <CircleAlert className="h-3 w-3" />
              自动保存失败，点【保存】重试
            </>
          ) : (
            <>
              <CloudUpload className="h-3 w-3" />
              改动会自动保存
            </>
          )}
        </motion.span>
        <Button variant="ghost" size="sm" onClick={handleClose}>
          <X className="h-3.5 w-3.5" /> 关闭
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
