<template>
  <div class="row" style="gap: 8px">
    <n-button secondary :loading="syncing" @click="$emit('sync')">同步数据</n-button>
    <div class="grow" />
    <n-button type="primary" @click="$emit('save')">保存</n-button>
    <n-button secondary @click="$emit('cancel')">取消</n-button>
  </div>
</template>

<script setup>
defineProps({
  syncing: { type: Boolean, default: false }
})
defineEmits(['sync', 'save', 'cancel'])
</script>
