import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DraftAiStatus } from './draft-ai-status'
import type { DebateState } from './types'

const running: DebateState = {
  state: 'running',
  kind: 'rewrite',
  note: 'MODEL1 正在按评审修订第 3/3 轮…',
  actor: 'model1',
  phase: 'revise',
  round: 3,
  rounds: 3
}

const failed: DebateState = {
  state: 'failed',
  kind: 'rewrite',
  note: '洗稿中断：timeout',
  actor: '',
  phase: '',
  round: null,
  rounds: null
}

describe('DraftAiStatus（R-173）', () => {
  it('没有任务时不渲染', () => {
    const { container } = render(<DraftAiStatus debate={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('running：显示类型 + 模型/步骤文案 + 第 x/y 轮 + 三点跳动', () => {
    const { container } = render(<DraftAiStatus debate={running} />)
    const box = screen.getByTestId('draft-ai-status')
    expect(box.dataset.state).toBe('running')
    expect(box.textContent).toContain('洗稿讨论')
    expect(box.textContent).toContain('MODEL1 正在按评审修订第 3/3 轮…')
    expect(box.textContent).toContain('第 3/3 轮')
    // 三点跳动：三个 motion span
    expect(container.querySelectorAll('span.block').length).toBe(3)
  })

  it('failed：显示「上次讨论中断」并提示可重新讨论（不是 running 动画）', () => {
    render(<DraftAiStatus debate={failed} />)
    const box = screen.getByTestId('draft-ai-status')
    expect(box.dataset.state).toBe('failed')
    expect(box.textContent).toContain('上次讨论中断')
    expect(box.textContent).toContain('洗稿中断：timeout')
    expect(box.textContent).toContain('重新讨论')
  })
})
