// R-087：轻量前端事件总线（SSE 事件分发到各页面/组件）
const listeners = {}

export function busOn(type, fn) {
  (listeners[type] ||= []).push(fn)
  return () => {
    const arr = listeners[type]
    if (arr) {
      const i = arr.indexOf(fn)
      if (i >= 0) arr.splice(i, 1)
    }
  }
}

export function busEmit(type, data) {
  const arr = listeners[type] || []
  for (const fn of arr.slice()) {
    try { fn(data) } catch (e) { /* 单监听器异常不影响其它 */ }
  }
}
