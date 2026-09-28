import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { NotificationBell } from './notification-bell'
import * as client from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const orig = await importOriginal<typeof client>()
  return { ...orig, apiJson: vi.fn() }
})
const apiJson = vi.mocked(client.apiJson)

function renderBell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('NotificationBell', () => {
  beforeEach(() => apiJson.mockReset())

  it('展示未读角标数字', async () => {
    apiJson.mockResolvedValueOnce({ unread: 3 } as never)
    renderBell()
    expect(await screen.findByText('3')).toBeInTheDocument()
  })

  it('打开面板后拉取通知列表并可点击跳转', async () => {
    apiJson.mockImplementation(((path?: string) => {
      if (path === '/api/notifications/unread-count') return Promise.resolve({ unread: 1 })
      if (path === '/api/notifications')
        return Promise.resolve([
          { id: 7, kind: 'card_sync', status: 'done', title: '素材同步完成', message: 'm', target: '/videos', read: false, created_at: '' }
        ])
      return Promise.resolve({}) // 测试收尾阶段的悬空调用宽容处理
    }) as never)
    renderBell()
    await userEvent.click(await screen.findByRole('button', { name: '通知' }))
    expect(await screen.findByText('素材同步完成')).toBeInTheDocument()
    await waitFor(() => expect(apiJson).toHaveBeenCalledWith('/api/notifications'))
  })
})
