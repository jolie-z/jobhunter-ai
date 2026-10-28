/** Token 数的人类可读缩写（预检弹窗/上传扫描卡共用）。 */
export function formatTokens(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "未知"
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1000)}K`
  return String(Math.round(n))
}
