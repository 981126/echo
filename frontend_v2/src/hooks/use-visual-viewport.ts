import { useEffect, useState } from 'react'

/** R-218：移动端键盘弹起时用 visualViewport 高度兜底（iOS Safari 的 100vh 不跟随键盘）。 */
export function useVisualViewportHeight(): number {
  const [height, setHeight] = useState(() => window.visualViewport?.height ?? window.innerHeight)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const update = () => setHeight(vv.height)
    update()
    vv.addEventListener('resize', update)
    vv.addEventListener('scroll', update)
    return () => {
      vv.removeEventListener('resize', update)
      vv.removeEventListener('scroll', update)
    }
  }, [])
  return height
}
