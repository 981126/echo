import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ScrollArea } from './scroll-area'

// R-177：脚本工作台「讨论」tab 滚动不了 —— 调用方只给 Root `max-h-*`（没有显式高度）时，
// Viewport 的 `h-full` 对 auto 高度父级解析成 auto（= 内容高度），自己没得滚，
// Root 又 overflow:hidden，超出的内容被直接裁掉。
// 修法：Viewport 加 `max-h-[inherit]`，继承 Root 的上限后自己成为滚动容器。
// 真实布局验证（浏览器探针）：Viewport clientHeight 468 / scrollHeight 4215 → 可滚，
// 滚轮 0 → 600 → 1200 → 3747（到底）；改前 Viewport 高度=4215=内容高度，scrollTop 恒为 0。
describe('ScrollArea Viewport 定高（R-177）', () => {
  it('Viewport 继承 Root 的 max-height，只有 max-h 约束时也能滚', () => {
    render(
      <ScrollArea className="max-h-[52vh]" data-testid="root">
        <div style={{ height: 4000 }}>长内容</div>
      </ScrollArea>
    )
    const viewport = document.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement
    expect(viewport).toBeTruthy()
    expect(viewport.className).toContain('max-h-[inherit]')
    // Root 的 max-h 由调用方给（不能被组件内部写死高度，否则短列表会有大片空白）
    expect((screen.getByTestId('root') as HTMLElement).className).toContain('max-h-[52vh]')
  })
})
