<template>
  <div class="card-tile">
    <div class="tile-cover has" @click="$emit('detail', post)">
      <img v-if="post.cover" :src="post.cover" alt="封面" />
      <span v-else>ECHO</span>
    </div>
    <h3 class="tile-title" style="word-break: break-all" @click="$emit('detail', post)">{{ post.title }}</h3>
    <p class="tile-meta">
      <template v-if="post.latest_stat">
        <template v-if="post.latest_stat.plays">播放 {{ fmtNum(post.latest_stat.plays) }}</template>
        <template v-if="post.latest_stat.likes"> · 赞 {{ fmtNum(post.latest_stat.likes) }}</template>
        <template v-if="post.latest_stat.favorites"> · 藏 {{ fmtNum(post.latest_stat.favorites) }}</template>
        <template v-if="post.latest_stat.comments"> · 评 {{ fmtNum(post.latest_stat.comments) }}</template>
      </template>
      <template v-else>暂无指标</template>
    </p>
    <div class="row" style="gap: 6px">
      <n-tag v-if="post.creator_kind === 'benchmark'" size="tiny" type="info" :bordered="false">对标</n-tag>
      <n-tag v-if="post.local_video_id" size="tiny" type="success" :bordered="false">已转素材</n-tag>
    </div>
    <div class="row" style="gap: 6px; margin-top: 8px">
      <n-button size="tiny" secondary :loading="syncingPostId === post.id" @click="$emit('sync', post)">同步</n-button>
      <n-button v-if="!post.local_video_id" size="tiny" secondary @click="$emit('toMaterial', post)">转素材</n-button>
      <n-button v-else size="tiny" secondary @click="$emit('openMaterial', post.local_video_id)">打开素材</n-button>
    </div>
  </div>
</template>

<script setup>
import { fmtNum } from '../lib/format'

defineProps({
  post: { type: Object, required: true },
  syncingPostId: { type: Number, default: -1 }
})
defineEmits(['detail', 'sync', 'toMaterial', 'openMaterial'])
</script>
