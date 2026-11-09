import { useEffect, useState } from 'react'

/** R-218：仅用于「选动画参数 / 触屏交互策略」，不用于切 DOM 结构（结构差异一律 CSS 断点）。
 *  R-258：例外——草稿瀑布流按列数渲染固定列容器（CSS 多列会在删除时整墙重排），列数断点由本 hook 读取。 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => (typeof window === 'undefined' ? false : window.matchMedia(query).matches))
  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = () => setMatches(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [query])
  return matches
}

/** 触屏（粗指针）判定：用于「回车换行 vs 回车发送」等输入策略。 */
export function useCoarsePointer(): boolean {
  return useMediaQuery('(pointer: coarse)')
}
