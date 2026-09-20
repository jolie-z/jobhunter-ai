export function replaceAllText(value: string, findText: string, replaceText: string): string {
  if (!findText) return value
  return value.split(findText).join(replaceText)
}

export function splitTagString(input: any): string[] {
  if (Array.isArray(input)) {
    const allTags = input.flatMap((item) => splitTagString(item))
    return Array.from(new Set(allTags))
  }
  if (!input || typeof input !== "string") return []
  const tags = input
    .split(/[\r\n,，、;；/|]+/)
    .map((item) => item.trim())
    .filter(Boolean)
  return Array.from(new Set(tags))
}

export function formatDateMaybeTimestamp(value: string): string {
  const ts = Number(value)
  if (!Number.isNaN(ts) && ts > 100000000000) {
    return new Date(Number(ts)).toLocaleDateString("zh-CN")
  }
  return value || "-"
}

/**
 * 移除简历改写时可能附带的内部证据强度标签（如 [稳]、[需补证]、[补证后可用]、**✅稳** 等）
 */
export function stripConfidenceTags(text: string): string {
  if (!text || typeof text !== "string") return text || ""
  return text
    .replace(/\s*\[(?:稳|需补证|补证后可用)\]/g, "")
    .replace(/\s*\*\*(?:✅稳|⚠️需补证|🔒补证后可用)\*\*/g, "")
}

