<template>
  <div class="acct-row">
    <div class="row wrap" style="gap: 10px; align-items: center">
      <div class="av-wrap" @click="openFile">
        <img v-if="account.avatar" class="av" :src="account.avatar" alt="头像" />
        <span v-else class="av av-empty" />
        <span class="av-edit">换</span>
      </div>
      <input :id="inputId" type="file" accept="image/jpeg,image/png" class="file-hidden" @change="$emit('avatar', account, $event)" />
      <div style="min-width: 0">
        <div class="row" style="gap: 6px; align-items: center">
          <n-tag size="small" :bordered="false" round>{{ platformName(account.platform) }}</n-tag>
          <b>{{ account.nickname || platformName(account.platform) }}</b>
        </div>
        <div class="row" style="gap: 10px; margin-top: 4px; flex-wrap: wrap">
          <span class="muted mini">粉 {{ fmtNum(account.followers) }}</span>
          <span class="muted mini">作品 {{ fmtNum(account.posts_total) }}</span>
          <span class="mono uid" :title="account.platform_user_id">{{ account.platform_user_id || '未解析 ID' }}</span>
          <span v-if="account.last_sync_at" class="muted mini">同步 {{ fmt(account.last_sync_at) }}</span>
        </div>
      </div>
      <div class="grow"></div>
      <n-button size="tiny" secondary :loading="syncingAcctId === account.id" @click="$emit('sync', account)">{{ syncLabel }}</n-button>
      <n-button size="tiny" secondary @click="$emit('posts', account)">云端作品</n-button>
      <n-button size="tiny" secondary @click="$emit('edit', account)">编辑</n-button>
      <n-button size="tiny" quaternary type="error" @click="$emit('remove', account)">删除</n-button>
    </div>
  </div>
</template>

<script setup>
import { fmt, fmtNum, platformName } from '../lib/format'

const props = defineProps({
  account: { type: Object, required: true },
  benchmark: { type: Boolean, default: false },
  syncingAcctId: { type: Number, default: -1 },
  syncLabel: { type: String, default: '同步' }
})
defineEmits(['sync', 'posts', 'edit', 'remove', 'avatar'])

const inputId = `av${props.benchmark ? 'b' : ''}-${props.account.id}`

function openFile() {
  const el = document.getElementById(inputId)
  if (el) el.click()
}
</script>

<style scoped>
.acct-row { margin-top: 8px; padding: 8px 10px; background: #f7f3ec; border-radius: 8px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.wrap { flex-wrap: wrap; }
.av { width: 34px; height: 34px; border-radius: 50%; object-fit: cover; flex: none; }
.av-empty { display: inline-block; background: #fffdfa; border: 1.5px dashed #cdbfae; box-sizing: border-box; }
.av-wrap { position: relative; cursor: pointer; flex: none; }
.av-wrap .av-edit { position: absolute; right: -4px; bottom: -4px; background: #a34f2c; color: #fff; font-size: 9px; padding: 1px 5px; border-radius: 8px; opacity: 0; transition: opacity .15s; }
.av-wrap:hover .av-edit { opacity: 1; }
.mini { font-size: 12px; white-space: nowrap; }
.uid { font-size: 12px; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
