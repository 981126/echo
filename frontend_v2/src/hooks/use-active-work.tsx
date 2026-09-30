// R-202：全局「进行中」事实源的客户端镜像。
// 三段式刷新：① 挂载/周期回扫 GET /api/tasks?status=pending,running（+ 平台同步 jobs）
// ② SSE task.update / sync.job 实时增量 ③ 有进行中项时 10s 轮询兜底（SSE 断线不重放事件）。
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react'
import { apiJson } from '@/api/client'
import { subscribeEvents } from '@/api/sse'
import type { SyncJobEvent, TaskUpdateEvent } from '@/api/types'

export interface ActiveItem {
  key: string // `task:12` | `sync:3`
  source: 'task' | 'sync'
  id: number
  kind: string
  label: string
  status: string
  progress: number
  note: string
  target: string
  payload: Record<string, unknown>
}

interface TaskRow {
  id: number
  kind: string
  status: string
  progress?: number
  note?: string
  label?: string
  target?: string
  payload?: unknown
}

interface SyncJob {
  id: number
  creator_id?: number | null
  status: string
  progress_done?: number
  progress_total?: number
  progress_note?: string
  message?: string
  scope?: string
}

const ACTIVE = new Set(['pending', 'running'])

function parsePayload(p: unknown): Record<string, unknown> {
  if (!p) return {}
  if (typeof p === 'string') {
    try {
      return JSON.parse(p) as Record<string, unknown>
    } catch {
      return {}
    }
  }
  return (p as Record<string, unknown>) || {}
}

export function taskRowToActiveItem(r: TaskRow): ActiveItem {
  return {
    key: `task:${r.id}`,
    source: 'task',
    id: r.id,
    kind: r.kind,
    label: r.label || r.kind,
    status: r.status,
    progress: Math.max(0, Math.min(100, Number(r.progress) || 0)),
    note: r.note || '',
    target: r.target || '',
    payload: parsePayload(r.payload)
  }
}

export function syncJobToActiveItem(j: SyncJob): ActiveItem {
  const total = Number(j.progress_total) || 0
  const done = Number(j.progress_done) || 0
  const pct = total > 0 ? Math.round((done / total) * 100) : done > 0 ? 40 : 5
  return {
    key: `sync:${j.id}`,
    source: 'sync',
    id: j.id,
    kind: 'platform_sync',
    label: '平台数据同步',
    status: j.status,
    progress: Math.max(0, Math.min(100, pct)),
    note: j.progress_note || j.message || '同步中…',
    target: '/creators',
    payload: { creator_id: j.creator_id ?? undefined, scope: j.scope }
  }
}

interface ActiveWorkCtx {
  items: ActiveItem[]
  tasks: ActiveItem[]
  has: (pred: (t: ActiveItem) => boolean) => boolean
  find: (pred: (t: ActiveItem) => boolean) => ActiveItem | undefined
}

const fallback: ActiveWorkCtx = { items: [], tasks: [], has: () => false, find: () => undefined }
const Ctx = createContext<ActiveWorkCtx>(fallback)

export function ActiveWorkProvider({ children }: { children: ReactNode }) {
  const [map, setMap] = useState<Record<string, ActiveItem>>({})
  const inflight = useRef(false)

  const rescan = useCallback(async () => {
    if (inflight.current) return
    inflight.current = true
    try {
      const [tasks, jobs] = await Promise.all([
        apiJson<TaskRow[]>('/api/tasks?status=pending,running&limit=200').catch(() => [] as TaskRow[]),
        apiJson<{ items: SyncJob[] }>('/api/platform/jobs?status=running&limit=50').catch(() => ({ items: [] }))
      ])
      const next: Record<string, ActiveItem> = {}
      for (const r of tasks || []) if (ACTIVE.has(r.status)) next[`task:${r.id}`] = taskRowToActiveItem(r)
      for (const j of jobs?.items || []) if (ACTIVE.has(j.status)) next[`sync:${j.id}`] = syncJobToActiveItem(j)
      setMap(next) // 服务端为唯一事实源：整体覆盖
    } finally {
      inflight.current = false
    }
  }, [])

  // SSE 实时增量
  useEffect(() => {
    const off = subscribeEvents((ev) => {
      if (ev.type === 'task.update') {
        const t = ev.data as TaskUpdateEvent & { kind?: string; label?: string; target?: string }
        if (!t?.id) return
        setMap((prev) => {
          const next = { ...prev }
          if (ACTIVE.has(t.status)) {
            const old = prev[`task:${t.id}`]
            next[`task:${t.id}`] = taskRowToActiveItem({
              id: t.id,
              kind: t.kind || old?.kind || '',
              status: t.status,
              progress: t.progress ?? old?.progress ?? 0,
              note: t.note ?? old?.note ?? '',
              label: t.label || old?.label,
              target: t.target || old?.target,
              payload: t.payload ?? old?.payload
            })
          } else {
            delete next[`task:${t.id}`]
          }
          return next
        })
      } else if (ev.type === 'sync.job') {
        const j = ev.data as SyncJobEvent
        if (!j?.id) return
        setMap((prev) => {
          const next = { ...prev }
          if (ACTIVE.has(j.status)) next[`sync:${j.id}`] = syncJobToActiveItem(j)
          else delete next[`sync:${j.id}`]
          return next
        })
      }
    })
    return off
  }, [])

  // 挂载回扫（补齐切页/刷新时正在跑的任务）
  useEffect(() => {
    void rescan()
  }, [rescan])

  // 10s 轮询兜底：仅在有进行中项时开，空闲停
  useEffect(() => {
    if (!Object.keys(map).length) return
    const timer = setInterval(() => void rescan(), 10_000)
    return () => clearInterval(timer)
  }, [map, rescan])

  const value = useMemo<ActiveWorkCtx>(() => {
    const items = Object.values(map).sort(
      (a, b) => Number(a.source === 'sync') - Number(b.source === 'sync') || a.id - b.id
    )
    const tasks = items.filter((i) => i.source === 'task')
    return {
      items,
      tasks,
      has: (pred) => items.some(pred),
      find: (pred) => items.find(pred)
    }
  }, [map])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useActiveWork(): ActiveWorkCtx {
  return useContext(Ctx)
}

/** 取某个/某类 kind 的进行中任务（可再传 payload 匹配，如 draft_id）。 */
export function useActiveTask(
  kinds: string | string[],
  match?: (t: ActiveItem) => boolean
): ActiveItem | undefined {
  const { tasks } = useActiveWork()
  const wantKey = (Array.isArray(kinds) ? kinds : [kinds]).join('|')
  return useMemo(() => {
    const want = wantKey.split('|')
    return tasks.find((t) => want.includes(t.kind) && (!match || match(t)))
  }, [tasks, wantKey, match])
}
