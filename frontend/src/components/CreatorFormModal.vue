<template>
  <n-modal :show="show" preset="card" :title="form.id ? '编辑博主' : form.kind === 'benchmark' ? '添加对标博主' : '新建主博主'" style="width: min(480px, 92vw)" @update:show="$emit('update:show', $event)">
    <div class="form-item">
      <label class="form-label">名称</label>
      <n-input :value="form.name" placeholder="如：我的主号 / 对标博主名" @update:value="$emit('update:name', $event)" />
    </div>
    <div v-if="form.kind === 'benchmark'" class="form-item">
      <label class="form-label">所属主博主</label>
      <n-select :value="form.parent_id" :options="ownerOptions" @update:value="$emit('update:parentId', $event)" />
    </div>
    <div class="form-item">
      <label class="form-label">备注 / 风格参考（对标风格卡可写在这里，1-3 句）</label>
      <n-input :value="form.note" type="textarea" :rows="3" placeholder="可选" @update:value="$emit('update:note', $event)" />
    </div>
    <div class="row">
      <n-button type="primary" @click="$emit('save')">保存</n-button>
      <n-button secondary @click="$emit('update:show', false)">取消</n-button>
    </div>
  </n-modal>
</template>

<script setup>
defineProps({
  show: { type: Boolean, default: false },
  form: { type: Object, required: true },
  ownerOptions: { type: Array, default: () => [] }
})
defineEmits(['update:show', 'update:name', 'update:parentId', 'update:note', 'save'])
</script>
