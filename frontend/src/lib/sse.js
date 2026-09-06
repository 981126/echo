// R-087：SSE 事件源客户端（fetch + ReadableStream，带鉴权头，自动重连）
import { getToken } from '../api'
import { busEmit } from './eventbus'

let retryTimer = null
let active = false

function onEvent(ev) {
  if (!ev || !ev.type) return
  busEmit('event', ev)
  busEmit(ev.type, ev.data || {})
}

async function connect() {
  if (!active) return
  try {
    const resp = await fetch('/api/events', { headers: { 'X-Access-Token': getToken() } })
    if (!resp.ok || !resp.body) throw new Error('sse ' + resp.status)
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
        for (const line of block.split('\n')) {
          if (!line.startsWith('data:')) continue
          try {
            onEvent(JSON.parse(line.slice(5).trim()))
          } catch { /* 忽略坏帧 */ }
        }
      }
    }
  } catch (e) { /* 连接断开，稍后重连 */ }
  if (active) retryTimer = setTimeout(connect, 5000)
}

export function connectEvents() {
  if (active) return
  active = true
  connect()
}

export function disconnectEvents() {
  active = false
  if (retryTimer) clearTimeout(retryTimer)
  retryTimer = null
}
