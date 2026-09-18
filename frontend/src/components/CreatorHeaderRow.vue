<template>
  <div>
    <div class="row wrap" style="gap: 8px; align-items: center">
      <img v-if="creator.avatar" class="av av-sm" :src="creator.avatar" alt="" />
      <template v-if="benchmark">
        <n-tag size="small" type="info" :bordered="false" round>对标</n-tag>
        <b>{{ creator.name }}</b>
      </template>
      <template v-else>
        <h3 style="margin: 0">{{ creator.name }}</h3>
        <n-tag v-if="isCurrent" type="primary" size="small" round :bordered="false">当前</n-tag>
        <span class="muted fans" style="font-size: 12px">全网粉丝 {{ fmtNum(creator.followers_total) }}</span>
      </template>
      <span class="muted grow" style="font-size: 12px">{{ creator.note || (benchmark ? '' : '（无备注）') }}</span>
      <n-button size="small" secondary :disabled="syncing" @click="$emit('initial', creator)">全量同步</n-button>
      <n-button
        v-if="!benchmark && showSyncBenchmarks"
        size="small"
        secondary
        :loading="benchmarkSyncing"
        :disabled="syncing || benchmarkSyncing"
        @click="$emit('syncBenchmarks', creator)"
      >同步对标博主前15条</n-button>
      <n-button size="small" secondary :loading="syncing" @click="$emit('daily', creator)">同步前15条</n-button>
      <n-button v-if="!benchmark && canSwitch" size="tiny" secondary @click="$emit('switch', creator)">切换到此博主</n-button>
      <n-button size="tiny" secondary @click="$emit('edit', creator)">编辑</n-button>
      <n-button v-if="benchmark" size="tiny" secondary @click="$emit('addAccount', creator)">+ 账号</n-button>
      <n-button size="tiny" quaternary type="error" @click="$emit('remove', creator)">删除</n-button>
    </div>
    <div v-if="!benchmark" class="row wrap" style="gap: 8px; margin-top: 10px">
      <n-button size="tiny" secondary @click="$emit('addAccount', creator)">+ 配置账号</n-button>
      <n-button v-if="showAddBenchmark" size="tiny" secondary @click="$emit('addBenchmark', creator)">+ 对标博主</n-button>
    </div>
  </div>
</template>

<script setup>
import { fmtNum } from '../lib/format'

defineProps({
  creator: { type: Object, required: true },
  benchmark: { type: Boolean, default: false },
  isCurrent: { type: Boolean, default: false },
  canSwitch: { type: Boolean, default: false },
  showAddBenchmark: { type: Boolean, default: false },
  showSyncBenchmarks: { type: Boolean, default: false },
  benchmarkSyncing: { type: Boolean, default: false },
  syncing: { type: Boolean, default: false }
})
defineEmits(['daily', 'initial', 'syncBenchmarks', 'switch', 'edit', 'addAccount', 'addBenchmark', 'remove'])
</script>

<style scoped>
.av { width: 34px; height: 34px; border-radius: 50%; object-fit: cover; flex: none; }
.av-sm { width: 26px; height: 26px; border-radius: 50%; object-fit: cover; flex: none; }
.wrap { flex-wrap: wrap; }
.grow { flex: 1; min-width: 0; }
.fans { font-size: 12px; }
</style>
