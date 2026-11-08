"use client"

// 全局意外错误总线（模块级 pub/sub，非 React 状态）：
// 让任意 hook/工具函数不经过组件树 prop 钻透就能唤起统一 ErrorDialog，
// 避免往 800+ 行的 use-strategy-store 里塞弹窗 UI 状态。
// 用法：showGlobalError({ title: "❌ 保存失败", detail: data.detail || `HTTP ${res.status}` })
// 挂载：<GlobalErrorDialog /> 在页面布局渲染一次（见 app/strategy/page.tsx）。

export type GlobalErrorPayload = {
  /** 弹窗标题，如「❌ 保存失败」 */
  title: string
  /** 后端 detail / 异常文案（含响应快照时原样展示，取证关键） */
  detail: string
}

type Listener = (payload: GlobalErrorPayload) => void

let listener: Listener | null = null

export function showGlobalError(payload: GlobalErrorPayload): void {
  if (listener) {
    listener(payload)
  } else {
    // 兜底：GlobalErrorDialog 尚未挂载的页面（打样期逐步铺开），退化为 alert 不丢现场
    if (typeof window !== "undefined") {
      window.alert(`${payload.title}\n${payload.detail}`)
    }
  }
}

/** 仅供 GlobalErrorDialog 订阅；返回取消函数 */
export function subscribeGlobalError(fn: Listener): () => void {
  listener = fn
  return () => {
    if (listener === fn) listener = null
  }
}
