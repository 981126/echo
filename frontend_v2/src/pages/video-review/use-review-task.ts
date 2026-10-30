import { apiJson } from '@/api/client'

export interface TaskState {
  id: number
  status: string
  progress: number
  note: string
  error?: string
  result?: string
}

export async function waitForReviewTask(taskId: number, signal?: AbortSignal): Promise<TaskState> {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    if (signal?.aborted) throw new Error('已停止等待任务结果')
    const task = await apiJson<TaskState>(`/api/tasks/${taskId}`)
    if (task.status === 'done') return task
    if (task.status === 'failed') throw new Error(task.error || '分析失败，请稍后重试')
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, 1000)
      signal?.addEventListener('abort', () => {
        window.clearTimeout(timer)
        reject(new Error('已停止等待任务结果'))
      }, { once: true })
    })
  }
  throw new Error('任务仍在进行，请稍后从页面恢复进度')
}
