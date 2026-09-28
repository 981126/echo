import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './tabs'

function Demo() {
  return (
    <Tabs defaultValue="a">
      <TabsList>
        <TabsTrigger value="a">A</TabsTrigger>
        <TabsTrigger value="b">B</TabsTrigger>
      </TabsList>
      <TabsContent value="a" className="space-y-2">
        <p>内容A</p>
      </TabsContent>
      <TabsContent value="b" className="space-y-2">
        <p>内容B</p>
      </TabsContent>
    </Tabs>
  )
}

const activePanel = () => document.querySelector('[role="tabpanel"][data-state="active"]') as HTMLElement

describe('TabsContent 入场动效（R-174）', () => {
  it('未选中的 tab 不渲染，切过去才挂载（因此动画每次都会播）', async () => {
    render(<Demo />)
    expect(screen.getByText('内容A')).toBeInTheDocument()
    expect(screen.queryByText('内容B')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'B' }))
    expect(screen.getByText('内容B')).toBeInTheDocument()
  })

  it('内容包在 motion 容器里，且调用方的 className 挂在内层（不破坏 space-y-*）', async () => {
    render(<Demo />)
    const panel = activePanel()
    const wrapper = panel.firstElementChild as HTMLElement
    expect(wrapper).toBeTruthy()
    expect(wrapper.className).toContain('space-y-2')
    expect(wrapper.className).toContain('outline-none')
    // 内层才是间距容器：space-y-2 的直接子元素应是内容本身
    expect(wrapper.firstElementChild?.tagName).toBe('P')
  })

  it('切回同一 tab 是重新挂载（DOM 节点不同）→ 入场动画会重播', async () => {
    render(<Demo />)
    await userEvent.click(screen.getByRole('tab', { name: 'B' }))
    const first = activePanel().firstElementChild
    await userEvent.click(screen.getByRole('tab', { name: 'A' }))
    await userEvent.click(screen.getByRole('tab', { name: 'B' }))
    const second = activePanel().firstElementChild
    expect(second).toBeTruthy()
    expect(second).not.toBe(first)
  })
})
