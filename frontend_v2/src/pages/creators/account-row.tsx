import { useRef, useState } from 'react'
import { RefreshCw, LoaderCircle, Pencil, Trash2, ExternalLink, ListVideo, ImagePlus } from 'lucide-react'
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

  return (
    <div className={cn('flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2.5 transition-colors', disabled && 'opacity-55')}>
      <div className="relative">
        <Avatar className="h-10 w-10">
          {avatarSrc ? <AvatarImage src={avatarSrc} alt={account.nickname} /> : null}
          <AvatarFallback>{(account.nickname || platformName(account.platform)).slice(0, 1)}</AvatarFallback>
        </Avatar>
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <button
              onClick={() => fileRef.current?.click()}
              className="absolute -bottom-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm transition-colors hover:text-foreground cursor-pointer"
            >
              {avatarBusy ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <ImagePlus className="h-3 w-3" />}
            </button>
          </TooltipTrigger>
          <TooltipContent>上传头像（jpg/png）</TooltipContent>
        </Tooltip>
        <input ref={fileRef} type="file" accept=".jpg,.jpeg,.png" className="hidden" onChange={(e) => e.target.files?.[0] && onAvatarFile(e.target.files[0])} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <Badge variant="secondary">{platformName(account.platform)}</Badge>
          <span className="truncate text-[13px] font-medium">{account.nickname || platformName(account.platform)}</span>
          {account.home_link && (
            <a href={account.home_link} target="_blank" rel="noreferrer" className="text-muted-foreground hover:text-accent">
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
        <div className="tnum mt-0.5 text-[11px] text-muted-foreground">
          粉丝 {fmtNum(account.followers)} · 作品 {fmtNum(account.posts_total)} · 获赞 {fmtNum(account.likes_total)}
          {account.last_sync_at ? ` · ${fmtDate(account.last_sync_at)} 同步` : ''}
        </div>
      </div>

      <div className="flex items-center gap-1">
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
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onEdit(account)}>
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive" onClick={() => onRemove(account)}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <span>
              <Switch checked={account.enabled} onCheckedChange={(v) => onToggleEnabled(account, v)} />
            </span>
          </TooltipTrigger>
          <TooltipContent>{account.enabled ? '禁用（停止同步/隐藏数据）' : '启用'}</TooltipContent>
        </Tooltip>
      </div>
    </div>
  )
}
