import { useCallback, useEffect, useRef, useState } from 'react'
import { apiJson } from '@/api/client'
import { subscribeEvents } from '@/api/sse'
import type { TaskUpdateEvent } from '@/api/types'
import type { CardItem } from './types'

export interface CardTaskState {
  progress: number
  note: string
  taskId?: number
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

// 卡片同步进度追踪：SSE 为主、5s 轮询兜底（断线可恢复）
export function useCardTasks(cards: CardItem[]) {
  const [tasks, setTasks] = useState<Record<string, CardTaskState>>({})
  const tasksRef = useRef(tasks)
  tasksRef.current = tasks
  const cardsRef = useRef(cards)
  cardsRef.current = cards
  const timersRef = useRef<Record<string, ReturnType<typeof setInterval>>>({})

  const clearLater = useCallback((key: string) => {
    setTimeout(() => {
      setTasks((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
      const t = timersRef.current[key]
      if (t) clearInterval(t)
      delete timersRef.current[key]
    }, 1200)
  }, [])

  const applyTask = useCallback(
    (key: string, t: TaskRow) => {
      if (t.status === 'running' || t.status === 'pending') {
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
      if (t.status === 'done') {
        setTasks((prev) => ({ ...prev, [key]: { progress: 100, note: '同步完成', taskId: t.id } }))
      }
      clearLater(key)
      return true
    },
    [clearLater]
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

  const claim = useCallback(
    (key: string, taskId: number, progress = 2, note = '同步中…') => {
      setTasks((prev) => ({ ...prev, [key]: { progress: Math.max(prev[key]?.progress ?? 0, progress), note, taskId } }))
      pollTask(key, taskId)
    },
    [pollTask]
  )

  // SSE 事件驱动
  useEffect(() => {
    const off = subscribeEvents((ev) => {
      if (ev.type !== 'task.update') return
      const t = ev.data as TaskUpdateEvent & { id: number }
      if (!t?.id) return
      // 已认领的卡
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
            [key]: { progress: Math.max(prev[key]?.progress ?? 2, Number(t.progress) || 2), note: t.note || '同步中…', taskId: t.id }
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
    return () => {
      Object.values(timers).forEach(clearInterval)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { tasks, claim, refreshActive }
}
