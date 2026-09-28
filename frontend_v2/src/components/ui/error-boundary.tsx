import { Component, type ReactNode } from 'react'

// 局部错误边界：子树渲染崩溃时降级展示 fallback，绝不让用户面对空白（R-167 防御）
export class ErrorBoundary extends Component<
  { children: ReactNode; fallback?: ReactNode; onError?: (e: Error) => void },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    this.props.onError?.(error)
  }

  render() {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <div className="rounded-lg border border-destructive/40 bg-[rgba(239,68,68,0.06)] p-4 text-sm text-destructive">
            这一块渲染出错了：{this.state.error.message}
          </div>
        )
      )
    }
    return this.props.children
  }
}
