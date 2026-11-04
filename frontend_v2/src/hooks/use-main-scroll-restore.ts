import { useEffect, useRef, type RefObject } from 'react'

// R-218：切 Tab / 返回时恢复该页滚动位置（main 是内部滚动容器，浏览器不会自动恢复）。
const positions = new Map<string, number>()

export function useMainScrollRestore(pathname: string, mainRef: RefObject<HTMLElement | null>): void {
  const prev = useRef(pathname)

  useEffect(() => {
    const el = mainRef.current
    if (!el) return
    if (prev.current !== pathname) positions.set(prev.current, el.scrollTop)
    prev.current = pathname
    const target = positions.get(pathname) ?? 0
    let tries = 0
    const apply = () => {
      const node = mainRef.current
      if (!node) return
      node.scrollTop = target
      // 懒加载页面内容可能在首帧后才撑开，最多重试 4 次
      if (Math.abs(node.scrollTop - target) > 2 && tries++ < 4) window.setTimeout(apply, 80)
    }
    const raf = window.requestAnimationFrame(apply)
    return () => window.cancelAnimationFrame(raf)
  }, [pathname, mainRef])
}
