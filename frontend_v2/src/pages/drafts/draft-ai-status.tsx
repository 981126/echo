// 草稿 AI 任务状态条（R-173）：卡片与讨论 tab 共用
import { motion } from 'framer-motion'
import { TriangleAlert } from 'lucide-react'
import { ThinkingDots } from '@/components/ui/thinking-dots'
import { softIn } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { aiKindLabel, type DebateState } from './types'

/**
 * 状态条：running = 模型名 + 三点跳动（note 里已含模型与轮次）；failed = 上次讨论中断。
 *
 * R-206：**入场不能从 `opacity: 0` 起步、也不做高度动画**。讨论进行中这条文案每换一步都会更新，
 * 抽屉里又会按 `state` 重挂——`height: 0 → auto` 会让状态条先空一下、并把它下面的留痕列表
 * 上下顶一次；从全透明起步还会让三点跳动看起来「停了又重来」（见 DESIGN §8.3 规则 2/3）。
 */
export function DraftAiStatus({ debate, className }: { debate?: DebateState | null; className?: string }) {
  if (!debate || !debate.state) return null
  const running = debate.state === 'running'
  const note = debate.note || (running ? 'AI 处理中…' : '讨论中断')
  const round = running && debate.round && debate.rounds ? `（第 ${debate.round}/${debate.rounds} 轮）` : ''
  return (
    <motion.div
      data-testid="draft-ai-status"
      data-state={debate.state}
      initial={{ opacity: 0.85, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4, transition: { duration: 0.15 } }}
      transition={softIn}
      className={cn(
        'flex items-start gap-1.5 rounded-md px-2 py-1.5 text-[11px] leading-snug',
        running ? 'bg-accent-soft/60 text-accent' : 'bg-[rgba(245,158,11,0.10)] text-warning',
        className
      )}
    >
      {running ? <ThinkingDots className="mt-1 shrink-0" /> : <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" />}
      <span className="min-w-0">
        {/* R-211：失败文案按 kind 区分（学习分析中断时给「重试」提示——下次完成/不采用会重新触发） */}
        <b className="font-medium">{running ? aiKindLabel(debate.kind) : `上次${aiKindLabel(debate.kind)}中断`}</b>
        <span className="ml-1 opacity-90">{note}</span>
        {round}
        {!running && debate.kind !== 'feedback' && <span className="ml-1 opacity-75">，可【重新讨论】</span>}
        {!running && debate.kind === 'feedback' && <span className="ml-1 opacity-75">，下次完成/不采用会重试</span>}
      </span>
    </motion.div>
  )
}
