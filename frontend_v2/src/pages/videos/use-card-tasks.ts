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

interface TaskRow {
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

  // SSE 事件驱动
  useEffect(() => {
    const off = subscribeEvents((ev) => {
      if (ev.type !== 'task.update') return
      const t = ev.data as TaskUpdateEvent & { id: number }
      if (!t?.id) return
      let key: string | undefined = Object.entries(tasksRef.current).find(([, v]) => v.taskId === t.id)?.[0]
      if (!key) {
        if (t.status === 'done' || t.status === 'failed') return
        key = cardKeyForPayload(t.payload || {}, cardsRef.current)
        if (!key) return
      }
      applyTask(key, t as TaskRow)
      if (t.status === 'running' || t.status === 'pending') pollTask(key, t.id)
    })
    return off
  }, [applyTask, pollTask])

  // 挂载时扫描进行中的媒体/卡片任务（切页回来恢复动画）
  const refreshActive = useCallback(async () => {
    try {
      const list = await apiJson<TaskRow[]>('/api/tasks?status=running&kind=platform_media,card_sync&limit=200')
      for (const t of list || []) {
        const key = cardKeyForPayload(t.payload, cardsRef.current)
        if (!key) continue
        setTasks((prev) => {
          if (prev[key]?.taskId && prev[key].taskId !== t.id) return prev
          return {
            ...prev,
            [key]: {
              progress: Math.max(prev[key]?.progress ?? 2, Number(t.progress) || 2),
              note: t.note || '同步中…',
              taskId: t.id
            }
          }
        })
        pollTask(key, t.id)
      }
    } catch {
      /* 静默 */
    }
  }, [pollTask])

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

  const hasTask = useCallback((key: string) => !!tasksRef.current[key]?.taskId, [])

  return { tasks, begin, claim, finish, refreshActive, hasTask }
}
