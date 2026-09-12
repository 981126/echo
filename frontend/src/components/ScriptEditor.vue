<template>
  <div class="script-editor">
    <div class="md-toolbar">
      <n-button size="tiny" secondary :type="btnType('bold')" @click="run(c => c.toggleBold())"><b>B</b></n-button>
      <n-button size="tiny" secondary :type="btnType('italic')" @click="run(c => c.toggleItalic())"><i>I</i></n-button>
      <n-button size="tiny" secondary :type="btnType('underline')" @click="run(c => c.toggleUnderline())"><u>U</u></n-button>
      <n-button size="tiny" secondary :type="btnType('strike')" @click="run(c => c.toggleStrike())"><s>S</s></n-button>
      <n-button size="tiny" secondary :type="btnType('heading', { level: 2 })" @click="run(c => c.toggleHeading({ level: 2 }))">H2</n-button>
      <n-button size="tiny" secondary :type="btnType('heading', { level: 3 })" @click="run(c => c.toggleHeading({ level: 3 }))">H3</n-button>
      <n-button size="tiny" secondary :type="btnType('blockquote')" @click="run(c => c.toggleBlockquote())">引用</n-button>
      <n-button size="tiny" secondary :type="btnType('bulletList')" @click="run(c => c.toggleBulletList())">列表</n-button>
      <n-button size="tiny" secondary :type="btnType('orderedList')" @click="run(c => c.toggleOrderedList())">1.</n-button>
      <n-button size="tiny" secondary :type="btnType('codeBlock')" @click="run(c => c.toggleCodeBlock())">代码</n-button>
      <n-button size="tiny" secondary @click="run(c => c.setHorizontalRule())">分隔线</n-button>
      <n-button size="tiny" secondary @click="run(c => c.insertTable({ rows: 3, cols: 3, withHeaderRow: true }))">表格</n-button>
      <n-button size="tiny" secondary :type="btnType('link')" @click="setLink">链接</n-button>
      <n-button size="tiny" secondary :loading="uploading" @click="pickImage">🖼 插图</n-button>
      <n-button size="tiny" secondary :disabled="!canUndo" @click="run(c => c.undo())">撤销</n-button>
      <n-button size="tiny" secondary :disabled="!canRedo" @click="run(c => c.redo())">重做</n-button>
      <span class="grow" />
      <span class="muted" style="font-size: 11px">支持粘贴/拖拽图片</span>
      <input ref="imgInput" type="file" accept="image/*" class="file-hidden" @change="onPick" />
    </div>
    <editor-content :editor="editor" class="md-editor prose" />
  </div>
</template>

<script setup>
// R-150：口播脚本块编辑器（Tiptap v3）。对外仍是 Markdown 字符串，drafts.script 契约不变。
import { ref, computed, watch } from 'vue'
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import Placeholder from '@tiptap/extension-placeholder'
import { TableKit } from '@tiptap/extension-table'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Markdown } from '@tiptap/markdown'
import { useMessage } from 'naive-ui'
import { uploadImage } from '../api'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '在这里撰写 / 改写脚本' }
})
const emit = defineEmits(['update:modelValue'])

const message = useMessage()
const imgInput = ref(null)
const uploading = ref(false)

const editor = useEditor({
  content: props.modelValue || '',
  contentType: 'markdown',
  extensions: [
    StarterKit.configure({ link: { openOnClick: false, autolink: true } }),
    Image.configure({ inline: false, allowBase64: false }),
    Placeholder.configure({ placeholder: props.placeholder }),
    // 表格/任务列表：StarterKit 不含，缺了会在「打开→保存」时把这类内容丢掉
    TableKit.configure({ table: { resizable: false } }),
    TaskList,
    TaskItem,
    Markdown
  ],
  editorProps: {
    handlePaste: (view, event) => {
      const file = firstImageFile(event.clipboardData)
      if (!file) return false
      event.preventDefault()
      uploadAndInsert(file)
      return true
    },
    handleDrop: (view, event, slice, moved) => {
      if (moved) return false
      const file = firstImageFile(event.dataTransfer)
      if (!file) return false
      event.preventDefault()
      uploadAndInsert(file)
      return true
    }
  },
  onUpdate: ({ editor }) => emit('update:modelValue', editor.getMarkdown())
})

// 外部换稿（切换草稿/AI 回填）时同步；自己敲字触发的回写不重设，避免光标跳走
watch(() => props.modelValue, (val) => {
  const ed = editor.value
  if (!ed) return
  if ((val || '') === ed.getMarkdown()) return
  ed.commands.setContent(val || '', { contentType: 'markdown', emitUpdate: false })
})

const canUndo = computed(() => !!editor.value?.can().undo())
const canRedo = computed(() => !!editor.value?.can().redo())

function run(fn) {
  const ed = editor.value
  if (ed) fn(ed.chain().focus()).run()
}

function btnType(name, attrs) {
  return editor.value?.isActive(name, attrs) ? 'primary' : 'default'
}

function firstImageFile(data) {
  const files = data?.files || []
  for (const f of files) {
    if (f.type && f.type.startsWith('image/')) return f
  }
  return null
}

async function uploadAndInsert(file) {
  uploading.value = true
  try {
    const r = await uploadImage(file)
    editor.value?.chain().focus().setImage({ src: r.url, alt: '图片' }).run()
    message.success('图片已插入')
  } catch (e) {
    message.error(e.message)
  } finally {
    uploading.value = false
  }
}

function pickImage() {
  if (imgInput.value) imgInput.value.click()
}

async function onPick(e) {
  const f = e.target.files && e.target.files[0]
  try {
    await uploadAndInsert(f)
  } finally {
    if (imgInput.value) imgInput.value.value = ''
  }
}

function setLink() {
  const ed = editor.value
  if (!ed) return
  const prev = ed.getAttributes('link').href || ''
  const url = window.prompt('链接地址（留空则取消链接）', prev || 'https://')
  if (url === null) return
  const chain = ed.chain().focus().extendMarkRange('link')
  if (!url.trim()) {
    chain.unsetLink().run()
    return
  }
  if (ed.state.selection.empty) {
    chain.insertContent({ type: 'text', text: url, marks: [{ type: 'link', attrs: { href: url } }] }).run()
  } else {
    chain.setLink({ href: url }).run()
  }
}
</script>

<style scoped>
.script-editor { margin-bottom: 4px; }
.md-editor {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px 14px;
  min-height: 320px;
  background: var(--bg);
  overflow-y: auto;
  max-height: 60vh;
}
.md-editor:focus-within { border-color: var(--accent); }
.md-editor :deep(.ProseMirror) { outline: none; min-height: 296px; }
.md-editor :deep(p.is-editor-empty:first-child::before) {
  content: attr(data-placeholder);
  color: var(--muted);
  float: left;
  height: 0;
  pointer-events: none;
}
.md-editor :deep(hr) { border: 0; border-top: 1px solid var(--line-strong); margin: 1em 0; }
.md-editor :deep(blockquote) { border-left: 3px solid var(--line-strong); margin: .6em 0; padding: 0 1em; color: var(--ink-soft); }
.md-editor :deep(pre) { background: #2f2b26; color: #ece6dc; border-radius: 8px; padding: 12px 14px; overflow-x: auto; }
.md-editor :deep(pre code) { background: none; color: inherit; padding: 0; }
.md-editor :deep(code) { font-family: var(--mono); font-size: .9em; background: var(--accent-soft); border-radius: 4px; padding: 1px 5px; }
.md-editor :deep(img) { max-width: 100%; border-radius: 8px; }
.md-editor :deep(img.ProseMirror-selectednode) { outline: 2px solid var(--accent); }
.md-editor :deep(a) { color: var(--accent); text-decoration: underline; }
.md-editor :deep(.tableWrapper) { overflow-x: auto; }
.md-editor :deep(table) { border-collapse: collapse; width: 100%; margin: .6em 0; }
.md-editor :deep(th), .md-editor :deep(td) { border: 1px solid var(--line-strong); padding: 4px 8px; vertical-align: top; }
.md-editor :deep(th) { background: var(--accent-soft); text-align: left; }
.md-editor :deep(ul[data-type='taskList']) { list-style: none; padding-left: 0; }
.md-editor :deep(ul[data-type='taskList'] li) { display: flex; gap: 6px; align-items: flex-start; }
.md-editor :deep(ul[data-type='taskList'] li > label) { margin-top: 4px; }
</style>
