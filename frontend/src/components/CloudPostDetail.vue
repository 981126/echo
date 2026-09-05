<template>
  <div v-if="post" class="row" style="gap: 12px; align-items: flex-start">
    <img v-if="post.cover" :src="post.cover" alt="封面" style="width: 220px; border-radius: 8px; object-fit: cover" />
    <div>
      <h3 style="margin-top: 0">{{ post.title }}</h3>
      <p class="muted" style="font-size: 13px">{{ post.desc }}</p>
      <p v-if="post.latest_stat" class="muted" style="font-size: 13px">
        播放 {{ fmtNum(post.latest_stat.plays) }} · 赞 {{ fmtNum(post.latest_stat.likes) }} ·
        藏 {{ fmtNum(post.latest_stat.favorites) }} · 转 {{ fmtNum(post.latest_stat.shares) }} · 评 {{ fmtNum(post.latest_stat.comments) }}
      </p>
    </div>
  </div>
</template>

<script setup>
import { fmtNum } from '../lib/format'

defineProps({
  post: { type: Object, default: null }
})
</script>
