import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { FilterValue } from './filter-value'

describe('FilterValue（R-198）', () => {
  it('默认态显示字段名且不高亮（text-muted-foreground）', () => {
    render(<FilterValue active={false} name="是否广告" label="仅广告" />)
    const el = screen.getByText('是否广告')
    expect(el).toBeDefined()
    expect(el.className).toContain('text-muted-foreground')
  })

  it('选中具体值后显示值且恢复正常前景色', () => {
    render(<FilterValue active name="是否广告" label="仅广告" />)
    const el = screen.getByText('仅广告')
    expect(el.className).not.toContain('text-muted-foreground')
  })

  it('选中但拿不到值文案时回落字段名（不空着）', () => {
    render(<FilterValue active name="当前主博主" />)
    expect(screen.getByText('当前主博主').className).not.toContain('text-muted-foreground')
  })
})
