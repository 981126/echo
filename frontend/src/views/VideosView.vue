<template>
  <div class="page">
    <h1 class="page-title">素材库</h1>

    <div class="panel row">
      <input ref="fileInput" type="file" accept="video/*" class="file-hidden" @change="onFile" />
      <n-button secondary @click="fileInput && fileInput.click()">选择视频文件</n-button>
      <span v-if="file" class="muted grow">{{ file.name }}</span>
      <span v-else class="muted grow">或拖入 data/inbox 自动入库</span>
      <n-button type="primary" :disabled="!file" :loading="uploading" @click="doUpload">
        {{ uploading ? '上传中…' : '上传' }}
      </n-button>
    </div>

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
      <div v-for="it in filteredCards" :key="it.key" class="card-tile" :class="{ picking: mergeMode && it.kind === 'cloud' }" @click="onCardClick(it)">
        <div class="tile-cover" :class="{ has: it.cover_url }" @click.stop="onCardClick(it)">
          <n-checkbox v-if="mergeMode && it.kind === 'cloud'" class="pick-box" :checked="selected.has(it.key)" @click.stop @update:checked="toggleSel(it)" />
          <img v-if="it.cover_url" :src="it.cover_url" alt="封面" />
          <span v-else>ECHO</span>
        </div>
        <div class="row" style="gap: 4px; margin-top: 6px; flex-wrap: wrap">
          <n-tag v-if="it.kind === 'cloud'" size="small" type="info" :bordered="false" round>云端</n-tag>
          <n-tag v-if="it.kind === 'cloud'" size="small" type="success" :bordered="false" round>已发布</n-tag>
          <n-tag v-if="it.kind === 'cloud' && it.merged" size="tiny" type="success" :bordered="false" round>合并×{{ it.merged }}</n-tag>
          <n-tag v-if="it.is_ad" size="small" :bordered="false" round type="error">广告{{ it.ad_price ? ' ¥' + it.ad_price : '' }}</n-tag>
          <n-tag v-for="t in it.main_topics || []" :key="t" size="small" :bordered="false" round type="info">{{ t }}</n-tag>
        </div>
        <h3 class="tile-title" :title="it.title">{{ it.title }}</h3>

        <template v-if="it.kind === 'local'">
          <div class="tag-row">
            <template v-for="t in it.tags.slice(0, 5)" :key="t">
              <n-tag size="small" :bordered="false">{{ t }}</n-tag>
            </template>
            <n-tag v-if="it.tags.length > 5" size="small" :bordered="false" round>… +{{ it.tags.length - 5 }}</n-tag>
            <span v-if="!it.tags.length" class="muted">无标签</span>
          </div>
          <p class="tile-meta">
            {{ it.status === 'published' ? '已发布' : '计划中' }}
            <template v-if="it.planned_publish_at"> · 计划 {{ fmt(it.planned_publish_at) }}</template>
            <template v-if="it.published_at"> · 发布 {{ fmt(it.published_at) }}</template>
          </p>
          <div class="row-actions" @click.stop>
            <n-tag v-if="it.platform_post_id" size="tiny" type="success" :bordered="false" round>已绑定作品</n-tag>
            <n-button v-if="it.platform_post_id" size="tiny" secondary :loading="syncing === it.id" @click="syncData(it)">同步数据</n-button>
            <n-button v-if="!it.tags_confirmed" size="tiny" secondary @click="confirmTags(it)">确认标签</n-button>
            <n-button size="tiny" quaternary type="error" @click="delLocal(it)">删除</n-button>
          </div>
        </template>

        <template v-else>
          <div class="row tag-row" style="gap: 4px; margin-top: 6px; flex-wrap: wrap; overflow: hidden">
            <template v-for="t in it.tags.slice(0, 5)" :key="t">
              <n-tag size="tiny" :bordered="false" round>{{ t }}</n-tag>
            </template>
            <n-tag v-if="it.tags.length > 5" size="tiny" :bordered="false" round>… +{{ it.tags.length - 5 }}</n-tag>
          </div>
          <div class="plat-zone">
            <div v-for="p in platOrder" :key="p" class="plat-line" :class="{ empty: !platOf(it, p) }">
              <template v-if="platOf(it, p)">
                <b>{{ platformName(p) }}</b>
                <template v-if="platOf(it, p).latest_stat">
                  <span>播放 {{ platOf(it, p).latest_stat.plays ? fmtNum(platOf(it, p).latest_stat.plays) : '—' }}</span>
                  <span>赞 {{ fmtNum(platOf(it, p).latest_stat.likes) }}</span>
                  <span>藏 {{ fmtNum(platOf(it, p).latest_stat.favorites) }}</span>
                  <span>评 {{ fmtNum(platOf(it, p).latest_stat.comments) }}</span>
                </template>
                <span v-else class="muted">暂无指标</span>
              </template>
            </div>
          </div>
          <p v-if="it.pub" class="tile-meta">发布时间 {{ it.pub }}</p>
          <div class="row-actions" @click.stop>
            <n-button size="tiny" secondary :loading="syncingPost === it.cloudPosts[0].id" @click="syncCloudPost(it.cloudPosts[0])">同步数据</n-button>
            <n-button v-if="it.merged >= 2" size="tiny" quaternary type="warning" @click="splitWork(it)">拆分</n-button>
                        <n-button size="tiny" quaternary type="error" @click="delCloud(it)">删除</n-button>
          </div>
        </template>
      </div>
    </div>

    <n-modal
      v-model:show="showEdit"
      preset="card"
      :title="editing ? '编辑：' + editing.filename : '编辑视频'"
      style="width: min(760px, 94vw)"
      :mask-closable="false"
      @close="closeEdit"
    >
      <div v-if="editing" style="max-height: 72vh; overflow-y: auto; padding-right: 6px">
        <n-tabs v-model:value="editPane" type="line" size="small" animated @update:value="onEditPane">
          <n-tab-pane name="edit" tab="编辑信息">
        <div class="form-item">
          <label class="form-label">标题</label>
          <n-input v-model:value="editing.title" placeholder="视频标题（选题标题）" />
        </div>
        <div class="form-item">
          <label class="form-label">平台链接（用于同步数据，可手动填写）</label>
          <div style="display: flex; flex-direction: column; gap: 8px">
            <div v-for="p in linkPlatforms" :key="p" class="row" style="gap: 8px; align-items: center">
              <span class="plat-tag">{{ platformName(p) }}</span>
              <n-input v-model:value="editing.links[p]" :placeholder="'粘贴' + platformName(p) + '作品链接'" clearable />
            </div>
          </div>
          <span class="muted" style="font-size: 12px">填了哪个平台就同步哪个；已绑定的会自动带出。保存后点「同步数据」拉取最新数据</span>
        </div>
        <div class="row" style="gap: 18px; align-items: flex-start; margin-bottom: 14px">
          <div class="cover-edit" @click="coverInput && coverInput.click()">
            <img v-if="editing.coverUrl" :src="editing.coverUrl" alt="封面" />
            <span v-else>上传封面</span>
          </div>
          <input ref="coverInput" type="file" accept="image/jpeg,image/png" class="file-hidden" @change="onCover" />
          <div class="grow muted" style="font-size: 12px">
            <div style="margin-top: 4px">jpg / png，点击图片上传或替换</div>
            <n-button v-if="editing.coverUrl" size="tiny" quaternary type="error" style="margin-top: 8px" @click="removeCover">
              移除封面
            </n-button>
          </div>
        </div>

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

        <div class="form-grid">
          <div class="form-item">
            <label class="form-label">平台（可多选）</label>
            <n-select v-model:value="editing.platforms" multiple :options="platformOptions" placeholder="选择平台" />
          </div>
          <div class="form-item">
            <label class="form-label">状态</label>
            <n-select v-model:value="editing.status" :options="statusOptions" />
          </div>
          <div class="form-item">
            <label class="form-label">商务广告</label>
            <n-checkbox v-model:checked="editing.is_ad">广告（不参与人设学习）</n-checkbox>
          </div>
          <div class="form-item">
            <label class="form-label">广告价格（元）</label>
            <n-input-number v-model:value="editing.adPrice" :min="0" placeholder="0" style="width: 100%" />
          </div>
          <div class="form-item">
            <label class="form-label">计划发布时间</label>
            <n-date-picker v-model:value="editing.plannedTs" type="datetime" clearable style="width: 100%" />
          </div>
          <div class="form-item">
            <label class="form-label">实际发布时间</label>
            <n-date-picker v-model:value="editing.publishedTs" type="datetime" clearable style="width: 100%" />
          </div>
          <div class="form-item full">
            <label class="form-label">标签（逗号分隔，自由填写）</label>
            <n-input v-model:value="tagsText" placeholder="干货, 反常识, 口播, 面试, 赚钱" />
            <span class="muted" style="font-size: 12px">命中 求职/面试/赚钱/知识/其他 的词会同时进入数据统计（复盘/缺口用）</span>
          </div>
          <div v-if="editing.filename" class="form-item full">
            <label class="form-label">语音转文字（阿里云 ASR）</label>
            <div class="row" style="gap: 8px; align-items: center; flex-wrap: wrap">
              <n-button
                v-if="!editing.transcriptText"
                secondary
                :loading="transcribing"
                @click="startTranscribe"
              >{{ transcribing ? '识别中…' : '开始转写' }}</n-button>
              <n-tag v-if="editing.transcriptText" size="small" type="success" :bordered="false" round>已转写</n-tag>
              <span v-if="transcribing" class="muted">后台识别中，完成后会提醒并自动展示在下方</span>
              <span v-else-if="!editing.transcriptText" class="muted">上传视频不会自动转写，点按钮把语音转成文字</span>
            </div>
          </div>
          <div class="form-item full" v-if="editing.transcriptText">
            <label class="form-label">ASR 转写（只读）</label>
            <div class="prose panel" style="margin-bottom: 0; background: var(--bg)">
              <p style="white-space: pre-wrap">{{ editing.transcriptText }}</p>
            </div>
          </div>
          <div class="form-item full">
            <label class="form-label">原始文案（可选）</label>
            <n-input v-model:value="editing.sourceText" type="textarea" :rows="3" placeholder="与口播可能不一致" />
          </div>
        </div>
        <div class="row" style="gap: 8px">
          <n-button secondary :loading="syncingEdit" @click="syncEditLinks">同步数据</n-button>
          <div class="grow" />
          <n-button type="primary" @click="saveEdit">保存</n-button>
          <n-button secondary @click="closeEdit">取消</n-button>
        </div>
          </n-tab-pane>
          <n-tab-pane name="comments" tab="评论数据">
            <div v-if="!editing.platformPosts || !editing.platformPosts.length" class="muted" style="padding: 14px 0">
              该素材还没绑定平台作品。先在「编辑信息」里填平台链接并保存，即可查看各平台评论
            </div>
            <div v-else style="display: flex; flex-direction: column; gap: 8px">
              <div v-for="pst in editing.platformPosts" :key="pst.post_id" class="comment-block">
                <div class="row" style="gap: 6px; align-items: center; flex-wrap: wrap">
                  <b>{{ platformName(pst.platform) }}</b>
                  <n-button size="tiny" secondary :loading="commentsLoading === pst.post_id" @click="refreshComments({ id: pst.post_id, platform: pst.platform })">加载评论</n-button>
                  <span v-if="(commentsMap[pst.post_id] || []).length" class="muted">{{ commentsMap[pst.post_id].length }} 条</span>
                </div>
                <ul v-if="(commentsMap[pst.post_id] || []).length" class="comment-list">
                  <li v-for="(c, i) in commentsMap[pst.post_id]" :key="i">{{ c }}</li>
                </ul>
                <p v-else class="muted" style="margin: 6px 0 0; font-size: 12px">暂无本地评论，点「加载评论」实时拉取并入库</p>
              </div>
            </div>
          </n-tab-pane>
        </n-tabs>
      </div>

    </n-modal>
    <n-modal v-model:show="showCloud" preset="card" :title="'转本地素材：' + (cloudItem && cloudItem.title || '')" style="width: min(620px, 94vw)">
      <div v-if="cloudItem" style="max-height: 70vh; overflow-y: auto; padding-right: 4px">
        <n-tabs v-model:value="cloudTab" type="line" animated @update:value="onCloudTab">
          <n-tab-pane name="local" tab="转本地素材">
            <div class="form-item">
              <label class="form-label">上传视频（可选；选后可一键「保存并语音转文字」）</label>
              <div class="row" style="gap: 8px">
                <input ref="cloudFileInput" type="file" accept="video/*" class="file-hidden" @change="onCloudFile" />
                <n-button secondary @click="cloudFileInput && cloudFileInput.click()">选择视频文件</n-button>
                <span v-if="cloudFile" class="muted grow">{{ cloudFile.name }}</span>
              </div>
            </div>
            <div class="form-item">
              <label class="form-label">文案 / 原始文字（可选）</label>
              <n-input v-model:value="cloudText" type="textarea" :rows="5" placeholder="粘贴你的口播文案或字幕，转本地素材后可用于 AI 学习" />
            </div>
            <div class="form-item">
              <label class="form-label">商务广告</label>
              <n-checkbox v-model:checked="cloudAd">广告（不参与人设学习）</n-checkbox>
            </div>
            <div class="form-item">
              <label class="form-label">广告价格（元）</label>
              <n-input-number v-model:value="cloudPrice" :min="0" style="width: 100%" />
            </div>
            <p class="muted" style="font-size: 12px">
              保存后此作品会出现在素材库（云端标识去掉），可继续编辑平台/赛道/发布时间。
            </p>
            <div class="row" style="gap: 8px">
              <n-button secondary :loading="cloudMetaSaving" @click="saveCloudMeta">仅保存广告设置</n-button>
              <n-button secondary :loading="cloudSaving" @click="saveCloudLocal(false)">保存为本地素材</n-button>
              <n-button type="primary" :disabled="!cloudFile" :loading="cloudSaving" @click="saveCloudLocal(true)">保存并语音转文字</n-button>
              <n-button secondary @click="showCloud = false">取消</n-button>
            </div>
          </n-tab-pane>
          <n-tab-pane name="comments" tab="评论数据">
            <div v-if="!(cloudItem.cloudPosts || []).length" class="empty">暂无平台记录</div>
            <div v-for="pst in cloudItem.cloudPosts || []" :key="pst.id" class="comment-block">
              <div class="row" style="gap: 6px; align-items: center; margin-top: 6px">
                <b>{{ platformName(pst.platform) }}</b>
                <n-button size="tiny" secondary :loading="commentsLoading === pst.id" @click="refreshComments(pst)">加载评论</n-button>
                <span v-if="(commentsMap[pst.id] || []).length" class="muted">{{ commentsMap[pst.id].length }} 条</span>
              </div>
              <ul v-if="(commentsMap[pst.id] || []).length" style="margin: 6px 0 0; padding-left: 1.2em; max-height: 180px; overflow-y: auto">
                <li v-for="(c, i) in commentsMap[pst.id]" :key="i" style="margin: 4px 0">{{ c }}</li>
              </ul>
            </div>
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

const message = useMessage()
const dialog = useDialog()
const topics = ['求职', '面试', '赚钱', '知识', '其他']
const videos = ref([])
const filter = ref({ status: null })
const adFilter = ref(null)
const adOptions = [
  { label: '广告', value: 'ad' },
  { label: '非广告', value: 'no' }
]
const platformSel = ref([])
const tagSel = ref([])
const loading = ref(false)
const uploading = ref(false)
const file = ref(null)
const fileInput = ref(null)
const coverInput = ref(null)
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
const cloudFileInput = ref(null)
const cloudAd = ref(false)
const cloudPrice = ref(null)
const cloudMetaSaving = ref(false)
const cloudTab = ref('local')
const commentsMap = ref({})
const commentsLoading = ref(0)
const mergeMode = ref(false)
const selected = ref(new Set())
const syncingPost = ref(0)
const autoMerging = ref(false)
const showEdit = ref(false)
const tagsText = ref('')

const platformOptions = [
  { label: '抖音', value: 'douyin' },
  { label: 'B站', value: 'bilibili' },
  { label: '小红书', value: 'xiaohongshu' }
]
const statusOptions = [
  { label: '计划中', value: 'planned' },
  { label: '已发布', value: 'published' }
]
const topicOptions = topics.map(t => ({ label: t, value: t }))
const PLATFORM_NAMES = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
const platformName = (p) => PLATFORM_NAMES[p] || p || ''

function fmt(v) {
  return v ? v.replace('T', ' ').slice(0, 16) : ''
}

function parseTs(v) {
  if (!v) return null
  const d = new Date(String(v).replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? null : d.getTime()
}

function tsLocal(ts) {
  if (!ts) return null
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function arrKey(arr) {
  return JSON.stringify([...(arr || [])].sort())
}

async function load() {
  loading.value = true
  try {
    const data = await api('/api/videos?limit=500')
    videos.value = data.items
    buildCards()
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function loadQuiet() {
  try {
    const data = await api('/api/videos?limit=500')
    videos.value = data.items
    buildCards()
  } catch (e) {
    /* 静默：后台刷新失败不打断当前编辑 */
  }
}

async function loadWorksQuiet() {
  try {
    const data = await api('/api/works')
    works.value = data.items || []
    buildCards()
  } catch (e) {
    /* 静默 */
  }
}

function onFile(e) {
  file.value = e.target.files[0] || null
}

async function doUpload() {
  if (!file.value) {
    message.warning('请先选择视频文件')
    return
  }
  uploading.value = true
  try {
    const r = await uploadVideo(file.value)
    message.success('上传成功')
    file.value = null
    if (fileInput.value) fileInput.value.value = ''
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

async function onCover(e) {
  const f = e.target.files[0]
  if (!f || !editing.value) return
  try {
    const r = await uploadCover(editing.value.id, f)
    editing.value.coverUrl = r.cover_url || null
    message.success('封面已更新')
    await loadQuiet()
  } catch (err) {
    message.error(err.message)
  } finally {
    if (coverInput.value) coverInput.value.value = ''
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
const platOrder = ['douyin', 'bilibili', 'xiaohongshu']
const syncingEdit = ref(false)
const editPane = ref('edit')

function platOf(card, platform) {
  return ((card && card.cloudPosts) || []).find(x => x.platform === platform) || null
}

function linksFromPlatform(platformLinks) {
  const out = { douyin: '', bilibili: '', xiaohongshu: '' }
  ;(platformLinks || []).forEach(x => {
    if (x && x.platform && x.platform in out && x.url) out[x.platform] = x.url
  })
  return out
}
function onEditPane(name) {
  if (name === 'comments') loadLocalComments()
}

function loadLocalComments() {
  const posts = (editing.value && editing.value.platformPosts) || []
  if (!posts.length) return
  posts.forEach(pst => loadComments({ id: pst.post_id, platform: pst.platform }))
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

function fmtNum(n) {
  n = Number(n || 0)
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return String(n)
}

async function initLoad() {
  // 首屏：本地素材 + 云端作品并行拉取，全部到齐后再渲染一次（避免先显示一两条再补齐）
  loading.value = true
  worksLoading.value = true
  try {
    const [vs, ws] = await Promise.all([
      api('/api/videos?limit=500'),
      api('/api/works')
    ])
    videos.value = vs.items || []
    works.value = ws.items || []
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
    const data = await api('/api/works')
    works.value = data.items || []
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
  commentsMap.value = {}
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

async function loadComments(pst) {
  try {
    const r = await api(`/api/platform/posts/${pst.id}/comments?limit=50`)
    commentsMap.value = { ...commentsMap.value, [pst.id]: r.items || [] }
  } catch (e) {
    /* 静默 */
  }
}

function onCloudTab(name) {
  if (name !== 'comments' || !cloudItem.value) return
  const posts = cloudItem.value.cloudPosts || []
  posts.forEach(pst => loadComments(pst))
}

async function refreshComments(pst) {
  commentsLoading.value = pst.id
  try {
    const r = await api(`/api/platform/posts/${pst.id}/comments/refresh`, { method: 'POST', body: '{}' })
    commentsMap.value = { ...commentsMap.value, [pst.id]: r.items || [] }
    message.success(r.added > 0 ? `已入库 ${r.added} 条新评论，共 ${(r.items || []).length} 条` : `已是最新（共 ${(r.items || []).length} 条）`)
  } catch (e) {
    message.error('评论拉取失败：' + e.message)
  } finally {
    commentsLoading.value = 0
  }
}

function onCloudFile(e) {
  cloudFile.value = e.target.files[0] || null
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
    if (cloudFileInput.value) cloudFileInput.value.value = ''
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
.plat-line {
  display: grid;
  grid-template-columns: 24px 54px 38px 36px 36px;
  gap: 0;
  align-items: baseline;
  white-space: nowrap;
  margin-top: 3px;
  font-size: 8px;
  color: #6f675c;
}
.plat-line b { color: #a34f2c; font-weight: 600; }
.plat-line span { overflow: hidden; text-overflow: ellipsis; }

.plat-stat b {
  color: #a34f2c;
}


.card-tile { position: relative; }
.tile-cover { position: relative; }
.card-tile.picking { cursor: pointer; }
.pick-box {
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 3;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 6px;
  padding: 2px;
}
.row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-height: 32px;
  margin-top: 8px;
}

.card-tile { display: flex; flex-direction: column; }
.row-actions { margin-top: auto; }

.tag-row {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 6px;
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


.comment-list {
  margin: 6px 0 0;
  padding-left: 1.2em;
  max-height: 180px;
  overflow-y: auto;
}
.comment-list li {
  margin: 4px 0;
  font-size: 13px;
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


.plat-zone {
  margin-top: 4px;
}
.plat-line.empty {
  visibility: hidden;
}
.plat-line {
  min-height: 12px;
}
.tile-meta {
  margin: 6px 0 0;
  font-size: 8px;
  line-height: 1.4;
  color: #6f675c;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}


.grid-videos {
  align-items: start;
}
.row-actions {
  margin-top: 8px;
  min-height: 24px;
}

</style>
