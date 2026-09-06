<template>
  <div class="spb">
    <div class="spb-row">
      <span class="spb-tag">同步进度</span>
      <span class="spb-note">{{ note }}</span>
      <span v-if="hasTotal" class="spb-count">{{ job.progress_done }}/{{ job.progress_total }}</span>
    </div>
    <div class="spb-track">
      <div class="spb-fill" :class="{ running: !hasTotal }" :style="hasTotal ? { width: pct + '%' } : {}"></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  job: { type: Object, required: true }
})
const hasTotal = computed(() => Number(props.job.progress_total || 0) > 0)
const pct = computed(() => {
  if (!hasTotal.value) return 0
  return Math.min(100, Math.round((Number(props.job.progress_done || 0) / Number(props.job.progress_total)) * 100))
})
const note = computed(() => props.job.progress_note || (props.job.status === 'running' ? '准备中…' : '同步中…'))
</script>

<style scoped>
.spb { margin: 8px 0 2px; }
.spb-row { display: flex; gap: 8px; align-items: center; font-size: 12px; margin-bottom: 4px; }
.spb-tag { color: #a34f2c; flex: none; }
.spb-note { color: #6f675c; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.spb-count { color: #6f675c; flex: none; }
.spb-track { height: 6px; border-radius: 3px; background: #eee8df; overflow: hidden; }
.spb-fill { height: 100%; border-radius: 3px; background: #a34f2c; transition: width 0.35s ease; }
.spb-fill.running { width: 30%; animation: spb-slide 1.1s ease-in-out infinite; }
@keyframes spb-slide {
  from { transform: translateX(-100%); }
  to { transform: translateX(400%); }
}
</style>
