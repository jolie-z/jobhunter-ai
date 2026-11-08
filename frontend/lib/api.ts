// 后端 API 地址解析链（M2 动态端口定稿：壳 preload 注入优先）：
// 1. window.appConfig.backendBase —— 桌面壳 preload 注入（动态端口唯一来源，最高优先）
// 2. BACKEND_BASE_URL —— 壳注入前端进程的运行时 env（服务端 SSR 唯一来源，无 window 时生效）
// 3. NEXT_PUBLIC_API_URL —— 构建期 env（部署场景）
// 4. window.location.hostname 推导 :8000 —— 浏览器直接访问 dev 前端的既有约定
// 约定：均为裸地址（不带 /api 路径段）；为兼容历史部署误填「.../api」，
// 统一剥掉尾部的 /api 段（调用方均已自行拼接 /api/...）
declare global {
  interface Window {
    appConfig?: {
      backendBase?: string
      /** 导出诊断包到桌面并打开文件夹（错误弹窗「导出诊断日志」用；web 模式无此桥） */
      exportDiagnostics?: () => Promise<string | null>
      /** 在文件管理器中定位 shell.log（底层配置页「打开日志文件夹」用；web 模式无此桥） */
      openLogFolder?: () => Promise<boolean>
    }
  }
}

/** 统一规整各来源地址：剥尾部 / 与历史误填的 /api 段 */
function normalizeApiBase(url: string): string {
  return url.replace(/\/$/, "").replace(/\/api$/, "")
}

export function getApiBase(): string {
  const injected =
    typeof window !== "undefined" ? window.appConfig?.backendBase : undefined
  if (injected) {
    return normalizeApiBase(injected)
  }
  // 服务端（Server Component / Route Handler，如 /print/* 打印页的 SSR fetch）无 window，
  // 读桌面壳注入前端进程的 BACKEND_BASE_URL。打包版后端跑动态端口（8978 起），不能靠
  // 末尾写死的 8000 兜底——0.3.7 能渲染 PDF 纯属后端首选端口恰为 8000 的巧合，0.3.8
  // 端口搬家后 SSR fetch 全部 ECONNREFUSED，PDF 渲染成「Failed to load resume data」。
  // 刻意不用 NEXT_PUBLIC_ 前缀：那类变量会被 next build 内联，这里必须运行时读取。
  if (typeof window === "undefined" && process.env.BACKEND_BASE_URL) {
    return normalizeApiBase(process.env.BACKEND_BASE_URL)
  }
  if (process.env.NEXT_PUBLIC_API_URL) {
    return normalizeApiBase(process.env.NEXT_PUBLIC_API_URL)
  }
  if (typeof window !== "undefined" && window.location?.hostname) {
    return `http://${window.location.hostname}:8000`
  }
  return "http://127.0.0.1:8000"
}

export const API_BASE = getApiBase()

// 后端 WebSocket 地址：根据 API_BASE 动态推导协议（http -> ws, https -> wss）
export function getWsBase(): string {
  const api = getApiBase()
  if (api.startsWith("https://")) {
    return api.replace(/^https:\/\//, "wss://")
  }
  return api.replace(/^http:\/\//, "ws://")
}

export const WS_BASE = getWsBase()

/**
 * 健壮 API 请求辅助函数：
 * 1. 相对路径自动拼接当前最佳 API_BASE（动态感知 window.location.hostname）；
 * 2. 遇到浏览器端 Failed to fetch（如本地代理/TUN 拦截 127.0.0.1 或 localhost 互斥），自动在 localhost 与 127.0.0.1 之间进行快速故障转移重试；
 * 3. 避免未捕获的网络层异常直接打崩前端或触发 Next.js Turbopack 致命红屏。
 */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const base = getApiBase()
  const url = input.startsWith("http://") || input.startsWith("https://")
    ? input
    : `${base}${input.startsWith("/") ? "" : "/"}${input}`

  try {
    return await fetch(url, init)
  } catch (err) {
    // 针对 localhost <-> 127.0.0.1 本地跨域/代理绕行异常触发平滑双向兜底
    let fallbackUrl: string | null = null
    if (url.includes("://localhost:")) {
      fallbackUrl = url.replace("://localhost:", "://127.0.0.1:")
    } else if (url.includes("://127.0.0.1:")) {
      fallbackUrl = url.replace("://127.0.0.1:", "://localhost:")
    }

    if (fallbackUrl) {
      try {
        return await fetch(fallbackUrl, init)
      } catch {
        // 双重尝试均无法连接，保留原始异常向上抛出
      }
    }
    throw err
  }
}
