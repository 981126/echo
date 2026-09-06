<template>
  <div class="page">
    <h1 class="page-title">素材库</h1>

    <UploadVideoBar :uploading="uploading" @upload="doUpload" />

    <div class="toolbar">
      <n-select v-model:value="creatorSel" :options="creatorOptions" placeholder="博主（默认当前主博主）" style="width: 210px" @update:value="onCreatorChange" />
      <n-select multiple filterable v-model:value="platformSel" :options="platformOptions" placeholder="平台（可多选/输入过滤）" clearable style="width: 210px" />
      <n-select v-model:value="filter.status" :options="statusOptions" placeholder="状态" clearable style="width: 120px" />
      <n-select v-model:value="videoFilter" :options="videoOptions" placeholder="视频" clearable style="width: 120px" />
      <n-select v-model:value="adFilter" :options="adOptions" placeholder="广告" clearable style="width: 110px" />
      <n-input v-model:value="searchText" placeholder="搜索标题…" clearable style="width: 150px" />
      <n-select multiple filterable v-model:value="tagSel" :options="allTags" placeholder="标签（可多选/输入过滤）" clearable style="width: 230px" />
      <n-input-number v-model:value="likesMax" :min="0" placeholder="≤ 点赞" clearable style="width: 108px" />
      <n-input-number v-model:value="likesMin" :min="0" placeholder="≥ 点赞" clearable style="width: 108px" />
      <span class="muted tl-hint">任一平台匹配即可</span>
      <n-button type="primary" @click="applyFilters">查询</n-button>
      <n-button size="small" secondary :loading="autoMerging" @click="autoMergeAll">自动合并</n-button>
    </div>


    <div class="merge-float">
      <n-button v-if="!mergeMode" size="small" type="primary" secondary @click="mergeMode = true">多选</n-button>
      <template v-else>
        <span class="muted tl-hint">已选 {{ selected.size }} 项</span>
        <n-button size="small" type="primary" :disabled="batchBusy || cloudCount < 2" :loading="batchBusy && batchAction === 'merge'" @click="doMergeCloud">合并所选</n-button>
        <n-button size="small" secondary :disabled="batchBusy || !selected.size" :loading="batchBusy && batchAction === 'sync'" @click="doBatchSync">同步所选</n-button>
        <n-button size="small" type="error" secondary :disabled="batchBusy || !selected.size" :loading="batchBusy && batchAction === 'delete'" @click="doBatchDelete">删除所选</n-button>
        <n-button size="small" secondary :disabled="batchBusy" @click="cancelMerge">取消</n-button>
      </template>
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
        :progress="cardProgress[it.key] || 0"
        :note="cardNote[it.key] || ''"
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
        <LocalVideoControl
          :has-file="!!editing.filename && !isPlaceholderFile(editing.filename)"
          :file-name="editing.filename"
          :uploading="videoUploading"
          @upload="onAttachVideo"
          @remove="onRemoveVideo"
        />

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
          :is-ad="editing.is_ad"
          :ad-price="editing.adPrice"
          :planned-ts="editing.plannedTs"
          :published-ts="editing.publishedTs"
          @update:platforms="v => (editing.platforms = v)"
          @update:status="v => (editing.status = v)"
          @update:isAd="v => (editing.is_ad = v)"
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
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import { api, uploadVideo, uploadVideoFile, uploadCover, getToken } from '../api'
import MediaComments from '../components/MediaComments.vue'
import UploadVideoBar from '../components/UploadVideoBar.vue'
import MaterialCard from '../components/MaterialCard.vue'
import CoverEditor from '../components/CoverEditor.vue'
import LocalVideoControl from '../components/LocalVideoControl.vue'
import TranscribeSection from '../components/TranscribeSection.vue'
import PlatformLinksInput from '../components/PlatformLinksInput.vue'
import EditActions from '../components/EditActions.vue'
import TranscriptEditor from '../components/TranscriptEditor.vue'
import TagsInput from '../components/TagsInput.vue'
import MetaFields from '../components/MetaFields.vue'
import CloudVideoPicker from '../components/CloudVideoPicker.vue'
import CloudActions from '../components/CloudActions.vue'
import CloudTextArea from '../components/CloudTextArea.vue'
import { adOptions, platformOptions, statusOptions, videoOptions } from '../lib/options'
import { fetchVideos, fetchWorks } from '../composables/media'
import { platformName, parseTs, tsLocal, arrKey } from '../lib/format'
import { busOn } from '../lib/eventbus'

const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const router = useRouter()
let dataReady = false  // 深链等数据就绪后再打开弹窗
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
const creatorSel = ref(0)  // 博主筛选：0=当前主博主（R-076）
const creatorOptions = ref([])
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
const batchBusy = ref(false)
const batchAction = ref('')
const showEdit = ref(false)
const tagsText = ref('')

async function load() {
  loading.value = true
  try {
    videos.value = await fetchVideos(creatorSel.value)
    buildCards()
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function loadQuiet() {
  try {
    videos.value = await fetchVideos(creatorSel.value)
    buildCards()
  } catch (e) {
    /* 静默：后台刷新失败不打断当前编辑 */
  }
}

async function loadWorksQuiet() {
  try {
    works.value = await fetchWorks(creatorSel.value)
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

const videoUploading = ref(false)

async function onAttachVideo(f) {
  if (!f || !editing.value) return
  videoUploading.value = true
  try {
    const r = await uploadVideoFile(editing.value.id, f)
    editing.value.filename = r.filename || editing.value.filename
    message.success('视频已上传')
    await loadQuiet()
  } catch (e) {
    message.error(e.message)
  } finally {
    videoUploading.value = false
  }
}

async function onRemoveVideo() {
  if (!editing.value) return
  try {
    const r = await api(`/api/videos/${editing.value.id}/video`, { method: 'DELETE' })
    editing.value.filename = r.filename || ''
    message.success('已删除视频文件')
    await loadQuiet()
  } catch (e) {
    message.error(e.message)
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
    message.success(applyMediaMsg(r, r.message || '同步完成'))
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
    const [vs, ws] = await Promise.all([fetchVideos(creatorSel.value), fetchWorks(creatorSel.value)])
    videos.value = vs
    works.value = ws
    buildCards()
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
    worksLoading.value = false
    dataReady = true
  }
}

async function loadWorks() {
  worksLoading.value = true
  try {
    works.value = await fetchWorks(creatorSel.value)
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
const videoFilter = ref('')
const FILTERS_KEY = 'echo:videos:filters.v1'  // R-084：切页/刷新后保留素材库筛选

function saveFilters() {
  try {
    localStorage.setItem(FILTERS_KEY, JSON.stringify({
      creatorSel: creatorSel.value,
      platformSel: platformSel.value || [],
      tagSel: tagSel.value || [],
      status: filter.value.status ?? null,
      ad: adFilter.value ?? null,
      video: videoFilter.value || '',
      kw: searchText.value || '',
      likesMin: likesMin.value ?? null,
      likesMax: likesMax.value ?? null
    }))
  } catch (e) { /* 存储失败忽略 */ }
}

function loadFilters() {
  try {
    const raw = localStorage.getItem(FILTERS_KEY)
    if (!raw) return
    const f = JSON.parse(raw) || {}
    if (typeof f.creatorSel === 'number' && f.creatorSel >= 0) creatorSel.value = f.creatorSel
    platformSel.value = Array.isArray(f.platformSel) ? f.platformSel : []
    tagSel.value = Array.isArray(f.tagSel) ? f.tagSel : []
    filter.value.status = f.status ?? null
    adFilter.value = f.ad ?? null
    videoFilter.value = f.video || ''
    searchText.value = f.kw || ''
    likesMin.value = f.likesMin ?? null
    likesMax.value = f.likesMax ?? null
  } catch (e) { /* 读取失败忽略 */ }
}

watch(
  [creatorSel, platformSel, tagSel, filter, adFilter, videoFilter, searchText, likesMin, likesMax],
  saveFilters,
  { deep: true }
)

function applyFilters() {
  applied.value = {
    kw: (searchText.value || '').trim(),
    plats: [...(platformSel.value || [])],
    tags: [...(tagSel.value || [])],
    ad: adFilter.value,
    status: filter.value.status,
    likesMin: likesMin.value,
    likesMax: likesMax.value,
    video: videoFilter.value
  }
}

const filteredCards = computed(() => {
  const a = applied.value
  return cards.value.filter(c => {
    if (a.kw && !(c.title || '').toLowerCase().includes(a.kw.toLowerCase())) return false
    if (a.status && c.status !== a.status) return false
    if (a.ad === 'ad' && !c.is_ad) return false
    if (a.ad === 'no' && c.is_ad) return false
    if (a.video === 'yes' && !c.hasVideo) return false
    if (a.video === 'no' && c.hasVideo) return false
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
  const videoById = new Map((videos.value || []).map(v => [v.id, v]))
  const realFile = (v) => {
    const f = v && v.filename
    return !!f && !f.startsWith('__cloud__')
  }

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
    hasVideo: realFile(v),
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
      hasVideo: realFile(videoById.get(anyLocal ? anyLocal.local_video_id : null)),
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
  if (mergeMode.value) toggleSel(it)
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
    fd.append('is_ad', cloudAd.value ? '1' : '0')
    fd.append('ad_price', cloudPrice.value == null ? '' : String(cloudPrice.value))
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

function toggleSel(w) {
  const key = w.key || w.id
  const next = new Set(selected.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selected.value = next
}

const selectedCards = computed(() => cards.value.filter(c => selected.value.has(c.key)))
const cloudCount = computed(() => selectedCards.value.filter(c => c.kind === 'cloud').length)

function cancelMerge() {
  mergeMode.value = false
  selected.value = new Set()
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

// R-080/R-081：卡片同步覆盖层——请求阶段本地过渡 + 媒体补齐后台任务实时进度/说明（切页回来可恢复）
const cardProgress = reactive({})
const cardNote = reactive({})
const cardRequestTimers = {}
const cardTaskPollers = {}
const cardTaskIds = {}
const cardTaskNotify = {}

function clearCardProgress(key) {
  clearInterval(cardRequestTimers[key]); delete cardRequestTimers[key]
  clearInterval(cardTaskPollers[key]); delete cardTaskPollers[key]
  delete cardTaskIds[key]
  delete cardProgress[key]
  delete cardNote[key]
}
function stopCardProgress(key, done = true) {
  clearInterval(cardRequestTimers[key]); delete cardRequestTimers[key]
  if (done) {
    cardProgress[key] = 100
    cardNote[key] = '同步完成'
    setTimeout(() => { clearCardProgress(key) }, 800)
  } else {
    clearCardProgress(key)
  }
}
function startRequestProgress(key) {
  stopCardProgress(key, false)
  cardProgress[key] = 5
  cardNote[key] = '数据/评论同步中…'
  cardRequestTimers[key] = setInterval(() => {
    const cur = cardProgress[key] ?? 0
    if (cur < 60) cardProgress[key] = cur + Math.max(0.5, (60 - cur) * 0.04)
  }, 200)
}
async function finishCardTask(key, t) {
  if (!cardTaskIds[key]) return  // 已结束，幂等
  const notify = !!cardTaskNotify[key]
  clearInterval(cardTaskPollers[key]); delete cardTaskPollers[key]
  delete cardTaskIds[key]; delete cardTaskNotify[key]
  if (t.status === 'done') {
    cardProgress[key] = 100
    cardNote[key] = '同步完成'
    setTimeout(() => { clearCardProgress(key) }, 800)
    if (notify) message.success('同步完成')
  } else {
    clearCardProgress(key)
    if (notify) message.warning('同步失败：' + (t.error || '请查看通知'))
  }
  await loadQuiet()
  await loadWorksQuiet()
}
function applyTaskState(key, t) {
  if (t.status === 'running' || t.status === 'pending') {
    cardProgress[key] = Math.max(cardProgress[key] || 2, Math.min(99, Number(t.progress) || 2))  // 不回退
    cardNote[key] = t.note || cardNote[key] || '同步中…'
    return false
  }
  return true
}
function handleTaskEvent(t) {
  const taskId = Number(t && t.id)
  if (!taskId) return
  let key = ''
  for (const k of Object.keys(cardTaskIds)) {
    if (cardTaskIds[k] === taskId) { key = k; break }
  }
  if (!key) {
    // R-089：事件带 payload → 可直接认领到卡片（博主页同步触发的媒体任务也能即时显示）
    if (t.status === 'done' || t.status === 'failed') return
    key = cardKeyForTask({ payload: t.payload || {} })
    if (!key) return
    showServerTask(key, taskId, false)
  }
  if (applyTaskState(key, t)) finishCardTask(key, t)
}
function pollCardTask(key, taskId, notify = false) {
  clearInterval(cardTaskPollers[key])
  cardTaskNotify[key] = notify
  const tick = async () => {
    if (!cardTaskIds[key]) return
    let t = null
    try {
      t = await api('/api/tasks/' + taskId)
    } catch (e) { /* 轮询抖动继续 */ }
    if (!t) return
    if (applyTaskState(key, t)) finishCardTask(key, t)
  }
  cardTaskPollers[key] = setInterval(tick, 5000)  // SSE 事件为主，轮询作兜底（断线仍能恢复）
  tick()
}
function showServerTask(key, taskId, notify = false) {
  // 只停本地过渡计时器，保留已有进度（进度单调不回退，R-089）
  clearInterval(cardRequestTimers[key]); delete cardRequestTimers[key]
  if (!(key in cardProgress)) cardProgress[key] = 2
  cardTaskIds[key] = taskId
  cardTaskNotify[key] = notify
  cardNote[key] = cardNote[key] || '同步中…'
  pollCardTask(key, taskId, notify)
}

// 任务 payload → 当前素材卡 key（切页回来/定期扫描恢复用）
function cardKeyForTask(t) {
  let pl = t && t.payload
  try {
    pl = typeof pl === 'string' ? JSON.parse(pl) : (pl || {})
  } catch (e) { return '' }
  for (const c of cards.value) {
    if (pl.video_id != null && c.kind === 'local' && c.id === Number(pl.video_id)) return c.key
    if (pl.work_id != null && c.kind === 'cloud' && c.type === 'work' && c.id === Number(pl.work_id)) return c.key
    if (pl.post_id != null && c.kind === 'cloud' && (c.cloudPosts || []).some(x => Number(x.id) === Number(pl.post_id))) return c.key
  }
  return ''
}
async function refreshActiveCardTasks() {
  let list = []
  try {
    list = await api('/api/tasks?status=running&kind=platform_media&limit=100')
  } catch (e) { return }
  for (const t of (list || [])) {
    const key = cardKeyForTask(t)
    if (!key) continue
    if (cardTaskIds[key] && cardTaskIds[key] !== t.id) continue  // 已有任务在跑，不重复覆盖
    if (!cardTaskIds[key]) showServerTask(key, t.id, true)
  }
}

function applyMediaMsg(r, baseMsg) {
  const m = r && r.media
  if (!m) return baseMsg
  if (m.status === 'skip') return baseMsg + '（已有视频与转写，跳过下载/转写）'
  if (m.status === 'started') return baseMsg + '（缺视频/转写，后台下载/转写中，进度见卡片）'
  return baseMsg
}

// R-077/R-080/R-081：单卡「同步」统一入口（请求阶段 + 后台媒体任务实时进度）
async function runCardSync(it) {
  const key = it.key
  startRequestProgress(key)
  try {
    let r
    if (it.kind === 'local') {
      syncing.value = key
      r = await api(`/api/platform/videos/${it.id}/sync`, { method: 'POST' })
    } else {
      syncingPost.value = key
      r = it.type === 'work'
        ? await api(`/api/platform/works/${it.id}/sync`, { method: 'POST' })
        : await api(`/api/platform/posts/${it.cloudPosts[0].id}/sync`, { method: 'POST' })
    }
    const m = r && r.media
    if (m && m.status === 'started' && m.task_id) {
      showServerTask(key, m.task_id, false)
    } else {
      stopCardProgress(key)
    }
    return r
  } catch (e) {
    stopCardProgress(key, false)
    throw e
  } finally {
    syncing.value = ''
    syncingPost.value = ''
  }
}

function syncMessage(r, fallback) {
  let m = (r && r.message) || fallback || '同步完成'
  const parts = []
  if (r && Array.isArray(r.platforms) && r.platforms.length && !/个平台/.test(m)) {
    parts.push(r.platforms.map(platformName).join('、'))
  }
  if (r && r.comments_added != null && r.comments_added > 0) parts.push('评论新增 ' + r.comments_added + ' 条')
  if (parts.length) m += '（' + parts.join('；') + '）'
  return m
}

async function syncCloudPost(it) {
  if (!it || !(it.cloudPosts || []).length) return
  try {
    // R-067：合并作品卡同步全部平台帖（不再只同步第一个平台），单平台帖走单条同步
    const r = await runCardSync(it)
    message.success(applyMediaMsg(r, syncMessage(r, '同步完成')))
    await loadWorks()
  } catch (e) {
    message.error(e.message)
  }
}

async function syncData(v) {
  try {
    const r = await runCardSync(v)
    message.success(applyMediaMsg(r, syncMessage(r, '同步完成')))
    await loadQuiet()  // R-067：同步后刷新本地素材卡，避免“只提示没变化”
    await loadWorksQuiet()
  } catch (e) {
    message.error(e.message)
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
  const clouds = selectedCards.value.filter(c => c.kind === 'cloud')
  const ids = []
  clouds.forEach(c => (c.cloudPosts || []).forEach(x => ids.push(x.id)))
  const uniq = [...new Set(ids)]
  if (uniq.length < 2) {
    message.warning('请选择至少 2 个云端素材')
    return
  }
  batchBusy.value = true
  batchAction.value = 'merge'
  try {
    await api('/api/works/merge', { method: 'POST', body: JSON.stringify({ platform_post_ids: uniq }) })
    message.success(`已合并 ${uniq.length} 条为同一作品`)
    cancelMerge()
    await loadWorks()
  } catch (e) {
    message.error(e.message)
  } finally {
    batchBusy.value = false
    batchAction.value = ''
  }
}

async function doBatchSync() {
  const list = selectedCards.value
  if (!list.length) return
  batchBusy.value = true
  batchAction.value = 'sync'
  let ok = 0
  const fails = []
  let mediaStarted = 0
  for (const it of list) {
    try {
      const r = await runCardSync(it)
      ok += 1
      if (r && r.media && r.media.status === 'started') mediaStarted += 1
    } catch (e) {
      fails.push((it.title || it.filename || '素材') + '：' + (e.message || '同步失败'))
    }
  }
  batchBusy.value = false
  batchAction.value = ''
  let msg = `已同步 ${ok} 张` + (fails.length ? `，失败 ${fails.length} 张` : '')
  if (mediaStarted) msg += `；其中 ${mediaStarted} 张开始下载/转写（完成后右上角提醒）`
  message[ok && !fails.length ? 'success' : 'warning'](msg)
  cancelMerge()
  await loadQuiet()
  await loadWorksQuiet()
  if (fails.length) fails.slice(0, 3).forEach(f => message.error(f))
}

async function doBatchDelete() {
  const list = selectedCards.value
  if (!list.length) return
  const locals = list.filter(c => c.kind === 'local')
  const clouds = list.filter(c => c.kind === 'cloud')
  const cloudNote = clouds.some(c => c.type === 'work') ? '，云端合并作品会连同其全部平台记录删除' : ''
  dialog.warning({
    title: '删除所选素材',
    content: `确定删除选中的 ${list.length} 个素材？本地 ${locals.length} 个会连同本地文件删除；云端 ${clouds.length} 个${cloudNote}。不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      batchBusy.value = true
      batchAction.value = 'delete'
      let ok = 0
      const fails = []
      for (const it of list) {
        try {
          if (it.kind === 'local') {
            await api(`/api/videos/${it.id}`, { method: 'DELETE' })
          } else {
            const kind = it.type === 'work' ? 'work' : 'post'
            await api(`/api/works/${it.id}?kind=${kind}`, { method: 'DELETE' })
          }
          ok += 1
        } catch (e) {
          fails.push((it.title || it.filename || '素材') + '：' + (e.message || '删除失败'))
        }
      }
      batchBusy.value = false
      batchAction.value = ''
      const msg = `已删除 ${ok} 个` + (fails.length ? `，失败 ${fails.length} 个` : '')
      message[ok && !fails.length ? 'success' : 'warning'](msg)
      cancelMerge()
      await load()
      await loadWorks()
      if (fails.length) fails.slice(0, 3).forEach(f => message.error(f))
    }
  })
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

// 深链处理：数据就绪后按 query 打开编辑/云端作品弹窗
function handleDeepLink() {
  if (!dataReady) return
  const editId = String(route.query.edit || '')
  const postId = String(route.query.post || '')
  if (editId) {
    const v = videos.value.find(x => x.id === Number(editId))
    if (v) openEdit(v)
    router.replace({ path: '/videos' })  // 清掉 query，保证再次点同一素材也能触发
  } else if (postId) {
    const pid = Number(postId)
    const card = cards.value.find(c => c.kind === 'cloud' && (c.cloudPosts || []).some(x => x.id === pid))
    if (card) openCloud(card)
    else message.info('未在当前素材库找到该云端作品（可能属于对标博主）')
    router.replace({ path: '/videos' })
  }
}

async function loadCreatorOptions() {
  try {
    const cs = await api('/api/creators')
    const opts = (cs || []).map(c => ({
      label: c.name + (c.kind === 'benchmark' ? '（对标）' : '') + (c.is_current ? '（当前主博主）' : ''),
      value: c.is_current ? 0 : c.id,
      current: !!c.is_current
    }))
    opts.sort((a, b) => Number(b.current) - Number(a.current))
    creatorOptions.value = opts
  } catch (e) {
    /* 拉取失败不阻塞素材库 */
  }
}

async function onCreatorChange() {
  // 切换博主：清空筛选回到该博主全量
  platformSel.value = []
  tagSel.value = []
  adFilter.value = null
  filter.value = { status: null }
  likesMin.value = null
  likesMax.value = null
  videoFilter.value = ''
  searchText.value = ''
  applyFilters()
  await initLoad()
}

watch(() => [route.query.edit, route.query.post], handleDeepLink)

let activeTasksTimer = null
let offTaskBus = null
onMounted(async () => {
  loadFilters()  // R-084：恢复上次筛选
  applyFilters()
  await loadCreatorOptions()
  await initLoad()
  handleDeepLink()
  offTaskBus = busOn('task.update', handleTaskEvent)  // R-087：SSE 任务进度/完成事件
  await refreshActiveCardTasks()
  activeTasksTimer = setInterval(refreshActiveCardTasks, 6000)  // R-081：切页回来/跨页触发的同步进度自动恢复
})
onUnmounted(() => {
  if (activeTasksTimer) {
    clearInterval(activeTasksTimer)
    activeTasksTimer = null
  }
  if (offTaskBus) offTaskBus()
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

</style>
