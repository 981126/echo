<template>
  <div class="notif-wrap">
    <n-badge :value="unreadCount" :max="99" :show="unreadCount > 0" type="error">
      <n-button quaternary circle size="small" class="notif-btn" aria-label="通知" @click.stop="toggle">
        <svg class="bell-icon" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
          stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
      </n-button>
    </n-badge>

    <transition name="drop">
      <div v-if="open" class="notif-panel" @click.stop>
        <div class="row" style="justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid var(--line)">
          <strong style="font-size: 13px">通知</strong>
          <div class="row" style="gap: 4px">
            <n-button size="tiny" quaternary @click="readAll">全部已读</n-button>
            <n-popconfirm @positive-click="clearAll">
              <template #trigger>
                <n-button size="tiny" quaternary type="error">清空</n-button>
              </template>
              清空全部通知？
            </n-popconfirm>
          </div>
        </div>
        <div class="notif-list">
          <div v-if="!notifs.length" class="empty" style="padding: 28px 0">暂无通知</div>
          <div
            v-for="n in notifs"
            :key="n.id"
            class="notif-item"
            :class="{ unread: !n.read }"
            @click="go(n)"
          >
            <div class="row" style="gap: 6px; align-items: center">
              <span v-if="!n.read" class="notif-dot" />
              <strong style="font-size: 13px">{{ n.title }}</strong>
              <n-tag v-if="n.status === 'failed'" size="tiny" :bordered="false" round type="error">失败</n-tag>
              <div class="grow"></div>
              <n-button size="tiny" quaternary @click.stop="copyText(n)">复制</n-button>
            </div>
            <p class="muted" style="margin: 2px 0 0">{{ n.message }}</p>
            <span class="muted" style="font-size: 11px">{{ fmt(n.created_at) }}</span>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'
import { busOn } from '../lib/eventbus'
import { connectEvents, disconnectEvents } from '../lib/sse'

const notifs = ref([])
const open = ref(false)
const message = useMessage()
let timer = null
let prevMaxId = 0
let inited = false
let offNotif = null

const unreadCount = computed(() => notifs.value.filter(n => !n.read).length)

function fmt(v) {
  return v ? v.replace('T', ' ').slice(5, 16) : ''
}

async function load(notify = false) {
  try {
    const rows = await api('/api/notifications?limit=50')
    notifs.value = rows
    if (notify && inited && rows.length) {
      const curMax = Math.max(...rows.map(r => r.id))
      if (curMax > prevMaxId) {
        const fresh = rows.filter(r => r.id > prevMaxId && !r.read)
        fresh.slice(0, 3).forEach(r => message.success(r.title))
      }
      prevMaxId = curMax
    }
    inited = true
  } catch {
    /* 未登录/后端暂不可用时不打扰 */
  }
}

function toggle() {
  open.value = !open.value
  if (open.value) load(false)
}

async function go(n) {
  open.value = false
  if (!n.read) {
    await api('/api/notifications/read', { method: 'POST', body: JSON.stringify({ ids: [n.id] }) })
  }
  location.hash = n.target || '/home'
  load(false)
}

async function copyText(n) {
  const text = `${n.title}\n${n.message}`
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    message.success('已复制')
  } catch {
    message.error('复制失败')
  }
}

async function readAll() {
  await api('/api/notifications/read', { method: 'POST', body: JSON.stringify({}) })
  load(false)
}

async function clearAll() {
  await api('/api/notifications/clear', { method: 'POST', body: '{}' })
  notifs.value = []
}

function onDocPointerDown(e) {
  const t = e.target
  if (t && t.closest) {
    if (t.closest('.notif-wrap')) return
    // 清空确认框(Naive popconfirm)渲染在面板外部的 portal，点它不能误关面板
    if (t.closest('.n-popconfirm') || t.closest('.n-popover')) return
  }
  open.value = false
}

onMounted(() => {
  load(true)
  connectEvents()  // R-087：SSE 长连接，收到新通知即时刷新
  offNotif = busOn('notification.new', () => load(true))
  timer = setInterval(() => load(true), 15000)  // 兜底轮询（SSE 断线时仍能补上）
  document.addEventListener('pointerdown', onDocPointerDown)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (offNotif) offNotif()
  disconnectEvents()
  document.removeEventListener('pointerdown', onDocPointerDown)
})
</script>
