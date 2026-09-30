import { motion } from 'framer-motion'
import { CheckCircle2, CircleSlash, LoaderCircle, XCircle } from 'lucide-react'
import { Progress } from '@/components/ui/progress'
import type { SyncJob } from './types'

// R-219：进度条三形态——running（转圈+进度）、done（绿条「同步完成」）、failed（红条失败原因）。
// done/failed 由页面层控制延迟淡出（超时后 job 变 null，走 exit 动画收口 opacity 1→0）。
export function SyncProgressBar({ job }: { job: SyncJob }) {
  const done = job.status === 'done'
  const failed = job.status === 'failed'
  const hasTotal = Number(job.progress_total || 0) > 0
  const pct = hasTotal
    ? Math.min(100, Math.round((Number(job.progress_done || 0) / Number(job.progress_total)) * 100))
    : 0
  const queued = !done && !failed && (job.progress_note || '').includes('排队')
  const note = failed
    ? job.message || job.progress_note || '同步失败'
    : done
      ? '同步完成'
      : job.progress_note || (job.status === 'running' ? '同步中…' : '准备中…')
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className={`overflow-hidden rounded-md border px-3 py-2 ${
        failed
          ? 'border-destructive/30 bg-[rgba(239,68,68,0.08)]'
          : done
            ? 'border-success/30 bg-[rgba(16,185,129,0.08)]'
            : 'border-accent/30 bg-accent-soft'
      }`}
    >
      <div className="flex items-center gap-2">
        {failed ? (
          <XCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
        ) : done ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" />
        ) : (
          <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" />
        )}
        <span className={`min-w-0 flex-1 truncate text-xs ${failed ? 'text-destructive' : 'text-foreground'}`}>
          {note}
        </span>
        {!failed && hasTotal && (
          <span className="tnum shrink-0 text-xs text-muted-foreground">
            {job.progress_done}/{job.progress_total}
          </span>
        )}
      </div>
      {!failed && (
        <Progress
          className="mt-1.5"
          value={done ? 100 : queued ? undefined : pct}
          indeterminate={done ? false : queued || !hasTotal}
        />
      )}
    </motion.div>
  )
}

// R-219：sync-all 被跳过的博主（已在运行/无启用账号）显示灰色提示条，而不是无声无息。
export function SyncSkippedBar({ reason }: { reason: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="overflow-hidden rounded-md border border-dashed border-border px-3 py-2"
    >
      <div className="flex items-center gap-2">
        <CircleSlash className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">本轮同步跳过：{reason}</span>
      </div>
    </motion.div>
  )
}
