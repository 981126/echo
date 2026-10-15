import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { EditDrawer } from './edit-drawer'
import * as client from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const orig = await importOriginal<typeof client>()
  return { ...orig, apiJson: vi.fn() }
})
const apiJson = vi.mocked(client.apiJson)

function renderDrawer(over: Partial<Parameters<typeof EditDrawer>[0]> = {}) {
  return render(
    <MemoryRouter>
      <EditDrawer
        videoId={1}
        open={true}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        currentCreatorId={1}
        onPlay={vi.fn()}
        onRewrite={vi.fn()}
        rewriting={false}
        {...over}
      />
    </MemoryRouter>
  )
}

describe('EditDrawer platform checkboxes (R-225)', () => {
  beforeEach(() => apiJson.mockReset())

  it('已绑定平台作品时，平台勾选框只读', async () => {
    apiJson.mockImplementation(((path?: string) => {
      if (path === '/api/videos/1') {
        return Promise.resolve({
          id: 1,
          filename: 'a.mp4',
          title: 't',
          creator_id: 1,
          platforms: ['douyin', 'xiaohongshu', 'bilibili'],
          status: 'published',
          created_at: '2026-10-15T00:00:00Z',
          platform_links: [
            { platform: 'douyin', platform_post_id: 'd1', post_id: 1, url: 'https://douyin.com/d1' },
            { platform: 'xiaohongshu', platform_post_id: 'x1', post_id: 2, url: 'https://xhs.com/x1' }
          ],
          transcript: null
        })
      }
      if (path === '/api/drafts?video_id=1&limit=20') return Promise.resolve([])
      return Promise.resolve({})
    }) as never)

    renderDrawer()
    await waitFor(() => expect(apiJson).toHaveBeenCalledWith('/api/videos/1'))
    const boxes = screen.getAllByRole('checkbox')
    const platformBoxes = boxes.slice(0, 3)
    expect(platformBoxes.length).toBe(3)
    expect(platformBoxes.every((b) => (b as HTMLButtonElement).disabled)).toBe(true)
  })

  it('未绑定平台作品时，平台勾选框可编辑', async () => {
    apiJson.mockImplementation(((path?: string) => {
      if (path === '/api/videos/1') {
        return Promise.resolve({
          id: 1,
          filename: 'a.mp4',
          title: 't',
          creator_id: 1,
          platforms: ['douyin'],
          status: 'published',
          created_at: '2026-10-15T00:00:00Z',
          platform_links: [],
          transcript: null
        })
      }
      if (path === '/api/drafts?video_id=1&limit=20') return Promise.resolve([])
      return Promise.resolve({})
    }) as never)

    renderDrawer()
    await waitFor(() => expect(apiJson).toHaveBeenCalledWith('/api/videos/1'))
    const boxes = screen.getAllByRole('checkbox')
    const platformBoxes = boxes.slice(0, 3)
    expect(platformBoxes.length).toBe(3)
    expect(platformBoxes.every((b) => !(b as HTMLButtonElement).disabled)).toBe(true)
  })
})
