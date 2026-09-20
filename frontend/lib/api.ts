// 后端 API 地址：本地开发默认 8000 端口，部署时通过 NEXT_PUBLIC_API_URL 环境变量覆盖
// 约定：env 必须为裸地址（不带 /api 路径段）；为兼容历史部署误填「.../api」，
// 这里统一剥掉尾部的 /api 段（调用方均已自行拼接 /api/...）
export function getApiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL
      .replace(/\/$/, "")
      .replace(/\/api$/, "")
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
