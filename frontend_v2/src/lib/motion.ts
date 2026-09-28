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
