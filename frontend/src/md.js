// 共用 Markdown 渲染（R-017 对话 / R-018 草稿预览）
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true
})

export function renderMd(text) {
  return md.render(text || '')
}
