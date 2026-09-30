// R-202：把「点一次 → 跑一个后台任务 → 拿结果」封装成可跨切页/刷新恢复的 scope。
// task_id 存 sessionStorage，回来若任务仍在跑则继续等，跑完自动回填结果。
import { useCallback, useEffect, useRef, useState } from 'react'
import { startTask, waitTaskResult } from '@/api/task'
import { toast } from '@/components/ui/toaster'

const keyOf = (scope: string) => `echo.task.${scope}`

export interface TaskScope<T> {
  data: T | null
  running: boolean
  run: (url: string, body?: unknown) => Promise<T | null>
  clear: () => void
}

export function useTaskScope<T>(scope: string): TaskScope<T> {
  const [data, setData] = useState<T | null>(null)
  const [running, setRunning] = useState(false)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const wait = useCallback(
    async (taskId: number) => {
      setRunning(true)
      try {
        const res = await waitTaskResult<T>(taskId)
        if (alive.current) setData(res)
        return res
      } catch (e) {
        if (alive.current) {
          toast.error((e as Error).message)
          sessionStorage.removeItem(keyOf(scope))
        }
        throw e
      } finally {
        if (alive.current) setRunning(false)
      }
    },
    [scope]
  )

  // 挂载回扫：上次发起的任务若还在跑就继续等；已完成则回填结果
  useEffect(() => {
    const raw = sessionStorage.getItem(keyOf(scope))
    const id = Number(raw || 0)
    if (!id) return
    let cancelled = false
    setRunning(true)
    waitTaskResult<T>(id)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch(() => {
        if (!cancelled) sessionStorage.removeItem(keyOf(scope))
      })
      .finally(() => {
        if (!cancelled) setRunning(false)
      })
    return () => {
      cancelled = true
    }
  }, [scope])

  const run = useCallback(
    async (url: string, body?: unknown): Promise<T | null> => {
      try {
        const taskId = await startTask(url, body)
        sessionStorage.setItem(keyOf(scope), String(taskId))
        return await wait(taskId)
      } catch {
        return null // wait 内已提示
      }
    },
    [scope, wait]
  )

  const clear = useCallback(() => {
    sessionStorage.removeItem(keyOf(scope))
    setData(null)
  }, [scope])

  return { data, running, run, clear }
}
