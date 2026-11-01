import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { CrossfadeTrendLine } from './charts'

const reducedMotion = vi.hoisted(() => ({ value: false }))
vi.mock('framer-motion', async (importOriginal) => {
  const actual = await importOriginal<typeof import('framer-motion')>()
  return { ...actual, useReducedMotion: () => reducedMotion.value }
})

afterEach(() => {
  reducedMotion.value = false
})

const pointsA = [
  { label: '10-01', value: 10 },
  { label: '10-02', value: 20 },
  { label: '10-03', value: 15 }
]
const pointsB = [
  { label: '10-01', value: 30 },
  { label: '10-02', value: 10 },
  { label: '10-03', value: 25 }
]

function Trend({ transitionKey, label }: { transitionKey: string; label: string }) {
  return (
    <CrossfadeTrendLine
      transitionKey={transitionKey}
      points={transitionKey === 'a' ? pointsA : pointsB}
      ariaLabel={label}
      height={300}
    />
  )
}

describe('CrossfadeTrendLine', () => {
  it('首次绘制只渲染当前曲线，不制造旧曲线层', () => {
    render(<Trend transitionKey="a" label="曲线 A" />)
    expect(screen.queryByTestId('trend-outgoing')).not.toBeInTheDocument()
    expect(screen.getByTestId('trend-current').style.opacity).toBe('1')
  })

  it('A 切 B 时旧曲线从 1 淡出，新曲线从 0 淡入', () => {
    const { rerender } = render(<Trend transitionKey="a" label="曲线 A" />)
    rerender(<Trend transitionKey="b" label="曲线 B" />)

    const outgoing = screen.getByTestId('trend-outgoing')
    const current = screen.getByTestId('trend-current')
    expect(outgoing.style.opacity).toBe('1')
    expect(current.style.opacity).toBe('0')
    expect(within(outgoing).getByText('曲线 A')).toBeInTheDocument()
    expect(within(current).getByText('曲线 B')).toBeInTheDocument()
  })

  it('连续快速切换时，旧层始终是上一轮可见曲线', () => {
    const { rerender } = render(<Trend transitionKey="a" label="曲线 A" />)
    rerender(<Trend transitionKey="b" label="曲线 B" />)
    rerender(<Trend transitionKey="c" label="曲线 C" />)

    expect(within(screen.getByTestId('trend-outgoing')).getByText('曲线 B')).toBeInTheDocument()
    expect(within(screen.getByTestId('trend-current')).getByText('曲线 C')).toBeInTheDocument()
  })

  it('减少动态效果时直接替换，不保留交叉动画层', () => {
    reducedMotion.value = true
    const { rerender } = render(<Trend transitionKey="a" label="曲线 A" />)
    rerender(<Trend transitionKey="b" label="曲线 B" />)

    expect(screen.queryByTestId('trend-outgoing')).not.toBeInTheDocument()
    expect(screen.getByTestId('trend-current').style.opacity).toBe('1')
  })
})
