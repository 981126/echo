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
  it('两个标签可切换：默认论点，点「引用来源」看来源并标「已引用」', async () => {
    render(<EvidencePanel outlines={outlines} sources={used} onlineSources={onlineSources} />)

    expect(screen.getByRole('tab', { name: /论点 2/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /引用来源 2/ })).toBeInTheDocument()
    expect(screen.getByText('论点一')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: /引用来源 2/ }))
    expect(screen.getByText('来源A')).toBeInTheDocument()
    expect(screen.getByText('来源B')).toBeInTheDocument()
    expect(screen.getByText('已引用')).toBeInTheDocument()
  })

  it('右侧箭头可收起/展开', async () => {
    render(<EvidencePanel outlines={outlines} sources={used} onlineSources={onlineSources} />)
    expect(screen.getByText('论点一')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '收起' }))
    expect(screen.queryByText('论点一')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '展开' }))
    expect(screen.getByText('论点一')).toBeInTheDocument()
  })

  it('只有来源时直接展示来源（无标签切换）', () => {
    render(<EvidencePanel sources={[]} onlineSources={onlineSources} />)
    expect(screen.getByText(/引用来源 2/)).toBeInTheDocument()
    expect(screen.getByText('来源A')).toBeInTheDocument()
  })

  it('全空不渲染', () => {
    const { container } = render(<EvidencePanel />)
    expect(container).toBeEmptyDOMElement()
  })
})
