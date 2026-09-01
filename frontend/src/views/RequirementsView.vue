<template>
  <div>
    <h1 class="page-title">需求管理</h1>
    <div class="card">
      <h3>提交新需求</h3>
      <div class="row">
        <label class="field grow">标题<input v-model="form.title" placeholder="一句话标题" /></label>
        <label class="field grow">描述<input v-model="form.summary" placeholder="原始需求（原样记录）" /></label>
        <button @click="create">登记</button>
      </div>
      <p class="muted">登记后生成 R-xxx 编号并归档；后续 agent 会按反问清单与你确认细节。</p>
    </div>
    <div v-if="msg" class="msg" :class="msgType">{{ msg }}</div>
    <div class="card">
      <table style="width: 100%; border-collapse: collapse">
        <thead><tr class="muted"><th style="text-align:left">编号</th><th style="text-align:left">标题</th><th style="text-align:left">状态</th><th style="text-align:left">摘要</th></tr></thead>
        <tbody>
          <tr v-for="r in items" :key="r.id" style="border-top: 1px solid var(--border)">
            <td style="padding: 6px 0">{{ r.id }}</td>
            <td>{{ r.title }}</td>
            <td>
              <select :value="r.status" @change="changeStatus(r, $event.target.value)">
                <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
              </select>
            </td>
            <td class="muted">{{ r.summary }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'

const items = ref([])
const form = ref({ title: '', summary: '' })
const msg = ref('')
const msgType = ref('ok')
const statuses = ['已登记', '澄清中', '已确认', '实施中', '已完成', '已搁置', '已拒绝']

async function load() { items.value = await api('/api/requirements') }

async function create() {
  if (!form.value.title.trim()) { show('请填写标题', 'err'); return }
  await api('/api/requirements', { method: 'POST', body: JSON.stringify(form.value) })
  form.value = { title: '', summary: '' }
  show('已登记归档', 'ok')
  load()
}

async function changeStatus(r, status) {
  await api(`/api/requirements/${r.id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
  load()
}

function show(text, type) { msg.value = text; msgType.value = type }

onMounted(load)
</script>
