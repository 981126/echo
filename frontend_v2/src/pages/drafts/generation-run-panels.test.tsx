import { fireEvent, render, screen } from '@testing-library/react'
import { GenerationRunPanels, type GenerationRun } from './generation-run-panels'

function run(patch: Partial<GenerationRun> = {}): GenerationRun {
  return {
    run_id: 1,
    draft_id: 2,
    status: 'succeeded',
    stage: 'done',
    topic: '主题',
    selected_angle: { angle_id: 'a1', title: '最佳角度', promise: '一个核心承诺', total_score: 88 },
    angles: [
      { angle_id: 'a1', title: '最佳角度', promise: '一个核心承诺' },
      { angle_id: 'a2', title: '备选角度', promise: '另一个核心承诺' }
    ],
    evidence: { author_assets: [], online_sources: [], questions: [] },
    review: { executed: true, logic_passed: true, attraction_score: 4, author_score: 4, issues: [] },
    quality_passed: true,
    ...patch
  }
}

describe('GenerationRunPanels', () => {
  it('shows real quality result and switches angle', () => {
    const onAngle = vi.fn()
    render(<GenerationRunPanels run={run()} onAngle={onAngle} reworking={false} />)
    expect(screen.getByText('质量通过')).toBeInTheDocument()
    expect(screen.getByText('一个核心承诺')).toBeInTheDocument()
    fireEvent.click(screen.getByText('用此角度重新生成'))
    expect(onAngle).toHaveBeenCalledWith('a2')
  })

  it('distinguishes needs_input and unexecuted review', () => {
    render(
      <GenerationRunPanels
        run={run({ status: 'needs_input', quality_passed: false, error: '缺少关键目标', review: { executed: false }, evidence: { questions: ['真正目标是什么？'], author_assets: [], online_sources: [] } })}
        onAngle={vi.fn()}
        reworking={false}
      />
    )
    expect(screen.getByText(/待补信息/)).toBeInTheDocument()
    expect(screen.getByText('真正目标是什么？')).toBeInTheDocument()
    expect(screen.getByText('评审未执行')).toBeInTheDocument()
    expect(screen.queryByText('质量通过')).not.toBeInTheDocument()
  })

  it('renders structured blueprint fields without crashing', () => {
    render(
      <GenerationRunPanels
        run={run({ blueprint: { goal: '明确目标', audience: { fit: '上班族', not_fit: '客服' }, core_promise: '一个核心承诺', reasoning_steps: [], actions: [] } })}
        onAngle={vi.fn()}
        reworking={false}
      />
    )
    expect(screen.getByText(/fit：上班族/)).toBeInTheDocument()
    expect(screen.getByText(/not_fit：客服/)).toBeInTheDocument()
  })

  it('does not present failed generation as success', () => {
    render(<GenerationRunPanels run={run({ status: 'failed', quality_passed: false, error: '模型超时', review: { executed: false } })} onAngle={vi.fn()} reworking={false} />)
    expect(screen.getByText(/模型超时/)).toBeInTheDocument()
    expect(screen.getByText('未通过')).toBeInTheDocument()
  })
})
