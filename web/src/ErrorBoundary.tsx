import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
  componentStack: string
}

/** 兜底：任何渲染期异常都不该把整页变成白屏。 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, componentStack: '' }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ componentStack: info.componentStack ?? '' })
    console.error('界面渲染失败', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="card">
        <div className="page-head">
          <div>
            <div className="eyebrow">界面异常</div>
            <h2>这一屏渲染失败了</h2>
            <p className="muted">
              后端数据没有丢失，刷新即可恢复；下面保留错误详情，方便排查是哪条记录触发的。
            </p>
          </div>
        </div>
        <pre className="code-block">{this.state.error.stack || this.state.error.message}</pre>
        {this.state.componentStack && (
          <details>
            <summary className="muted">组件栈</summary>
            <pre className="code-block">{this.state.componentStack}</pre>
          </details>
        )}
        <div className="page-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => this.setState({ error: null, componentStack: '' })}
          >
            重试渲染
          </button>
          <button type="button" className="btn btn-outline" onClick={() => window.location.reload()}>
            刷新页面
          </button>
        </div>
      </div>
    )
  }
}
