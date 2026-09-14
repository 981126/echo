<template>
  <div class="page">
    <h1 class="page-title">脚本工作台</h1>

    <div class="toolbar">
      <n-button type="primary" @click="createDraft">新建草稿</n-button>
    </div>

    <n-tabs v-model:value="listTab" type="line" animated>
      <n-tab-pane name="draft" :tab="`草稿 (${list('draft').length})`">
        <div v-if="!list('draft').length" class="panel empty">暂无草稿，新建或从热点生成</div>
        <div class="grid">
          <div v-for="d in list('draft')" :key="d.id" class="card-tile" @click="open(d)">
            <h3 class="tile-title">{{ d.title || '（无标题）' }}</h3>
            <p class="tile-meta">{{ srcLabel(d) }}<template v-if="srcTitle(d)"> · {{ srcTitle(d) }}</template> · {{ fmt(d.updated_at) }}</p>
            <div v-if="modelInfo(d)" class="tile-models">
              <n-tag size="tiny" :bordered="false" round>{{ modelInfo(d) }}</n-tag>
              <n-tag v-if="d.quality && d.quality.fallback" size="tiny" :bordered="false" round type="warning">
                由备用模型生成
              </n-tag>
            </div>
            <div class="tile-actions" @click.stop>
              <n-button size="small" secondary @click="markUsed(d)">✅ 采用</n-button>
              <n-button size="small" secondary @click="markArchived(d)">不采用</n-button>
              <n-button size="small" quaternary type="error" @click="softDelete(d)">删除</n-button>
            </div>
            <div class="tile-rate" @click.stop>
              <span class="muted">打分</span>
              <button v-for="i in 5" :key="i" class="rate-star" :class="{ on: (ratings[d.id] || 0) >= i }" @click="rate(d, i)">{{ (ratings[d.id] || 0) >= i ? '★' : '☆' }}</button>
              <span v-if="ratings[d.id]" class="muted" style="font-size: 11px">{{ ratings[d.id] }} 分</span>
              <span v-else class="muted" style="font-size: 11px">← 打分是 AI 学你偏好最强的信号</span>
            </div>
            <div class="tile-rate dims" @click.stop>
              <span class="muted">分节</span>
              <template v-for="def in dimDefs" :key="def.key">
                <span class="dim-label">{{ def.label }}</span>
                <button
                  v-for="opt in dimOpts"
                  :key="def.key + opt.v"
                  class="rate-star dim-star"
                  :class="{ on: (dims[d.id] || {})[def.key] === opt.v }"
                  @click="setDim(d.id, def.key, opt.v)"
                >{{ opt.label }}</button>
              </template>
              <n-button size="tiny" secondary @click="submitDims(d)">记反馈</n-button>
            </div>
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="used" :tab="`待制作 (${list('used').length})`">
        <div v-if="!list('used').length" class="panel empty">暂无待制作（点草稿的「采用」会进这里）</div>
        <div class="grid">
          <div v-for="d in list('used')" :key="d.id" class="card-tile" @click="open(d)">
            <h3 class="tile-title">{{ d.title || '（无标题）' }}</h3>
            <p class="tile-meta">{{ srcLabel(d) }}<template v-if="srcTitle(d)"> · {{ srcTitle(d) }}</template> · {{ fmt(d.updated_at) }}</p>
            <div class="tile-actions" @click.stop>
              <n-button size="small" secondary @click="markArchived(d)">移入废稿</n-button>
              <n-button size="small" quaternary type="error" @click="softDelete(d)">删除</n-button>
            </div>
          </div>
        </div>
      </n-tab-pane>
    </n-tabs>

    <n-modal
      v-model:show="showEdit"
      preset="card"
      :title="editing ? (editing.id ? '草稿 #' + editing.id : '新建草稿') : '草稿'"
      style="width: min(860px, 95vw)"
      :mask-closable="false"
      @close="closeEdit"
    >
      <div v-if="editing" style="max-height: 76vh; overflow-y: auto; padding-right: 6px">
        <div class="form-grid" style="margin-bottom: 8px">
          <div class="form-item">
            <label class="form-label">标题</label>
            <n-input v-model:value="editing.title" placeholder="视频标题" />
          </div>
          <div class="form-item">
            <label class="form-label">封面字</label>
            <n-input v-model:value="editing.cover_text" placeholder="与标题不同，3-8 字" />
          </div>
        </div>
        <div class="form-item" style="margin-bottom: 10px">
          <label class="form-label">关联素材视频（可选）</label>
          <n-select v-model:value="editing.video_id" :options="videoOptions" placeholder="选择一个素材视频" clearable />
        </div>
        <div class="form-item" style="margin-bottom: 10px">
          <label class="form-label">素材标签（逗号分隔）</label>
          <n-input v-model:value="tagsText" placeholder="如：求职, 面试, 赚钱" />
        </div>

        <div v-if="editing.source_ref && editing.source_ref.source_title" class="source-banner">
          来源素材：
          <a v-if="editing.source_ref.post_id" :href="'#/videos?post=' + editing.source_ref.post_id" class="source-link">{{ editing.source_ref.source_title }}</a>
          <span v-else>{{ editing.source_ref.source_title }}</span>
          <template v-if="editing.source_ref.benchmark_name"> · 对标「{{ editing.source_ref.benchmark_name }}」</template>
        </div>
        <n-tabs v-model:value="editTab" type="line" animated>
          <n-tab-pane name="edit" tab="编辑">
            <div class="form-item">
              <div class="row" style="align-items: center; margin-bottom: 6px">
                <label class="form-label" style="margin: 0">口播脚本（Markdown，可插图）</label>
                <span class="grow" />
                <n-button size="tiny" secondary :type="preview ? 'primary' : 'default'" @click="preview = !preview">
                  {{ preview ? '返回编辑' : '预览' }}
                </n-button>
              </div>
              <div v-if="preview" class="prose md-preview" v-html="renderMd(editing.script)" />
              <ScriptEditor
                v-else
                :model-value="editing.script"
                placeholder="在这里撰写 / 改写脚本"
                @update:model-value="v => (editing.script = v)"
              />
            </div>
            <div v-if="checkInfo && editing.id" class="panel check-panel" style="margin-bottom: 10px">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="section-title" style="margin: 0">脚本体检</span>
                <n-tag v-if="checkInfo.ok" size="small" type="success" :bordered="false" round>通过</n-tag>
                <n-tag v-else size="small" type="warning" :bordered="false" round>建议回炉</n-tag>
                <div class="grow" />
                <n-button v-if="!checkInfo.ok && editing.id" size="tiny" type="primary" secondary :loading="reworking" @click="rework(editing.id)">一键回炉重写</n-button>
                <n-button size="tiny" secondary @click="runCheck(editing.id)">重新体检</n-button>
              </div>
              <ul v-if="checkInfo.issues.length" style="margin: 6px 0 0; padding-left: 1.2em; color: var(--warn)">
                <li v-for="(iss, i) in checkInfo.issues" :key="i">{{ iss }}</li>
              </ul>
            </div>
            <div v-if="modelInfo(editing)" class="panel" style="margin-bottom: 10px">
              <div class="row" style="gap: 8px; align-items: center; flex-wrap: wrap">
                <span class="muted" style="font-size: 12px">本篇生成模型：{{ modelInfo(editing) }}</span>
                <n-tag v-if="editing.quality && editing.quality.fallback" size="tiny" :bordered="false" round type="warning">
                  由备用模型生成
                </n-tag>
                <n-tag v-if="editing.quality && editing.quality.rounds" size="tiny" :bordered="false" round>
                  讨论 {{ editing.quality.rounds_done ?? editing.quality.rounds }}/{{ editing.quality.rounds }} 轮
                </n-tag>
                <n-tag v-if="editing.quality && editing.quality.mock" size="tiny" :bordered="false" round type="error">
                  mock 稿（模型不可用）
                </n-tag>
              </div>
            </div>
            <div class="row">
              <n-button type="primary" @click="save">保存</n-button>
              <n-button type="info" secondary :loading="finalizing" @click="finalize">定稿</n-button>
              <n-button secondary @click="closeEdit">取消</n-button>
            </div>
          </n-tab-pane>

          <n-tab-pane name="discuss" tab="讨论（双模型留痕）">
            <div class="discuss-box">
              <div v-if="!editing.id" class="empty" style="padding: 30px 0">
                先保存草稿，再让双模型基于原文讨论
              </div>
              <template v-else>
                <div v-if="!discussions.length" class="empty" style="padding: 24px 0">
                  <div style="margin-bottom: 10px">暂无讨论记录{{ isPending ? '（生成中…）' : '' }}</div>
                  <n-button v-if="!discussing" size="small" type="primary" :disabled="!canDiscuss" @click="startDiscussion">讨论</n-button>
                  <div v-if="!canDiscuss" class="muted" style="font-size: 12px; margin-top: 8px">这篇草稿没有可讨论的原文或正文</div>
                </div>
                <div v-for="m in discussions" :key="m.id" class="discuss-msg" :class="m.actor">
                  <div class="discuss-head">
                    <strong>{{ actorName(m) }}</strong>
                    <span class="muted">{{ kindName(m.kind) }} · 第{{ m.round }}轮</span>
                  </div>
                  <div class="discuss-body" style="white-space: pre-wrap">{{ m.content }}</div>
                </div>
                <div v-if="debateStatus" class="empty" style="padding: 12px 0; color: var(--warn)">⏳ {{ debateStatus }}</div>
                <div v-else-if="isPending" class="empty" style="padding: 12px 0">模型讨论中…</div>
                <div v-if="discussions.length && !discussing" style="text-align: center; padding: 16px 0 4px">
                  <n-button size="small" type="primary" secondary :disabled="!canDiscuss" @click="startDiscussion">重新讨论</n-button>
                </div>
              </template>
            </div>
          </n-tab-pane>

          <n-tab-pane name="compare" tab="原文对照">
            <div v-if="editing.original_script" class="source-box">
              <div class="cmp-grid">
                <div class="cmp-col">
                  <div class="cmp-h">原文案（红 = 被改写/删除）</div>
                  <div class="diff-body"><template v-for="(seg, i) in draftDiff.left" :key="i"><span :class="seg.type">{{ seg.text }}</span></template></div>
                </div>
                <div class="cmp-col">
                  <div class="cmp-h">修改后（绿 = 新增/修改）</div>
                  <div class="diff-body"><template v-for="(seg, i) in draftDiff.right" :key="i"><span :class="seg.type">{{ seg.text }}</span></template></div>
                </div>
              </div>
            </div>
            <div v-else class="empty" style="padding: 30px 0">暂无原文案（对标洗稿或「讨论」后会记录）</div>
          </n-tab-pane>

          <n-tab-pane name="versions" :tab="versions.length ? `版本 (${versions.length})` : '版本'">
            <div v-if="!editing.id" class="empty" style="padding: 30px 0">先保存草稿，再进行定稿与版本比较</div>
            <template v-else>
              <div v-if="!versions.length" class="empty" style="padding: 24px 0">
                还没有版本，点下方或编辑区的【定稿】保存一版
              </div>
              <template v-else>
                <div class="row" style="justify-content: space-between; align-items: center; margin-bottom: 6px">
                  <span class="muted" style="font-size: 12px">点选两个版本对比（已选 {{ verSel.length }}/2）</span>
                  <span v-if="finalizedState" class="muted" style="font-size: 12px">{{ finalizedState }}</span>
                </div>
                <div
                  v-for="ver in versionsDesc"
                  :key="ver.id"
                  class="ver-row"
                  :class="{ on: verSel.includes(ver.id) }"
                  @click="toggleVer(ver.id)"
                >
                  <n-tag size="tiny" :bordered="false" round :type="ver.source === 'ai_discuss' ? 'info' : 'success'">{{ verLabel(ver.source) }}</n-tag>
                  <span class="ver-title">{{ ver.title || '（无标题）' }}</span>
                  <span class="muted ver-time">{{ fmt(ver.created_at) }}</span>
                </div>
                <div v-if="verDiff" class="cmp-grid" style="margin-top: 10px">
                  <div class="cmp-col">
                    <div class="cmp-h">{{ verDiff.leftLabel }}</div>
                    <div class="diff-body"><template v-for="(seg, i) in verDiff.left" :key="i"><span :class="seg.type">{{ seg.text }}</span></template></div>
                  </div>
                  <div class="cmp-col">
                    <div class="cmp-h">{{ verDiff.rightLabel }}</div>
                    <div class="diff-body"><template v-for="(seg, i) in verDiff.right" :key="i"><span :class="seg.type">{{ seg.text }}</span></template></div>
                  </div>
                </div>
                <div v-else class="empty" style="padding: 16px 0">再选一个版本即可对比</div>
              </template>
            </template>
          </n-tab-pane>
        </n-tabs>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, watch, defineAsyncComponent, onMounted, onUnmounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'
import { fetchVideos } from '../composables/media'
import { fmt } from '../lib/format'
import { renderMd } from '../md'
import { buildDiff } from '../lib/diff'

// R-150：Tiptap 块编辑器（含 ProseMirror）体积较大，异步加载不进首屏
const ScriptEditor = defineAsyncComponent(() => import('../components/ScriptEditor.vue'))

const drafts = ref([])
const videos = ref([])
const videoOptions = computed(() => videos.value.map(v => ({ label: v.title || v.filename, value: v.id })))
const listTab = ref('draft')

function srcLabel(d) {
  if (d.source === 'ai' && d.source_ref && d.source_ref.source_title) return '对标洗稿'
  return d.source === 'ai' ? 'AI 生成' : '手动'
}
function srcTitle(d) {
  return (d.source_ref && d.source_ref.source_title) || ''
}
// R-139：展示本篇的生成模型组合（生成方 / 评审方），便于核对「用的是哪个模型」
function modelInfo(d) {
  const models = d && d.quality && d.quality.models
  if (!models) return ''
  const gen = models.gen || ''
  const critic = models.critic || ''
  if (!gen) return ''
  return critic && critic !== gen ? `${gen} × ${critic}` : gen
}
const editing = ref(null)
const showEdit = ref(false)
const checkInfo = ref(null)
const reworking = ref(false)
const editTab = ref('edit')
const draftDiff = computed(() => buildDiff(editing.value?.original_script || '', editing.value?.script || ''))
const tagsText = computed({
  get: () => (editing.value?.tags || []).join(', '),
  set: (v) => { if (editing.value) editing.value.tags = (v || '').split(/[,，]/).map(x => x.trim()).filter(Boolean) }
})
const discussions = ref([])
const discussionsMap = ref({})
const debateStatus = ref('')
const preview = ref(false)
const ratings = ref({})
const dimDefs = [
  { key: 'hook_score', label: '钩子' },
  { key: 'pace_score', label: '节奏' },
  { key: 'ending_score', label: '结尾' },
  { key: 'style_score', label: '像我' }
]
const dimOpts = [
  { v: 5, label: '好' },
  { v: 3, label: '中' },
  { v: 1, label: '差' }
]
const dims = ref({})
const message = useMessage()
let pollTimer = null

const isPending = computed(() => (editing.value?.script || '').includes('双模型讨论生成中'))

// R-155：讨论 / 重新讨论（基于原文跑双模型多轮讨论）
const discussRunning = ref(false)
const discussSeen = ref(false)
let discussTaskId = 0
const discussing = computed(() => discussRunning.value || !!debateStatus.value)
const canDiscuss = computed(() => {
  const e = editing.value
  return !!(e && e.id && ((e.original_script || '').trim() || (e.script || '').trim()))
})

// R-156：定稿 + 版本留痕（每次定稿存一条；可任选两版做差异比较）
const versions = ref([])
const verSel = ref([])
const verLoadedFor = ref(0)
const finalizing = ref(false)
const versionsDesc = computed(() => [...versions.value].reverse())

function verLabel(source) {
  return source === 'ai_discuss' ? 'AI 讨论定稿' : '手动定稿'
}

async function loadVersions(id) {
  verLoadedFor.value = id || 0
  if (!id) {
    versions.value = []
    verSel.value = []
    return
  }
  try {
    versions.value = await api(`/api/drafts/${id}/versions`)
  } catch {
    versions.value = []
  }
  verSel.value = [...versions.value].reverse().slice(0, 2).map(v => v.id)  // 默认选最新两版
}

function toggleVer(id) {
  const cur = verSel.value
  if (cur.includes(id)) {
    verSel.value = cur.filter(x => x !== id)
  } else if (cur.length >= 2) {
    verSel.value = [cur[1], id]  // 满两个则挤掉先选的
  } else {
    verSel.value = [...cur, id]
  }
}

const verDiff = computed(() => {
  if (verSel.value.length !== 2) return null
  const picked = versions.value.filter(v => verSel.value.includes(v.id)).sort((a, b) => a.id - b.id)
  if (picked.length !== 2) return null
  const [older, newer] = picked
  return {
    ...buildDiff(older.script || '', newer.script || ''),
    leftLabel: `#${older.id} · ${verLabel(older.source)}`,
    rightLabel: `#${newer.id} · ${verLabel(newer.source)}`
  }
})

const finalizedState = computed(() => {
  const e = editing.value
  if (!e || !versions.value.length) return ''
  const last = versions.value[versions.value.length - 1]
  const same = (last.script || '') === (e.script || '')
    && (last.title || '') === (e.title || '')
    && (last.cover_text || '') === (e.cover_text || '')
  return same ? '当前正文与最新版本一致（已定稿）' : '当前正文有未定稿改动'
})

watch(editTab, (tab) => {
  if (tab === 'versions' && editing.value?.id && verLoadedFor.value !== editing.value.id) {
    loadVersions(editing.value.id)
  }
})

function list(status) {
  if (status === 'archived') {
    return drafts.value.filter(d => d.status === 'archived' || d.status === 'deleted')
  }
  return drafts.value.filter(d => d.status === status)
}
function actorName(m) {
  if (m.actor === 'kimi') return 'Kimi'
  if (m.actor === 'deepseek') return 'DeepSeek'
  if (m.actor === 'system') return '系统'
  return m.actor
}
function kindName(k) {
  return { draft: '初稿', critique: '评审', revise: '修订', note: '说明' }[k] || k
}

async function load() {
  const [ds, vs] = await Promise.all([
    api('/api/drafts?limit=500'),
    fetchVideos()
  ])
  drafts.value = ds
  videos.value = vs
  const counts = await Promise.all(
    drafts.value.map(d => api(`/api/drafts/${d.id}/discussions`).catch(() => []))
  )
  discussionsMap.value = {}
  drafts.value.forEach((d, i) => {
    discussionsMap.value[d.id] = counts[i] || []
  })
}

async function fetchStatus(id) {
  try {
    const r = await api(`/api/drafts/${id}/debate-status`)
    debateStatus.value = r.status || ''
  } catch {
    debateStatus.value = ''
  }
}

// R-154：新建草稿不落库——先打开本地空白稿，保存时仍有内容才创建
function createDraft() {
  open({ id: null, title: '', cover_text: '', script: '', tags: [], video_id: null, status: 'draft' }, true)
}

function open(d, isNew = false) {
  editing.value = { ...d, video_id: d.video_id ?? null }
  preview.value = false
  showEdit.value = true
  editTab.value = (d.original_script && d.source_ref && d.source_ref.source_title) ? 'compare' : 'edit'
  discussions.value = discussionsMap.value[d.id] || []
  discussRunning.value = false
  discussSeen.value = false
  discussTaskId = 0
  versions.value = []
  verSel.value = []
  verLoadedFor.value = 0
  if (!isNew && editing.value.id) location.hash = `#/drafts?id=${editing.value.id}`
  if (editing.value.id) runCheck(editing.value.id)
}

async function runCheck(id) {
  if (!id) return
  try {
    checkInfo.value = await api(`/api/drafts/${id}/check`)
  } catch (e) {
    checkInfo.value = null
  }
}

async function rework(id) {
  if (!id) return
  reworking.value = true
  try {
    await api(`/api/drafts/${id}/rework`, { method: 'POST', body: '{}' })
    message.success('已提交回炉生成，完成后右上角通知（将替换本稿）')
  } catch (e) {
    message.error(e.message)
  } finally {
    reworking.value = false
  }
}

// R-155：提交一次「基于原文」的双模型多轮讨论（后台任务，完成后通知 + 自动刷新本稿）
async function startDiscussion() {
  const e = editing.value
  if (!e || !e.id) {
    message.warning('先保存草稿再讨论')
    return
  }
  if (discussRunning.value) return
  discussRunning.value = true
  discussSeen.value = false
  try {
    const d = await api(`/api/drafts/${e.id}/discuss`, { method: 'POST', body: '{}' })
    discussTaskId = d.task_id || 0
    message.success('已提交讨论，完成后会更新本篇并提醒')
  } catch (err) {
    discussRunning.value = false
    discussTaskId = 0
    message.error(err.message)
  }
}

// R-155：讨论完成后把标题/封面字/正文/标签/原文案刷回弹窗，供【原文对照】展示
async function refreshEditing(id) {
  let d
  try {
    d = await api('/api/drafts/' + id)
  } catch (e) {
    return
  }
  if (!editing.value || editing.value.id !== id) return
  editing.value = {
    ...editing.value,
    title: d.title,
    cover_text: d.cover_text,
    script: d.script,
    tags: d.tags || [],
    original_script: d.original_script || '',
    source_ref: d.source_ref || {},
    quality: d.quality || {}
  }
  runCheck(id)
}

// R-154：关闭弹窗（叉掉 / 取消 / 保存）都重新查询列表，避免要切页才看到新数据
async function closeEdit() {
  showEdit.value = false
  editing.value = null
  debateStatus.value = ''
  checkInfo.value = null
  discussRunning.value = false
  discussSeen.value = false
  discussTaskId = 0
  versions.value = []
  verSel.value = []
  verLoadedFor.value = 0
  try {
    await load()
  } catch (e) {
    /* 刷新失败不打断关闭 */
  }
}

async function setStatus(id, status) {
  await api(`/api/drafts/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
}
async function markUsed(d) {
  await setStatus(d.id, 'used')
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked: true }) })
  message.success('已采用 → 待制作')
  load()
}
async function markArchived(d) {
  await setStatus(d.id, 'archived')
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked: false }) })
  message.success('已移入废稿')
  load()
}

async function softDelete(d) {
  await setStatus(d.id, 'deleted')
  // R-152：【废稿/已删除】tab 不再展示，逻辑删除的稿子只能在后端数据里查到
  message.success('已删除')
  load()
}

// R-154：新建草稿「有任何一项内容」才算数；全空则不落库
function draftHasContent(e) {
  return !!(e && ((e.title || '').trim() || (e.cover_text || '').trim() || (e.script || '').trim()
    || (e.tags || []).length || e.video_id))
}

async function save() {
  const e = editing.value
  if (!e) return
  if (!e.id && !draftHasContent(e)) {
    message.warning('草稿内容为空，未保存')
    await closeEdit()
    return
  }
  const body = {
    title: e.title,
    cover_text: e.cover_text,
    script: e.script,
    tags: e.tags || [],
    video_id: e.video_id ?? null
  }
  try {
    if (e.id) {
      await api(`/api/drafts/${e.id}`, { method: 'PATCH', body: JSON.stringify(body) })
    } else {
      await api('/api/drafts', { method: 'POST', body: JSON.stringify(body) })
      listTab.value = 'draft'  // 新稿必在草稿 tab，保存后直接可见
    }
  } catch (err) {
    message.error(err.message)
    return
  }
  message.success('已保存')
  await closeEdit()
}

// R-156：定稿——先保存当前编辑，再记一条版本（正文+标题+封面字+标签）
async function finalize() {
  const e = editing.value
  if (!e) return
  if (!e.id && !draftHasContent(e)) {
    message.warning('草稿内容为空，未定稿')
    return
  }
  finalizing.value = true
  try {
    const body = {
      title: e.title,
      cover_text: e.cover_text,
      script: e.script,
      tags: e.tags || [],
      video_id: e.video_id ?? null
    }
    if (!e.id) {
      const created = await api('/api/drafts', { method: 'POST', body: JSON.stringify(body) })
      e.id = created.id
      listTab.value = 'draft'
    }
    const r = await api(`/api/drafts/${e.id}/finalize`, { method: 'POST', body: JSON.stringify(body) })
    message.success(`已定稿（版本 #${r.version.id}）`)
    await refreshEditing(e.id)
    await loadVersions(e.id)
    await load()
  } catch (err) {
    message.error(err.message)
  } finally {
    finalizing.value = false
  }
}

async function rate(d, i) {
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked: null, rating: i }) })
  ratings.value = { ...ratings.value, [d.id]: i }
  message.success(`已打 ${i} 分（进入人设/选题学习）`)
}

function setDim(id, key, v) {
  const cur = dims.value[id] || {}
  dims.value = { ...dims.value, [id]: { ...cur, [key]: cur[key] === v ? null : v } }
}

async function submitDims(d) {
  const sel = dims.value[d.id] || {}
  const body = { liked: null, comment: '' }
  let has = false
  for (const def of dimDefs) {
    if (sel[def.key] != null) {
      body[def.key] = sel[def.key]
      has = true
    }
  }
  if (!has) {
    message.warning('先点选至少一个维度')
    return
  }
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify(body) })
  dims.value = { ...dims.value, [d.id]: {} }
  message.success('分节反馈已记录（会按维度作为生成范例）')
}

async function poll() {
  if (!showEdit.value || !editing.value?.id) return
  const id = editing.value.id
  try {
    const rows = await api(`/api/drafts/${id}/discussions`)
    discussionsMap.value = { ...discussionsMap.value, [id]: rows }
    if (editTab.value === 'discuss') discussions.value = rows
    await fetchStatus(id)
  } catch {
    /* ignore */
  }
  // R-155：讨论结束检测——优先看任务终态；重开弹窗等场景用「状态从有到无」兜底
  if (discussTaskId) {
    try {
      const t = await api('/api/tasks/' + discussTaskId)
      if (t.status === 'done' || t.status === 'failed') {
        discussTaskId = 0
        discussRunning.value = false
        discussSeen.value = false
        if (t.status === 'done') message.success('讨论完成，已更新本篇')
        else message.error(t.error || '讨论失败')
        await refreshEditing(id)
        await load()
        return
      }
    } catch {
      /* 任务查询失败下轮再试 */
    }
    if (debateStatus.value) discussSeen.value = true
    return
  }
  if (debateStatus.value) {
    discussSeen.value = true
    return
  }
  if (discussSeen.value) {
    discussSeen.value = false
    discussRunning.value = false
    await refreshEditing(id)
    await load()
  }
}

onMounted(async () => {
  await load()
  const m = location.hash.match(/id=(\d+)/)
  if (m) {
    const d = drafts.value.find(x => x.id === Number(m[1]))
    if (d) {
      open(d)
      // R-152：【废稿/已删除】tab 已不再展示，深链打开这类稿子时列表停留在草稿，弹窗照常可看
      if (d.status === 'used') listTab.value = 'used'
    }
  }
  pollTimer = setInterval(poll, 3000)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.source-box { margin: 8px 0; }
.source-pre { white-space: pre-wrap; word-break: break-word; background: #faf7f2; border-radius: 8px; padding: 12px; max-height: 55vh; overflow: auto; font-size: 13px; }
.source-banner { margin: 4px 0 10px; padding: 8px 10px; background: #fdf6ef; border: 1px solid #f0dfc8; border-radius: 8px; color: #8a5a2b; font-size: 13px; }
.source-link { color: #a34f2c; text-decoration: none; font-weight: 600; }
.source-link:hover { text-decoration: underline; }
.cmp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.cmp-h { font-size: 12px; color: #a34f2c; font-weight: 600; margin-bottom: 4px; }
.diff-body { white-space: pre-wrap; word-break: break-word; background: #faf7f2; border-radius: 8px; padding: 12px; max-height: 55vh; overflow: auto; font-size: 13px; line-height: 1.7; }
.diff-body .del { background: #ffe3e3; color: #c0392b; border-radius: 3px; }
.diff-body .add { background: #dcf5dc; color: #1a7f37; border-radius: 3px; }
.ver-row { display: flex; align-items: center; gap: 8px; padding: 8px 10px; margin-bottom: 4px; border: 1px solid var(--line, #eee5d8); border-radius: 8px; cursor: pointer; }
.ver-row.on { border-color: #a34f2c; background: #fdf6ef; }
.ver-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.ver-time { font-size: 11px; flex: none; }
@media (max-width: 640px) { .cmp-grid { grid-template-columns: 1fr; } }
</style>
