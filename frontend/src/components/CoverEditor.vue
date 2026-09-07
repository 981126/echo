<template>
  <div class="row" style="gap: 18px; align-items: flex-start">
    <div class="cover-edit" :class="{ playable: canPlay }" @click="onCoverClick">
      <img v-if="coverUrl" :src="coverUrl" alt="封面" />
      <span v-else>上传封面</span>
      <span v-if="canPlay" class="play-hint">▶ 播放</span>
    </div>
    <input ref="inputEl" type="file" accept="image/jpeg,image/png" class="file-hidden" @change="onPick" />
    <div class="grow muted" style="font-size: 12px">
      <div style="margin-top: 4px">jpg / png{{ canPlay ? '；点击封面播放视频' : '' }}</div>
      <n-button size="tiny" secondary style="margin-top: 8px" @click="inputEl && inputEl.click()">{{ coverUrl ? '替换封面' : '上传封面' }}</n-button>
      <n-button v-if="coverUrl" size="tiny" quaternary type="error" style="margin-top: 8px; margin-left: 8px" @click="$emit('remove')">移除封面</n-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  coverUrl: { type: String, default: null },
  canPlay: { type: Boolean, default: false }
})
const emit = defineEmits(['change', 'remove', 'play'])
const inputEl = ref(null)

function onCoverClick() {
  if (props.canPlay) {
    emit('play')
  } else if (inputEl.value) {
    inputEl.value.click()
  }
}

function onPick(e) {
  const f = e.target.files[0]
  if (inputEl.value) inputEl.value.value = ''
  if (f) emit('change', f)
}
</script>

<style scoped>
.cover-edit { position: relative; width: 120px; height: 120px; border-radius: 8px; overflow: hidden; background: #fffdfa; border: 1.5px dashed #cdbfae; display: flex; align-items: center; justify-content: center; cursor: pointer; color: #a34f2c; font-size: 12px; }
.cover-edit img { width: 100%; height: 100%; object-fit: cover; }
.cover-edit.playable:hover img { filter: brightness(0.7); }
.play-hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 600; opacity: 0; transition: opacity .15s; }
.cover-edit.playable:hover .play-hint { opacity: 1; }
</style>
