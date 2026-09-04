<template>
  <div class="page">
    <h1 class="page-title">AI 提示词</h1>
    <p class="page-sub">查看/编辑各功能提示词；上传新视频会自动产出候选版（不直接启用）</p>

    <div class="toolbar">
      <span class="muted">生成模型策略：</span>
      <n-select v-model:value="genMode" :options="modeOptions" style="width: 200px" @update:value="saveMode" />
      <span class="muted">讨论轮次：</span>
      <n-input-number v-model:value="debateRounds" :min="1" :max="10" style="width: 90px" @update:value="saveRounds" />
    </div>

    <n-tabs v-model:value="activeKey" type="line" animated>
      <n-tab-pane v-for="item in items" :key="item.key" :name="item.key" :tab="item.label">
        <div class="panel">
          <div class="row" style="justify-content: space-between; margin-bottom: 8px">
            <strong>当前启用 · v{{ item.enabled_version }}</strong>
            <n-tag v-if="item.has_candidate" size="small" :bordered="false" round type="warning">
              有候选 v{{ item.candidate_version }} 待启用
            </n-tag>
          </div>
          <n-input
            v-model:value="editing[item.key]"
            type="textarea"
            :rows="14"
            class="prompt-input"
            placeholder="提示词正文"
          />
          <div class="row" style="margin-top: 12px">
            <n-button type="primary" @click="save(item)">保存为新版本并启用</n-button>
            <n-button secondary :loading="optimizingKey === item.key" @click="optimize(item)">
              AI 基于最新素材优化（候选）
            </n-button>
          </div>
        </div>

        <div v-if="candidate(item)" class="panel" style="border-left: 3px solid var(--warn)">
          <div class="row" style="justify-content: space-between; margin-bottom: 6px">
            <strong>候选版 v{{ candidate(item).version }}</strong>
            <n-button size="small" type="primary" @click="enable(item, candidate(item).version)">启用此版本</n-button>
          </div>
          <p class="muted" style="margin: 0 0 8px">{{ candidate(item).note }}</p>
          <pre class="prompt-pre dview"><span
            v-for="(l, i) in diffOf(item)"
            :key="i"
            :class="'d-' + l.type"
          >{{ prefix(l.type) + l.text }}</span></pre>
        </div>

        <div class="panel">
          <div class="section-title" style="margin-top: 0">历史版本</div>
          <div v-if="!versions(item).length" class="empty" style="padding: 20px 0">暂无历史</div>
          <div v-for="v in versions(item)" :key="v.id" class="ver-row">
            <details>
              <summary>
                <span class="ver-title">v{{ v.version }}</span>
                <n-tag v-if="v.status === 'enabled'" size="tiny" :bordered="false" round type="success">启用中</n-tag>
                <n-tag v-else-if="v.status === 'candidate'" size="tiny" :bordered="false" round type="warning">候选</n-tag>
                <n-tag v-else size="tiny" :bordered="false" round>历史</n-tag>
                <span class="muted" style="margin-left: 8px">{{ v.note }} · {{ fmt(v.created_at) }}</span>
              </summary>
              <pre class="prompt-pre">{{ v.content }}</pre>
              <n-button v-if="v.status !== 'enabled'" size="tiny" type="primary" ghost @click="enable(item, v.version)">
                启用 v{{ v.version }}
              </n-button>
            </details>
          </div>
        </div>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'
import { diffLines } from '../diff'

const ORDER = ['generation', 'persona_init', 'video_tags', 'persona_updates', 'review', 'diff', 'chat', 'correct']
const items = ref([])
const activeKey = ref('generation')
const editing = ref({})
const optimizingKey = ref(null)
const message = useMessage()
const genMode = ref('deepseek')
const debateRounds = ref(5)
const modeOptions = [
  { label: 'DeepSeek（Kimi 评审）', value: 'deepseek' },
  { label: 'Kimi（DeepSeek 评审）', value: 'kimi' },
  { label: '随机生成方', value: 'random' },
  { label: '轮流生成方', value: 'alternate' }
]

function fmt(v) {
  return v ? v.replace('T', ' ').slice(0, 16) : ''
}

function versions(item) {
  return [...(item.versions || [])].sort((a, b) => b.version - a.version)
}

function candidate(item) {
  return (item.versions || []).find(v => v.status === 'candidate')
}

function diffOf(item) {
  const c = candidate(item)
  if (!c) return []
  return diffLines(item.content || '', c.content || '')
}

function prefix(type) {
  if (type === 'add') return '+ '
  if (type === 'del') return '- '
  return '  '
}

async function loadMode() {
  try {
    const r = await api('/api/settings/generation-model')
    genMode.value = r.mode
  } catch {
    /* ignore */
  }
}

async function loadRounds() {
  try {
    const r = await api('/api/settings/debate-rounds')
    debateRounds.value = r.rounds
  } catch {
    /* ignore */
  }
}

async function saveRounds(n) {
  try {
    await api('/api/settings/debate-rounds', { method: 'PUT', body: JSON.stringify({ rounds: n }) })
    message.success('已更新讨论轮次')
  } catch (e) {
    message.error(e.message)
  }
}

async function saveMode(mode) {
  try {
    await api('/api/settings/generation-model', { method: 'PUT', body: JSON.stringify({ mode }) })
    message.success('已切换生成模型策略')
  } catch (e) {
    message.error(e.message)
  }
}

async function load() {
  const rows = await api('/api/prompts/keys')
  rows.sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key))
  items.value = rows
  rows.forEach((r) => {
    if (editing.value[r.key] === undefined) editing.value[r.key] = r.content || ''
  })
}

async function save(item) {
  const content = (editing.value[item.key] || '').trim()
  if (!content) {
    message.warning('提示词不能为空')
    return
  }
  await api(`/api/prompts/${item.key}/save`, { method: 'POST', body: JSON.stringify({ content }) })
  message.success('已保存为新版本并启用（旧版已归档）')
  await load()
}

async function optimize(item) {
  optimizingKey.value = item.key
  try {
    const r = await api(`/api/prompts/${item.key}/optimize`, { method: 'POST', body: JSON.stringify({ material: '' }) })
    message.success(`已产出候选 v${r.version}，可预览后启用`)
    await load()
  } catch (e) {
    message.error(e.message)
  } finally {
    optimizingKey.value = null
  }
}

async function enable(item, version) {
  await api(`/api/prompts/${item.key}/enable`, { method: 'POST', body: JSON.stringify({ version }) })
  message.success(`已启用 v${version}`)
  await load()
}

onMounted(() => { load(); loadMode(); loadRounds() })
</script>
