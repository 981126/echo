import { useEffect, useMemo, useState } from 'react'
import { LoaderCircle, Save, Mic, Upload, BadgeCheck } from 'lucide-react'
import { apiFetch, apiJson } from '@/api/client'
import { platformName } from '@/lib/format'
import { Drawer, DrawerHeader, DrawerTitle, DrawerBody, DrawerFooter } from '@/components/ui/drawer'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { toast } from '@/components/ui/toaster'
import { MediaComments } from './media-comments'
import type { CardItem } from './types'

export function CloudDrawer({
  item,
  open,
  onClose,
  onConverted
}: {
  item: CardItem | null
  open: boolean
  onClose: () => void
  onConverted: (videoId?: number, transcribe?: boolean) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [isAd, setIsAd] = useState(false)
  const [price, setPrice] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [metaSaving, setMetaSaving] = useState(false)

  useEffect(() => {
    if (!open || !item) return
    setFile(null)
    setText('')
    const posts = item.cloudPosts || []
    setIsAd(posts.some((x) => x.is_ad))
    const prices = posts.filter((x) => x.ad_price != null).map((x) => Number(x.ad_price))
    setPrice(prices.length ? Math.max(...prices) : null)
  }, [open, item])

  const commentPosts = useMemo(
    () => (item?.cloudPosts || []).map((x) => ({ id: x.id, platform: x.platform })),
    [item]
  )

  if (!open || !item) return null

  async function saveMeta() {
    if (!item) return
    setMetaSaving(true)
    try {
      const body: Record<string, unknown> = { is_ad: isAd, ad_price: price == null ? null : Number(price) }
      if (item.type === 'work') body.work_id = item.id
      else body.post_id = item.id
      await apiJson('/api/works/meta', { method: 'POST', body: JSON.stringify(body) })
      toast.success('广告设置已保存')
      onConverted()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setMetaSaving(false)
    }
  }

  async function toLocal(transcribe: boolean) {
    if (!item) return
    if (transcribe && !file) {
      toast.warning('请先选择视频文件，再「保存并语音转文字」')
      return
    }
    setSaving(true)
    try {
      const fd = new FormData()
      if (file) fd.append('file', file)
      if (text) fd.append('text', text)
      if (item.type === 'work') fd.append('work_id', String(item.id))
      else fd.append('post_id', String(item.id))
      fd.append('is_ad', isAd ? '1' : '0')
      fd.append('ad_price', price == null ? '' : String(price))
      const resp = await apiFetch('/api/works/to-local', { method: 'POST', body: fd })
      const r = (await resp.json()) as { video_id?: number }
      toast.success(file ? '已转为本地素材（可到编辑页「语音转文字」）' : '已转为本地素材')
      onClose()
      onConverted(r.video_id, transcribe)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open={open} onOpenChange={(v) => !v && onClose()} width="min(620px, 96vw)">
      <DrawerHeader>
        <DrawerTitle>转本地素材：{item.title}</DrawerTitle>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {item.platforms.map((p) => platformName(p)).join(' / ')}
          {item.merged > 1 ? ` · 合并 ${item.merged} 平台` : ''}
        </p>
      </DrawerHeader>

      <DrawerBody>
        <Tabs defaultValue="local">
          <TabsList>
            <TabsTrigger value="local">转本地素材</TabsTrigger>
            <TabsTrigger value="comments">评论数据</TabsTrigger>
          </TabsList>

          <TabsContent value="local" className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                上传视频（可选；选后可一键「保存并语音转文字」）
              </label>
              <label className="cursor-pointer">
                <input type="file" accept="video/*" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                <Button variant="outline" size="sm" asChild>
                  <span><Upload className="h-3.5 w-3.5" /> {file ? file.name : '选择视频文件'}</span>
                </Button>
              </label>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">文稿（可选，粘贴口播文案）</label>
              <Textarea rows={7} value={text} onChange={(e) => setText(e.target.value)} placeholder="粘贴/输入文稿，保存后进入素材库" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex items-center gap-2 pt-5">
                <Checkbox checked={isAd} onCheckedChange={(v) => setIsAd(!!v)} />
                <span className="text-xs">商务广告（不参与人设学习）</span>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">广告价格（元）</label>
                <Input
                  type="number"
                  min={0}
                  className="h-8 text-xs"
                  value={price ?? ''}
                  onChange={(e) => setPrice(e.target.value === '' ? null : Number(e.target.value))}
                />
              </div>
            </div>

            <p className="text-xs text-muted-foreground">
              保存后此作品会出现在素材库（云端标识去掉），可继续编辑平台/赛道/发布时间。
            </p>
          </TabsContent>

          <TabsContent value="comments">
            <MediaComments posts={commentPosts} />
          </TabsContent>
        </Tabs>
      </DrawerBody>

      <DrawerFooter className="flex-wrap">
        <Button variant="outline" size="sm" onClick={saveMeta} disabled={metaSaving}>
          {metaSaving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <BadgeCheck className="h-3.5 w-3.5" />}
          保存广告设置
        </Button>
        <span className="flex-1" />
        <Button variant="ghost" size="sm" onClick={onClose}>取消</Button>
        <Button variant="secondary" size="sm" onClick={() => toLocal(false)} disabled={saving}>
          {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          保存
        </Button>
        <Button size="sm" onClick={() => toLocal(true)} disabled={saving || !file}>
          {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Mic className="h-3.5 w-3.5" />}
          保存并语音转文字
        </Button>
      </DrawerFooter>
    </Drawer>
  )
}
