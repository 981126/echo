import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EvidencePanel } from './evidence-panel'

const outlines = [
  { claim: '论点一', support: '一个具体事例' },
  { claim: '论点二', support: '一个数字' },
]
const onlineSources = [
  { title: '来源A', url: 'https://a.example/x', site: 'a.example' },
  { title: '来源B', url: 'https://b.example/y', site: 'b.example' },
]
const used = [{ title: '来源A', url: 'https://a.example/x', site: 'a.example' }]

describe('EvidencePanel（R-227）', () => {
  it('顶部显示联网搜索词', () => {
    render(<EvidencePanel outlines={outlines} queries={[{ query: '面试反问 薪资社保' }]} />)
    expect(screen.getByText(/联网搜索词/)).toBeInTheDocument()
    expect(screen.getByText(/面试反问 薪资社保/)).toBeInTheDocument()
  })

  it('R-233：双源搜索词显示 provider', () => {
    render(
      <EvidencePanel
        queries={[
          { provider: 'doubao', query: '面试反问' },
          { provider: 'deepseek', query: '面试反问' },
        ]}
      />,
    )
    expect(screen.getByText(/豆包/)).toBeInTheDocument()
    expect(screen.getByText(/DeepSeek/)).toBeInTheDocument()
  })

  it('R-233：默认只展示生成方选中的参考与理由，可展开全部候选', async () => {
    const refs = [
      {
        title: '来源A',
        url: 'https://a.example/x',
        site: 'a.example',
        provider: 'deepseek',
        reason: '提供薪资数据',
      },
    ]
    render(
      <EvidencePanel
        outlines={outlines}
        sources={used}
        onlineSources={onlineSources}
        references={refs}
      />,
    )
    await userEvent.click(screen.getByRole('tab', { name: /引用来源 2/ }))
    expect(screen.getByText(/生成方按人设选了 1 篇/)).toBeInTheDocument()
    expect(screen.getByText(/提供薪资数据/)).toBeInTheDocument()
    expect(screen.getByText('来源A')).toBeInTheDocument()
    expect(screen.queryByText('来源B')).not.toBeInTheDocument()
    await userEvent.click(screen.getByText(/查看全部候选 2 条/))
    expect(screen.getByText('来源B')).toBeInTheDocument()
  })

  it('引用来源默认只看已引用，可展开全部检索', async () => {
    render(<EvidencePanel outlines={outlines} sources={used} onlineSources={onlineSources} />)
    await userEvent.click(screen.getByRole('tab', { name: /引用来源 2/ }))
    expect(screen.getByText('来源A')).toBeInTheDocument()
    expect(screen.getByText('已引用')).toBeInTheDocument()
    expect(screen.queryByText('来源B')).not.toBeInTheDocument()
    await userEvent.click(screen.getByText(/查看全部检索到的 2 条/))
    expect(screen.getByText('来源B')).toBeInTheDocument()
  })

  it('右侧箭头可收起/展开', async () => {
    render(<EvidencePanel outlines={outlines} sources={used} onlineSources={onlineSources} />)
    expect(screen.getByText('论点一')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '收起' }))
    expect(screen.queryByText('论点一')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '展开' }))
    expect(screen.getByText('论点一')).toBeInTheDocument()
  })

  it('只有搜索词也可渲染', () => {
    const { container } = render(<EvidencePanel queries={[{ query: '某搜索词' }]} />)
    expect(container).not.toBeEmptyDOMElement()
    expect(screen.getByText(/某搜索词/)).toBeInTheDocument()
  })

  it('全空不渲染', () => {
    const { container } = render(<EvidencePanel />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('EvidencePanel（R-230 论点漂移提示）', () => {
  it('outlineDrift 时论点区与来源区各提示「以正文为准」口径', async () => {
    render(
      <EvidencePanel
        outlines={outlines}
        sources={used}
        onlineSources={onlineSources}
        outlineDrift
      />,
    )
    // 论点 tab 默认激活：论点区提示可见
    expect(screen.getByText(/论点为讨论前初稿口径/)).toBeInTheDocument()
    // 来源区提示要先切到来源 tab
    await userEvent.click(screen.getByRole('tab', { name: /引用来源 2/ }))
    expect(screen.getByText(/引用为讨论前初稿口径/)).toBeInTheDocument()
  })

  it('outlineDrift 为 false/缺省时无提示', () => {
    render(<EvidencePanel outlines={outlines} sources={used} onlineSources={onlineSources} />)
    expect(screen.queryByText(/论点为讨论前初稿口径/)).not.toBeInTheDocument()
  })
})
