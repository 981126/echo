<template>
  <div class="page">
    <h1 class="page-title">人设档案</h1>

    <div class="toolbar">
      <n-button secondary :loading="running" @click="initPersona">
        {{ running ? '初始化中…' : '用历史转写稿初始化人设' }}
      </n-button>
    </div>

    <div class="section-title">待确认建议</div>
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

    <div class="section-title">已确认档案</div>
    <div v-if="!confirmed.length" class="panel empty">暂无已确认人设</div>
    <div v-for="t in confirmed" :key="t.id" class="panel row" style="align-items: flex-start">
      <div class="grow">
        <div class="row" style="gap: 8px">
          <strong>{{ t.label }}</strong>
          <n-tag size="small" :bordered="false" round>{{ categoryName(t.category) }}</n-tag>
          <n-tag v-if="t.category === 'redline'" size="small" :bordered="false" round type="error">红线</n-tag>
        </div>
        <span class="muted" style="display: block; margin-top: 2px">{{ t.description }}</span>
      </div>
      <n-button size="tiny" secondary @click="startEdit(t)">编辑</n-button>
      <n-popconfirm @positive-click="removeTag(t)">
        <template #trigger>
          <n-button size="tiny" quaternary type="error">删除</n-button>
        </template>
        删除该人设标签？
      </n-popconfirm>
    </div>

    <div class="section-title">手动添加</div>
    <div class="panel">
      <div class="form-grid">
        <div class="form-item">
          <label class="form-label">标签</label>
          <n-input v-model:value="form.label" placeholder="如：犀利敢说" />
        </div>
        <div class="form-item">
          <label class="form-label">描述</label>
          <n-input v-model:value="form.description" placeholder="一句话描述" />
        </div>
        <div class="form-item full">
          <label class="form-label">类别</label>
          <n-select v-model:value="form.category" :options="categoryOptions" />
        </div>
      </div>
      <n-button type="primary" @click="addTag">添加</n-button>
    </div>

    <n-modal
      v-model:show="showEdit"
      preset="card"
      title="编辑人设标签"
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
        <n-button type="primary" @click="saveEdit">保存</n-button>
        <n-button secondary @click="closeEdit">取消</n-button>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'

const suggested = ref([])
const confirmed = ref([])
const running = ref(false)
const message = useMessage()
const form = ref({ label: '', description: '', category: 'style' })
const showEdit = ref(false)
const editForm = ref({ id: null, label: '', description: '', category: 'style' })

const categoryOptions = [
  { label: '风格', value: 'style' },
  { label: '赛道', value: 'topic' },
  { label: '红线', value: 'redline' }
]
const CATEGORY_NAMES = { style: '风格', topic: '赛道', redline: '红线' }
const categoryName = (c) => CATEGORY_NAMES[c] || c

async function load() {
  const [s, c] = await Promise.all([
    api('/api/persona?status=suggested'),
    api('/api/persona?status=confirmed')
  ])
  suggested.value = s
  confirmed.value = c
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

function closeEdit() {
  showEdit.value = false
}

async function saveEdit() {
  const f = editForm.value
  if (!f.label.trim()) {
    message.warning('标签不能为空')
    return
  }
  await api(`/api/persona/tags/${f.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ label: f.label.trim(), description: f.description, category: f.category })
  })
  message.success('已保存')
  closeEdit()
  load()
}

async function removeTag(t) {
  await api(`/api/persona/tags/${t.id}`, { method: 'DELETE' })
  message.success('已删除')
  load()
}

async function addTag() {
  if (!form.value.label.trim()) {
    message.warning('请填写标签')
    return
  }
  await api('/api/persona/tags', { method: 'POST', body: JSON.stringify(form.value) })
  form.value = { label: '', description: '', category: 'style' }
  message.success('已添加')
  load()
}

onMounted(load)
</script>
