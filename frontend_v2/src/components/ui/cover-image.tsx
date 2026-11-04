import { useEffect, useState, type ReactNode } from 'react'
import { coverThumb } from '@/lib/covers'

/**
 * R-249：封面图统一兜底，避免出现浏览器「裂图」。
 *
 * 1) 先按显示宽度取缩略图（本地 `/covers/*` 会追加 `?w=`）；
 * 2) 缩略图加载/解码失败（历史坏缩略图缓存、缩略生成失败）→ 回退**原图**（URL 不同，跳过坏缓存）；
 * 3) 原图仍失败（远程签名 URL 过期/防盗链）→ 渲染传入的占位内容，绝不显示裂图。
 */
export function CoverImage({
  url,
  alt,
  width = 400,
  className,
  placeholder = null
}: {
  url?: string | null
  alt: string
  width?: number
  className?: string
  placeholder?: ReactNode
}) {
  const [original, setOriginal] = useState(false)
  const [failed, setFailed] = useState(false)

  // 卡片复用到另一个素材（无 key / 同位置换数据）时重置兜底状态
  useEffect(() => {
    setOriginal(false)
    setFailed(false)
  }, [url])

  if (!url || failed) return <>{placeholder}</>

  const thumb = coverThumb(url, width)
  const fallbackable = thumb !== url
  const fail = () => {
    if (fallbackable && !original) setOriginal(true)
    else setFailed(true)
  }
  return (
    <img
      src={original || !fallbackable ? url : thumb}
      alt={alt}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      className={className}
      onError={fail}
      onLoad={(event) => {
        // 少数浏览器对损坏图片只触发 load、naturalWidth=0，按失败处理
        if (!event.currentTarget.naturalWidth) fail()
      }}
    />
  )
}
