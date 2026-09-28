import { useEffect, useRef, useState } from 'react'
import { useEditor, EditorContent, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import Placeholder from '@tiptap/extension-placeholder'
import { TableKit } from '@tiptap/extension-table'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Markdown } from '@tiptap/markdown'
import {
  Bold,
  Italic,
  Strikethrough,
  Heading2,
  Heading3,
  Quote,
  List,
  ListOrdered,
  Code,
  Minus,
  Table,
  Link2,
  ImagePlus,
  Undo2,
  Redo2,
  LoaderCircle
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { uploadFile } from '@/api/client'
import { toast } from '@/components/ui/toaster'

// R-150 对齐：对外仍是 Markdown 字符串，drafts.script 契约不变
export function ScriptEditor({
  value,
  onChange,
  placeholder = '在这里撰写 / 改写脚本'
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  const imgInput = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const editor = useEditor({
    immediatelyRender: false,
    content: value || '',
    contentType: 'markdown',
    extensions: [
      StarterKit.configure({ link: { openOnClick: false, autolink: true } }),
      Image.configure({ inline: false, allowBase64: false }),
      Placeholder.configure({ placeholder }),
      TableKit.configure({ table: { resizable: false } }),
      TaskList,
      TaskItem,
      Markdown
    ],
    editorProps: {
      attributes: { class: 'prose-echo' },
      handlePaste: (_view, event) => {
        const file = firstImageFile(event.clipboardData)
        if (!file) return false
        event.preventDefault()
        void uploadAndInsert(file)
        return true
      },
      handleDrop: (_view, event, _slice, moved) => {
        if (moved) return false
        const file = firstImageFile(event.dataTransfer)
        if (!file) return false
        event.preventDefault()
        void uploadAndInsert(file)
        return true
      }
    },
    onUpdate: ({ editor }) => onChange(editor.getMarkdown())
  })

  // 外部换稿（AI 回填/切换草稿）时同步；自己敲字触发的回写不重设，避免光标跳走
  useEffect(() => {
    if (!editor) return
    if ((value || '') === editor.getMarkdown()) return
    editor.commands.setContent(value || '', { contentType: 'markdown', emitUpdate: false })
  }, [editor, value])

  function firstImageFile(data?: DataTransfer | null): File | null {
    const files = data?.files || []
    for (const f of Array.from(files)) {
      if (f.type?.startsWith('image/')) return f
    }
    return null
  }

  async function uploadAndInsert(file: File) {
    setUploading(true)
    try {
      const r = await uploadFile<{ url: string }>('/api/uploads/image', file)
      editor?.chain().focus().setImage({ src: r.url, alt: '图片' }).run()
      toast.success('图片已插入')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  function run(fn: (e: Editor) => void) {
    if (editor) fn(editor)
  }

  function setLink() {
    if (!editor) return
    const prev = editor.getAttributes('link').href || ''
    const url = window.prompt('链接地址', prev)
    if (url === null) return
    if (!url) {
      editor.chain().focus().unsetLink().run()
      return
    }
    editor.chain().focus().setLink({ href: url }).run()
  }

  const btn = (active?: boolean) =>
    cn(
      'flex h-7 min-w-7 items-center justify-center rounded-md px-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer',
      active && 'bg-accent-soft text-accent'
    )

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="flex flex-wrap items-center gap-0.5 border-b border-border bg-muted/40 px-2 py-1.5">
        <button type="button" className={btn(editor?.isActive('bold'))} onClick={() => run((e) => e.chain().focus().toggleBold().run())} title="加粗"><Bold className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn(editor?.isActive('italic'))} onClick={() => run((e) => e.chain().focus().toggleItalic().run())} title="斜体"><Italic className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn(editor?.isActive('strike'))} onClick={() => run((e) => e.chain().focus().toggleStrike().run())} title="删除线"><Strikethrough className="h-3.5 w-3.5" /></button>
        <span className="mx-1 h-4 w-px bg-border" />
        <button type="button" className={btn(editor?.isActive('heading', { level: 2 }))} onClick={() => run((e) => e.chain().focus().toggleHeading({ level: 2 }).run())} title="标题2"><Heading2 className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn(editor?.isActive('heading', { level: 3 }))} onClick={() => run((e) => e.chain().focus().toggleHeading({ level: 3 }).run())} title="标题3"><Heading3 className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn(editor?.isActive('blockquote'))} onClick={() => run((e) => e.chain().focus().toggleBlockquote().run())} title="引用"><Quote className="h-3.5 w-3.5" /></button>
        <span className="mx-1 h-4 w-px bg-border" />
        <button type="button" className={btn(editor?.isActive('bulletList'))} onClick={() => run((e) => e.chain().focus().toggleBulletList().run())} title="列表"><List className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn(editor?.isActive('orderedList'))} onClick={() => run((e) => e.chain().focus().toggleOrderedList().run())} title="有序列表"><ListOrdered className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn(editor?.isActive('codeBlock'))} onClick={() => run((e) => e.chain().focus().toggleCodeBlock().run())} title="代码块"><Code className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn()} onClick={() => run((e) => e.chain().focus().setHorizontalRule().run())} title="分隔线"><Minus className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn()} onClick={() => run((e) => e.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run())} title="表格"><Table className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn(editor?.isActive('link'))} onClick={setLink} title="链接"><Link2 className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn()} onClick={() => imgInput.current?.click()} title="插图" disabled={uploading}>
          {uploading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />}
        </button>
        <span className="mx-1 h-4 w-px bg-border" />
        <button type="button" className={btn()} disabled={!editor?.can().undo()} onClick={() => run((e) => e.chain().focus().undo().run())} title="撤销"><Undo2 className="h-3.5 w-3.5" /></button>
        <button type="button" className={btn()} disabled={!editor?.can().redo()} onClick={() => run((e) => e.chain().focus().redo().run())} title="重做"><Redo2 className="h-3.5 w-3.5" /></button>
        <span className="flex-1" />
        <span className="text-[10px] text-muted-foreground">支持粘贴/拖拽图片</span>
        <input ref={imgInput} type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && uploadAndInsert(e.target.files[0])} />
      </div>
      <EditorContent editor={editor} className="script-editor-content" />
    </div>
  )
}
