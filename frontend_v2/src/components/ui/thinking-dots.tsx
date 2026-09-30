// 三点跳动：表示「模型正在思考」（R-173）
//
// R-206：**这个指示器不能用 framer 的循环关键帧**。
// 抽屉讨论 tab 的状态条外层是 `<AnimatePresence initial={false}>`，它会把子组件的 `initial` 变成 false；
// 对 `animate={{ opacity: [0.25, 1, 0.25], y: [0, -2, 0] }}` 这种**关键帧数组**，framer 只会把样式停到
// 第一帧（opacity 0.25 / y 0）就再也不动了——生产包实测 98 帧里 transform 与 opacity 各只有 1 种取值、
// 零个 WAAPI 动画；草稿页卡片上同一组件（没有那层 AnimatePresence）却完全正常。
// 给点补显式 `initial` 也兜不住（实测仍冻住），所以改成纯 CSS 关键帧：
// 「正在跑」的状态指示必须无条件动起来（R-202/§8.6），不能依赖调用方的 framer 上下文。
import { cn } from '@/lib/utils'

export function ThinkingDots({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-end gap-0.5', className)} aria-hidden>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="thinking-dot block h-1 w-1 rounded-full bg-current"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  )
}
