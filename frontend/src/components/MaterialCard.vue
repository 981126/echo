<template>
  <div class="card-tile" :class="{ picking: mergeMode && item.kind === 'cloud' }" @click="click(item)">
    <div class="tile-cover" :class="{ has: item.cover_url }" @click.stop="click(item)">
      <n-checkbox v-if="mergeMode && item.kind === 'cloud'" class="pick-box" :checked="selected" @click.stop @update:checked="toggle(item)" />
      <img v-if="item.cover_url" :src="item.cover_url" alt="封面" />
      <span v-else>ECHO</span>
    </div>
    <div class="row" style="gap: 4px; margin-top: 6px; flex-wrap: wrap">
      <n-tag v-if="item.kind === 'cloud'" size="small" type="info" :bordered="false" round>云端</n-tag>
      <n-tag v-if="item.kind === 'cloud'" size="small" type="success" :bordered="false" round>已发布</n-tag>
      <n-tag v-if="item.kind === 'cloud' && item.merged" size="tiny" type="success" :bordered="false" round>合并×{{ item.merged }}</n-tag>
      <n-tag v-if="item.is_ad" size="small" :bordered="false" round type="error">广告{{ item.ad_price ? ' ¥' + item.ad_price : '' }}</n-tag>
      <n-tag v-for="t in item.main_topics || []" :key="t" size="small" :bordered="false" round type="info">{{ t }}</n-tag>
    </div>
    <h3 class="tile-title" :title="item.title">{{ item.title }}</h3>

    <template v-if="item.kind === 'local'">
      <div class="tag-row">
        <template v-for="t in item.tags.slice(0, 5)" :key="t">
          <n-tag size="small" :bordered="false">{{ t }}</n-tag>
        </template>
        <n-tag v-if="item.tags.length > 5" size="small" :bordered="false" round>… +{{ item.tags.length - 5 }}</n-tag>
        <span v-if="!item.tags.length" class="muted">无标签</span>
      </div>
      <PlatformStats :posts="[]" />
      <p class="tile-meta">
        {{ item.status === 'published' ? '已发布' : '计划中' }}
        <template v-if="item.planned_publish_at"> · 计划 {{ fmt(item.planned_publish_at) }}</template>
        <template v-if="item.published_at"> · 发布 {{ fmt(item.published_at) }}</template>
      </p>
      <div class="row-actions" @click.stop>
        <n-tag v-if="item.platform_post_id" size="tiny" type="success" :bordered="false" round>已绑定作品</n-tag>
        <n-button v-if="item.platform_post_id" size="tiny" secondary :loading="syncingId === item.id" @click="syncLocal(item)">同步数据</n-button>
        <n-button v-if="!item.tags_confirmed" size="tiny" secondary @click="confirm(item)">确认标签</n-button>
        <n-button size="tiny" quaternary type="error" @click="delLocal(item)">删除</n-button>
      </div>
    </template>

    <template v-else>
      <div class="row tag-row" style="gap: 4px; margin-top: 6px; flex-wrap: wrap">
        <template v-for="t in item.tags.slice(0, 5)" :key="t">
          <n-tag size="tiny" :bordered="false" round>{{ t }}</n-tag>
        </template>
        <n-tag v-if="item.tags.length > 5" size="tiny" :bordered="false" round>… +{{ item.tags.length - 5 }}</n-tag>
      </div>
      <PlatformStats :posts="item.cloudPosts || []" />
      <p v-if="item.pub" class="tile-meta">发布时间 {{ item.pub }}</p>
      <div class="row-actions" @click.stop>
        <n-button size="tiny" secondary :loading="syncingPostId === item.cloudPosts[0].id" @click="syncPost(item.cloudPosts[0])">同步数据</n-button>
        <n-button v-if="item.merged >= 2" size="tiny" quaternary type="warning" @click="split(item)">拆分</n-button>
        <n-button size="tiny" quaternary type="error" @click="delCloud(item)">删除</n-button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { fmt } from '../lib/format'
import PlatformStats from './PlatformStats.vue'

defineProps({
  item: { type: Object, required: true },
  mergeMode: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  syncingId: { type: Number, default: -1 },
  syncingPostId: { type: Number, default: -1 },
  click: { type: Function, required: true },
  toggle: { type: Function, required: true },
  syncLocal: { type: Function, required: true },
  syncPost: { type: Function, required: true },
  confirm: { type: Function, required: true },
  delLocal: { type: Function, required: true },
  delCloud: { type: Function, required: true },
  split: { type: Function, required: true }
})
</script>

<style scoped>
.card-tile { display: flex; flex-direction: column; height: 100%; position: relative; }
.card-tile.picking { cursor: pointer; }
.tile-cover { position: relative; }
.pick-box {
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 3;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 6px;
  padding: 2px;
}
.row-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: auto; padding-top: 8px; min-height: 24px; }
.tag-row { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px; }
.tile-meta { margin: 6px 0 0; font-size: 8px; line-height: 1.4; color: #6f675c; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
