<template>
  <div class="page">
    <h1 class="page-title">素材库</h1>

    <UploadVideoBar :uploading="uploading" @upload="doUpload" />

    <div class="toolbar">
      <n-select multiple filterable v-model:value="platformSel" :options="platformOptions" placeholder="平台（可多选/输入过滤）" clearable style="width: 210px" />
      <n-select v-model:value="filter.status" :options="statusOptions" placeholder="状态" clearable style="width: 120px" />
      <n-select v-model:value="adFilter" :options="adOptions" placeholder="广告" clearable style="width: 110px" />
      <n-input v-model:value="searchText" placeholder="搜索标题…" clearable style="width: 150px" />
      <n-select multiple filterable v-model:value="tagSel" :options="allTags" placeholder="标签（可多选/输入过滤）" clearable style="width: 230px" />
      <n-input-number v-model:value="likesMax" :min="0" placeholder="≤ 点赞" clearable style="width: 108px" />
      <n-input-number v-model:value="likesMin" :min="0" placeholder="≥ 点赞" clearable style="width: 108px" />
      <span class="muted tl-hint">任一平台匹配即可</span>
      <n-button type="primary" @click="applyFilters">查询</n-button>
      <n-button size="small" secondary :loading="autoMerging" @click="autoMergeAll">自动合并</n-button>
      <n-button :type="mergeMode ? 'primary' : 'default'" size="small" secondary @click="mergeMode = !mergeMode">合并</n-button>
    </div>
    <div v-if="mergeMode" class="row" style="gap: 8px; margin: 8px 0">
      <span class="muted">勾选 2 个以上云端素材，合并为同一作品</span>
      <div class="grow" />
      <n-button size="tiny" type="primary" :disabled="selected.size < 2" @click="doMergeCloud">合并所选（{{ selected.size }}）</n-button>
      <n-button size="tiny" secondary @click="cancelMerge">取消</n-button>
    </div>

    <div v-if="loading" class="panel empty">加载中…</div>
    <div v-else-if="!filteredCards.length" class="panel empty">没有匹配的素材（换个关键词/标签，或去「博主」页同步）</div>
    <div v-else class="grid grid-videos">
      <MaterialCard
        v-for="it in filteredCards"
        :key="it.key"
        :item="it"
        :merge-mode="mergeMode"
        :selected="selected.has(it.key)"
        :syncing-id="syncing"
        :syncing-post-id="syncingPost"
        :click="onCardClick"
        :toggle="toggleSel"
        :sync-local="syncData"
        :sync-post="syncCloudPost"
        :confirm="confirmTags"
        :del-local="delLocal"
        :del-cloud="delCloud"
        :split="splitWork"
      />
    </div>

    <n-modal
      v-model:show="showEdit"
      preset="card"
      :title="editing ? '编辑：' + (editing.title || (!isPlaceholderFile(editing.filename) ? editing.filename : '素材')) : '编辑视频'"
      style="width: min(760px, 94vw)"
      :mask-closable="false"
      @close="closeEdit"
    >
      <div v-if="editing" style="max-height: 72vh; overflow-y: auto; padding-right: 6px">
        <n-tabs v-model:value="editPane" type="line" size="small" animated>
          <n-tab-pane name="edit" tab="编辑信息">
        <div class="form-item">
          <label class="form-label">标题</label>
          <n-input v-model:value="editing.title" placeholder="视频标题（选题标题）" />
        </div>
        <PlatformLinksInput :links="editing.links" @update:links="v => (editing.links = v)" />
        <CoverEditor :cover-url="editing.coverUrl" @change="onCover" @remove="removeCover" />

        <div v-if="linkedDrafts.length" class="form-item">
          <label class="form-label">已关联脚本（点击打开）</label>
          <div class="row" style="gap: 6px">
            <n-button
              v-for="d in linkedDrafts"
              :key="d.id"
              size="tiny"
              secondary
              @click="goDraft(d.id)"
            >#{{ d.id }} {{ d.title || '（无标题）' }}</n-button>
          </div>
        </div>

                <MetaFields
          :platform-options="platformOptions"
          :status-options="statusOptions"
          :platforms="editing.platforms"
          :status="editing.status"
          :is-ad="editing.isAd"
          :ad-price="editing.adPrice"
          :planned-ts="editing.plannedTs"
          :published-ts="editing.publishedTs"
          @update:platforms="v => (editing.platforms = v)"
          @update:status="v => (editing.status = v)"
          @update:isAd="v => (editing.isAd = v)"
          @update:adPrice="v => (editing.adPrice = v)"
          @update:plannedTs="v => (editing.plannedTs = v)"
          @update:publishedTs="v => (editing.publishedTs = v)"
        />
<div class="form-grid">
<TagsInput :model-value="tagsText" @update:modelValue="v => (tagsText = v)" />
          <TranscribeSection
            v-if="editing.filename && !isPlaceholderFile(editing.filename)"
            :transcript-text="editing.transcriptText"
            :transcribing="transcribing"
            @start="startTranscribe"
          />
          <TranscriptEditor :transcript-text="editing.transcriptText" :source-text="editing.sourceText" @update:sourceText="v => (editing.sourceText = v)" />
        </div>
        <EditActions :syncing="syncingEdit" @sync="syncEditLinks" @save="saveEdit" @cancel="closeEdit" />
          </n-tab-pane>
          <n-tab-pane name="comments" tab="评论数据">
            <div v-if="!editing.platformPosts || !editing.platformPosts.length" class="muted" style="padding: 14px 0">
              该素材还没绑定平台作品。先在「编辑信息」里填平台链接并保存，即可查看各平台评论
            </div>
            <div v-else>
              <MediaComments :posts="editCommentPosts" />
            </div>
          </n-tab-pane>
        </n-tabs>
      </div>

    </n-modal>
    <n-modal v-model:show="showCloud" preset="card" :title="'转本地素材：' + (cloudItem && cloudItem.title || '')" style="width: min(620px, 94vw)">
      <div v-if="cloudItem" style="max-height: 70vh; overflow-y: auto; padding-right: 4px">
        <n-tabs v-model:value="cloudTab" type="line" animated>
          <n-tab-pane name="local" tab="转本地素材">
            <div class="form-item">
              <label class="form-label">上传视频（可选；选后可一键「保存并语音转文字」）</label>
              <CloudVideoPicker :file-name="cloudFile ? cloudFile.name : ''" @file="onCloudFile" />
            </div>
            <CloudTextArea :model-value="cloudText" @update:modelValue="v => (cloudText = v)" />
            <div class="row" style="gap: 18px">
              <div class="form-item" style="flex: 1">
                <label class="form-label">商务广告</label>
                <n-checkbox v-model:checked="cloudAd">广告（不参与人设学习）</n-checkbox>
              </div>
              <div class="form-item" style="flex: 1">
                <label class="form-label">广告价格（元）</label>
                <n-input-number v-model:value="cloudPrice" :min="0" style="width: 100%" />
              </div>
            </div>
            <p class="muted" style="font-size: 12px">
              保存后此作品会出现在素材库（云端标识去掉），可继续编辑平台/赛道/发布时间。
            </p>
            <CloudActions
              :meta-saving="cloudMetaSaving"
              :saving="cloudSaving"
              :can-transcribe="!!cloudFile"
              @meta="saveCloudMeta"
              @save="saveCloudLocal(false)"
              @transcribe="saveCloudLocal(true)"
              @cancel="showCloud = false"
            />
          </n-tab-pane>
          <n-tab-pane name="comments" tab="评论数据">
            <div v-if="!(cloudItem.cloudPosts || []).length" class="empty">暂无平台记录</div>
            <MediaComments v-else :posts="cloudCommentPosts" />
          </n-tab-pane>
        </n-tabs>
      </div>
    </n-modal>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api, uploadVideo, uploadCover, getToken } from '../api'
import MediaComments from '../components/MediaComments.vue'
import PlatformStats from '../components/PlatformStats.vue'
import UploadVideoBar from '../components/UploadVideoBar.vue'
import MaterialCard from '../components/MaterialCard.vue'
import CoverEditor from '../components/CoverEditor.vue'
import TranscribeSection from '../components/TranscribeSection.vue'
import PlatformLinksInput from '../components/PlatformLinksInput.vue'
import EditActions from '../components/EditActions.vue'
import TranscriptEditor from '../components/TranscriptEditor.vue'
import TagsInput from '../components/TagsInput.vue'
import MetaFields from '../components/MetaFields.vue'
import CloudVideoPicker from '../components/CloudVideoPicker.vue'
import CloudActions from '../components/CloudActions.vue'
import CloudTextArea from '../components/CloudTextArea.vue'
import { adOptions, platformOptions, statusOptions } from '../lib/options'
import { fetchVideos, fetchWorks } from '../composables/media'
import { fmt, fmtNum, platformName, parseTs, tsLocal, arrKey } from '../lib/format'

const message = useMessage()
const dialog = useDialog()
const topics = ['求职', '面试', '赚钱', '知识', '其他']
const videos = ref([])
const filter = ref({ status: null })
const adFilter = ref(null)
const platformSel = ref([])
const tagSel = ref([])
const loading = ref(false)
const uploading = ref(false)
const editing = ref(null)
const linkedDrafts = ref([])
const orig = ref(null)
const syncing = ref(0)
const works = ref([])
const worksLoading = ref(false)
const cards = ref([])
const searchText = ref('')
const showCloud = ref(false)
const cloudItem = ref(null)
const cloudFile = ref(null)
const cloudText = ref('')
const cloudSaving = ref(false)
const cloudAd = ref(false)
const cloudPrice = ref(null)
const cloudMetaSaving = ref(false)
const cloudTab = ref('local')
const mergeMode = ref(false)
const selected = ref(new Set())
const syncingPost = ref(0)
const autoMerging = ref(false)
const showEdit = ref(false)
const tagsText = ref('')

const topicOptions = topics.map(t => ({ label: t, value: t }))
async function load() {
  loading.value = true
  try {
    videos.value = await fetchVideos()
    buildCards()
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function loadQuiet() {
  try {
    videos.value = await fetchVideos()
    buildCards()
  } catch (e) {
    /* 静默：后台刷新失败不打断当前编辑 */
  }
}

async function loadWorksQuiet() {
  try {
    works.value = await fetchWorks()
    buildCards()
  } catch (e) {
    /* 静默 */
  }
}

async function doUpload(f) {
  if (!f) {
    message.warning('请先选择视频文件')
    return
  }
  uploading.value = true
  try {
    const r = await uploadVideo(f)
    message.success('上传成功')
    await loadQuiet()
    if (r && r.id) {
      let v = videos.value.find(x => x.id === r.id)
      if (!v) {
        try { v = await api('/api/videos/' + r.id) } catch { v = null }
      }
      if (v) openEdit(v)
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    uploading.value = false
  }
}

async function onCover(f) {
  if (!f || !editing.value) return
  try {
    const r = await uploadCover(editing.value.id, f)
    editing.value.coverUrl = r.cover_url || null
    message.success('封面已更新')
    await loadQuiet()
  } catch (err) {
    message.error(err.message)
  }
}

async function removeCover() {
  try {
    await api(`/api/videos/${editing.value.id}/cover`, { method: 'DELETE' })
    editing.value.coverUrl = null
    message.success('封面已移除')
    await loadQuiet()
  } catch (e) {
    message.error(e.message)
  }
}

function goDraft(id) {
  showEdit.value = false
  editing.value = null
  location.hash = `#/drafts?id=${id}`
}

async function openEdit(v) {
  editPane.value = 'edit'
  let detail = v
  try {
    detail = await api('/api/videos/' + v.id)
  } catch {
    /* 列表数据已够用 */
  }
  try {
    linkedDrafts.value = await api(`/api/drafts?video_id=${v.id}&limit=20`)
  } catch {
    linkedDrafts.value = []
  }
  const tr = detail.transcript
  editing.value = {
    ...v,
    platforms: [...(v.platforms || [])],
    main_topics: [...(v.main_topics || [])],
    coverUrl: v.cover_url || null,
    links: linksFromPlatform(detail.platform_links || []),
    adPrice: v.ad_price == null ? null : Number(v.ad_price),
    sourceText: tr?.source_text || '',
    transcriptText: tr?.transcript_text || '',
    platformLinks: detail.platform_links || [],
    platformPosts: detail.platform_links || [],
    plannedTs: parseTs(v.planned_publish_at),
    publishedTs: parseTs(v.published_at)
  }
  const known5 = ['求职', '面试', '赚钱', '知识', '其他']
  const allTags = [...new Set([...(v.main_topics || []), ...(v.tags || [])])]
  tagsText.value = allTags.join(', ')
  orig.value = {
    title: editing.value.title,
    platforms: [...editing.value.platforms],
    main_topics: [...editing.value.main_topics],
    status: editing.value.status,
    is_ad: editing.value.is_ad,
    plannedTs: editing.value.plannedTs,
    publishedTs: editing.value.publishedTs,
    tagsText: tagsText.value,
    sourceText: editing.value.sourceText,
    links: { ...(editing.value.links || {}) },
    adPrice: editing.value.adPrice
  }
  showEdit.value = true
}

const transcribing = ref(false)
let transcribeTimer = null
const linkPlatforms = ['douyin', 'bilibili', 'xiaohongshu']
function isPlaceholderFile(name) {
  return !!name && name.startsWith('__cloud__')
}

const editCommentPosts = computed(() => ((editing.value && editing.value.platformPosts) || []).map(x => ({ id: x.post_id, platform: x.platform })))
const cloudCommentPosts = computed(() => ((cloudItem.value && cloudItem.value.cloudPosts) || []).map(x => ({ id: x.id, platform: x.platform })))
const syncingEdit = ref(false)
const editPane = ref('edit')


function linksFromPlatform(platformLinks) {
  const out = { douyin: '', bilibili: '', xiaohongshu: '' }
  ;(platformLinks || []).forEach(x => {
    if (x && x.platform && x.platform in out && x.url) out[x.platform] = x.url
  })
  return out
}


async function applyLinks() {
  if (!editing.value || !orig.value) return true
  const links = {}
  for (const p of linkPlatforms) {
    const v = (((editing.value.links || {})[p]) || '').trim()
    const prev = (((orig.value.links || {})[p]) || '').trim()
    if (v && v !== prev) links[p] = v
  }
  if (!Object.keys(links).length) return true
  const r = await api(`/api/platform/videos/${editing.value.id}/bind-links`, { method: 'POST', body: JSON.stringify({ links }) })
  if (r && r.errors && r.errors.length) message.warning('部分链接未绑定：' + r.errors.join('；'))
  for (const p of Object.keys(links)) {
    if (orig.value.links) orig.value.links[p] = editing.value.links[p]
  }
  return true
}

async function syncEditLinks() {
  if (!editing.value || syncingEdit.value) return
  syncingEdit.value = true
  try {
    await applyLinks()
    const r = await api(`/api/platform/videos/${editing.value.id}/sync`, { method: 'POST' })
    message.success(r.message || '同步完成')
    await loadQuiet()
    await loadWorksQuiet()
  } catch (e) {
    message.error(e.message)
  } finally {
    syncingEdit.value = false
  }
}


function clearTranscribePoll() {
  if (transcribeTimer) {
    clearInterval(transcribeTimer)
    transcribeTimer = null
  }
}

async function startTranscribe() {
  if (!editing.value || transcribing.value) return
  transcribing.value = true
  try {
    await api(`/api/videos/${editing.value.id}/transcribe`, { method: 'POST' })
    message.success('已开始语音转文字')
    pollTranscript()
  } catch (e) {
    transcribing.value = false
    message.error(e.message)
  }
}

function pollTranscript() {
  clearTranscribePoll()
  let tries = 0
  transcribeTimer = setInterval(async () => {
    tries += 1
    try {
      const d = await api('/api/videos/' + editing.value.id)
      const t = d.transcript
      if (t && t.transcript_text) {
        editing.value.transcriptText = t.transcript_text
        clearTranscribePoll()
        transcribing.value = false
        message.success('语音转文字完成')
      } else if (t && t.asr_status === 'failed') {
        clearTranscribePoll()
        transcribing.value = false
        message.error('语音转文字失败，请重试')
      } else if (tries > 200) {
        clearTranscribePoll()
        transcribing.value = false
        message.warning('仍在识别中，完成后右上角会提醒，可刷新查看')
      }
    } catch (e) {
      /* 轮询期间网络抖动则继续 */
    }
  }, 5000)
}

function closeEdit() {
  editPane.value = 'edit'
  clearTranscribePoll()
  transcribing.value = false
  showEdit.value = false
  editing.value = null
  orig.value = null
  linkedDrafts.value = []
}

async function saveEdit() {
  const o = orig.value
  if (!o) return
  const body = {}
  if ((editing.value.title || '') !== (o.title || '')) body.title = editing.value.title || ''
  if (arrKey(editing.value.platforms) !== arrKey(o.platforms)) body.platforms = editing.value.platforms || []
  if (editing.value.status !== o.status) body.status = editing.value.status
  if (editing.value.is_ad !== o.is_ad) body.is_ad = editing.value.is_ad
  if ((editing.value.plannedTs || null) !== o.plannedTs) body.planned_publish_at = tsLocal(editing.value.plannedTs)
  if ((editing.value.publishedTs || null) !== o.publishedTs) body.published_at = tsLocal(editing.value.publishedTs)
  if (tagsText.value !== o.tagsText) {
    const known5 = ['求职', '面试', '赚钱', '知识', '其他']
    const parts = tagsText.value.split(/[,，]/).map(x => x.trim()).filter(Boolean)
    body.main_topics = parts.filter(x => known5.includes(x))
    body.tags = parts.filter(x => !known5.includes(x))
  }
  if (editing.value.sourceText !== o.sourceText) body.source_text = editing.value.sourceText || null
  if ((editing.value.adPrice ?? null) !== (o.adPrice ?? null)) body.ad_price = editing.value.adPrice == null ? null : Number(editing.value.adPrice)
  try {
    await api('/api/videos/' + editing.value.id, { method: 'PATCH', body: JSON.stringify(body) })
    try {
      await applyLinks()
    } catch (e) {
      message.warning('已保存，但平台链接绑定失败：' + e.message)
    }
    message.success('已保存')
    closeEdit()
    await loadQuiet()
    await loadWorksQuiet()
  } catch (e) {
    message.error(e.message)
  }
}

async function initLoad() {
  // 首屏：本地素材 + 云端作品并行拉取，全部到齐后再渲染一次（避免先显示一两条再补齐）
  loading.value = true
  worksLoading.value = true
  try {
    const [vs, ws] = await Promise.all([fetchVideos(), fetchWorks()])
    videos.value = vs
    works.value = ws
    buildCards()
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
    worksLoading.value = false
  }
}

async function loadWorks() {
  worksLoading.value = true
  try {
    works.value = await fetchWorks()
    buildCards()
  } catch (e) {
    works.value = []
  } finally {
    worksLoading.value = false
  }
}

const allTags = computed(() => {
  const set = new Set()
  cards.value.forEach(c => (c.tags || []).forEach(t => set.add(t)))
  return [...set].sort().map(t => ({ label: t, value: t }))
})

const applied = ref({ kw: '', plats: [], tags: [], ad: null, status: null, likesMin: null, likesMax: null })
const likesMin = ref(null)
const likesMax = ref(null)

function applyFilters() {
  applied.value = {
    kw: (searchText.value || '').trim(),
    plats: [...(platformSel.value || [])],
    tags: [...(tagSel.value || [])],
    ad: adFilter.value,
    status: filter.value.status,
    likesMin: likesMin.value,
    likesMax: likesMax.value
  }
}

const filteredCards = computed(() => {
  const a = applied.value
  return cards.value.filter(c => {
    if (a.kw && !(c.title || '').toLowerCase().includes(a.kw.toLowerCase())) return false
    if (a.status && c.status !== a.status) return false
    if (a.ad === 'ad' && !c.is_ad) return false
    if (a.ad === 'no' && c.is_ad) return false
    if (a.plats.length && !a.plats.some(x => (c.platforms || []).includes(x))) return false
    if (a.tags.length && !a.tags.every(x => (c.tags || []).includes(x))) return false
    const likeLo = a.likesMin
    const likeHi = a.likesMax
    if (likeLo != null || likeHi != null) {
      // 取该素材各平台最新点赞；任一平台落在区间内即命中
      const likes = (c.cloudPosts || [])
        .map(x => (x.latest_stat && x.latest_stat.likes != null) ? Number(x.latest_stat.likes) : null)
        .filter(v => v != null)
      if (!likes.some(v => (likeLo == null || v >= likeLo) && (likeHi == null || v <= likeHi))) return false
    }
    return true
  })
})

function buildCards() {
  // 云端已绑定本地素材(转素材后)的记录不重复展示，避免合并后多个素材
  const linkedLocal = new Set()
  const cloudWorks = works.value || []
  cloudWorks.forEach(w => {
    const wPosts = w.posts || []
    wPosts.forEach(pst => { if (pst.local_video_id) linkedLocal.add(pst.local_video_id) })
  })
  const local = videos.value.filter(v => !linkedLocal.has(v.id)).map(v => ({
    key: 'v' + v.id,
    kind: 'local',
    id: v.id,
    title: v.title || v.filename || '',
    cover_url: v.cover_url || '',
    platforms: v.platforms || [],
    main_topics: v.main_topics || [],
    is_ad: v.is_ad,
    ad_price: v.ad_price == null ? null : Number(v.ad_price),
    tags: v.tags || [],
    status: v.status,
    planned_publish_at: v.planned_publish_at,
    published_at: v.published_at,
    filename: v.filename,
    tags_confirmed: v.tags_confirmed,
    platform_post_id: v.platform_post_id,
    date: (v.published_at || v.planned_publish_at || v.created_at || '').slice(0, 10)
  }))
  const cloud = (works.value || []).map(w => {
    const anyLocal = (w.posts || []).find(x => x.local_video_id)
    const tags = []
    const wPosts = w.posts || []
    wPosts.forEach(x => {
      const xTags = x.tags || []
      xTags.forEach(t => { if (t && !tags.includes(t)) tags.push(t) })
    })
    return {
      key: (w.type === 'work' ? 'w' : 'p') + w.id,
      kind: 'cloud',
      id: w.id,
      type: w.type,
      title: w.title || '（无标题）',
      cover_url: w.cover || '',
      tags,
      platforms: w.platforms || [],
      main_topics: [],
      status: 'published',
      is_ad: (w.posts || []).some(x => x.is_ad),
      ad_price: (() => { const arr = (w.posts || []).filter(x => x.ad_price != null).map(x => x.ad_price); return arr.length ? Math.max(...arr) : null })(),
      merged: w.type === 'work' ? (w.posts || []).length : 0,
      cloudPosts: w.posts || [],
      local_video_id: anyLocal ? anyLocal.local_video_id : null,
      pub: ((w.posts || [])[0] && (w.posts[0].publish_time || '')).slice(0, 10) || '',
      date: (((w.posts || [])[0] && (w.posts[0].publish_time || '')) || '').slice(0, 10)
    }
  })
  cards.value = [...local, ...cloud].sort((a, b) => (b.date < a.date ? -1 : 1))
}

function openItem(it) {
  if (it.kind === 'cloud') {
    if (it.local_video_id) {
      goLocal(it.local_video_id)
      return
    }
    openCloud(it)
  } else openEdit(it)
}

function onCardClick(it) {
  if (mergeMode.value && it.kind === 'cloud') toggleSel(it)
  else openItem(it)
}

function openCloud(it) {
  cloudItem.value = it
  cloudFile.value = null
  cloudText.value = ''
  cloudTab.value = 'local'
  const posts = it.cloudPosts || []
  cloudAd.value = posts.some(x => x.is_ad)
  const priced = posts.filter(x => x.ad_price != null).map(x => x.ad_price)
  cloudPrice.value = priced.length ? Math.max(...priced) : null
  showCloud.value = true
}

async function saveCloudMeta() {
  if (!cloudItem.value) return
  cloudMetaSaving.value = true
  try {
    const body = { is_ad: cloudAd.value, ad_price: cloudPrice.value == null ? null : Number(cloudPrice.value) }
    if (cloudItem.value.type === 'work') body.work_id = cloudItem.value.id
    else body.post_id = cloudItem.value.id
    await api('/api/works/meta', { method: 'POST', body: JSON.stringify(body) })
    message.success('广告设置已保存')
    await loadWorks()
  } catch (e) {
    message.error(e.message)
  } finally {
    cloudMetaSaving.value = false
  }
}

function onCloudFile(f) {
  cloudFile.value = f || null
}

async function goLocal(id) {
  let v = videos.value.find(x => x.id === id)
  if (!v) {
    try {
      v = await api('/api/videos/' + id)
    } catch {
      v = null
    }
  }
  if (v) openEdit(v)
  else {
    message.warning('本地素材不存在或已删除')
    await load()
  }
}

async function saveCloudLocal(transcribe = false) {
  if (!cloudItem.value) return
  if (transcribe && !cloudFile.value) {
    message.warning('请先选择视频文件，再「保存并语音转文字」')
    return
  }
  cloudSaving.value = true
  try {
    const fd = new FormData()
    if (cloudFile.value) fd.append('file', cloudFile.value)
    if (cloudText.value) fd.append('text', cloudText.value)
    if (cloudItem.value.type === 'work') fd.append('work_id', String(cloudItem.value.id))
    else fd.append('post_id', String(cloudItem.value.id))
    const resp = await fetch('/api/works/to-local', {
      method: 'POST',
      headers: { 'X-Access-Token': getToken() },
      body: fd
    })
    if (!resp.ok) {
      let detail = resp.statusText
      try { detail = (await resp.json()).detail || detail } catch (e) { detail = detail || e.message }
      throw new Error(detail)
    }
    const r = await resp.json()
    message.success(cloudFile.value ? '已转为本地素材（可到编辑页「语音转文字」）' : '已转为本地素材（可继续编辑）')
    showCloud.value = false
    await loadQuiet()
    await loadWorksQuiet()
    if (r.video_id) {
      const v = videos.value.find(x => x.id === r.video_id)
      if (v) {
        await openEdit(v)
        if (transcribe) await startTranscribe()
      }
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    cloudSaving.value = false
  }
}

function openWorkDetail(w) {
  message.info('同一作品：' + (w.platforms || []).map(platformName).join(' / '))
}

function toggleSel(w) {
  const key = w.key || w.id
  const next = new Set(selected.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selected.value = next
}

function cancelMerge() {
  mergeMode.value = false
  selected.value = new Set()
}

async function doMerge() {
  const ids = [...selected.value]
  if (ids.length < 2) return
  try {
    await api('/api/works/merge', { method: 'POST', body: JSON.stringify({ platform_post_ids: ids }) })
    message.success('已合并为同一作品')
    cancelMerge()
    loadWorks()
  } catch (e) {
    message.error(e.message)
  }
}

async function splitWork(w) {
  try {
    await api(`/api/works/${w.id}/split`, { method: 'POST', body: JSON.stringify({ platform_post_ids: [] }) })
    message.success('已拆分')
    loadWorks()
  } catch (e) {
    message.error(e.message)
  }
}

async function syncCloudPost(pst) {
  syncingPost.value = pst.id
  try {
    await api(`/api/platform/posts/${pst.id}/sync`, { method: 'POST' })
    message.success('已同步 ' + platformName(pst.platform))
    loadWorks()
  } catch (e) {
    message.error(e.message)
  } finally {
    syncingPost.value = 0
  }
}

async function syncData(v) {
  syncing.value = v.id
  try {
    const r = await api(`/api/platform/videos/${v.id}/sync`, { method: 'POST' })
    message.success(r.message || '同步完成')
  } catch (e) {
    message.error(e.message)
  } finally {
    syncing.value = 0
  }
}

async function confirmTags(v) {
  await api(`/api/videos/${v.id}/confirm-tags`, { method: 'POST', body: JSON.stringify({ tags_confirmed: true }) })
  message.success('标签已确认')
  load()
}

async function autoMergeAll() {
  autoMerging.value = true
  try {
    const r = await api('/api/works/auto-merge', { method: 'POST', body: '{}' })
    if (r.merged_groups > 0) message.success(`自动合并完成：合并了 ${r.merged_groups} 组同标题作品`)
    else message.info('没有需要合并的同标题作品（同标题会自动识别为同一作品）')
    await loadWorks()
    await load()
  } catch (e) {
    message.error(e.message)
  } finally {
    autoMerging.value = false
  }
}

async function doMergeCloud() {
  const keys = [...selected.value]
  const ids = []
  cards.value.forEach(c => {
    if (c.kind === 'cloud' && keys.includes(c.key)) {
      (c.cloudPosts || []).forEach(x => ids.push(x.id))
    }
  })
  const uniq = [...new Set(ids)]
  if (uniq.length < 2) {
    message.warning('请选择至少 2 个云端素材')
    return
  }
  try {
    await api('/api/works/merge', { method: 'POST', body: JSON.stringify({ platform_post_ids: uniq }) })
    message.success('已合并为同一作品')
    cancelMerge()
    await loadWorks()
  } catch (e) {
    message.error(e.message)
  }
}

function delLocal(it) {
  dialog.warning({
    title: '删除素材',
    content: `确定删除「${it.title || it.filename}」？会删除本地记录与文件，不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api(`/api/videos/${it.id}`, { method: 'DELETE' })
        message.success('已删除')
        await load()
        await loadWorks()
      } catch (e) {
        message.error(e.message)
      }
    }
  })
}

function delCloud(it) {
  const kind = it.type === 'work' ? 'work' : 'post'
  dialog.warning({
    title: '删除云端素材',
    content: `确定删除「${it.title}」？会删除该${kind === 'work' ? '合并作品及其所有平台记录' : '平台记录'}。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api(`/api/works/${it.id}?kind=${kind}`, { method: 'DELETE' })
        message.success('已删除')
        await loadWorks()
      } catch (e) {
        message.error(e.message)
      }
    }
  })
}

onMounted(async () => {
  await initLoad()
  const m = location.hash.match(/edit=(\d+)/)
  const pm = location.hash.match(/post=(\d+)/)
  if (m) {
    const v = videos.value.find(x => x.id === Number(m[1]))
    if (v) openEdit(v)
  } else if (pm) {
    const pid = Number(pm[1])
    const card = cards.value.find(c => c.kind === 'cloud' && (c.cloudPosts || []).some(x => x.id === pid))
    if (card) openCloud(card)
    else message.info('未在当前素材库找到该云端作品（可能属于对标博主）')
  }
})
</script>

<style scoped>
.work-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}
@media (max-width: 1100px) { .work-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 820px) { .work-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 480px) { .work-grid { grid-template-columns: 1fr; } }
.work-card {
  background: #fffdfa;
  border: 1px solid #eee5d8;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.work-card.sel { border-color: #a34f2c88; }
.work-cover {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #efe6d9;
  color: #a34f2c;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  cursor: pointer;
  overflow: hidden;
}
.work-cover img { width: 100%; height: 100%; object-fit: cover; }
.work-sel { position: absolute; top: 6px; left: 6px; }
.work-body { padding: 6px 6px 8px; min-width: 0; }
.work-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  font-size: 14px;
}
.plat-stat b {
  color: #a34f2c;
}


.plat-tag {
  flex: 0 0 58px;
  text-align: center;
  padding: 3px 0;
  border-radius: 6px;
  color: #a34f2c;
  font-size: 12px;
  font-weight: 600;
  background: rgba(163, 79, 44, 0.08);
}



/* 筛选栏：控件与提示文案字号调小 */
.toolbar { font-size: 12px; }
.toolbar .muted { font-size: 11px; }
.toolbar :deep(.n-input),
.toolbar :deep(.n-input-number),
.toolbar :deep(.n-select) {
  --n-font-size: 12px;
}


.tl-hint {
  font-size: 11px;
  opacity: 0.7;
}
.toolbar :deep(.n-base-selection-placeholder),
.toolbar :deep(input::placeholder),
.toolbar :deep(textarea::placeholder) {
  font-size: 11px;
}


.grid-videos {
  align-items: stretch;
}
</style>
