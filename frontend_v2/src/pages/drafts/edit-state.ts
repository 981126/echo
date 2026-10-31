// R-243：草稿编辑态类型/空稿常量抽到独立模块——避免 `pages/drafts/index.tsx` 为了拿到
// 类型与 EMPTY_DRAFT 而静态 import 整个 edit-drawer（进而首屏加载 tiptap/markdown ~600KB）。
// `pages/drafts/edit-drawer.tsx` 仍 re-export 这两个符号，保持既有 import 兼容。
export interface DraftEditState {
  id: number
  title: string
  cover_text: string
  script: string
  video_id: number | null
  tagsText: string
  publish_platform: string
  publish_url: string
  published_at: string
}

export const EMPTY_DRAFT: DraftEditState = {
  id: 0,
  title: '',
  cover_text: '',
  script: '',
  video_id: null,
  tagsText: '',
  publish_platform: '',
  publish_url: '',
  published_at: ''
}
