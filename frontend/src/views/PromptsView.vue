<template>
  <div class="page">
    <h1 class="page-title">AI 设置</h1>
    <p class="page-sub">
      第一个 tab 配置项目用的模型（模型1/2、生成方/评审方、ASR、每日篇数），保存即生效；
      其余 tab 是各功能的提示词（AI 的「支架 + 高级设置」，默认不建议改）。
      「像不像作者」主要由人设页维护的运行时上下文决定（人设档案 / 红线 / 语言习惯画像 / 金句锚点 / 禁用词 / 风格范本）
    </p>

    <div class="toolbar">
      <span class="muted">讨论轮次（所有脚本生成的评审轮数）：</span>
      <n-input-number v-model:value="debateRounds" :min="1" :max="10" style="width: 90px" @update:value="saveRounds" />
      <n-button secondary size="small" :loading="ruleOptimizing" @click="optimizeRules">
        一键优化规则型（预打标/校对/差异/复盘）
      </n-button>
    </div>

    <n-tabs v-model:value="activeKey" type="line" animated>
      <n-tab-pane name="__models" tab="模型设置">
        <div class="panel">
          <div class="section-title" style="margin-top: 0">模型槽位（可分别配厂家 / 模型 / API Key）</div>
          <n-alert v-for="(w, i) in modelWarnings" :key="i" type="warning" :bordered="false" style="margin-bottom: 8px">
            {{ w }}
          </n-alert>

          <div v-for="slot in ['model1', 'model2']" :key="slot" class="slot-box">
            <div class="row" style="gap: 8px; align-items: center; flex-wrap: wrap">
              <strong style="min-width: 56px">{{ slot === 'model1' ? '模型1' : '模型2' }}</strong>
              <n-select
                v-model:value="models[slot].vendor"
                :options="vendorOptions"
                style="width: 150px"
                @update:value="(v) => onVendorChange(slot, v)"
              />
              <n-select
                v-model:value="models[slot].model"
                :options="modelOptionsFor(slot)"
                filterable
                tag
                placeholder="模型 ID（可直接输入新模型）"
                style="width: 240px"
              />
              <n-input
                v-model:value="models[slot].key"
                :placeholder="models[slot].keyHint || 'API Key（留空则用 .env）'"
                style="width: 300px"
                show-password-on="click"
                type="password"
              />
              <n-tag v-if="models[slot].keyPresent" size="small" :bordered="false" round type="success">
                已配置{{ models[slot].keyFromEnv ? '（来自 .env）' : '' }}
              </n-tag>
              <n-tag v-else size="small" :bordered="false" round type="error">缺少 Key</n-tag>
            </div>
            <p class="muted" style="font-size: 12px; margin: 4px 0 0">
              {{ models[slot].vendorLabel }} · {{ models[slot].baseUrl }} · {{ models[slot].keyHint }}
            </p>
          </div>

          <div class="row" style="gap: 10px; margin-top: 14px; flex-wrap: wrap; align-items: center">
            <span class="muted">脚本生成 · 生成方：</span>
            <n-select v-model:value="models.genRole" :options="roleOptions" style="width: 150px" />
            <span class="muted">评审方：</span>
            <n-select v-model:value="models.refereeRole" :options="roleOptions" style="width: 150px" />
            <span class="muted" style="font-size: 12px">两方可以选同一个模型</span>
          </div>

          <div class="row" style="gap: 10px; margin-top: 14px; flex-wrap: wrap; align-items: center">
            <span class="muted">ASR 服务商：</span>
            <n-select v-model:value="models.asrMode" :options="asrModeOptions" style="width: 190px" />
            <template v-if="models.asrMode === 'siliconflow'">
              <span class="muted">ASR 模型：</span>
              <n-select
                v-model:value="models.asrModel"
                :options="asrModelOptions"
                filterable
                tag
                style="width: 260px"
              />
            </template>
          </div>

          <div class="row" style="gap: 10px; margin-top: 14px; flex-wrap: wrap; align-items: center">
            <span class="muted">每日自动生成篇数：</span>
            <n-input-number v-model:value="models.topicsCount" :min="1" :max="10" style="width: 90px" />
            <span class="muted" style="font-size: 12px">
              双模型讨论成本 ≈ 篇数 × 轮次 × 2 次调用，建议 1–2 篇
            </span>
          </div>

          <div class="row" style="gap: 8px; margin-top: 16px">
            <n-button type="primary" :loading="savingModels" @click="saveModels">保存（立即生效）</n-button>
            <n-button secondary :loading="loadingModels" @click="loadModels">重新读取</n-button>
          </div>
          <p class="muted" style="font-size: 12px; margin: 8px 0 0">
            保存后会自动跑一次「双模型兼容性自检」（各功能的极简样例 × 模型1/2，校验输出契约），
            结果这里显示，也会发一条站内通知。
          </p>
          <div v-if="selfcheck" class="selfcheck-box">
            <div class="row" style="gap: 8px; align-items: center; flex-wrap: wrap">
              <strong style="font-size: 13px">双模型兼容性自检</strong>
              <n-tag size="tiny" :bordered="false" round :type="selfcheck.ok ? 'success' : 'error'">
                {{ selfcheck.ok ? '模型1/2 均兼容' : '发现问题' }}
              </n-tag>
              <span class="muted" style="font-size: 12px">{{ selfcheck.checked_at }}</span>
            </div>
            <div v-for="slotKey in ['model1', 'model2']" :key="slotKey" class="muted" style="font-size: 12px; margin-top: 6px">
              <template v-if="selfcheck.slots && selfcheck.slots[slotKey]">
                {{ selfcheck.slots[slotKey].label }}：
                <template v-for="(p, pk) in selfcheck.slots[slotKey].probes" :key="pk">
                  <n-tag size="tiny" :bordered="false" round :type="p.ok ? 'success' : 'error'" style="margin-right: 4px">
                    {{ p.label }}{{ p.ok ? '✓' : '✗' }}
                  </n-tag>
                </template>
              </template>
            </div>
            <ul v-if="selfcheck.warnings && selfcheck.warnings.length" style="margin: 6px 0 0; padding-left: 1.2em; color: var(--warn); font-size: 12px">
              <li v-for="(w, i) in selfcheck.warnings" :key="i">{{ w }}</li>
            </ul>
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane v-for="item in items" :key="item.key" :name="item.key">
        <template #tab>
          {{ item.label }}
          <n-tag v-if="item.group === 'persona_engine'" size="tiny" :bordered="false" round type="info">人设引擎</n-tag>
        </template>
        <div class="panel">
          <div class="row" style="justify-content: space-between; margin-bottom: 8px; flex-wrap: wrap; gap: 8px">
            <strong>当前启用 · v{{ item.enabled_version }}</strong>
            <div class="row" style="gap: 8px">
              <n-tag v-if="item.group === 'persona_engine'" size="small" :bordered="false" round type="info">
                改这里会影响人设提取质量
              </n-tag>
              <n-tag v-if="item.key === 'generation'" size="small" :bordered="false" round>
                自动优化已改为手动（素材更新会提醒你）
              </n-tag>
              <n-tag v-if="item.key === 'generation'" size="small" :bordered="false" round type="info">
                素材/反馈更新会自动注入，无需改提示词；此按钮只在你想调整写法与结构时用
              </n-tag>
              <n-tag v-if="item.has_candidate" size="small" :bordered="false" round type="warning">
                有候选 v{{ item.candidate_version }} 待启用
              </n-tag>
            </div>
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
              AI 基于真实样本优化（候选）
            </n-button>
          </div>
        </div>

        <div v-if="candidate(item)" class="panel" style="border-left: 3px solid var(--warn)">
          <div class="row" style="justify-content: space-between; margin-bottom: 6px; flex-wrap: wrap; gap: 8px">
            <strong>候选版 v{{ candidate(item).version }}</strong>
            <div class="row" style="gap: 8px">
              <n-button size="small" type="primary" @click="enable(item, candidate(item).version)">启用此版本</n-button>
              <n-button size="small" type="error" secondary @click="rejectCandidate(item)">拒绝候选</n-button>
            </div>
          </div>
          <p class="muted" style="margin: 0 0 8px; white-space: pre-wrap">{{ candidate(item).note }}</p>

          <div class="eval-box">
            <template v-if="evalOf(item) && evalOf(item).supported">
              <n-tag size="small" :bordered="false" round :type="scoreType(item)">
                候选 {{ fmtScore(evalOf(item).candidate_score) }} vs 当前 {{ fmtScore(evalOf(item).base_score) }}
              </n-tag>
              <span class="muted" style="font-size: 12px">
                格式 {{ pct(evalOf(item).detail && evalOf(item).detail.candidate && evalOf(item).detail.candidate.format_rate) }}
                · 红线命中 {{ pct(evalOf(item).detail && evalOf(item).detail.candidate && evalOf(item).detail.candidate.redline_rate) }}
                <template v-if="styleRate(item) !== null"> · 像作者 {{ pct(styleRate(item)) }}</template>
                · 金样本 {{ probeCount(item) }} 个
              </span>
              <n-button size="tiny" secondary :loading="evalRunning(item.key)" @click="rerunEval(item)">重跑评测</n-button>
            </template>
            <template v-else-if="evalOf(item)">
              <n-tag size="small" :bordered="false" round>未评测：{{ evalOf(item).reason }}</n-tag>
              <n-button size="tiny" secondary :loading="evalRunning(item.key)" @click="rerunEval(item)">重跑评测</n-button>
            </template>
            <template v-else>
              <span class="muted" style="font-size: 12px">{{ evalRunning(item.key) ? '金样本回放评分中…' : '暂无评测结果' }}</span>
              <n-button size="tiny" secondary :loading="evalRunning(item.key)" @click="rerunEval(item)">跑评测</n-button>
            </template>
          </div>

          <pre class="prompt-pre dview"><span
            v-for="(l, i) in diffOf(item)"
            :key="i"
            :class="'d-' + l.type"
          >{{ prefix(l.type) + l.text }}</span></pre>
        </div>

        <div v-if="item.effect && item.effect.length" class="panel">
          <div class="section-title" style="margin-top: 0">版本效果对比（按草稿反馈）</div>
          <div v-for="e in item.effect" :key="e.version" class="row" style="gap: 10px; font-size: 13px; flex-wrap: wrap">
            <span class="ver-title">v{{ e.version }}</span>
            <span class="muted">
              草稿 {{ e.drafts }} 篇 · 已评分 {{ e.rated }} · 均分 {{ e.avg_rating == null ? '—' : e.avg_rating }} · 采用 {{ e.used }}
            </span>
            <n-tag v-if="e.mixed_persona" size="tiny" :bordered="false" round type="warning">
              跨 {{ (e.persona_versions || []).length }} 个人设版本，均分不宜直接横向比
            </n-tag>
          </div>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'
import { diffLines } from '../diff'

const ORDER = ['generation', 'persona_init', 'persona_merge', 'video_tags', 'persona_updates', 'persona_compare', 'diff', 'chat', 'correct']
const items = ref([])
const activeKey = ref('generation')
const editing = ref({})
const optimizingKey = ref(null)
const ruleOptimizing = ref(false)
const evalTasks = ref({})
let evalPoll = null
const message = useMessage()
const debateRounds = ref(5)

// ---- R-138 模型设置 ----
const models = ref({
  model1: { vendor: 'deepseek', model: '', key: '', keyPresent: false, keyFromEnv: false, vendorLabel: '', baseUrl: '', keyHint: '' },
  model2: { vendor: 'kimi', model: '', key: '', keyPresent: false, keyFromEnv: false, vendorLabel: '', baseUrl: '', keyHint: '' },
  genRole: 'model2',
  refereeRole: 'model1',
  asrMode: 'siliconflow',
  asrModel: '',
  topicsCount: 2
})
const vendors = ref({})
const asrOptions = ref({})
const asrModelList = ref([])
const modelWarnings = ref([])
const selfcheck = ref(null)
const loadingModels = ref(false)
const savingModels = ref(false)

const vendorOptions = computed(() =>
  Object.entries(vendors.value).map(([value, meta]) => ({ label: meta.label, value }))
)
const roleOptions = [
  { label: '模型1', value: 'model1' },
  { label: '模型2', value: 'model2' }
]
const asrModeOptions = computed(() =>
  Object.entries(asrOptions.value).map(([value, label]) => ({ label, value }))
)
const asrModelOptions = computed(() => asrModelList.value.map(m => ({ label: m, value: m })))

function modelOptionsFor(slot) {
  const vendor = models.value[slot].vendor
  const list = (vendors.value[vendor] && vendors.value[vendor].models) || []
  const opts = list.map(m => ({ label: m, value: m }))
  const current = models.value[slot].model
  if (current && !list.includes(current)) opts.unshift({ label: current, value: current })
  return opts
}

function onVendorChange(slot, vendor) {
  const meta = vendors.value[vendor] || {}
  const item = models.value[slot]
  item.vendorLabel = meta.label || vendor
  item.keyHint = meta.key_hint || ''
  if (!item.model || !(meta.models || []).includes(item.model)) {
    item.model = meta.default_model || ''
  }
}

async function loadModels() {
  loadingModels.value = true
  try {
    const r = await api('/api/settings/models')
    vendors.value = r.vendors || {}
    asrOptions.value = (r.asr && r.asr.options) || {}
    asrModelList.value = (r.asr && r.asr.siliconflow_models) || []
    modelWarnings.value = r.warnings || []
    selfcheck.value = r.selfcheck || null
    models.value = {
      model1: {
        vendor: r.model1.vendor, model: r.model1.model, key: r.model1.key || '',
        keyPresent: r.model1.key_present, keyFromEnv: r.model1.key_from_env,
        vendorLabel: r.model1.vendor_label, baseUrl: r.model1.base_url, keyHint: r.model1.key_hint
      },
      model2: {
        vendor: r.model2.vendor, model: r.model2.model, key: r.model2.key || '',
        keyPresent: r.model2.key_present, keyFromEnv: r.model2.key_from_env,
        vendorLabel: r.model2.vendor_label, baseUrl: r.model2.base_url, keyHint: r.model2.key_hint
      },
      genRole: r.gen_role,
      refereeRole: r.referee_role,
      asrMode: (r.asr && r.asr.mode) || 'mock',
      asrModel: (r.asr && r.asr.model) || '',
      topicsCount: r.topics_count || 2
    }
  } catch (e) {
    message.error('读取模型设置失败：' + e.message)
  } finally {
    loadingModels.value = false
  }
}

async function saveModels() {
  savingModels.value = true
  try {
    const body = {
      model1: { vendor: models.value.model1.vendor, model: models.value.model1.model, key: models.value.model1.key },
      model2: { vendor: models.value.model2.vendor, model: models.value.model2.model, key: models.value.model2.key },
      gen_role: models.value.genRole,
      referee_role: models.value.refereeRole,
      asr_mode: models.value.asrMode,
      asr_model: models.value.asrModel,
      topics_count: models.value.topicsCount,
      debate_rounds: debateRounds.value
    }
    await api('/api/settings/models', { method: 'PUT', body: JSON.stringify(body) })
    await loadModels()
    message.success('已保存，立即生效（无需重启）')
  } catch (e) {
    message.error(e.message || '保存失败')
  } finally {
    savingModels.value = false
  }
}


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

function evalOf(item) {
  return item.eval || null
}

function pct(v) {
  return v === null || v === undefined ? '—' : `${Math.round(Number(v) * 100)}%`
}

function fmtScore(v) {
  return v === null || v === undefined ? '—' : Number(v).toFixed(0)
}

function styleRate(item) {
  const e = evalOf(item)
  if (!e || !e.supported || !e.detail) return null
  const c = e.detail.candidate || {}
  return c.style_rate === undefined ? null : c.style_rate
}

function probeCount(item) {
  const e = evalOf(item)
  return e && e.detail && e.detail.probes ? e.detail.probes.length : 0
}

function scoreType(item) {
  const e = evalOf(item)
  if (!e || !e.supported) return 'default'
  return Number(e.candidate_score) >= Number(e.base_score) ? 'success' : 'warning'
}

function evalRunning(key) {
  return !!evalTasks.value[key]
}

async function refreshEvalTasks() {
  try {
    const tasks = await api('/api/tasks?status=running&kind=prompt_eval&limit=20')
    const map = {}
    ;(tasks || []).forEach((t) => {
      let key = ''
      try {
        key = JSON.parse(t.payload || '{}').key || ''
      } catch {
        key = ''
      }
      if (key) map[key] = true
    })
    evalTasks.value = map
    if (!Object.keys(map).length && evalPoll) {
      clearInterval(evalPoll)
      evalPoll = null
      await load()  // 评测结束 → 拉一次最新结果
    }
  } catch {
    /* 轮询失败不打断页面 */
  }
}

function ensureEvalPoll() {
  if (!evalPoll) evalPoll = setInterval(refreshEvalTasks, 4000)
}

async function rejectCandidate(item) {
  const c = candidate(item)
  if (!c) return
  try {
    await api(`/api/prompts/${item.key}/candidates/${c.version}/reject`, { method: 'POST', body: '{}' })
    message.success(`已拒绝候选 v${c.version}`)
    await load()
  } catch (e) {
    message.error(e.message)
  }
}

async function rerunEval(item) {
  const c = candidate(item) || { version: item.enabled_version }
  try {
    await api(`/api/prompts/${item.key}/eval/rerun`, { method: 'POST', body: JSON.stringify({ version: c.version }) })
    message.success('已开始金样本回放评分，完成后右上角通知')
    await refreshEvalTasks()
    ensureEvalPoll()
  } catch (e) {
    message.error(e.message)
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
    message.success(`已产出候选 v${r.version}，正在做金样本回放评分`)
    await load()
    await refreshEvalTasks()
    ensureEvalPoll()
  } catch (e) {
    message.error(e.message || '优化失败')
  } finally {
    optimizingKey.value = null
  }
}

async function enable(item, version) {
  await api(`/api/prompts/${item.key}/enable`, { method: 'POST', body: JSON.stringify({ version }) })
  if (item.group === 'persona_engine') {
    // R-130：人设引擎提示词改完，产出的人设档案会变 → 引导去人设页确认
    message.success(`已启用 v${version}；这是人设引擎提示词，建议到「人设档案」页重跑一次并确认新建议`)
  } else {
    message.success(`已启用 v${version}`)
  }
  await load()
}

async function optimizeRules() {
  ruleOptimizing.value = true
  try {
    const r = await api('/api/prompts/optimize-rules', { method: 'POST', body: '{}' })
    message.success(`已开始规则型提示词优化（task #${r.task_id}），完成后右上角通知`)
    await refreshEvalTasks()
    ensureEvalPoll()
  } catch (e) {
    message.error(e.message || '启动失败')
  } finally {
    ruleOptimizing.value = false
  }
}

function applyDeepLink() {
  // R-134：通知里的 /prompts?key=xxx 要能定位到对应提示词页签
  const m = location.hash.match(/key=([a-z_]+)/)
  const key = m ? m[1] : ''
  if (key && items.value.some((i) => i.key === key)) activeKey.value = key
}

onMounted(async () => {
  loadModels()
  await load()
  applyDeepLink()
  loadRounds()
  refreshEvalTasks()
  ensureEvalPoll()
  window.addEventListener('hashchange', applyDeepLink)
})

onUnmounted(() => {
  window.removeEventListener('hashchange', applyDeepLink)
  if (evalPoll) {
    clearInterval(evalPoll)
    evalPoll = null
  }
})
</script>

<style scoped>
.eval-box {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  padding: 8px 10px;
  background: rgba(219, 163, 125, 0.08);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.slot-box {
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.5);
}
.selfcheck-box {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(219, 163, 125, 0.06);
}
</style>
