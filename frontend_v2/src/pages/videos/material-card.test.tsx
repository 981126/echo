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

const statItem: CardItem = {
  ...item,
  platforms: ['bilibili', 'douyin', 'xiaohongshu'],
  cloudPosts: [
    {
      id: 11,
      platform: 'douyin',
      latest_stat: { plays: 17621, likes: 388, favorites: 60, comments: 26, shares: 42, plays_known: true }
    },
    {
      id: 12,
      platform: 'bilibili',
      latest_stat: { plays: 1184, likes: 16, favorites: 7, comments: 8, shares: 0, plays_known: true }
    },
    {
      id: 13,
      platform: 'xiaohongshu',
      latest_stat: { plays: 0, likes: 5, favorites: 1, comments: 3, shares: 0, plays_known: false }
    }
  ]
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

  // R-260：逐平台播放/点赞/收藏/评论/转发；未发布平台不出现；接口没有的字段灰色「-」
  it('逐平台展示 5 项指标，B站转发/小红书播放置灰「-」', () => {
    renderCard({ item: statItem })
    expect(screen.getByLabelText('抖音播放')).toHaveTextContent('1.8w')
    expect(screen.getByLabelText('抖音点赞')).toHaveTextContent('388')
    expect(screen.getByLabelText('抖音收藏')).toHaveTextContent('60')
    expect(screen.getByLabelText('抖音评论')).toHaveTextContent('26')
    expect(screen.getByLabelText('抖音转发')).toHaveTextContent('42')
    expect(screen.getByLabelText('B站播放')).toHaveTextContent('1.2k')
    const bShares = screen.getByLabelText('B站转发')
    expect(bShares).toHaveTextContent('-')
    expect(bShares.className).toContain('text-muted-foreground/40')
    const xhsPlays = screen.getByLabelText('小红书播放')
    expect(xhsPlays).toHaveTextContent('-')
    expect(xhsPlays.className).toContain('text-muted-foreground/40')
    expect(screen.getByLabelText('小红书点赞')).toHaveTextContent('5')
  })

  it('没有发布作品的平台不展示对应行', () => {
    renderCard({
      item: { ...item, platforms: ['douyin'], cloudPosts: [statItem.cloudPosts[0]] }
    })
    expect(screen.getByLabelText('抖音播放')).toBeInTheDocument()
    expect(screen.queryByLabelText('B站播放')).toBeNull()
    expect(screen.queryByLabelText('小红书播放')).toBeNull()
  })

  it('接口没有该平台统计时该行全部灰色「-」', () => {
    renderCard({
      item: { ...item, platforms: ['douyin'], cloudPosts: [{ id: 21, platform: 'douyin', latest_stat: null }] }
    })
    for (const label of ['抖音播放', '抖音点赞', '抖音收藏', '抖音评论', '抖音转发']) {
      const cell = screen.getByLabelText(label)
      expect(cell).toHaveTextContent('-')
      expect(cell.className).toContain('text-muted-foreground/40')
    }
  })

  it('抖音播放量未知（plays_known=false 且为 0）展示灰色「-」', () => {
    renderCard({
      item: {
        ...item,
        platforms: ['douyin'],
        cloudPosts: [
          {
            id: 31,
            platform: 'douyin',
            latest_stat: { plays: 0, likes: 3, favorites: 0, comments: 0, shares: 0, plays_known: false }
          }
        ]
      }
    })
    expect(screen.getByLabelText('抖音播放')).toHaveTextContent('-')
    expect(screen.getByLabelText('抖音点赞')).toHaveTextContent('3')
  })
})
