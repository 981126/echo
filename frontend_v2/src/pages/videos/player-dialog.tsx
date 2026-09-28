import { useEffect, useState } from 'react'
import { apiJson } from '@/api/client'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { hasRealFile } from './types'

// 视频/音频播放（R-096：纯音频素材只显示音频轨）
export function PlayerDialog({
  videoId,
  title,
  open,
  onOpenChange
}: {
  videoId: number | null
  title: string
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const [src, setSrc] = useState('')
  const [kind, setKind] = useState<'video' | 'audio'>('video')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !videoId) return
    setError('')
    setSrc('')
    setKind('video')
    ;(async () => {
      try {
        const v = await apiJson<{ filename?: string }>(`/api/videos/${videoId}`)
        if (!hasRealFile(v?.filename)) {
          setError('该素材还没有本地视频文件')
          return
        }
        setSrc('/media/videos/' + encodeURIComponent(v.filename as string))
        try {
          const meta = await apiJson<{ kind?: string }>(`/api/videos/${videoId}/media-meta`)
          if (meta?.kind === 'audio') setKind('audio')
        } catch {
          /* 按视频处理 */
        }
      } catch {
        setError('找不到该视频文件')
      }
    })()
  }, [open, videoId])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(760px,96vw)]">
        <DialogHeader>
          <DialogTitle>{title || '视频播放'}</DialogTitle>
        </DialogHeader>
        {error ? (
          <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">{error}</div>
        ) : !src ? (
          <Skeleton className="h-64 w-full" />
        ) : kind === 'video' ? (
          <video src={src} controls autoPlay playsInline className="max-h-[70vh] w-full rounded-lg bg-black" />
        ) : (
          <div className="rounded-lg border border-border bg-muted/40 p-6">
            <audio src={src} controls autoPlay className="w-full" />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
