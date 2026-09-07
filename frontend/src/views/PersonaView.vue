<template>
  <div class="page">
    <h1 class="page-title">人设档案</h1>

    <div class="toolbar">
      <n-button secondary :loading="running" @click="initPersona">
        {{ running ? '初始化中…' : '用历史转写稿初始化人设' }}
      </n-button>
    </div>

    <div class="section-title">
      像我金句库
      <n-button size="tiny" secondary style="margin-left: 10px" :loading="phraseLoading" @click="suggestPhrases">从高表现素材提取</n-button>
      <span class="muted" style="font-size: 12px">确认后的句子会作为风格锚点强注入生成</span>
    </div>
    <div v-if="!phrases.length" class="panel empty">先点「从高表现素材提取」生成候选（需已有素材转写稿）</div>
    <div v-for="(ph, i) in phrases" :key="i" class="panel row" style="align-items: flex-start; padding: 10px 12px">
      <div class="grow">
        <p style="margin: 0">“{{ ph.text }}”</p>
        <span class="muted" style="font-size: 12px">{{ ph.source_title || '素材' }}</span>
      </div>
      <n-button size="tiny" type="primary" @click="adoptPhrase(ph)">收为锚点</n-button>
    </div>

    <div class="section-title">
      表达风格（自动统计）
      <n-button size="tiny" secondary style="margin-left: 10px" :loading="!styleInfo" @click="loadStyle">刷新</n-button>
    </div>
    <div v-if="!styleInfo" class="panel empty">暂无统计（需先有素材转写稿）</div>
    <div v-else class="panel">
      <p style="margin: 0 0 6px; white-space: pre-wrap; font-size: 13px">{{ styleInfo.profile }}</p>
      <div class="row" style="gap: 6px; flex-wrap: wrap; align-items: center">
        <span class="muted" style="font-size: 12px">AI 腔禁用/少用词：</span>
        <n-tag v-for="w in avoidList" :key="w" size="small" closable @close="removeAvoid(w)">{{ w }}</n-tag>
      </div>
      <div class="row" style="gap: 8px; margin-top: 8px; flex-wrap: wrap">
        <n-input v-model:value="avoidText" placeholder="添加（逗号分隔）" clearable style="max-width: 320px" />
        <n-button size="small" secondary @click="addAvoidWords">添加</n-button>
        <n-button size="small" type="primary" :loading="savingStyle" @click="saveStyle">保存</n-button>
      </div>
      <p class="muted" style="font-size: 12px; margin: 6px 0 0">
        禁用词会注入生成提示词；每周日凌晨自动做一次风格重建并产出提示词新候选（右上角通知，可回滚）
      </p>
    </div>

    <div class="section-title">
      待确认建议
      <n-button v-if="suggested.length" size="tiny" type="primary" secondary style="margin-left: 10px" :loading="confirmingAll" @click="confirmAll">一键确认建议</n-button>
      <n-button v-if="suggested.length" size="tiny" type="error" secondary style="margin-left: 8px" :loading="rejectingAll" @click="askRejectAll">一键拒绝建议</n-button>
    </div>
    <div v-if="!suggested.length" class="panel empty">暂无待确认建议</div>
    <div v-for="t in suggested" :key="t.id" class="panel row" style="align-items: flex-start">
      <div class="grow">
        <div class="row" style="gap: 8px">
          <strong>{{ t.label }}</strong>
          <n-tag size="small" :bordered="false" round>{{ categoryName(t.category) }}</n-tag>
        </div>
        <p class="muted" style="margin: 4px 0 0">{{ t.description }}</p>
      </div>
      <n-button size="small" type="primary" @click="decide(t, 'confirmed')">确认</n-button>
      <n-button size="small" secondary @click="decide(t, 'rejected')">拒绝</n-button>
    </div>

    <div class="section-title">
      已确认档案
      <n-button size="tiny" type="primary" secondary style="margin-left: 10px" @click="startAdd">新增</n-button>
    </div>
    <div v-if="!confirmed.length" class="panel empty">暂无已确认人设</div>
    <template v-else>
      <div class="merge-float">
        <n-button v-if="!multiMode" size="small" type="primary" secondary @click="multiMode = true">多选</n-button>
        <template v-else>
          <span class="muted">已选 {{ selected.size }} 项</span>
          <n-button size="small" type="error" secondary :disabled="batchDeleting || !selected.size" :loading="batchDeleting" @click="askBatchDelete">删除所选</n-button>
          <n-button size="small" secondary :disabled="batchDeleting" @click="cancelMulti">取消</n-button>
        </template>
      </div>
      <div
        v-for="t in confirmed"
        :key="t.id"
        class="panel row persona-row"
        :class="{ picking: multiMode, picked: multiMode && selected.has(t.id) }"
        @click="multiMode && toggleSel(t)"
      >
        <n-checkbox v-if="multiMode" class="persona-pick" :checked="selected.has(t.id)" @click.stop @update:checked="toggleSel(t)" />
        <div class="grow">
          <div class="row" style="gap: 8px">
            <strong>{{ t.label }}</strong>
            <n-tag size="small" :bordered="false" round>{{ categoryName(t.category) }}</n-tag>
            <n-tag v-if="t.category === 'redline'" size="small" :bordered="false" round type="error">红线</n-tag>
          </div>
          <span class="muted" style="display: block; margin-top: 2px">{{ t.description }}</span>
        </div>
        <template v-if="!multiMode">
          <n-button size="tiny" secondary @click="startEdit(t)">编辑</n-button>
          <n-popconfirm @positive-click="removeTag(t)">
            <template #trigger>
              <n-button size="tiny" quaternary type="error">删除</n-button>
            </template>
            删除该人设标签？
          </n-popconfirm>
        </template>
      </div>
    </template>

    <n-modal
      v-model:show="showEdit"
      preset="card"
      :title="editForm.id ? '编辑人设标签' : '新增风格档案'"
      style="width: min(460px, 92vw)"
      :mask-closable="false"
      @close="closeEdit"
    >
      <div class="form-item">
        <label class="form-label">标签</label>
        <n-input v-model:value="editForm.label" placeholder="如：犀利敢说" />
      </div>
      <div class="form-item">
        <label class="form-label">描述</label>
        <n-input v-model:value="editForm.description" placeholder="一句话描述" />
      </div>
      <div class="form-item">
        <label class="form-label">类别</label>
        <n-select v-model:value="editForm.category" :options="categoryOptions" />
      </div>
      <div class="row">
        <n-button type="primary" @click="saveEdit">{{ editForm.id ? '保存' : '新增' }}</n-button>
        <n-button secondary @click="closeEdit">取消</n-button>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api'

const suggested = ref([])
const confirmed = ref([])
const running = ref(false)
const message = useMessage()
const dialog = useDialog()
const showEdit = ref(false)
const editForm = ref({ id: null, label: '', description: '', category: 'style' })
const phrases = ref([])
const phraseLoading = ref(false)
const confirmingAll = ref(false)
const rejectingAll = ref(false)
const multiMode = ref(false)
const selected = ref(new Set())
const batchDeleting = ref(false)
const styleInfo = ref(null)
const avoidList = ref([])
const avoidText = ref('')
const savingStyle = ref(false)

const categoryOptions = [
  { label: '风格', value: 'style' },
  { label: '赛道', value: 'topic' },
  { label: '红线', value: 'redline' },
  { label: '金句锚点', value: 'phrase' }
]
const CATEGORY_NAMES = { style: '风格', topic: '赛道', redline: '红线', phrase: '金句锚点' }
const categoryName = (c) => CATEGORY_NAMES[c] || c

async function load() {
  const [s, c] = await Promise.all([
    api('/api/persona?status=suggested'),
    api('/api/persona?status=confirmed')
  ])
  suggested.value = s
  confirmed.value = c
}

async function confirmAll() {
  if (!suggested.value.length) return
  confirmingAll.value = true
  try {
    const r = await api('/api/persona/confirm-all', { method: 'POST', body: '{}' })
    message.success(`已确认 ${r.count || 0} 条建议`)
    await load()
  } catch (e) {
    message.error(e.message)
  } finally {
    confirmingAll.value = false
  }
}

function askRejectAll() {
  const n = suggested.value.length
  if (!n) return
  dialog.warning({
    title: '一键拒绝建议',
    content: `确定拒绝全部 ${n} 条待确认建议？拒绝后不再出现在待确认列表。`,
    positiveText: '拒绝',
    negativeText: '取消',
    onPositiveClick: async () => {
      rejectingAll.value = true
      try {
        const r = await api('/api/persona/reject-all', { method: 'POST', body: '{}' })
        message.success(`已拒绝 ${r.count || 0} 条建议`)
        await load()
      } catch (e) {
        message.error(e.message)
      } finally {
        rejectingAll.value = false
      }
    }
  })
}

function toggleSel(t) {
  const id = Number(t.id)
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function cancelMulti() {
  multiMode.value = false
  selected.value = new Set()
}

function askBatchDelete() {
  const n = selected.value.size
  if (!n) return
  dialog.warning({
    title: '删除所选档案',
    content: `确定删除选中的 ${n} 条人设档案？删除后不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      batchDeleting.value = true
      try {
        const r = await api('/api/persona/tags/batch-delete', { method: 'POST', body: JSON.stringify({ ids: [...selected.value] }) })
        message.success(`已删除 ${r.deleted || 0} 条`)
        cancelMulti()
        await load()
      } catch (e) {
        message.error(e.message)
      } finally {
        batchDeleting.value = false
      }
    }
  })
}

async function loadStyle() {
  try {
    const r = await api('/api/persona/style')
    styleInfo.value = r
    avoidList.value = [...(r.avoid_words || [])]
  } catch (e) {
    /* 静默 */
  }
}

function removeAvoid(w) {
  avoidList.value = avoidList.value.filter(x => x !== w)
}

function addAvoidWords() {
  const parts = avoidText.value.split(/[,，]/).map(x => x.trim()).filter(Boolean)
  parts.forEach(x => { if (!avoidList.value.includes(x)) avoidList.value.push(x) })
  avoidText.value = ''
}

async function saveStyle() {
  savingStyle.value = true
  try {
    const r = await api('/api/persona/style', { method: 'PUT', body: JSON.stringify({ avoid_words: avoidList.value }) })
    avoidList.value = [...(r.avoid_words || [])]
    if (styleInfo.value) styleInfo.value = { ...styleInfo.value, avoid_words: avoidList.value }
    message.success('已保存')
  } catch (e) {
    message.error(e.message)
  } finally {
    savingStyle.value = false
  }
}

async function initPersona() {
  running.value = true
  try {
    const r = await api('/api/persona/init', { method: 'POST', body: '{}' })
    message.success(`初始化任务已启动（task #${r.task_id}），可稍后在素材库查看`)
  } catch (e) {
    message.error(e.message)
  } finally {
    running.value = false
  }
}

async function decide(t, status) {
  await api(`/api/persona/tags/${t.id}/decision`, { method: 'POST', body: JSON.stringify({ status }) })
  message.success(status === 'confirmed' ? '已确认' : '已拒绝')
  load()
}

function startEdit(t) {
  editForm.value = { id: t.id, label: t.label, description: t.description, category: t.category }
  showEdit.value = true
}

function startAdd() {
  editForm.value = { id: null, label: '', description: '', category: 'style' }
  showEdit.value = true
}

function closeEdit() {
  showEdit.value = false
}

async function saveEdit() {
  const f = editForm.value
  if (!f.label.trim()) {
    message.warning('标签不能为空')
    return
  }
  const body = JSON.stringify({ label: f.label.trim(), description: f.description, category: f.category })
  try {
    if (f.id) {
      await api(`/api/persona/tags/${f.id}`, { method: 'PATCH', body })
      message.success('已保存')
    } else {
      await api('/api/persona/tags', { method: 'POST', body })
      message.success('已新增')
    }
    closeEdit()
    await load()
  } catch (e) {
    message.error(e.message)
  }
}

async function removeTag(t) {
  await api(`/api/persona/tags/${t.id}`, { method: 'DELETE' })
  message.success('已删除')
  load()
}

async function suggestPhrases() {
  phraseLoading.value = true
  try {
    const r = await api('/api/persona/phrases/suggest?limit=12')
    phrases.value = r.items || []
    if (!phrases.value.length) message.info('暂无可提取的金句（需要先有素材转写稿）')
  } catch (e) {
    message.error(e.message)
  } finally {
    phraseLoading.value = false
  }
}

async function adoptPhrase(ph) {
  await api('/api/persona/tags', {
    method: 'POST',
    body: JSON.stringify({ label: ph.text.slice(0, 100), description: '风格锚点：来自「' + (ph.source_title || '高表现素材') + '」', category: 'phrase' })
  })
  message.success('已收为金句锚点（生成时会注入）')
  phrases.value = phrases.value.filter(x => x !== ph)
  load()
}

onMounted(() => { load(); loadStyle() })
</script>
<style scoped>
.merge-float {
  position: fixed;
  right: 18px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 40;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  padding: 8px;
  background: rgba(255, 253, 250, 0.92);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: 0 4px 18px rgba(43, 40, 35, 0.12);
  backdrop-filter: blur(2px);
}
.persona-row { cursor: default; }
.persona-row.picking { cursor: pointer; }
.persona-row.picked { border-color: #dba37d; background: #fdf3ea; }
.persona-pick { margin-right: 10px; }
</style>
