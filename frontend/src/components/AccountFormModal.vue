<template>
  <n-modal :show="show" preset="card" :title="form.id ? '编辑账号' : '配置 ' + platformName(form.platform) + ' 账号'" style="width: min(560px, 94vw)" @update:show="$emit('update:show', $event)">
    <div class="form-item">
      <label class="form-label">平台</label>
      <n-select :value="form.platform" :options="platformOptions" :disabled="!!form.id" placeholder="选择平台"
        @update:value="v => $emit('update:platform', v)" />
    </div>
    <div class="form-item">
      <label class="form-label">昵称（可选）</label>
      <n-input :value="form.nickname" placeholder="自动同步时会用主页昵称覆盖" @update:value="$emit('update:nickname', $event)" />
    </div>
    <div class="form-item">
      <label class="form-label">主页分享链接</label>
      <div class="row" style="gap: 6px">
        <n-input :value="form.home_link" placeholder="粘贴主页分享链接，点右侧自动解析 ID" style="flex: 1" @update:value="$emit('update:homeLink', $event)" />
        <n-button secondary :loading="parsing" @click="$emit('parse')">解析</n-button>
      </div>
    </div>
    <div class="form-item">
      <label class="form-label">平台用户 ID（解析后自动填入，也可手动改）</label>
      <n-input :value="form.platform_user_id" placeholder="sec_user_id / user_id / uid" @update:value="$emit('update:userId', $event)" />
    </div>
    <div class="form-item">
      <label class="form-label">增强配置（JSON，可选：cookie/share_text 等）</label>
      <n-input :value="extraText" type="textarea" :rows="2" placeholder='{"share_text":""}' @update:value="$emit('update:extra', $event)" />
    </div>
    <n-checkbox :checked="form.enabled" @update:checked="$emit('update:enabled', $event)">启用自动同步</n-checkbox>
    <div class="row" style="margin-top: 14px">
      <n-button type="primary" @click="$emit('save')">保存</n-button>
      <n-button secondary @click="$emit('update:show', false)">取消</n-button>
    </div>
  </n-modal>
</template>

<script setup>
import { platformName } from '../lib/format'
import { platformOptions } from '../lib/options'

defineProps({
  show: { type: Boolean, default: false },
  form: { type: Object, required: true },
  extraText: { type: String, default: '' },
  parsing: { type: Boolean, default: false }
})
defineEmits(['update:show', 'update:platform', 'update:nickname', 'update:homeLink', 'update:userId', 'update:enabled', 'update:extra', 'parse', 'save'])
</script>
