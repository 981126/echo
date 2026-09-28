// 动效令牌：全站统一的曲线与编排（表现力优先但克制）
import type { Variants, Transition } from 'framer-motion'

export const EASE_OUT_EXPO = [0.16, 1, 0.3, 1] as const
export const EASE_SPRING = { type: 'spring', stiffness: 380, damping: 34 } as const

export const pageTransition: Transition = { duration: 0.32, ease: EASE_OUT_EXPO }

export const pageVariants: Variants = {
  initial: { opacity: 0, y: 12, filter: 'blur(4px)' },
  animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
  exit: { opacity: 0, y: -8, filter: 'blur(4px)' }
}

// 列表 stagger：父容器 + 子项
export const listVariants: Variants = {
  animate: { transition: { staggerChildren: 0.045, delayChildren: 0.04 } }
}

export const itemVariants: Variants = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.34, ease: EASE_OUT_EXPO } }
}

export const cardHover = {
  rest: { y: 0, boxShadow: 'var(--shadow-card)' },
  hover: { y: -3, transition: { duration: 0.22, ease: EASE_OUT_EXPO } }
}

export const fadeIn: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.25 } },
  exit: { opacity: 0, transition: { duration: 0.15 } }
}

// R-178 / R-175：新元素（模型标签、运行头摘要、新批次卡片）入场用的轻过渡——
// **不从 opacity:0 起步**（切换/复用容器时会先闪一帧空白），统一从 0.85 起、收口到 1，
// 配合 8–10px 位移表达「新内容进来了」。
export const softIn: Transition = { duration: 0.24, ease: EASE_OUT_EXPO }

// R-199：素材库「换一批结果」（切博主 / 改筛选后查询）的编排。
// 原因：AnimatePresence 用 `mode="popLayout"` 时退场卡被绝对定位在原地，若新卡同时淡入，
// 两组卡叠在同一批网格位置上互相抵消，看起来就是「结果卡没有动画」。
// 做法：**逐格交接**——新卡在「同一个格子」里的旧卡退完之后才入场（退场延迟 + 退场时长 + 一点呼吸）。
// ① 退场严格用换批前的原值（作者明确要求保留这波老动画）；
// ② 新旧波不重叠 → 两段动画都看得见；③ 网格任何时刻都不会整片空掉（R-175：别闪空白）。
export const listReplace = {
  /** 旧卡退场：= 换批前的原样（0.35s 淡出 + 缩到 0.94 + index×0.035 错峰扫过） */
  exit: { duration: 0.35, stagger: 0.035, maxItems: 16, scale: 0.94 },
  /**
   * 新卡入场 = 退场倒放（显影 + 长大），但要**慢到看得见**：
   * - `fromScale 0.8`：退场只收到 0.94，6% 的放大人眼几乎看不出来（作者反馈「一点都不明显」）；
   * - `duration 0.5` + `backOut` 缓动：0.8 → 略微冲过 1（≈1.04）→ 落回 1，**过冲发生在动画中段**，
   *   所以整段 0.5s 都有肉眼可见的变化（用 spring 时 150ms 就落定了，等于没动画）；
   * - 延迟 = 本格旧卡的退场延迟 + 退场时长 + `breathAfterExit`。
   */
  enter: {
    breathAfterExit: 0.04,
    fromScale: 0.8,
    duration: 0.5,
    ease: 'backOut'
  }
} as const
