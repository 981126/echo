<template>
  <div class="page">
    <h1 class="page-title">博主管理</h1>

    <div class="panel" style="margin-bottom: 16px">
      <div class="row wrap" style="gap: 10px; align-items: center">
        <span class="muted">当前主博主：</span>
        <n-tag v-if="current && current.id" type="primary" round :bordered="false">{{ current.name }}</n-tag>
        <n-tag v-else type="warning" round :bordered="false">未创建</n-tag>
        <n-button size="small" secondary @click="openOwnerModal()">+ 新建主博主</n-button>
        <n-button
          size="small"
          type="primary"
          :disabled="!current || !current.id"
          :loading="syncing"
          @click="runSync('daily')"
        >同步今日 top10</n-button>
        <n-button size="small" secondary :disabled="!current || !current.id" @click="openSyncInit">
          首次全量同步
        </n-button>
        <div class="grow"></div>
        <span class="muted" style="font-size: 12px">
          预算 {{ budget.used }}/{{ budget.limit }}
          <n-button text type="primary" size="tiny" @click="showBudget = true">调整</n-button>
        </span>
        <n-button size="small" secondary @click="load">刷新</n-button>
      </div>
      <div v-if="summary.items && summary.items.length" class="row wrap" style="gap: 18px; margin-top: 12px; font-size: 13px">
        <template v-for="it in summary.items" :key="it.creator.id">
          <div>
            <b>{{ it.creator.name }}</b>
            <span class="muted">（{{ it.creator.kind === 'owner' ? '我' : '对标' }}）</span>
            <span class="muted" style="margin-left: 8px">粉丝 {{ fmtNum(it.totals.followers) }}</span>
            <span class="muted" style="margin-left: 8px">作品 {{ it.totals.posts }}</span>
          </div>
        </template>
      </div>
    </div>

    <div v-if="loading" class="panel empty">加载中…</div>
    <div v-else-if="!creators.length" class="panel empty">
      还没有博主。先点“新建主博主”创建你自己的账号，再为它配置抖音/小红书/B站账号。
    </div>

    <div v-for="c in owners" :key="c.id" class="card creator-card" :class="{ active: c.is_current }">
      <div class="row wrap" style="gap: 8px; align-items: center">
        <h3 style="margin: 0">{{ c.name }}</h3>
        <n-tag v-if="c.is_current" type="primary" size="small" round :bordered="false">当前</n-tag>
        <span class="muted grow" style="font-size: 12px">{{ c.note || '（无备注）' }}</span>
        <n-button v-if="!c.is_current" size="tiny" secondary @click="askSwitch(c)">切换到此博主</n-button>
        <n-button size="tiny" secondary @click="openOwnerModal(c)">编辑</n-button>
        <n-button size="tiny" quaternary type="error" @click="delCreator(c)">删除</n-button>
      </div>

      <div class="row wrap" style="gap: 8px; margin-top: 10px">
        <n-button size="tiny" secondary @click="openAccountModal(c)">+ 配置账号</n-button>
        <n-button v-if="benchmarksOf(c).length" size="tiny" secondary @click="openBenchmarkModal(c)">+ 对标博主</n-button>
      </div>

      <div v-for="a in accountsOf(c)" :key="a.id" class="acct-row">
        <div class="row wrap" style="gap: 8px; align-items: center; flex-wrap: wrap">
          <n-tag size="small" :bordered="false" round>{{ platformName(a.platform) }}</n-tag>
          <b>{{ a.nickname || platformName(a.platform) }}</b>
          <n-tag size="tiny" :bordered="false" :type="a.enabled ? 'success' : 'default'">{{ freqName(a.sync_frequency) }}</n-tag>
          <span class="muted mono" style="font-size: 12px">{{ a.platform_user_id || '（未解析 ID）' }}</span>
          <span v-if="a.last_sync_at" class="muted" style="font-size: 12px">同步于 {{ fmt(a.last_sync_at) }}</span>
          <div class="grow"></div>
          <n-button size="tiny" secondary :loading="syncingAcct === a.id" @click="runSync('daily', a.id)">同步</n-button>
          <n-button size="tiny" secondary @click="openPosts(a)">云端作品</n-button>
          <n-button size="tiny" secondary @click="openAccountModal(c, a)">编辑</n-button>
          <n-button size="tiny" quaternary type="error" @click="delAccount(a)">删除</n-button>
        </div>
      </div>

      <div v-for="bm in benchmarksOf(c)" :key="bm.id" class="bm-card">
        <div class="row wrap" style="gap: 8px; align-items: center">
          <n-tag size="small" type="info" :bordered="false" round>对标</n-tag>
          <b>{{ bm.name }}</b>
          <span class="muted grow" style="font-size: 12px">{{ bm.note || '' }}</span>
          <n-button size="tiny" secondary @click="openOwnerModal(bm)">编辑</n-button>
          <n-button size="tiny" secondary @click="openAccountModal(bm)">+ 账号</n-button>
          <n-button size="tiny" quaternary type="error" @click="delCreator(bm)">删除</n-button>
        </div>
        <div v-for="a in accountsOf(bm)" :key="a.id" class="acct-row">
          <div class="row wrap" style="gap: 8px; align-items: center">
            <n-tag size="small" :bordered="false" round>{{ platformName(a.platform) }}</n-tag>
            <b>{{ a.nickname || platformName(a.platform) }}</b>
            <span class="muted mono" style="font-size: 12px">{{ a.platform_user_id || '（未解析）' }}</span>
            <div class="grow"></div>
            <n-button size="tiny" secondary :loading="syncingAcct === a.id" @click="runSync('weekly', a.id)">每周同步</n-button>
            <n-button size="tiny" secondary @click="openPosts(a)">云端作品</n-button>
            <n-button size="tiny" secondary @click="openAccountModal(bm, a)">编辑</n-button>
            <n-button size="tiny" quaternary type="error" @click="delAccount(a)">删除</n-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建/编辑 主博主 or 对标 -->
    <n-modal v-model:show="showCreatorModal" preset="card" :title="creatorForm.id ? '编辑博主' : creatorForm.kind === 'benchmark' ? '添加对标博主' : '新建主博主'" style="width: min(480px, 92vw)">
      <div class="form-item">
        <label class="form-label">名称</label>
        <n-input v-model:value="creatorForm.name" placeholder="如：我的主号 / 对标博主名" />
      </div>
      <div v-if="creatorForm.kind === 'benchmark'" class="form-item">
        <label class="form-label">所属主博主</label>
        <n-select v-model:value="creatorForm.parent_id" :options="ownerOptions" />
      </div>
      <div class="form-item">
        <label class="form-label">备注 / 风格参考（对标风格卡可写在这里，1-3 句）</label>
        <n-input v-model:value="creatorForm.note" type="textarea" :rows="3" placeholder="可选" />
      </div>
      <div class="row">
        <n-button type="primary" @click="saveCreator">保存</n-button>
        <n-button secondary @click="showCreatorModal = false">取消</n-button>
      </div>
    </n-modal>

    <!-- 账号配置 -->
    <n-modal v-model:show="showAccountModal" preset="card" :title="acctForm.id ? '编辑账号' : '配置 ' + platformName(acctForm.platform) + ' 账号'" style="width: min(560px, 94vw)">
      <div class="form-item">
        <label class="form-label">平台</label>
        <n-select
          v-model:value="acctForm.platform"
          :options="platformOptions"
          :disabled="!!acctForm.id"
          placeholder="选择平台"
          @update:value="() => (acctForm.platform_user_id = '')"
        />
      </div>
      <div class="form-item">
        <label class="form-label">昵称（可选）</label>
        <n-input v-model:value="acctForm.nickname" placeholder="自动同步时会用主页昵称覆盖" />
      </div>
      <div class="form-item">
        <label class="form-label">主页分享链接</label>
        <div class="row" style="gap: 6px">
          <n-input v-model:value="acctForm.home_link" placeholder="粘贴主页分享链接，点右侧自动解析 ID" style="flex: 1" />
          <n-button secondary :loading="parsing" @click="parseLink">解析</n-button>
        </div>
      </div>
      <div class="form-item">
        <label class="form-label">平台用户 ID（解析后自动填入，也可手动改）</label>
        <n-input v-model:value="acctForm.platform_user_id" placeholder="sec_user_id / user_id / uid" />
      </div>
      <div class="form-item">
        <label class="form-label">同步频率</label>
        <n-select v-model:value="acctForm.sync_frequency" :options="freqOptions" />
      </div>
      <div class="form-item">
        <label class="form-label">增强配置（JSON，可选：cookie/share_text 等）</label>
        <n-input v-model:value="acctExtraText" type="textarea" :rows="2" placeholder='{"share_text":""}' />
      </div>
      <n-checkbox v-model:checked="acctForm.enabled">启用自动同步</n-checkbox>
      <div class="row" style="margin-top: 14px">
        <n-button type="primary" @click="saveAccount">保存</n-button>
        <n-button secondary @click="showAccountModal = false">取消</n-button>
      </div>
    </n-modal>

    <!-- 云端作品 -->
    <n-modal v-model:show="showPosts" preset="card" :title="'云端作品 · ' + (currentAcct ? platformName(currentAcct.platform) + ' ' + (currentAcct.nickname || '') : '')" style="width: min(960px, 96vw)">
      <div style="max-height: 70vh; overflow-y: auto">
        <div v-if="postsLoading" class="panel empty">加载中…</div>
        <div v-else-if="!posts.items.length" class="panel empty">暂无作品，先点“同步”拉取</div>
        <div class="grid grid-videos">
          <div v-for="p in posts.items" :key="p.id" class="card-tile">
            <div class="tile-cover has" @click="openPostsDetail(p)">
              <img v-if="p.cover" :src="p.cover" alt="封面" />
              <span v-else>ECHO</span>
            </div>
            <h3 class="tile-title" style="word-break: break-all" @click="openPostsDetail(p)">{{ p.title }}</h3>
            <p class="tile-meta">
              <template v-if="p.latest_stat">
                <template v-if="p.latest_stat.plays">播放 {{ fmtNum(p.latest_stat.plays) }}</template>
                <template v-if="p.latest_stat.likes"> · 赞 {{ fmtNum(p.latest_stat.likes) }}</template>
                <template v-if="p.latest_stat.favorites"> · 藏 {{ fmtNum(p.latest_stat.favorites) }}</template>
                <template v-if="p.latest_stat.comments"> · 评 {{ fmtNum(p.latest_stat.comments) }}</template>
              </template>
              <template v-else>暂无指标</template>
            </p>
            <div class="row" style="gap: 6px">
              <n-tag v-if="p.creator_kind === 'benchmark'" size="tiny" type="info" :bordered="false">对标</n-tag>
              <n-tag v-if="p.local_video_id" size="tiny" type="success" :bordered="false">已转素材</n-tag>
            </div>
            <div class="row" style="gap: 6px; margin-top: 8px">
              <n-button size="tiny" secondary :loading="syncingPost === p.id" @click="syncPost(p)">同步数据</n-button>
              <n-button v-if="!p.local_video_id" size="tiny" secondary @click="toMaterial(p)">转素材</n-button>
              <n-button v-else size="tiny" secondary @click="goMaterial(p.local_video_id)">打开素材</n-button>
            </div>
          </div>
        </div>
      </div>
    </n-modal>

    <n-modal v-model:show="showPostDetail" preset="card" style="width: min(720px, 94vw)">
      <div v-if="detailPost">
        <div class="row" style="gap: 12px; align-items: flex-start">
          <img v-if="detailPost.cover" :src="detailPost.cover" alt="封面" style="width: 220px; border-radius: 8px; object-fit: cover" />
          <div>
            <h3 style="margin-top: 0">{{ detailPost.title }}</h3>
            <p class="muted" style="font-size: 13px">{{ detailPost.desc }}</p>
            <p v-if="detailPost.latest_stat" class="muted" style="font-size: 13px">
              播放 {{ fmtNum(detailPost.latest_stat.plays) }} · 赞 {{ fmtNum(detailPost.latest_stat.likes) }} ·
              藏 {{ fmtNum(detailPost.latest_stat.favorites) }} · 转 {{ fmtNum(detailPost.latest_stat.shares) }} · 评 {{ fmtNum(detailPost.latest_stat.comments) }}
            </p>
          </div>
        </div>
      </div>
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
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api'

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
const syncingAcct = ref(0)
const syncingPost = ref(0)
const summary = ref({ items: [] })

const platformOptions = [
  { label: '抖音', value: 'douyin' },
  { label: 'B站', value: 'bilibili' },
  { label: '小红书', value: 'xiaohongshu' }
]
const freqOptions = [
  { label: '每日自动（主博主）', value: 'daily' },
  { label: '每周（对标）', value: 'weekly' },
  { label: '手动', value: 'manual' }
]
const PLATFORM_NAMES = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
const platformName = (p) => PLATFORM_NAMES[p] || p || ''
const freqName = (f) => ({ daily: '每日', weekly: '每周', manual: '手动' }[f] || f)

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

function fmt(v) {
  return v ? String(v).replace('T', ' ').slice(0, 16) : ''
}
function fmtNum(n) {
  n = Number(n || 0)
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return String(n)
}
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
    creators.value = await api('/api/creators')
    current.value = await api('/api/creators/current')
    budget.value = await api('/api/platform/budget')
    budgetLimit.value = budget.value.limit
    summary.value = await api('/api/platform/creator-summary')
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
    content: '删除该平台账号配置？（云端作品会一并删除）',
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

async function runSync(scope, accountId) {
  if (accountId) syncingAcct.value = accountId
  else syncing.value = true
  try {
    await api('/api/platform/sync', { method: 'POST', body: JSON.stringify({ scope, account_id: accountId || null }) })
    message.success('同步任务已开始，完成后右上角通知')
    load()
  } catch (e) {
    message.error(e.message)
  } finally {
    syncing.value = false
    syncingAcct.value = 0
  }
}

function openSyncInit() {
  dialog.info({
    title: '首次全量同步',
    content: '将同步当前主博主三平台最近 50 条作品（对标 20 条），视频不下载，封面缓存本地。确认开始？',
    positiveText: '开始',
    negativeText: '取消',
    onPositiveClick: () => runSync('initial')
  })
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
    const r = await api(`/api/platform/posts/${p.id}/to-material`, { method: 'POST' })
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

onMounted(load)
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
</style>
