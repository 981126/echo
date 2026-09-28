// 三点跳动：表示「模型正在思考」（R-173）
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

export function ThinkingDots({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-end gap-0.5', className)} aria-hidden>
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="block h-1 w-1 rounded-full bg-current"
          animate={{ opacity: [0.25, 1, 0.25], y: [0, -2, 0] }}
          transition={{ duration: 0.9, repeat: Infinity, ease: 'easeInOut', delay: i * 0.15 }}
        />
      ))}
    </span>
  )
}
