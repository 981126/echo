// R-202：后台任务的结果轮询（切页/刷新后仍可凭 task_id 取回即可回填）。
import { apiJson } from './client'

export interface TaskSnapshot {
  id: number
  status: string
  progress?: number
  note?: string
  result?: string
  error?: string
}

export async function getTask(taskId: number): Promise<TaskSnapshot> {
  return apiJson<TaskSnapshot>(`/api/tasks/${taskId}`)
}

/** 提交会返回 `{task_id}` 的后台任务。 */
export async function startTask(url: string, body?: unknown): Promise<number> {
  const r = await apiJson<{ task_id: number }>(url, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  return r.task_id
}

/** 等任务结束并解析 `task.result`；失败抛可读错误。 */
export async function waitTaskResult<T>(
  taskId: number,
  opts?: { intervalMs?: number; timeoutMs?: number }
): Promise<T> {
  const interval = opts?.intervalMs ?? 1500
  const timeout = opts?.timeoutMs ?? 30 * 60 * 1000
  const deadline = Date.now() + timeout
  for (;;) {
    const t = await getTask(taskId)
    if (t.status === 'done') {
      try {
        return JSON.parse(t.result || '{}') as T
      } catch {
        return {} as T
      }
    }
    if (t.status === 'failed') throw new Error(t.error || '任务失败')
    if (Date.now() > deadline) throw new Error('任务等待超时，可稍后在通知中心查看')
    await new Promise((r) => setTimeout(r, interval))
  }
}
