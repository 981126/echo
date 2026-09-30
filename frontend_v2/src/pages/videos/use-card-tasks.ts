import { useCallback, useEffect, useRef, useState } from 'react'
import { apiJson } from '@/api/client'
import { subscribeEvents } from '@/api/sse'
import type { TaskUpdateEvent } from '@/api/types'
import type { CardItem } from './types'

export interface CardTaskState {
  progress: number
  note: string
  taskId?: number
  local?: boolean
}

export interface TaskRow {
  id: number
  status: string
  progress?: number
  note?: string
  error?: string
  payload?: unknown
}

// 任务 payload → 卡片 key（视频/合并作品/平台帖三路认领）
export function cardKeyForPayload(payload: unknown, cards: CardItem[]): string {
  let pl: Record<string, unknown> = {}
  try {
    pl = typeof payload === 'string' ? JSON.parse(payload) : ((payload as Record<string, unknown>) || {})
  } catch {
    return ''
  }
  for (const c of cards) {
    if (pl.video_id != null && c.kind === 'local' && c.id === Number(pl.video_id)) return c.key
    if (pl.work_id != null && c.kind === 'cloud' && c.type === 'work' && c.id === Number(pl.work_id)) return c.key
    if (pl.post_id != null && c.kind === 'cloud' && c.cloudPosts.some((x) => Number(x.id) === Number(pl.post_id)))
      return c.key
  }
  return ''
}

// R-220：未认领池重映射——任务恢复时卡片可能还没加载（/api/tasks 比 /api/library 先回），
// 入池暂存，等卡片每次变化（首帧到位/翻页加载）再按当前列表重新匹配，命中即认领。
// 纯函数：已被认领（claimedIds）/已终态 → 出池丢弃；命中但卡片已被其它任务接管（claimedKeys）→ 留池待重试。
export function claimPool(
  pool: Map<number, TaskRow>,
  cards: CardItem[],
  claimedIds: Set<number>,
  claimedKeys: Set<string>
): { claims: { key: string; task: TaskRow }[]; pool: Map<number, TaskRow> } {
  const next = new Map(pool)
  const claims: { key: string; task: TaskRow }[] = []
  for (const [id, t] of pool) {
    if (claimedIds.has(id) || t.status === 'done' || t.status === 'failed') {
      next.delete(id)
      continue
    }
    const key = cardKeyForPayload(t.payload, cards)
    if (!key || claimedKeys.has(key)) continue
    next.delete(id)
    claims.push({ key, task: t })
  }
  return { claims, pool: next }
}

// 卡片同步进度：点击即时本地过渡 → 服务端任务接管（SSE 为主、5s 轮询兜底）
export function useCardTasks(cards: CardItem[], onSettled?: () => void) {
  const [tasks, setTasks] = useState<Record<string, CardTaskState>>({})
  const tasksRef = useRef(tasks)
  tasksRef.current = tasks
  const cardsRef = useRef(cards)
  cardsRef.current = cards
  const timersRef = useRef<Record<string, ReturnType<typeof setInterval>>>({})
  const rampsRef = useRef<Record<string, ReturnType<typeof setInterval>>>({})
  const onSettledRef = useRef(onSettled)
  onSettledRef.current = onSettled
  // R-220：未认领池——恢复扫描/SSE 收到但卡片还没加载的任务（taskId → TaskRow）
  const poolRef = useRef<Map<number, TaskRow>>(new Map())

  const stopRamp = useCallback((key: string) => {
    const t = rampsRef.current[key]
    if (t) clearInterval(t)
    delete rampsRef.current[key]
  }, [])

  const clearKey = useCallback(
    (key: string) => {
      stopRamp(key)
      const t = timersRef.current[key]
      if (t) clearInterval(t)
      delete timersRef.current[key]
      setTimeout(() => {
        setTasks((prev) => {
          const next = { ...prev }
          delete next[key]
          return next
        })
      }, 1200)
    },
    [stopRamp]
  )

  const applyTask = useCallback(
    (key: string, t: TaskRow): boolean => {
      if (t.status === 'running' || t.status === 'pending') {
        stopRamp(key) // 服务端任务接管后停掉本地过渡
        setTasks((prev) => ({
          ...prev,
          [key]: {
            progress: Math.max(prev[key]?.progress ?? 2, Math.min(99, Number(t.progress) || 2)),
            note: t.note || prev[key]?.note || '同步中…',
            taskId: t.id
          }
        }))
        return false
      }
      // 终态
      stopRamp(key)
      if (t.status === 'done') {
        setTasks((prev) => ({ ...prev, [key]: { progress: 100, note: '同步完成', taskId: t.id } }))
      } else {
        setTasks((prev) => ({ ...prev, [key]: { progress: prev[key]?.progress ?? 0, note: '同步失败', taskId: t.id } }))
      }
      clearKey(key)
      onSettledRef.current?.()
      return true
    },
    [clearKey, stopRamp]
  )

  const pollTask = useCallback(
    (key: string, taskId: number) => {
      if (timersRef.current[key]) clearInterval(timersRef.current[key])
      timersRef.current[key] = setInterval(async () => {
        try {
          const t = await apiJson<TaskRow>(`/api/tasks/${taskId}`)
          if (applyTask(key, t)) {
            clearInterval(timersRef.current[key])
            delete timersRef.current[key]
          }
        } catch {
          /* 轮询抖动继续 */
        }
      }, 5000)
    },
    [applyTask]
  )

  // 点击同步后立刻调用：本地过渡动画（不等服务端任务注册）
  const begin = useCallback(
    (key: string, note = '数据/评论同步中…') => {
      stopRamp(key)
      setTasks((prev) => ({ ...prev, [key]: { progress: Math.max(prev[key]?.progress ?? 0, 5), note, local: true } }))
      rampsRef.current[key] = setInterval(() => {
        setTasks((prev) => {
          const cur = prev[key]
          if (!cur || cur.taskId) return prev // 服务端接管即停
          if (cur.progress >= 60) return prev
          return { ...prev, [key]: { ...cur, progress: cur.progress + Math.max(0.5, (60 - cur.progress) * 0.04) } }
        })
      }, 200)
    },
    [stopRamp]
  )

  // 服务端任务接管（同步接口返回的 media.task_id 直接传入）
  const claim = useCallback(
    (key: string, taskId: number, progress = 2, note = '同步中…') => {
      stopRamp(key)
      setTasks((prev) => ({
        ...prev,
        [key]: { progress: Math.max(prev[key]?.progress ?? 0, progress), note, taskId }
      }))
      pollTask(key, taskId)
    },
    [pollTask, stopRamp]
  )

  // 无需补齐（skip）或同步请求结束：完成并清除
  const finish = useCallback(
    (key: string, ok = true, note?: string) => {
      stopRamp(key)
      setTasks((prev) => ({ ...prev, [key]: { progress: 100, note: note ?? (ok ? '同步完成' : '同步失败') } }))
      clearKey(key)
      onSettledRef.current?.()
    },
    [clearKey, stopRamp]
  )

  // R-220：任务统一入口——能匹配到卡片立即接管（挂遮罩+轮询），匹配不到且非终态则入池等卡片到位
  const ingestTask = useCallback(
    (t: TaskRow) => {
      if (Object.values(tasksRef.current).some((v) => v.taskId === t.id)) {
        poolRef.current.delete(t.id)
        return
      }
      if (t.status === 'done' || t.status === 'failed') {
        poolRef.current.delete(t.id)
        return
      }
      const key = cardKeyForPayload(t.payload, cardsRef.current)
      if (!key) {
        poolRef.current.set(t.id, t)
        return
      }
      const cur = tasksRef.current[key]
      if (cur?.taskId && cur.taskId !== t.id) {
        poolRef.current.set(t.id, t) // 该卡片已被其它服务端任务接管，留池待重试
        return
      }
      poolRef.current.delete(t.id)
      applyTask(key, t)
      pollTask(key, t.id)
    },
    [applyTask, pollTask]
  )

  // SSE 事件驱动
  useEffect(() => {
    const off = subscribeEvents((ev) => {
      if (ev.type !== 'task.update') return
      const t = ev.data as TaskUpdateEvent & { id: number }
      if (!t?.id) return
      const key: string | undefined = Object.entries(tasksRef.current).find(([, v]) => v.taskId === t.id)?.[0]
      if (!key) {
        if (t.status === 'done' || t.status === 'failed') {
          poolRef.current.delete(t.id)
          return
        }
        ingestTask(t as TaskRow) // 命中即接管；卡片未加载则入池（R-220）
        return
      }
      applyTask(key, t as TaskRow)
      if (t.status === 'running' || t.status === 'pending') pollTask(key, t.id)
    })
    return off
  }, [applyTask, ingestTask, pollTask])

  // 挂载时扫描进行中的媒体/卡片任务（切页回来恢复动画）；含 pending 窗口（R-220）
  const refreshActive = useCallback(async () => {
    try {
      const list = await apiJson<TaskRow[]>('/api/tasks?status=pending,running&kind=platform_media,card_sync&limit=200')
      for (const t of list || []) ingestTask(t)
    } catch {
      /* 静默 */
    }
  }, [ingestTask])

  useEffect(() => {
    void refreshActive()
    const timers = timersRef.current
    const ramps = rampsRef.current
    return () => {
      Object.values(timers).forEach(clearInterval)
      Object.values(ramps).forEach(clearInterval)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // R-220：卡片数据每次变化（首帧到位/翻页加载）都重试未认领池——修复与 /api/library 的竞速
  useEffect(() => {
    if (!poolRef.current.size) return
    const entries = Object.entries(tasksRef.current)
    const claimedIds = new Set(entries.map(([, v]) => v.taskId).filter((x): x is number => typeof x === 'number'))
    const claimedKeys = new Set(entries.filter(([, v]) => v.taskId).map(([k]) => k))
    const { claims, pool } = claimPool(poolRef.current, cards, claimedIds, claimedKeys)
    poolRef.current = pool
    for (const { key, task } of claims) {
      applyTask(key, task)
      pollTask(key, task.id)
    }
  }, [cards, applyTask, pollTask])

  const hasTask = useCallback((key: string) => !!tasksRef.current[key]?.taskId, [])

  return { tasks, begin, claim, finish, refreshActive, hasTask }
}
