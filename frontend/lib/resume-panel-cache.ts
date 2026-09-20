"use client"

/**
 * AI 面板结果缓存公共工具（战略折叠 / 智能删减 / 初稿改写共用）：
 * - sessionStorage 级：按 jobId（+可选子维度）硬隔离，杜绝 A 岗位的结果被恢复到 B 岗位；
 * - localStorage 级：持久缓存 key 携带 jobId 前缀，避免跨岗位命中；
 * - 归属校验（结果必须与当前条目一一对应）由调用方提供 matcher，
 *   校验失败调用方应 clearSession / 删除 local 条目，防止索引错位串写。
 */
export interface PanelResult {
  id: string
}

export interface PanelCacheOptions {
  /** localStorage 持久缓存 key，如 resume_compress_cache */
  storageKey: string
  /** sessionStorage 维度前缀，如 session_compress_last_results */
  sessionScope: string
  /** 岗位维度（跨岗位隔离的硬边界） */
  jobId?: string
  /** 面板内子维度（如初稿面板的「工作经历/项目经历」分类） */
  scope?: string
}

export function createPanelResultCache<T extends PanelResult>({ storageKey, sessionScope, jobId, scope }: PanelCacheOptions) {
  const jobKey = jobId || "nojob"
  const sessionKey = [sessionScope, jobKey, scope].filter(Boolean).join("_")

  function saveSession(results: T[]) {
    try { sessionStorage.setItem(sessionKey, JSON.stringify(results)) } catch {}
  }

  function loadSession(): T[] | null {
    try {
      const raw = sessionStorage.getItem(sessionKey)
      return raw ? JSON.parse(raw) : null
    } catch { return null }
  }

  function clearSession() {
    try { sessionStorage.removeItem(sessionKey) } catch {}
  }

  function getLocalMap(): Map<string, T[]> {
    if (typeof window === "undefined") return new Map()
    try {
      const raw = localStorage.getItem(storageKey)
      if (raw) return new Map(JSON.parse(raw))
    } catch (e) {
      console.error(`Failed to parse ${storageKey}`, e)
    }
    return new Map()
  }

  function saveLocalMap(cache: Map<string, T[]>) {
    if (typeof window === "undefined") return
    try { localStorage.setItem(storageKey, JSON.stringify(Array.from(cache.entries()))) } catch {}
  }

  /** 持久缓存条目 key：jobId（+scope）前缀 + 条目签名 + 上下文签名 */
  function localKey(itemsSignature: string, contextSignature: string): string {
    const prefix = scope ? `${jobKey}::${scope}::` : `${jobKey}::`
    return `${prefix}${itemsSignature}-${contextSignature}`
  }

  return { saveSession, loadSession, clearSession, getLocalMap, saveLocalMap, localKey }
}
