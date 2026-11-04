import { useEffect, useRef } from 'react'

/**
 * R-218：移动端「返回键先关弹层」。
 *
 * 现象：手机浏览器/Android 返回键默认直接退页，而全屏抽屉/弹层还开着，用户会觉得“卡住/乱跳”。
 * 做法：打开弹层时 push 一个同 URL 的 history 哨兵；popstate 时关闭弹层（不切路由）。
 * 程序内关闭（点 X/遮罩）时把标记置回 false，避免用户在“已关闭状态”再按返回被卡一层。
 *
 * 注意：hash 路由下 push 同 URL + state 不会触发路由变化，只影响 history 栈。
 */
export function useBackToClose(open: boolean, onClose: () => void): void {
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    if (!open) return
    const baseState = (window.history.state ?? {}) as Record<string, unknown>
    window.history.pushState({ ...baseState, echoOverlay: true }, '', window.location.href)
    const onPop = () => closeRef.current()
    window.addEventListener('popstate', onPop)
    return () => {
      window.removeEventListener('popstate', onPop)
      const current = (window.history.state ?? {}) as Record<string, unknown>
      if (current.echoOverlay) {
        window.history.replaceState({ ...current, echoOverlay: false }, '', window.location.href)
      }
    }
  }, [open])
}
