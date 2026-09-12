<template>
  <div class="page chat-page">
    <div class="chat-layout">
      <aside class="conv-panel panel">
        <div class="row" style="justify-content: space-between; margin-bottom: 10px">
          <span class="section-title" style="margin: 0">对话</span>
          <n-button size="tiny" type="primary" ghost @click="newChat">＋ 新建</n-button>
        </div>
        <div v-if="!conversations.length" class="muted" style="padding: 8px 2px">暂无对话</div>
        <div
          v-for="c in conversations"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === currentId }"
          @click="selectConversation(c.id)"
        >
          <template v-if="renameId === c.id">
            <n-input
              v-model:value="renameTitle"
              size="tiny"
              @keyup.enter="saveRename"
              @blur="saveRename"
              autofocus
            />
          </template>
          <template v-else>
            <span class="conv-title">{{ c.title }}</span>
            <span class="conv-actions">
              <button class="icon-btn" title="重命名" @click.stop="startRename(c)">✎</button>
              <n-popconfirm @positive-click="removeConversation(c.id)">
                <template #trigger>
                  <button class="icon-btn danger" title="删除">✕</button>
                </template>
                删除该对话？
              </n-popconfirm>
            </span>
          </template>
        </div>
      </aside>

      <div class="chat-main">
        <div class="panel">
          <div ref="box" class="chat-box">
            <div v-if="!messages.length" class="empty">
              <div style="margin-bottom: 12px">想聊点什么？</div>
              <div class="row" style="justify-content: center; gap: 8px">
                <n-button size="tiny" secondary @click="ask('素材库里有哪些视频？')">素材库</n-button>
                <n-button size="tiny" secondary @click="ask('我的人设档案是什么？')">人设档案</n-button>
                <n-button size="tiny" secondary @click="ask('最近的数据表现如何？')">数据表现</n-button>
              </div>
            </div>
            <template v-for="m in messages" :key="m.key">
              <div v-if="m.role === 'assistant'" class="bubble assistant">
                <div v-if="(m.steps || []).length" class="agent-steps">
                  <div v-for="(st, i) in m.steps" :key="i" class="agent-step">
                    <span class="dot" :class="st.kind" />
                    <span class="what">{{ st.text }}</span>
                  </div>
                </div>
                <div class="prose" v-html="renderMd(m.content)" />
                <div v-for="a in (m.actions || [])" :key="a.id" class="action-card">
                  <div class="row" style="justify-content: space-between; align-items: center; gap: 8px">
                    <strong>⚠ 待你确认：{{ a.label }}</strong>
                    <n-tag size="tiny" :bordered="false" round :type="tagType(a.status)">{{ statusText(a.status) }}</n-tag>
                  </div>
                  <p class="muted" style="margin: 6px 0 0; font-size: 12.5px">{{ a.preview }}</p>
                  <p v-if="a.result" class="muted" style="margin: 4px 0 0; font-size: 12.5px">✓ {{ a.result }}</p>
                  <p v-if="a.error" style="margin: 4px 0 0; font-size: 12.5px; color: var(--warn)">✗ {{ a.error }}</p>
                  <div v-if="a.status === 'pending'" class="row" style="gap: 8px; margin-top: 8px">
                    <n-button size="tiny" type="primary" :loading="deciding === a.id" @click="confirmAction(a)">确认执行</n-button>
                    <n-button size="tiny" secondary :loading="deciding === a.id" @click="cancelAction(a)">取消</n-button>
                  </div>
                </div>
                <span v-if="m.streaming" class="caret" />
                <div v-if="!m.streaming" class="bubble-actions">
                  <button class="icon-btn" title="复制" @click="copy(m.content)">复制</button>
                </div>
              </div>
              <div v-else class="bubble user">{{ m.content }}</div>
            </template>
          </div>
        </div>

        <div class="panel row" style="padding: 14px 16px">
          <n-input
            v-model:value="text"
            class="grow"
            type="textarea"
            :rows="2"
            placeholder="输入问题，Enter 发送"
            :disabled="sending"
            @keydown.enter.exact.prevent="send"
          />
          <n-button type="primary" :disabled="sending || !text.trim()" @click="send">发送</n-button>
        </div>
        <p class="muted" style="margin: 4px 2px 0">只读查询直接回答 · 生成/修改等写操作需你确认</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api, getToken } from '../api'
import { renderMd } from '../md'

const conversations = ref([])
const currentId = ref(null)
const messages = ref([])
const text = ref('')
const sending = ref(false)
const box = ref(null)
const renameId = ref(null)
const renameTitle = ref('')
const message = useMessage()
let keySeq = 0

async function loadConversations() {
  conversations.value = await api('/api/chat/conversations')
  if (!conversations.value.length) {
    const c = await api('/api/chat/conversations', { method: 'POST', body: JSON.stringify({}) })
    conversations.value = [c]
  }
  if (currentId.value == null) {
    await selectConversation(conversations.value[0].id)
  }
}

async function selectConversation(id) {
  currentId.value = id
  await loadActions()
  const rows = await api(`/api/chat/history?conversation_id=${id}&limit=200`)
  messages.value = rows.map(r => ({ key: r.id, role: r.role, content: r.content, streaming: false, steps: [], actions: [] }))
  // R-147 P2：刷新/切会话后，把该会话最近的写操作提案挂到最后的助手消息上，作者仍能确认
  const lastAssistant = [...messages.value].reverse().find(m => m.role === 'assistant')
  if (lastAssistant && actions.value.length) {
    lastAssistant.actions = actions.value.filter(a => a.status === 'pending' || a.status === 'done' || a.status === 'failed')
  }
  scroll()
}

async function newChat() {
  const c = await api('/api/chat/conversations', { method: 'POST', body: JSON.stringify({}) })
  conversations.value.unshift(c)
  currentId.value = c.id
  messages.value = []
  text.value = ''
}

function startRename(c) {
  renameId.value = c.id
  renameTitle.value = c.title
}

async function saveRename() {
  if (renameId.value == null) return
  const id = renameId.value
  renameId.value = null
  const title = (renameTitle.value || '').trim()
  if (!title) return
  await api(`/api/chat/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) })
  await loadConversations()
  currentId.value = id
}

async function removeConversation(id) {
  await api(`/api/chat/conversations/${id}`, { method: 'DELETE' })
  conversations.value = conversations.value.filter(c => c.id !== id)
  if (currentId.value === id) {
    currentId.value = null
    await loadConversations()
  }
}

async function autoTitle(q) {
  const c = conversations.value.find(x => x.id === currentId.value)
  if (c && c.title === '新对话') {
    await api(`/api/chat/conversations/${c.id}`, { method: 'PATCH', body: JSON.stringify({ title: q.slice(0, 20) }) })
    c.title = q.slice(0, 20)
  }
}

function ask(q) {
  text.value = q
  send()
}

const deciding = ref(0)
const actions = ref([])

function stepText(ev) {
  if (ev.kind === 'tool') {
    const args = ev.args && Object.keys(ev.args).length ? ' ' + JSON.stringify(ev.args).slice(0, 60) : ''
    return `调用 ${ev.name}${args}`
  }
  return `${ev.name} → ${ev.summary || '完成'}`
}
function statusText(s) {
  return { pending: '待确认', done: '已执行', cancelled: '已取消', failed: '执行失败', confirmed: '已确认' }[s] || s
}
function tagType(s) {
  return { pending: 'warning', done: 'success', cancelled: 'default', failed: 'error' }[s] || 'default'
}

async function loadActions() {
  if (currentId.value == null) return
  try {
    actions.value = await api(`/api/chat/actions?conversation_id=${currentId.value}`)
  } catch {
    actions.value = []
  }
}

function attachActions(msgKey) {
  const msg = messages.value.find(m => m.key === msgKey)
  if (!msg || !actions.value.length) return
  const known = new Set(messages.value.flatMap(m => (m.actions || []).map(a => a.id)))
  const fresh = actions.value.filter(a => !known.has(a.id))
  if (fresh.length) msg.actions = [...(msg.actions || []), ...fresh]
}

async function refreshAction(a) {
  await loadActions()
  const updated = actions.value.find(x => x.id === a.id)
  if (updated) Object.assign(a, updated)
}

async function confirmAction(a) {
  deciding.value = a.id
  try {
    const r = await api(`/api/chat/actions/${a.id}/confirm`, { method: 'POST', body: '{}' })
    Object.assign(a, r)
    message.success('已执行')
  } catch (e) {
    message.error(e.message || '执行失败')
  } finally {
    deciding.value = 0
  }
}

async function cancelAction(a) {
  deciding.value = a.id
  try {
    const r = await api(`/api/chat/actions/${a.id}/cancel`, { method: 'POST', body: '{}' })
    Object.assign(a, r)
  } catch (e) {
    message.error(e.message || '取消失败')
  } finally {
    deciding.value = 0
  }
}

async function send() {
  const q = text.value.trim()
  if (!q || sending.value) return
  if (currentId.value == null) return
  await autoTitle(q)
  text.value = ''
  sending.value = true
  messages.value.push({ key: 'u' + (++keySeq), role: 'user', content: q })
  const asst = { key: 'a' + (++keySeq), role: 'assistant', content: '', streaming: true, steps: [], actions: [] }
  const asstKey = asst.key
  messages.value.push(asst)
  scroll()
  try {
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Access-Token': getToken() },
      body: JSON.stringify({ conversation_id: currentId.value, message: q })
    })
    if (!resp.ok || !resp.body) throw new Error('连接失败（' + resp.status + '）')
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const evName = (block.split('\n').find(l => l.startsWith('event:')) || '').slice(6).trim()
        for (const line of block.split('\n')) {
          if (!line.startsWith('data:')) continue
          let data
          try {
            data = JSON.parse(line.slice(5).trim())
          } catch {
            continue
          }
          if (data.error) throw new Error(data.message || data.error)
          if (evName === 'step') {
            const kind = data.kind === 'result' ? 'ok' : 'run'
            asst.steps.push({ kind, text: stepText(data) })
            scroll()
          } else if (data.delta) {
            asst.content += data.delta
            scroll()
          }
        }
      }
    }
    asst.streaming = false
    await loadActions()
    attachActions(asstKey)
    await loadConversations()
  } catch (e) {
    asst.content = '出错了：' + e.message
    asst.streaming = false
    message.error(e.message)
  } finally {
    sending.value = false
    scroll()
  }
}

async function copy(content) {
  try {
    await navigator.clipboard.writeText(content)
    message.success('已复制')
  } catch {
    message.error('复制失败')
  }
}

async function scroll() {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
}

onMounted(async () => {
  await loadConversations()
})
</script>
