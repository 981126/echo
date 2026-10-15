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
  it('顶部显示提交给豆包的搜索词', () => {
    render(<EvidencePanel outlines={outlines} queries={[{ query: '面试反问 薪资社保' }]} />)
    expect(screen.getByText(/豆包搜索词/)).toBeInTheDocument()
    expect(screen.getByText(/面试反问 薪资社保/)).toBeInTheDocument()
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
