import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { BaselineBars, formatMetric, WatchTrendChart } from './charts'
import type { Metric } from './types'

const metric: Metric = {
  key: 'plays', label: '播放量', unit: '次', value: 48000, baseline: 12000,
  percentile: 90, state: 'high', sample_count: 10, missing: false
}

describe('视频复盘图表', () => {
  it('按单位格式化，缺失值不显示为0', () => {
    expect(formatMetric(null, '次')).toBe('暂无数据')
    expect(formatMetric(0, '次')).toBe('0次')
    expect(formatMetric(0.256, 'ratio')).toBe('25.6%')
    expect(formatMetric(42, '秒')).toBe('42.0秒')
  })

  it('同时显示当前与平时，并可切换数据表', () => {
    render(<BaselineBars metrics={[metric]} />)
    expect(screen.getAllByText('48,000次').length).toBeGreaterThan(0)
    expect(screen.getAllByText('12,000次').length).toBeGreaterThan(0)
    expect(screen.getByText('↑ 高于平时')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '数据表' }))
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('趋势图带中文说明、时间和百分比', () => {
    const { container } = render(<WatchTrendChart data={{
      reliable: true,
      plays: 1000,
      has_timed_transcript: false,
      points: [
        { time_seconds: 0, time_label: '00:00', current: 0.8, similar_author: 0.7 },
        { time_seconds: 10, time_label: '00:10', current: 0.5, similar_author: 0.6 }
      ]
    }} />)
    expect(screen.getByRole('img', { name: '观看趋势折线图' })).toBeInTheDocument()
    expect(screen.getByText('00:00')).toBeInTheDocument()
    expect(screen.getByText('00:10')).toBeInTheDocument()
    expect(container.textContent).toContain('下降30.0个百分点')
  })
})
