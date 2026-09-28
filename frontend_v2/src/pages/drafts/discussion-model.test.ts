import { describe, it, expect } from 'vitest'
import {
  UNKNOWN_MODEL,
  discussionModelInfo,
  discussModelLabel,
  discussRoleLabel,
  latestRun,
  modelInfo,
  parseRun,
  type Discussion,
  type Draft
} from './types'

const row = (over: Partial<Discussion> = {}): Discussion => ({
  id: 1,
  actor: 'model2',
  kind: 'critique',
  round: 1,
  content: '评审内容',
  ...over
})

// R-178：讨论留痕要展示「真实模型 + 版本」，老数据（只有 model1/model2）诚实标注未记录。
describe('讨论留痕的模型展示（R-178）', () => {
  it('角色按 kind 判定：评审=评审方，初稿/修订=生成方', () => {
    expect(discussRoleLabel(row({ kind: 'critique' }))).toBe('评审方')
    expect(discussRoleLabel(row({ kind: 'draft' }))).toBe('生成方')
    expect(discussRoleLabel(row({ kind: 'revise' }))).toBe('生成方')
    expect(discussRoleLabel(row({ kind: 'note', actor: 'system' }))).toBe('系统')
  })

  it('有模型记录时显示「厂家 · 模型版本」', () => {
    expect(discussModelLabel(row({ model_label: 'DeepSeek · deepseek-flash' }))).toBe('DeepSeek · deepseek-flash')
  })

  it('老留痕（只有 model1/model2）显示「未记录模型（历史）」而不是槽位名', () => {
    // 坏数据/历史数据：actor=model1 且没有 model_label
    const legacy = row({ actor: 'model1', kind: 'revise' })
    expect(discussModelLabel(legacy)).toBe(UNKNOWN_MODEL)
    expect(discussModelLabel(legacy)).not.toContain('model1')
    expect(discussModelLabel(row({ model_label: '   ' }))).toBe(UNKNOWN_MODEL)
  })

  it('运行头解析出当时配置的两个模型；坏 JSON 不炸', () => {
    const run = row({
      kind: 'run',
      actor: 'system',
      content: JSON.stringify({
        gen: { slot: 'model1', vendor: 'deepseek', model: 'deepseek-flash', label: 'DeepSeek · deepseek-flash' },
        critic: { slot: 'model2', vendor: 'kimi', model: 'kimi-k2.6', label: 'Kimi（月之暗面） · kimi-k2.6' },
        rounds: 3,
        rounds_done: 3,
        degraded: false
      })
    })
    const parsed = parseRun(run)
    expect(parsed.gen).toBe('DeepSeek · deepseek-flash')
    expect(parsed.critic).toBe('Kimi（月之暗面） · kimi-k2.6')
    expect(parsed.rounds_done).toBe(3)
    expect(parsed.degraded).toBe(false)

    const broken = parseRun(row({ kind: 'run', content: '{不是 JSON' }))
    expect(broken.gen).toBe(UNKNOWN_MODEL)
    expect(broken.rounds).toBeNull()
    expect(broken.degraded).toBeNull()
  })

  it('latestRun 取最近一次运行头（切模型后仍显示历史那次）', () => {
    const list: Discussion[] = [
      row({ id: 1, kind: 'run', content: JSON.stringify({ gen: { label: '旧 · old-1' }, critic: { label: '旧 · old-2' } }) }),
      row({ id: 2, kind: 'critique', model_label: '旧 · old-2' }),
      row({ id: 3, kind: 'run', content: JSON.stringify({ gen: { label: 'DeepSeek · deepseek-flash' }, critic: { label: 'Kimi（月之暗面） · kimi-k2.6' } }) }),
      row({ id: 4, kind: 'revise', model_label: 'DeepSeek · deepseek-flash' })
    ]
    expect(latestRun(list)?.gen).toBe('DeepSeek · deepseek-flash')
    expect(latestRun([row()])).toBeNull()
    expect(discussionModelInfo(list)).toBe('生成方 DeepSeek · deepseek-flash × 评审方 Kimi（月之暗面） · kimi-k2.6')
  })

  it('没有运行头（老数据）回退 quality；两个都没有就不显示', () => {
    const draft = { quality: { models: { gen: 'model1(deepseek/deepseek-flash)', critic: 'model2(kimi/kimi-k2.6)' } } } as unknown as Draft
    expect(modelInfo(draft)).toBe('deepseek-flash × kimi-k2.6')
    expect(discussionModelInfo([row()], draft)).toBe('deepseek-flash × kimi-k2.6')
    expect(discussionModelInfo([], { quality: {} } as unknown as Draft)).toBe('')
  })
})
