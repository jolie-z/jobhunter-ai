/**
 * 四平台 Tab 共享的 API 调用层。
 * 统一 URL、响应解析与三态语义，避免同一段 fetch 逻辑在四个 Tab 手工拷贝漂移
 * （历史上 liepin 回写端点错配、51job 判定字段缺失均源于拷贝不一致）
 */

export type Platform = "boss" | "liepin" | "51job" | "zhilian"

export const PLATFORM_KEYS: Platform[] = ["boss", "liepin", "51job", "zhilian"]

/**
 * 保存平台数据（整份覆盖 POST /api/resume-editor/save/{platform}）。
 * 返回 { ok, message }；message 供调用方 toast 展示具体失败原因。
 */
export async function savePlatformData(
  apiBase: string,
  platform: Platform,
  data: unknown
): Promise<{ ok: boolean; message?: string }> {
  try {
    const res = await fetch(`${apiBase}/api/resume-editor/save/${platform}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
    const result = await res.json()
    if (result.success) return { ok: true }
    return { ok: false, message: result.message || "后端拒绝保存" }
  } catch (e: any) {
    return { ok: false, message: String(e?.message || e) }
  }
}

/**
 * 拉取指定平台的映射报告（GET /api/agent-map/reports）三态：
 * - ok: 有该平台报告（report 为报告内容）
 * - absent: 后端正常但该平台无报告（调用方应清掉旧报告）
 * - error: 网络/后端异常（调用方应保留旧报告，不闪空）
 */
export type ReportFetchResult =
  | { status: "ok"; report: any }
  | { status: "absent" }
  | { status: "error"; message: string }

export async function fetchPlatformReport(apiBase: string, platform: Platform): Promise<ReportFetchResult> {
  try {
    const res = await fetch(`${apiBase}/api/agent-map/reports`)
    const result = await res.json()
    if (result.success) {
      const report = result.reports?.[platform]
      return report ? { status: "ok", report } : { status: "absent" }
    }
    return { status: "error", message: result.message || "获取映射报告失败" }
  } catch (e: any) {
    return { status: "error", message: String(e?.message || e) }
  }
}
