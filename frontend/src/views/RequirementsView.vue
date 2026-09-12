<template>
  <div class="page">
    <h1 class="page-title">需求管理</h1>

    <div class="panel">
      <div class="section-title" style="margin-top: 0">提交新需求</div>
      <div class="form-grid">
        <div class="form-item">
          <label class="form-label">标题</label>
          <n-input v-model:value="form.title" placeholder="一句话标题" />
        </div>
        <div class="form-item">
          <label class="form-label">描述</label>
          <n-input v-model:value="form.summary" placeholder="原始需求（原样记录）" />
        </div>
      </div>
      <div class="row">
        <n-button type="primary" @click="create">登记归档</n-button>
      </div>
    </div>

    <div class="panel">
      <!-- R-148：宽表用 .table-wrap 兜底横向滚动，长标题不会再撑破页面 -->
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>编号</th>
              <th>标题</th>
              <th>状态</th>
              <th>摘要</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in items" :key="r.id">
              <td style="font-family: var(--mono); font-size: 12.5px; white-space: nowrap">{{ r.id }}</td>
              <td style="min-width: 180px">{{ r.title }}</td>
              <td style="min-width: 130px">
                <n-select size="small" :value="r.status" :options="statusOptions" @update:value="(v) => changeStatus(r, v)" />
              </td>
              <td class="muted">{{ r.summary }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!items.length" class="empty">暂无需求记录</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'

const items = ref([])
const message = useMessage()
const form = ref({ title: '', summary: '' })
const statusOptions = ['已登记', '澄清中', '已确认', '实施中', '已完成', '已搁置', '已拒绝'].map(s => ({ label: s, value: s }))

async function load() {
  items.value = await api('/api/requirements')
}

async function create() {
  if (!form.value.title.trim()) {
    message.warning('请填写标题')
    return
  }
  await api('/api/requirements', { method: 'POST', body: JSON.stringify(form.value) })
  form.value = { title: '', summary: '' }
  message.success('已登记归档')
  load()
}

async function changeStatus(r, status) {
  await api(`/api/requirements/${r.id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
  load()
}

onMounted(load)
</script>
