/**
 * 平台登录授权共享层 —— 全前端唯一的「登录状态检测 / 授权拉起浏览器」入口。
 *
 * 全链路指挥中心、调试面板-蜘蛛引擎（AuthMonitor）、简历回写等所有界面
 * 都必须经由此层调用，禁止各自硬编码端点或端口。
 *
 * 端口号由后端唯一配置区（backend/app/session/registry.py）提供，
 * 前端通过 GET /api/v1/auth/platforms 获取，禁止在前端硬编码端口。
 */

// 与 lib/api.ts 的 API_BASE 同源：本地默认 8000，部署时由 NEXT_PUBLIC_API_URL 覆盖
export function getMainApiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.replace(/\/api$/, "") + "/api"
  }
  if (typeof window !== "undefined" && window.location?.hostname) {
    return `http://${window.location.hostname}:8000/api`
  }
  return "http://127.0.0.1:8000/api"
}

export const MAIN_API_BASE = getMainApiBase()

/** 后端 registry 返回的平台授权元数据 */
export interface PlatformMeta {
  key: string // 注册表规范名：boss / liepin / 51job / zhilian / xiaohongshu
  display_name: string
  port: number
}

/** 归一化后的单平台登录状态 */
export interface PlatformLoginState {
  online: boolean
  logged_in: boolean
  message: string
}

export type AuthStatusMap = Record<string, PlatformLoginState>

/**
 * 获取平台授权配置表（端口唯一来源，供界面文案展示）。
 * 后端读自全项目唯一配置区 registry，改端口只需改后端一处。
 */
export async function fetchPlatformMeta(): Promise<PlatformMeta[]> {
  const res = await fetch(`${MAIN_API_BASE}/v1/auth/platforms`)
  const data = await res.json()
  if (res.ok && data.status === "success" && Array.isArray(data.platforms)) {
    return data.platforms as PlatformMeta[]
  }
  return []
}

/**
 * 读取各平台登录状态（统一检测入口）。
 * - force=false：走缓存接口（适合轮询）
 * - force=true：走 /session/recheck 强制重查，绕过 5 分钟缓存（手动刷新 / 授权唤起后用）
 *
 * 返回值已归一化：platform → { online, logged_in, message }
 */
export async function fetchAuthStatus(force = false): Promise<AuthStatusMap> {
  const url = force
    ? `${MAIN_API_BASE}/v1/crawlers/session/recheck`
    : `${MAIN_API_BASE}/v1/crawlers/status`
  const res = await fetch(url, force ? { method: "POST" } : undefined)
  const data = await res.json()

  const status: AuthStatusMap = {}
  for (const [key, val] of Object.entries(data as Record<string, unknown>)) {
    if (key.endsWith("_detail") || key.endsWith("_cookie_backed_up")) continue
    if (typeof val === "object" && val !== null && "state" in val) {
      // recheck 返回格式：{platform: {state, message, ...}}
      const obj = val as Record<string, unknown>
      const st = String(obj.state || "")
      status[key] = {
        online: st !== "unknown",
        logged_in: st === "healthy" || st === "degraded",
        message: String(obj.message || ""),
      }
    } else {
      const dataObj = data as Record<string, unknown>
      const detail = (dataObj[`${key}_detail`] && typeof dataObj[`${key}_detail`] === "object")
        ? (dataObj[`${key}_detail`] as Record<string, unknown>)
        : {}
      status[key] = {
        online: detail.state !== "unknown",
        logged_in: val === true,
        message: String(detail.message || ""),
      }
    }
  }
  return status
}

// 本机未装 Edge 时的兜底下载页（正常以后端返回为准，仅后端不可达时使用）
export const FALLBACK_EDGE_DOWNLOAD_URL = "https://www.microsoft.com/zh-cn/edge/download"

/** 结构化错误码：本机未安装 Microsoft Edge（与后端 edge_not_installed_detail 对应） */
export const EDGE_NOT_INSTALLED = "edge_not_installed"

/** Edge 未安装的统一前端展示文案（标题/兜底用；后端 message 含行动指引，二者语义不同层） */
export const EDGE_MISSING_MESSAGE = "未检测到 Microsoft Edge 浏览器"

/** 后端 /auth/edge-status 返回的本机 Edge 安装状态 */
export interface EdgeInstallStatus {
  installed: boolean
  downloadUrl: string
}

/**
 * 预检本机是否安装 Microsoft Edge（唤起浏览器前调用）。
 * 2.5s 超时：预检不该拖慢唤起主链路；超时/不可达按「已安装」放行，由唤起接口的结构化错误兜底。
 * 刻意不缓存结果：用户点弹窗装完 Edge 回到本页再点唤起时，必须拿到最新状态。
 */
export async function fetchEdgeStatus(): Promise<EdgeInstallStatus> {
  try {
    const res = await fetch(`${MAIN_API_BASE}/v1/auth/edge-status`, {
      signal: AbortSignal.timeout(2500),
    })
    const data = await res.json()
    if (res.ok && data.status === "success") {
      return {
        installed: !!data.installed,
        downloadUrl: data.download_url || FALLBACK_EDGE_DOWNLOAD_URL,
      }
    }
  } catch {
    // 后端不可达：放行走唤起链路的既有报错
  }
  return { installed: true, downloadUrl: FALLBACK_EDGE_DOWNLOAD_URL }
}

/** 唤起结果：code=edge_not_installed 时前端弹「下载 Edge」引导弹窗 */
export interface EdgeLaunchResult {
  ok: boolean
  message: string
  code?: string
  downloadUrl?: string
}

/**
 * 唤起指定平台的 Edge 浏览器完成登录 —— 所有平台同一套调用：
 * POST /api/v1/auth/{platform}/edge（后端按 registry 配置决定端口/profile/落地页）。
 */
export async function launchPlatformEdge(
  platform: string
): Promise<EdgeLaunchResult> {
  const res = await fetch(`${MAIN_API_BASE}/v1/auth/${platform}/edge`, {
    method: "POST",
  })
  const data = await res.json()
  if (res.ok && data.status === "success") {
    return { ok: true, message: data.message || "唤起成功" }
  }
  // 后端结构化错误（detail 为对象）：Edge 未安装等需要引导的场景
  const parsed = parseEdgeErrorDetail(data.detail)
  if (parsed) {
    return { ok: false, ...parsed }
  }
  return { ok: false, message: data.message || data.detail || "未知错误" }
}

/**
 * 「Edge 未安装」结构化错误体的统一解析（含 object 判定，非对象返回 null 交回调用方
 * 走各自的字符串 detail 兜底）。当前后端唯一结构化 code 是 edge_not_installed，故兜底
 * 文案为 Edge 专属；未来新增结构化 code 时应在此按 code 分派。成功形态各端点契约不同
 * （扁平体 / 信封体），由调用方各自解析。
 */
export function parseEdgeErrorDetail(
  detail: unknown
): Pick<EdgeLaunchResult, "message" | "code" | "downloadUrl"> | null {
  if (!detail || typeof detail !== "object") return null
  const d = detail as Record<string, unknown>
  return {
    message: String(d.message || EDGE_MISSING_MESSAGE),
    code: typeof d.code === "string" ? d.code : undefined,
    downloadUrl: typeof d.download_url === "string" && d.download_url
      ? d.download_url
      : FALLBACK_EDGE_DOWNLOAD_URL,
  }
}

/** 该唤起失败是否已被守卫处理（弹了下载引导），调用方无需再 toast 报错 */
export function isEdgeMissing(result: EdgeLaunchResult): boolean {
  return result.code === EDGE_NOT_INSTALLED
}
