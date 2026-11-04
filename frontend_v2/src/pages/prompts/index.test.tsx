import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PromptsPage from './index'
import { toast } from '@/components/ui/toaster'
import * as client from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const orig = await importOriginal<typeof client>()
  return { ...orig, apiJson: vi.fn() }
})
vi.mock('@/components/ui/toaster', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }
}))

const apiJson = vi.mocked(client.apiJson)
const toastError = vi.mocked(toast.error)

// 页面基础 tab 也依赖模型设置，给一份最小可用数据
const modelsPayload = {
  model1: { vendor: 'siliconflow', model: 'm1', key: '', base_url: 'https://x', key_present: true, key_from_env: true, vendor_label: '厂家1', key_hint: '' },
  model2: { vendor: 'siliconflow', model: 'm2', key: '', base_url: 'https://x', key_present: true, key_from_env: true, vendor_label: '厂家2', key_hint: '' },
  gen_role: 'model1',
  referee_role: 'model2',
  asr: { mode: 'aliyun', model: '', options: {}, siliconflow_models: [], tencent_models: [] },
  debate_rounds: 5,
  topics_count: 3,
  vendors: {},
  warnings: [],
  budgets: {},
  feature_routes: {},
  selfcheck: null
}

/** R-255 之前的旧接口行（没有 title/module/category/editable 等新字段） */
function oldItem(key: string, label: string, group: string, enabledVersion: number) {
  return {
    key,
    label,
    group,
    enabled_version: enabledVersion,
    content: `${label}正文`,
    has_candidate: false,
    candidate_version: 0,
    candidate_content: '',
    candidate_note: '',
    eval: null,
    effect: [],
    versions: []
  }
}

/** R-255 新接口行 */
function newItem(over: Record<string, unknown>) {
  return {
    key: 'k',
    label: '',
    group: 'production',
    enabled_version: 1,
    content: '正文',
    has_candidate: false,
    candidate_version: 0,
    candidate_content: '',
    candidate_note: '',
    eval: null,
    effect: [],
    versions: [],
    category: 'system',
    editable: true,
    optimizable: true,
    sort_order: 0,
    ...over
  }
}

function mockApi(keys: () => Promise<unknown>) {
  apiJson.mockImplementation(((path?: string) => {
    if (path === '/api/settings/models') return Promise.resolve(modelsPayload)
    if (path === '/api/prompts/keys') return keys()
    return Promise.resolve({})
  }) as never)
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <PromptsPage />
    </QueryClientProvider>
  )
  return qc
}

async function openAdvanced() {
  await userEvent.click(await screen.findByRole('tab', { name: /高级/ }))
}

describe('PromptsPage R-255 提示词清单', () => {
  beforeEach(() => {
    apiJson.mockReset()
    toastError.mockReset()
  })

  it('旧接口（无新字段）兜底：归入「全部提示词」组，选中可编辑并显示保存按钮', async () => {
    mockApi(() => Promise.resolve([oldItem('generation', '生成脚本', 'production', 3), oldItem('persona_init', '人设逐篇提取', 'persona_engine', 2)]))
    renderPage()
    await openAdvanced()

    expect(await screen.findByText('全部提示词')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /保存为新版本并启用/ })).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('生成脚本正文')

    await userEvent.click(screen.getByRole('button', { name: /人设逐篇提取/ }))
    expect(screen.getByRole('textbox')).toHaveValue('人设逐篇提取正文')
    expect(screen.queryByRole('button', { name: /AI 基于真实样本优化/ })).not.toBeNull()
  })

  it('新接口：按 module 分组、组内按 sort_order 排序，契约行只出现在只读折叠区', async () => {
    mockApi(() =>
      Promise.resolve([
        newItem({ key: 'b', title: '脚本B', label: '脚本B', module: 'gen', module_label: '脚本生成', purpose: '用途B', sort_order: 1, has_candidate: true, candidate_version: 2, candidate_content: '候选B', optimizable: false }),
        newItem({ key: 'a', title: '脚本A', label: '脚本A', module: 'gen', module_label: '脚本生成', purpose: '用途A', sort_order: 2 }),
        newItem({ key: 'p', title: '自检探针', label: '自检探针', module: 'selfcheck', module_label: '系统自检', purpose: '用途P', category: 'probe', editable: false, optimizable: false, enabled_version: 0, content: '探针正文' }),
        newItem({ key: 'c', title: '输出契约C', label: '输出契约C', module: 'contract', module_label: '输出契约', purpose: '用途C', category: 'contract', editable: false, optimizable: false, enabled_version: 0, content: '契约正文', versions: [] })
      ])
    )
    renderPage()
    await openAdvanced()

    expect((await screen.findAllByText('系统自检')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('脚本生成').length).toBeGreaterThan(0)
    // 组内 sort_order 升序：B(1) 在 A(2) 之前
    const rowA = screen.getByRole('button', { name: /脚本A/ })
    const rowB = screen.getByRole('button', { name: /脚本B/ })
    expect(rowB.compareDocumentPosition(rowA) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // 契约行不进入可选清单，只在只读契约区展示正文
    expect(screen.queryByRole('button', { name: /输出契约C/ })).toBeNull()
    expect(screen.getByText('契约正文')).toBeInTheDocument()

    // 内部探针：只读文本域，无保存/优化按钮
    await userEvent.click(screen.getByRole('button', { name: /自检探针/ }))
    expect(screen.getByRole('textbox')).toHaveAttribute('readonly')
    expect(screen.getByRole('textbox')).toHaveValue('探针正文')
    expect(screen.queryByRole('button', { name: /保存为新版本并启用/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /AI 基于真实样本优化/ })).toBeNull()

    // optimizable=false：仍可编辑，但隐藏 AI 优化与评测按钮
    await userEvent.click(screen.getByRole('button', { name: /脚本B/ }))
    expect(screen.getByRole('textbox')).not.toHaveAttribute('readonly')
    expect(screen.getByRole('button', { name: /保存为新版本并启用/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /跑评测|重跑评测/ })).toBeNull()
    expect(screen.getByRole('button', { name: /启用此版本/ })).toBeInTheDocument()
  })

  it('空数据：提示尚未初始化并提供重新读取按钮', async () => {
    mockApi(() => Promise.resolve([]))
    renderPage()
    await openAdvanced()

    const tip = await screen.findByText('提示词清单尚未初始化，后端启动会自动补种；若持续为空请检查数据库迁移')
    expect(within(tip.parentElement as HTMLElement).getByRole('button', { name: /重新读取/ })).toBeInTheDocument()
  })

  it('请求失败：toast 报错且保留上一次成功的清单', async () => {
    let fail = false
    mockApi(() => (fail ? Promise.reject(new Error('模拟接口失败')) : Promise.resolve([oldItem('generation', '生成脚本', 'production', 3)])))
    const qc = renderPage()
    await openAdvanced()
    expect(await screen.findByRole('button', { name: /生成脚本/ })).toBeInTheDocument()

    fail = true
    await qc.refetchQueries({ queryKey: ['prompts', 'keys'] })
    await waitFor(() => expect(toastError).toHaveBeenCalled(), { timeout: 4000 })
    // 失败后旧数据仍在，页面不清空
    expect(screen.getByRole('button', { name: /生成脚本/ })).toBeInTheDocument()
  }, 10000)
})
