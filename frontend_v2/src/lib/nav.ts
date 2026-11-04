import type { LucideIcon } from 'lucide-react'
import {
  BarChart3,
  ChartNoAxesCombined,
  Clapperboard,
  Fingerprint,
  LayoutDashboard,
  MessageSquare,
  NotebookPen,
  PenLine,
  Settings2,
  Target,
  Users
} from 'lucide-react'

// R-218：导航单一数据源——桌面侧栏 / 移动底部 Tab / 「更多」Sheet 共用，避免三处菜单不同步。
export interface NavItem {
  to: string
  label: string
  /** 320px 底部 Tab 用的短名；缺省用 label */
  shortLabel?: string
  icon: LucideIcon
}

/** 底部 Tab 一级入口（作者 2026-09-30 定型，顺序即 Tab 顺序） */
export const PRIMARY_NAV: NavItem[] = [
  { to: '/home', label: '主页', icon: LayoutDashboard },
  { to: '/videos', label: '素材库', shortLabel: '素材库', icon: Clapperboard },
  { to: '/drafts', label: '脚本工作台', shortLabel: '脚本', icon: PenLine },
  { to: '/inspiration', label: '灵感随手记', shortLabel: '灵感', icon: NotebookPen },
  { to: '/chat', label: 'AI 对话', shortLabel: '对话', icon: MessageSquare }
]

/** 「更多」Sheet 里的 4 个低频入口 */
export const MORE_NAV: NavItem[] = [
  { to: '/benchmark', label: '博主对标', icon: Target },
  { to: '/creators', label: '博主管理', icon: Users },
  { to: '/persona', label: '人设档案', icon: Fingerprint },
  { to: '/prompts', label: 'AI 设置', icon: Settings2 }
]

/** 桌面侧栏 11 项（保持改造前顺序与视觉不变） */
export const SIDEBAR_NAV: NavItem[] = [
  { to: '/home', label: '主页', icon: LayoutDashboard },
  { to: '/videos', label: '素材库', icon: Clapperboard },
  { to: '/dashboard', label: '数据看板', icon: ChartNoAxesCombined },
  { to: '/video-review', label: '视频复盘', icon: BarChart3 },
  { to: '/drafts', label: '脚本工作台', icon: PenLine },
  { to: '/inspiration', label: '灵感随手记', icon: NotebookPen },
  { to: '/benchmark', label: '博主对标', icon: Target },
  { to: '/creators', label: '博主管理', icon: Users },
  { to: '/persona', label: '人设档案', icon: Fingerprint },
  { to: '/prompts', label: 'AI 设置', icon: Settings2 },
  { to: '/chat', label: 'AI 对话', icon: MessageSquare }
]

/** 精确匹配：避免 /videos 误匹配 /video-review */
export function isNavActive(pathname: string, to: string): boolean {
  return pathname === to
}
