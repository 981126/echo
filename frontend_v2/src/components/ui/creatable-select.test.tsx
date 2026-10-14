import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CreatableSelect } from './creatable-select'

// R-224：单选可输入下拉框——打开时必须展示全部候选，不能被当前字段值过滤掉
describe('CreatableSelect（R-224）', () => {
  it('已填当前值时，打开仍展示全部候选', async () => {
    render(
      <CreatableSelect
        value="我说月入过万很简单被喷惨了"
        options={['候选标题一', '候选标题二']}
        onChange={() => {}}
        placeholder="视频标题"
      />
    )
    await userEvent.click(screen.getByPlaceholderText('视频标题'))
    expect(await screen.findByText('候选标题一')).toBeInTheDocument()
    expect(screen.getByText('候选标题二')).toBeInTheDocument()
  })

  it('输入后按搜索词收窄候选', async () => {
    render(<CreatableSelect value="" options={['苹果', '香蕉', '苹果派']} onChange={() => {}} placeholder="标题" />)
    const input = screen.getByPlaceholderText('标题')
    await userEvent.click(input)
    await userEvent.type(input, '苹果')
    expect(await screen.findByText('苹果')).toBeInTheDocument()
    expect(screen.getByText('苹果派')).toBeInTheDocument()
    expect(screen.queryByText('香蕉')).not.toBeInTheDocument()
  })
})
