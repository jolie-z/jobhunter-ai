export const GREETING_SUPPORTED_PLATFORMS = new Set(["boss", "zhilian", "liepin"])

export function normalizePlatformCode(platform?: string | null): string {
  if (!platform || typeof platform !== "string") return ""
  const p = platform.trim().toLowerCase()
  if (p.includes("51") || p.includes("前程")) return "51job"
  if (p.includes("智联") || p.includes("zhilian")) return "zhilian"
  if (p.includes("猎聘") || p.includes("liepin")) return "liepin"
  if (p.includes("boss")) return "boss"
  return p
}

export function isGreetingSupportedPlatform(platform?: string | null): boolean {
  return GREETING_SUPPORTED_PLATFORMS.has(normalizePlatformCode(platform))
}
