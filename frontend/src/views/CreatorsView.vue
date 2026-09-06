<template>
  <div class="page">
    <h1 class="page-title">博主管理</h1>

    <div class="panel" style="margin-bottom: 16px">
      <div class="row wrap" style="gap: 10px; align-items: center">
        <span class="muted">当前主博主：</span>
        <span v-if="current && current.id" class="current-pill">
          <img v-if="current.avatar" class="av" :src="current.avatar" alt="" />
          <span class="av av-empty" v-else />
          <b>{{ current.name }}</b>
          <span class="muted fans">全网粉丝 {{ fmtNum(current.followers_total) }}</span>
        </span>
        <n-tag v-else type="warning" round :bordered="false">未创建</n-tag>
        <n-button size="small" secondary @click="openOwnerModal()">+ 新建主博主</n-button>
        <div class="grow"></div>
        <span class="muted" style="font-size: 12px">
          预算 {{ budget.used }}/{{ budget.limit }}
          <n-button text type="primary" size="tiny" @click="showBudget = true">调整</n-button>
        </span>
        <n-button size="small" secondary @click="load">刷新</n-button>
      </div>
    </div>

    <div v-if="loading" class="panel empty">加载中…</div>
    <div v-else-if="!creators.length" class="panel empty">
      还没有博主。先点“新建主博主”创建你自己的账号，再为它配置抖音/小红书/B站账号。
    </div>

    <div v-for="c in owners" :key="c.id" class="card creator-card" :class="{ active: c.is_current }">
      <CreatorHeaderRow
        :creator="c"
        :is-current="c.is_current"
        :can-switch="!c.is_current"
        :show-add-benchmark="benchmarksOf(c).length > 0"
        :syncing-owner-id="syncingOwner"
        @daily="c => syncCreator(c, 'daily')"
        @initial="c => syncCreator(c, 'initial')"
        @switch="askSwitch"
        @edit="openOwnerModal"
        @addAccount="openAccountModal"
        @addBenchmark="openBenchmarkModal"
        @remove="delCreator"
      />
      <div v-if="!c.is_current" class="row" style="justify-content: flex-end; gap: 8px; padding: 4px 0">
        <span class="muted" style="font-size: 12px">对标博主</span>
        <n-switch size="small" :value="false" @update:value="v => askBenchmark(c, v)" />
      </div>
      <SyncProgressBar v-if="jobFor(c)" :job="jobFor(c)" />
      <CreatorAccountRow
        v-for="a in accountsOf(c)"
        :key="a.id"
        :account="a"
        :benchmark="false"
        :syncing-acct-id="syncingAcct"
        sync-label="同步"
        @sync="a => runSync('daily', a.id, c.id)"
        @posts="openPosts"
        @edit="a => openAccountModal(c, a)"
        @remove="delAccount"
        @avatar="onAvatar"
      />
      <div v-for="bm in benchmarksOf(c)" :key="bm.id" class="bm-card">
        <CreatorHeaderRow
        :creator="bm"
        :benchmark="true"
        :syncing-owner-id="syncingOwner"
        @daily="bm => syncCreator(bm, 'daily')"
        @initial="bm => syncCreator(bm, 'initial')"
        @edit="openOwnerModal"
        @addAccount="openAccountModal"
        @remove="delCreator"
      />
      <div class="row" style="justify-content: flex-end; gap: 8px; padding: 4px 0">
        <span class="muted" style="font-size: 12px">恢复为独立主博主</span>
        <n-switch size="small" :value="true" @update:value="v => askBenchmark(bm, v)" />
      </div>
      <SyncProgressBar v-if="jobFor(bm)" :job="jobFor(bm)" />
      <CreatorAccountRow
        v-for="a in accountsOf(bm)"
        :key="a.id"
        :account="a"
        :benchmark="true"
        :syncing-acct-id="syncingAcct"
        sync-label="每周同步"
        @sync="a => runSync('weekly', a.id, bm.id)"
        @posts="openPosts"
        @edit="a => openAccountModal(bm, a)"
        @remove="delAccount"
        @avatar="onAvatar"
      />
      </div>
    </div>

    <!-- 新建/编辑 主博主 or 对标 -->
    <CreatorFormModal
      :show="showCreatorModal"
      :form="creatorForm"
      :owner-options="ownerOptions"
      @update:show="v => (showCreatorModal = v)"
      @update:name="v => (creatorForm.name = v)"
      @update:parentId="v => (creatorForm.parent_id = v)"
      @update:note="v => (creatorForm.note = v)"
      @save="saveCreator"
    />

    <!-- 账号配置 -->
    <AccountFormModal
      :show="showAccountModal"
      :form="acctForm"
      :extra-text="acctExtraText"
      :parsing="parsing"
      @update:show="v => (showAccountModal = v)"
      @update:platform="v => { acctForm.platform = v; acctForm.platform_user_id = '' }"
      @update:nickname="v => (acctForm.nickname = v)"
      @update:homeLink="v => (acctForm.home_link = v)"
      @update:userId="v => (acctForm.platform_user_id = v)"
      @update:enabled="v => (acctForm.enabled = v)"
      @update:extra="v => (acctExtraText = v)"
      @parse="parseLink"
      @save="saveAccount"
    />

    <!-- 作品 -->
    <n-modal v-model:show="showPosts" preset="card" :title="'作品 · ' + (currentAcct ? platformName(currentAcct.platform) + ' ' + (currentAcct.nickname || '') : '')" style="width: min(960px, 96vw)">
      <div style="max-height: 70vh; overflow-y: auto">
        <div v-if="postsLoading" class="panel empty">加载中…</div>
        <div v-else-if="!posts.items.length" class="panel empty">暂无作品，先点“同步”拉取</div>
        <div class="grid grid-videos">
<CloudPostTile
          v-for="p in posts.items"
          :key="p.id"
          :post="p"
          :syncing-post-id="syncingPost"
          @detail="openPostsDetail"
          @sync="syncPost"
          @toMaterial="toMaterial"
          @openMaterial="goMaterial"
        />
        </div>
      </div>
    </n-modal>

    <n-modal v-model:show="showPostDetail" preset="card" style="width: min(720px, 94vw)">
      <CloudPostDetail :post="detailPost" />
    </n-modal>

    <!-- 预算 -->
    <n-modal v-model:show="showBudget" preset="card" title="每日请求预算" style="width: min(420px, 92vw)">
      <div class="form-item">
        <label class="form-label">每日预算上限（次）</label>
        <n-input-number v-model:value="budgetLimit" :min="1" style="width: 100%" />
      </div>
      <div class="row">
        <n-button type="primary" @click="saveBudget">保存</n-button>
        <n-button secondary @click="showBudget = false">取消</n-button>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api, getToken } from '../api'
import SyncProgressBar from '../components/SyncProgressBar.vue'
import { fmtNum, platformName } from '../lib/format'

const message = useMessage()
const dialog = useDialog()

const creators = ref([])
const accountsBy = ref({})
const loading = ref(false)
const current = ref({ id: null, name: '' })
const budget = ref({ limit: 2000, used: 0 })
const budgetLimit = ref(2000)
const showBudget = ref(false)
const syncing = ref(false)
const syncingOwner = ref(0)
const syncingAcct = ref(0)
const syncingPost = ref(0)
const activeJobs = ref({}) // R-070：creatorId -> 正在运行的同步任务进度
let progressTimer = null

const owners = computed(() => creators.value.filter(c => c.kind === 'owner'))
const ownerOptions = computed(() => owners.value.map(c => ({ label: c.name, value: c.id })))
const benchmarksOf = (c) => creators.value.filter(x => x.kind === 'benchmark' && x.parent_id === c.id)
const accountsOf = (c) => accountsBy.value[c.id] || []

// creator modal
const showCreatorModal = ref(false)
const creatorForm = ref({ id: null, kind: 'owner', parent_id: null, name: '', note: '' })

// account modal
const showAccountModal = ref(false)
const acctFor = ref(null) // creator 卡片
const acctForm = ref({ id: null, platform: 'douyin', nickname: '', home_link: '', platform_user_id: '', sync_frequency: 'daily', enabled: true })
const acctExtraText = ref('{}')
const parsing = ref(false)

// posts modal
const showPosts = ref(false)
const showPostDetail = ref(false)
const currentAcct = ref(null)
const posts = ref({ items: [], total: 0 })
const postsLoading = ref(false)
const detailPost = ref(null)

function parseExtra(text) {
  try {
    const v = JSON.parse(text || '{}')
    return v && typeof v === 'object' ? v : {}
  } catch {
    throw new Error('增强配置不是合法 JSON')
  }
}

async function load() {
  loading.value = true
  try {
    const [cs, cur, bud] = await Promise.all([
      api('/api/creators'),
      api('/api/creators/current'),
      api('/api/platform/budget')
    ])
    creators.value = cs
    current.value = cur
    budget.value = bud
    budgetLimit.value = bud.limit
    accountsBy.value = {}
    await Promise.all(creators.value.map(async (c) => {
      accountsBy.value[c.id] = await api(`/api/creators/${c.id}/accounts`)
    }))
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function pollJobs() {
  try {
    const d = await api('/api/platform/jobs?limit=12')
    const map = {}
    // jobs 已按最新在前返回
    for (const j of d.items || []) {
      if (j.status === 'running' && j.creator_id && ['daily', 'initial', 'weekly'].includes(j.scope) && !(j.creator_id in map)) {
        map[j.creator_id] = j
      }
    }
    activeJobs.value = map
    if (!Object.keys(map).length && progressTimer) {
      clearInterval(progressTimer)
      progressTimer = null
    }
  } catch (e) { /* 轮询失败不打断 */ }
}
function startProgressPoll() {
  pollJobs()
  if (!progressTimer) progressTimer = setInterval(pollJobs, 1000)
}
function stopProgressPoll() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}
function jobFor(c) {
  return activeJobs.value[c.id] || null
}

function openOwnerModal(c) {
  creatorForm.value = c
    ? { id: c.id, kind: c.kind, parent_id: c.parent_id, name: c.name, note: c.note }
    : { id: null, kind: 'owner', parent_id: null, name: '', note: '' }
  showCreatorModal.value = true
}
function openBenchmarkModal(owner) {
  creatorForm.value = { id: null, kind: 'benchmark', parent_id: owner.id, name: '', note: '' }
  showCreatorModal.value = true
}

async function saveCreator() {
  const body = {
    kind: creatorForm.value.kind,
    parent_id: creatorForm.value.parent_id,
    name: creatorForm.value.name,
    note: creatorForm.value.note
  }
  try {
    if (creatorForm.value.id) {
      await api('/api/creators/' + creatorForm.value.id, { method: 'PATCH', body: JSON.stringify(body) })
    } else {
      await api('/api/creators', { method: 'POST', body: JSON.stringify(body) })
    }
    message.success('已保存')
    showCreatorModal.value = false
    load()
  } catch (e) {
    message.error(e.message)
  }
}

function askBenchmark(c, on) {
  const title = on ? '设为对标博主' : '恢复为独立主博主'
  const content = on
    ? `把「${c.name}」设为「${current.value && current.value.name || ''}」的对标博主？它的内容只做对标分析与洗稿参考，不进你当前主博主的人设学习语料；之后可随时恢复为独立主博主。`
    : `把「${c.name}」恢复为独立主博主？它的数据会重新作为独立博主展示。`
  dialog.warning({
    title,
    content,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api('/api/creators/' + c.id + '/benchmark', { method: 'POST', body: JSON.stringify({ on }) })
        message.success(on ? '已设为对标博主' : '已恢复为独立主博主')
        load()
      } catch (e) {
        message.error(e.message)
      }
    }
  })
}

function askSwitch(c) {
  dialog.warning({
    title: '切换主博主',
    content: `确定切换到「${c.name}」吗？切换后 AI 人设、素材、脚本、复盘都会跟随此博主。`,
    positiveText: '切换',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api(`/api/creators/${c.id}/activate`, { method: 'POST' })
        message.success(`已切换到 ${c.name}`)
        load()
      } catch (e) {
        message.error(e.message)
      }
    }
  })
}

function delCreator(c) {
  dialog.warning({
    title: '删除博主',
    content: `确定删除「${c.name}」？（有账号/作品/素材/草稿时不可删除）`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api(`/api/creators/${c.id}`, { method: 'DELETE' })
        message.success('已删除')
        load()
      } catch (e) {
        message.error(e.message)
      }
    }
  })
}

function openAccountModal(creator, acct) {
  acctFor.value = creator
  acctForm.value = acct
    ? { ...acct, extra_config: {} }
    : { id: null, platform: 'douyin', nickname: '', home_link: '', platform_user_id: '', sync_frequency: creator.kind === 'benchmark' ? 'weekly' : 'daily', enabled: true }
  acctExtraText.value = acct ? JSON.stringify(acct.extra_config || {}, null, 0) : '{}'
  showAccountModal.value = true
}

async function parseLink() {
  if (!acctFor.value || !acctForm.value.home_link) {
    message.warning('先填写主页分享链接')
    return
  }
  parsing.value = true
  try {
    const r = await api('/api/creators/parse-link', { method: 'POST', body: JSON.stringify({ platform: acctForm.value.platform, home_link: acctForm.value.home_link }) })
    acctForm.value.platform_user_id = r.platform_user_id
    message.success(`解析成功：${r.platform_user_id}`)
  } catch (e) {
    message.error(e.message)
  } finally {
    parsing.value = false
  }
}

async function saveAccount() {
  if (!acctForm.value.platform_user_id && !acctForm.value.home_link) {
    message.warning('请填主页分享链接或平台用户 ID')
    return
  }
  let extra
  try {
    extra = parseExtra(acctExtraText.value)
  } catch (e) {
    message.error(e.message)
    return
  }
  const body = {
    platform: acctForm.value.platform,
    nickname: acctForm.value.nickname,
    home_link: acctForm.value.home_link,
    platform_user_id: acctForm.value.platform_user_id,
    extra_config: extra,
    enabled: acctForm.value.enabled,
    sync_frequency: acctForm.value.sync_frequency
  }
  try {
    if (acctForm.value.id) {
      await api('/api/creators/accounts/' + acctForm.value.id, { method: 'PATCH', body: JSON.stringify(body) })
    } else {
      await api(`/api/creators/${acctFor.value.id}/accounts`, { method: 'POST', body: JSON.stringify(body) })
    }
    message.success('账号已保存')
    showAccountModal.value = false
    load()
  } catch (e) {
    message.error(e.message)
  }
}

function delAccount(a) {
  dialog.warning({
    title: '删除账号',
    content: '删除该平台账号配置？（作品会一并删除）',
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api('/api/creators/accounts/' + a.id, { method: 'DELETE' })
        message.success('已删除')
        load()
      } catch (e) {
        message.error(e.message)
      }
    }
  })
}

async function syncCreator(c, scope) {
  if (scope === 'initial') {
    dialog.info({
      title: '全量同步',
      content: `同步「${c.name}」三个平台主页数据 + 全部作品数据（视频不下载）。确认开始？`,
      positiveText: '开始',
      negativeText: '取消',
      onPositiveClick: () => startCreatorSync(c, scope)
    })
  } else {
    startCreatorSync(c, scope)
  }
}

async function startCreatorSync(c, scope) {
  syncingOwner.value = c.id
  try {
    await api('/api/platform/sync', { method: 'POST', body: JSON.stringify({ scope, creator_id: c.id }) })
    message.success('已开始同步「' + c.name + '」，完成后右上角通知')
    startProgressPoll()
    load()
  } catch (e) {
    message.error(e.message)
  } finally {
    syncingOwner.value = 0
  }
}

async function runSync(scope, accountId, creatorId) {
  if (accountId) syncingAcct.value = accountId
  else syncing.value = true
  try {
    const body = { scope, account_id: accountId || null }
    if (creatorId) body.creator_id = creatorId
    await api('/api/platform/sync', { method: 'POST', body: JSON.stringify(body) })
    message.success('同步任务已开始，完成后右上角通知')
    startProgressPoll()
    load()
  } catch (e) {
    message.error(e.message)
  } finally {
    syncing.value = false
    syncingAcct.value = 0
  }
}



async function openPosts(acct) {
  currentAcct.value = acct
  showPosts.value = true
  postsLoading.value = true
  try {
    const data = await api(`/api/platform/posts?account_id=${acct.id}&limit=200`)
    posts.value = data
  } catch (e) {
    message.error(e.message)
  } finally {
    postsLoading.value = false
  }
}

async function syncPost(p) {
  syncingPost.value = p.id
  try {
    const r = await api(`/api/platform/posts/${p.id}/sync`, { method: 'POST' })
    message.success(r.message || '同步完成')
    openPosts(currentAcct.value)
  } catch (e) {
    message.error(e.message)
  } finally {
    syncingPost.value = 0
  }
}

async function toMaterial(p) {
  try {
    await api(`/api/platform/posts/${p.id}/to-material`, { method: 'POST' })
    message.success('已转为素材（可在素材库继续上传/编辑）')
    openPosts(currentAcct.value)
  } catch (e) {
    message.error(e.message)
  }
}

function openPostsDetail(p) {
  detailPost.value = p
  showPostDetail.value = true
}

function goMaterial(id) {
  showPosts.value = false
  location.hash = `#/videos?edit=${id}`
}

async function onAvatar(a, e) {
  const f = e.target.files[0]
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  try {
    const resp = await fetch(`/api/creators/accounts/${a.id}/avatar`, {
      method: 'POST',
      headers: { 'X-Access-Token': getToken() },
      body: fd
    })
    if (!resp.ok) {
      let detail = resp.statusText
      try { detail = (await resp.json()).detail || detail } catch (e) { detail = detail || e.message }
      throw new Error(detail)
    }
    message.success('头像已更新（之后自动同步不覆盖手动头像）')
    load()
  } catch (err) {
    message.error(err.message)
  } finally {
    e.target.value = ''
  }
}

async function saveBudget() {
  try {
    await api('/api/platform/budget', { method: 'PUT', body: JSON.stringify({ limit: budgetLimit.value }) })
    message.success('预算已更新')
    showBudget.value = false
    load()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(async () => {
  await load()
  startProgressPoll()  // R-088：切页回来也恢复博主页同步进度条
})
onUnmounted(stopProgressPoll)
</script>

<style scoped>
.creator-card {
  margin-bottom: 14px;
  border: 1px solid var(--line, #e6e0d5);
  border-radius: 12px;
  padding: 14px 16px;
  background: #fffdfa;
}
.creator-card.active {
  border-color: #a34f2c55;
  box-shadow: 0 0 0 1px #a34f2c22;
}
.bm-card {
  margin: 10px 0 4px 18px;
  padding: 10px 12px;
  border-left: 2px solid #d9c7b8;
  background: #faf7f2;
  border-radius: 0 8px 8px 0;
}
.acct-row {
  margin-top: 8px;
  padding: 8px 10px;
  background: #f7f3ec;
  border-radius: 8px;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.wrap {
  flex-wrap: wrap;
}

.current-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #f7f3ec;
  border: 1px solid #eee5d8;
  border-radius: 20px;
  padding: 4px 12px 4px 5px;
}
.av {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  object-fit: cover;
  flex: none;
}
.av-sm {
  width: 26px;
  height: 26px;
}
.av-empty {
  display: inline-block;
  background: #fffdfa;
  border: 1.5px dashed #cdbfae;
  box-sizing: border-box;
}
.av-wrap {
  position: relative;
  cursor: pointer;
  flex: none;
}
.av-wrap .av-edit {
  position: absolute;
  right: -4px;
  bottom: -4px;
  background: #a34f2c;
  color: #fff;
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 8px;
  opacity: 0;
  transition: opacity .15s;
}
.av-wrap:hover .av-edit {
  opacity: 1;
}
.fans {
  font-size: 12px;
}
.mini {
  font-size: 12px;
  white-space: nowrap;
}
.uid {
  font-size: 12px;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
