import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, Copy, FileText } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { toast } from '@/components/ui/toaster'

export interface RewriteResult {
  script: string
  original_script: string
  draft_id: number
  source_title: string
  benchmark_name: string
}

export function RewriteDiffDialog({
  result,
  open,
  onOpenChange
}: {
  result: RewriteResult | null
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const navigate = useNavigate()
  if (!open || !result) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(920px,96vw)]">
        <DialogHeader>
          <DialogTitle>洗稿完成 · 原文对照</DialogTitle>
          <DialogDescription>
            来源：{result.benchmark_name || '对标'}《{result.source_title || '—'}》
            {result.draft_id ? ` · 已存草稿 #${result.draft_id}` : ''}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-border">
            <div className="flex items-center gap-2 border-b border-border px-3 py-2">
              <FileText className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-medium text-muted-foreground">原文（对标 ASR）</span>
            </div>
            <ScrollArea className="h-72">
              <p className="whitespace-pre-wrap px-3 py-2 text-xs leading-relaxed text-muted-foreground">{result.original_script || '（无原文）'}</p>
            </ScrollArea>
          </div>
          <motion.div
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            className="rounded-lg border border-accent/40 bg-accent-soft/50"
          >
            <div className="flex items-center gap-2 border-b border-accent/30 px-3 py-2">
              <Badge>洗稿后</Badge>
              <span className="text-xs text-muted-foreground">按你的人设重写</span>
              <span className="flex-1" />
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => {
                  navigator.clipboard.writeText(result.script)
                  toast.success('已复制')
                }}
              >
                <Copy className="h-3 w-3" />
              </Button>
            </div>
            <ScrollArea className="h-72">
              <p className="whitespace-pre-wrap px-3 py-2 text-xs leading-relaxed">{result.script}</p>
            </ScrollArea>
          </motion.div>
        </div>

        <div className="mt-2 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>关闭</Button>
          {!!result.draft_id && (
            <Button size="sm" onClick={() => { onOpenChange(false); navigate(`/drafts?id=${result.draft_id}`) }}>
              打开草稿 <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
