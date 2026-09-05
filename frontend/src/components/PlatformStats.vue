<template>
  <div class="plat-zone">
    <div v-for="p in order" :key="p" class="plat-line" :class="{ missing: !postOf(p) }">
      <template v-if="postOf(p)">
        <b>{{ platformName(p) }}</b>
        <template v-if="postOf(p).latest_stat">
          <span>播放 {{ postOf(p).latest_stat.plays ? fmtNum(postOf(p).latest_stat.plays) : '—' }}</span>
          <span>赞 {{ fmtNum(postOf(p).latest_stat.likes) }}</span>
          <span>藏 {{ fmtNum(postOf(p).latest_stat.favorites) }}</span>
          <span>评 {{ fmtNum(postOf(p).latest_stat.comments) }}</span>
        </template>
        <span v-else class="ph">暂无指标</span>
      </template>
      <template v-else>
        <b>{{ platformName(p) }}</b>
        <span class="ph">播放 —</span>
        <span class="ph">赞 —</span>
        <span class="ph">藏 —</span>
        <span class="ph">评 —</span>
      </template>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  posts: { type: Array, default: () => [] }
})
const order = ['douyin', 'bilibili', 'xiaohongshu']
const NAMES = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
const platformName = (p) => NAMES[p] || p || ''

function postOf(p) {
  return (props.posts || []).find(x => x.platform === p) || null
}

function fmtNum(n) {
  n = Number(n || 0)
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return String(n)
}
</script>

<style scoped>
.plat-zone { margin-top: 4px; }
.plat-line {
  display: grid;
  grid-template-columns: 24px 54px 38px 36px 36px;
  align-items: baseline;
  white-space: nowrap;
  margin-top: 3px;
  min-height: 12px;
  font-size: 8px;
  color: #6f675c;
}
.plat-line b { color: #a34f2c; font-weight: 600; }
.plat-line span { overflow: hidden; text-overflow: ellipsis; }
.plat-line.missing { color: #bdb4a8; }
.plat-line.missing b { color: #bdb4a8; font-weight: 400; }
.plat-line .ph { color: #bdb4a8; }
</style>
