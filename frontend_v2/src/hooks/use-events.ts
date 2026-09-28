import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { connectEvents, disconnectEvents, subscribeEvents } from '@/api/sse'
import type { EchoEvent } from '@/api/types'

// 全局 SSE：挂载即连接；事件驱动相关 query 失效刷新
export function useEventStream(onEvent?: (ev: EchoEvent) => void) {
  const qc = useQueryClient()

  useEffect(() => {
    connectEvents()
    const off = subscribeEvents((ev) => {
      if (ev.type === 'notification.new') {
        qc.invalidateQueries({ queryKey: ['notifications'] })
      } else if (ev.type === 'task.update') {
        qc.invalidateQueries({ queryKey: ['tasks'] })
      } else if (ev.type === 'sync.job') {
        qc.invalidateQueries({ queryKey: ['sync-jobs'] })
      }
      onEvent?.(ev)
    })
    return () => {
      off()
      disconnectEvents()
    }
  }, [qc, onEvent])
}
