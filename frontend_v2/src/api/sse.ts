// SSE 客户端：fetch + ReadableStream（带鉴权），自动重连；事件经轻量总线分发
import { getToken } from '@/lib/token'
import type { EchoEvent } from './types'

type Listener = (ev: EchoEvent) => void

const listeners = new Set<Listener>()
let retryTimer: ReturnType<typeof setTimeout> | null = null
let abort: AbortController | null = null
let active = false

export function subscribeEvents(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function dispatch(ev: EchoEvent) {
  for (const fn of listeners) {
    try {
      fn(ev)
    } catch {
      /* 单个监听器异常不影响其它 */
    }
  }
}

export function parseSseBlock(block: string): EchoEvent | null {
  for (const line of block.split('\n')) {
    if (!line.startsWith('data:')) continue
    try {
      return JSON.parse(line.slice(5).trim()) as EchoEvent
    } catch {
      return null
    }
  }
  return null
}

async function connect() {
  if (!active) return
  abort = new AbortController()
  try {
    const resp = await fetch('/api/events', {
      headers: { 'X-Access-Token': getToken() },
      signal: abort.signal
    })
    if (!resp.ok || !resp.body) throw new Error(`sse ${resp.status}`)
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const ev = parseSseBlock(block)
        if (ev) dispatch(ev)
      }
    }
  } catch {
    /* 断开稍后重连 */
  }
  if (active) retryTimer = setTimeout(connect, 5000)
}

export function connectEvents() {
  if (active) return
  active = true
  void connect()
}

export function disconnectEvents() {
  active = false
  if (retryTimer) clearTimeout(retryTimer)
  retryTimer = null
  abort?.abort()
  abort = null
}
