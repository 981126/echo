import { motion } from 'framer-motion'
import { LoaderCircle } from 'lucide-react'
import { Progress } from '@/components/ui/progress'
import type { SyncJob } from './types'

export function SyncProgressBar({ job }: { job: SyncJob }) {
  const hasTotal = Number(job.progress_total || 0) > 0
  const pct = hasTotal
    ? Math.min(100, Math.round((Number(job.progress_done || 0) / Number(job.progress_total)) * 100))
    : 0
  const queued = (job.progress_note || '').includes('排队')
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="overflow-hidden rounded-md border border-accent/30 bg-accent-soft px-3 py-2"
    >
      <div className="flex items-center gap-2">
        <LoaderCircle className="h-3.5 w-3.5 animate-spin text-accent" />
        <span className="min-w-0 flex-1 truncate text-xs text-foreground">
          {job.progress_note || (job.status === 'running' ? '同步中…' : '准备中…')}
        </span>
        {hasTotal && (
          <span className="tnum shrink-0 text-xs text-muted-foreground">
            {job.progress_done}/{job.progress_total}
          </span>
        )}
      </div>
      <Progress className="mt-1.5" value={queued ? undefined : pct} indeterminate={queued || !hasTotal} />
    </motion.div>
  )
}
