/**
 * 深度链接与 URL 状态保活工具
 */

export function clearDeepLinkParams() {
  if (typeof window === "undefined") return
  const url = new URL(window.location.href)
  if (!url.searchParams.has("job_id") && !url.searchParams.has("record_id")) return
  url.searchParams.delete("job_id")
  url.searchParams.delete("record_id")
  window.history.replaceState(null, "", url.pathname + url.search + url.hash)
}

export function setDeepLinkParam(jobId?: string) {
  if (typeof window === "undefined" || !jobId) return
  const url = new URL(window.location.href)
  if (url.searchParams.get("job_id") === jobId && !url.searchParams.has("record_id")) return
  url.searchParams.set("job_id", jobId)
  url.searchParams.delete("record_id")
  window.history.replaceState(null, "", url.pathname + url.search + url.hash)
}
