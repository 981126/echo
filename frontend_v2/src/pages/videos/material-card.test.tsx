import { describe, it, expect, vi } from 'vitest'
import { createRef } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TooltipProvider } from '@/components/ui/tooltip'
import { MaterialCard } from './material-card'
import type { CardItem } from './types'

const item: CardItem = {
  key: 'v1',
  kind: 'local',
  id: 1,
  title: '测试素材标题',
  cover_url: '',
  platforms: ['douyin'],
  tags: ['求职'],
  status: 'published',
  is_ad: false,
  merged: 0,
  cloudPosts: [],
  hasVideo: true,
  filename: 'a.mp4',
  tags_confirmed: false,
  date: '2026-09-10'
}

function renderCard(over: Partial<Parameters<typeof MaterialCard>[0]> = {}) {
  const props = {
    item,
    index: 0,
    selectMode: false,
    selected: false,
    onOpen: vi.fn(),
    onToggle: vi.fn(),
    onPlay: vi.fn(),
    onSync: vi.fn(),
    onConfirmTags: vi.fn(),
    onDelete: vi.fn(),
    onSplit: vi.fn(),
    ...over
  }
  render(
    <TooltipProvider>
      <MaterialCard {...props} />
    </TooltipProvider>
  )
  return props
}

describe('MaterialCard', () => {
  it('渲染标题/平台/日期/标签确认按钮', () => {
    renderCard()
    expect(screen.getByText('测试素材标题')).toBeInTheDocument()
    expect(screen.getByText('本地')).toBeInTheDocument()
    expect(screen.getByText('2026-09-10')).toBeInTheDocument()
    expect(screen.getByText('求职')).toBeInTheDocument()
  })

  it('同步进度覆盖层展示百分比与说明', () => {
    renderCard({ task: { progress: 46, note: '下载中…', taskId: 9 } })
    expect(screen.getByText('下载中…')).toBeInTheDocument()
    expect(screen.getByText('46%')).toBeInTheDocument()
  })

  it('点击信息区打开编辑、操作行触发同步', async () => {
    const props = renderCard()
    await userEvent.click(screen.getByText('测试素材标题'))
    expect(props.onOpen).toHaveBeenCalledWith(item)
    const buttons = screen.getAllByRole('button')
    await userEvent.click(buttons[0]) // 同步
    expect(props.onSync).toHaveBeenCalledWith(item)
  })

  // R-199 根因回归：AnimatePresence mode="popLayout" 靠给子元素挂 ref 量盒子来把「退场卡」弹出文档流。
  // 卡片若不 forwardRef（或用 memo 包住忘了透传），framer 量不到元素 → 退场卡留在流里 → 新卡被挤到屏幕外播动画。
  it('ref 透传到根节点（popLayout 量测退场卡必需）', () => {
    const ref = createRef<HTMLDivElement>()
    render(
      <TooltipProvider>
        <MaterialCard
          ref={ref}
          item={item}
          index={0}
          selectMode={false}
          selected={false}
          onOpen={vi.fn()}
          onToggle={vi.fn()}
          onPlay={vi.fn()}
          onSync={vi.fn()}
          onConfirmTags={vi.fn()}
          onDelete={vi.fn()}
          onSplit={vi.fn()}
        />
      </TooltipProvider>
    )
    expect(ref.current).toBeInstanceOf(HTMLElement)
    expect(ref.current?.textContent).toContain('测试素材标题')
  })
})
