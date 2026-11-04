import { useRef, useState } from 'react'
import { RefreshCw, LoaderCircle, Pencil, Trash2, ExternalLink, ListVideo, ImagePlus } from 'lucide-react'
import { coverThumb } from '@/lib/covers'
import { platformName, fmtNum, fmtDate } from '@/lib/format'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { uploadFile } from '@/api/client'
import { toast } from '@/components/ui/toaster'
import { cn } from '@/lib/utils'
import type { AccountMeta } from './types'

export function AccountRow({
  account,
  syncing,
  onSync,
  onPosts,
  onEdit,
  onRemove,
  onToggleEnabled
}: {
  account: AccountMeta
  syncing: boolean
  onSync: (a: AccountMeta) => void
  onPosts: (a: AccountMeta) => void
  onEdit: (a: AccountMeta) => void
  onRemove: (a: AccountMeta) => void
  onToggleEnabled: (a: AccountMeta, on: boolean) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const avatarSrc = account.avatar || (account.avatar_url ?? '') || ''

  async function onAvatarFile(f: File) {
    setAvatarBusy(true)
    try {
      await uploadFile(`/api/creators/accounts/${account.id}/avatar`, f)
      toast.success('头像已更新')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setAvatarBusy(false)
    }
  }

  const disabled = !account.enabled
  const lastSync = account.last_sync_at ? `${fmtDate(account.last_sync_at)} 同步` : ''

  return (
    // R-218：<md 账号行卡片化（三行：身份徽标 / 数据 / 操作），md+ 保持原来单行
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border border-border bg-card px-3 py-2.5 transition-colors md:flex-row md:items-center md:gap-3',
        disabled && 'opacity-55'
      )}
    >
      <div className="flex min-w-0 flex-1 items-start gap-2.5 md:items-center">
        <div className="relative shrink-0">
          <Avatar className="h-10 w-10">
            {avatarSrc ? <AvatarImage src={coverThumb(avatarSrc, 160)} alt={account.nickname} decoding="async" /> : null}
            <AvatarFallback>{(account.nickname || platformName(account.platform)).slice(0, 1)}</AvatarFallback>
          </Avatar>
          <Tooltip delayDuration={0}>
            <TooltipTrigger asChild>
              {/* R-218：<md 热区 44×44，视觉徽标仍 20×20（放在按钮右下角） */}
              <button
                onClick={() => fileRef.current?.click()}
                aria-label="上传头像"
                className="pressable absolute -bottom-1 -right-1 flex h-5 w-5 cursor-pointer items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm transition-colors hover:text-foreground max-md:-bottom-2 max-md:-right-2 max-md:h-11 max-md:w-11 max-md:items-end max-md:justify-end max-md:border-0 max-md:bg-transparent max-md:shadow-none"
              >
                <span className="flex h-5 w-5 items-center justify-center rounded-full border border-border bg-card">
                  {avatarBusy ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <ImagePlus className="h-3 w-3" />}
                </span>
              </button>
            </TooltipTrigger>
            <TooltipContent>上传头像（jpg/png）</TooltipContent>
          </Tooltip>
          <input ref={fileRef} type="file" accept=".jpg,.jpeg,.png" className="hidden" onChange={(e) => e.target.files?.[0] && onAvatarFile(e.target.files[0])} />
        </div>

        <div className="min-w-0 flex-1">
          {/* 行1：平台徽标 + 昵称 + 状态徽标（可换行，不竖排） */}
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="secondary">{platformName(account.platform)}</Badge>
            <span className="max-w-full truncate text-[13px] font-medium">{account.nickname || platformName(account.platform)}</span>
            {account.home_link && (
              <a
                href={account.home_link}
                target="_blank"
                rel="noreferrer"
                aria-label="打开主页"
                title="打开主页"
                className="relative inline-flex items-center text-muted-foreground hover:text-accent max-md:after:absolute max-md:after:-inset-4 max-md:after:content-['']"
              >
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
            {!account.enabled && <Badge variant="warning">已禁用</Badge>}
            {account.platform === 'douyin' && account.douyin_credential && (() => {
              const c = account.douyin_credential
              if (c.status === 'valid') return <Badge variant="secondary">创作者可用</Badge>
              if (c.status === 'invalid') return (
                <Tooltip delayDuration={0}>
                  <TooltipTrigger asChild><Badge variant="destructive">Cookie 已失效</Badge></TooltipTrigger>
                  <TooltipContent>{c.last_error || '请在编辑账号更新 Cookie'}</TooltipContent>
                </Tooltip>
              )
              if (c.status === 'disabled') return <Badge variant="outline">创作者已关闭</Badge>
              return <Badge variant="outline">未配置创作者</Badge>
            })()}
            {account.sync_status === 'failed' && (
              <Tooltip delayDuration={0}>
                <TooltipTrigger asChild>
                  <Badge variant="destructive">同步失败</Badge>
                </TooltipTrigger>
                <TooltipContent>{account.sync_message || '同步失败'}</TooltipContent>
              </Tooltip>
            )}
          </div>
          {/* 行2：粉丝 / 作品 / 获赞 / 最后同步（完整文字，可换行） */}
          <div className="tnum mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            <span>粉丝 {fmtNum(account.followers)}</span>
            <span>作品 {fmtNum(account.posts_total)}</span>
            <span>获赞 {fmtNum(account.likes_total)}</span>
            {lastSync && <span>{lastSync}</span>}
          </div>
        </div>
      </div>

      {/* 行3：操作（移动可换行，每项 ≥44；桌面单行原尺寸） */}
      <div className="flex flex-wrap items-center gap-1 md:flex-nowrap">
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <span>
              <Button variant="outline" size="sm" disabled={syncing || disabled} onClick={() => onSync(account)}>
                {syncing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                同步
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>同步前15条（含评论/下载/转写）</TooltipContent>
        </Tooltip>
        <Button variant="ghost" size="sm" onClick={() => onPosts(account)}>
          <ListVideo className="h-3.5 w-3.5" /> 作品
        </Button>
        <Button variant="ghost" size="icon" className="h-11 w-11 md:h-8 md:w-8" aria-label="编辑账号" onClick={() => onEdit(account)}>
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="icon" className="h-11 w-11 text-destructive md:h-8 md:w-8" aria-label="删除账号" onClick={() => onRemove(account)}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            {/* 开关视觉保持原尺寸，外层 44 热区（点空白处也能切换） */}
            <span
              onClick={(e) => {
                if (e.target === e.currentTarget) onToggleEnabled(account, !account.enabled)
              }}
              className="flex h-11 w-11 cursor-pointer items-center justify-center md:h-auto md:w-auto"
            >
              <Switch checked={account.enabled} onCheckedChange={(v) => onToggleEnabled(account, v)} aria-label={account.enabled ? '禁用账号' : '启用账号'} />
            </span>
          </TooltipTrigger>
          <TooltipContent>{account.enabled ? '禁用（停止同步/隐藏数据）' : '启用'}</TooltipContent>
        </Tooltip>
      </div>
    </div>
  )
}
