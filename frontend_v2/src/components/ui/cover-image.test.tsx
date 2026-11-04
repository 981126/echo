import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CoverImage } from './cover-image'

describe('封面图兜底（R-249）', () => {
  it('本地封面缩略图失败后回退原图，再失败显示占位（不出现裂图）', () => {
    render(<CoverImage url="/covers/测试-封面.jpg" alt="封面" placeholder={<span>占位</span>} />)
    let img = screen.getByAltText('封面') as HTMLImageElement
    expect(img.getAttribute('src')).toBe('/covers/测试-封面.jpg?w=400')

    fireEvent.error(img)
    img = screen.getByAltText('封面') as HTMLImageElement
    expect(img.getAttribute('src')).toBe('/covers/测试-封面.jpg')

    fireEvent.error(img)
    expect(screen.queryByAltText('封面')).toBeNull()
    expect(screen.getByText('占位')).toBeInTheDocument()
  })

  it('远程封面 URL 不追加缩略参数，失败直接显示占位', () => {
    render(<CoverImage url="https://example.com/a.jpg" alt="远程封面" placeholder={<span>远程占位</span>} />)
    const img = screen.getByAltText('远程封面') as HTMLImageElement
    expect(img.getAttribute('src')).toBe('https://example.com/a.jpg')

    fireEvent.error(img)
    expect(screen.queryByAltText('远程封面')).toBeNull()
    expect(screen.getByText('远程占位')).toBeInTheDocument()
  })

  it('无封面 URL 时直接渲染占位', () => {
    render(<CoverImage url={null} alt="空封面" placeholder={<span>空占位</span>} />)
    expect(screen.getByText('空占位')).toBeInTheDocument()
    expect(screen.queryByAltText('空封面')).toBeNull()
  })
})
