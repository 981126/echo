// 草稿 AI 任务状态条（R-173）：卡片与讨论 tab 共用
import { motion } from 'framer-motion'
import { TriangleAlert } from 'lucide-react'
import { ThinkingDots } from '@/components/ui/thinking-dots'
import { cn } from '@/lib/utils'
import { aiKindLabel, type DebateState } from './types'

/** 状态条：running = 模型名 + 三点跳动（note 里已含模型与轮次）；failed = 上次讨论中断 */
export function DraftAiStatus({ debate, className }: { debate?: DebateState | null; className?: string }) {
  if (!debate || !debate.state) return null
  const running = debate.state === 'running'
  const note = debate.note || (running ? 'AI 处理中…' : '讨论中断')
  const round = running && debate.round && debate.rounds ? `（第 ${debate.round}/${debate.rounds} 轮）` : ''
  return (
    <motion.div
      data-testid="draft-ai-status"
      data-state={debate.state}
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.25 }}
      className={cn(
        'flex items-start gap-1.5 overflow-hidden rounded-md px-2 py-1.5 text-[11px] leading-snug',
        running ? 'bg-accent-soft/60 text-accent' : 'bg-[rgba(245,158,11,0.10)] text-warning',
        className
      )}
    >
      {running ? <ThinkingDots className="mt-1 shrink-0" /> : <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" />}
      <span className="min-w-0">
        <b className="font-medium">{running ? aiKindLabel(debate.kind) : '上次讨论中断'}</b>
        <span className="ml-1 opacity-90">{note}</span>
        {round}
        {!running && <span className="ml-1 opacity-75">，可【重新讨论】</span>}
      </span>
    </motion.div>
  )
}
