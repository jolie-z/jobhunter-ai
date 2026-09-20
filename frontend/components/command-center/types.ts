export type TabType =
  | "all"
  | "rejected"
  | "review"
  | "ready_to_deliver"
  | "evaluating"
  | "delivered"
  | "failed"

export type StageKey =
  | "scraping"
  | "cleaning"
  | "feishu_sync"
  | "evaluating"
  | "deep_eval"
  | "rewriting"
  | "greeting"
  | "review"
  | "delivering"
  | "done"

export interface StageMeta {
  key: StageKey
  label: string
  icon: string
  desc: string
  requiredConfig?: boolean
}

export const STAGES_META: StageMeta[] = [
  { key: "scraping", label: "平台抓取", icon: "🕷️", desc: "多平台并发爬取与计划上限", requiredConfig: true },
  { key: "cleaning", label: "规则清洗", icon: "🧹", desc: "硬规则过滤与AI侦察兵初筛", requiredConfig: true },
  { key: "feishu_sync", label: "飞书推送", icon: "📤", desc: "写入多维表格数据线索", requiredConfig: true },
  { key: "evaluating", label: "AI初评", icon: "🤖", desc: "八维多因子智能打分与画像", requiredConfig: true },
  { key: "deep_eval", label: "深度评估", icon: "🔍", desc: "高价值岗位深度画像诊断", requiredConfig: false },
  { key: "rewriting", label: "简历改写", icon: "✍️", desc: "针对JD定向定制精修简历", requiredConfig: true },
  { key: "greeting", label: "打招呼语", icon: "💬", desc: "海投通用话术与高情商开场白", requiredConfig: true },
  { key: "review", label: "待审批", icon: "⏸️", desc: "大公司防误投门槛与安检放行", requiredConfig: true },
  { key: "delivering", label: "自动投递", icon: "🚀", desc: "浏览器端自动沟通与发简历", requiredConfig: true },
]

export const PLATFORM_NAMES: Record<string, string> = {
  boss: "BOSS直聘",
  liepin: "猎聘",
  "51job": "51job",
  zhilian: "智联招聘",
  xiaohongshu: "小红书",
}

export interface PlatformTheme {
  key: string
  name: string
  bg: string
  text: string
  badgeBg: string
  border: string
}

export const PLATFORM_THEMES_CONFIG: Record<string, PlatformTheme> = {
  boss: {
    key: "boss",
    name: "BOSS直聘",
    bg: "bg-emerald-500/10",
    text: "text-emerald-600 dark:text-emerald-400",
    badgeBg: "bg-emerald-500",
    border: "border-emerald-500/20",
  },
  liepin: {
    key: "liepin",
    name: "猎聘",
    bg: "bg-orange-500/10",
    text: "text-orange-600 dark:text-orange-400",
    badgeBg: "bg-orange-500",
    border: "border-orange-500/20",
  },
  zhilian: {
    key: "zhilian",
    name: "智联招聘",
    bg: "bg-blue-600/10",
    text: "text-blue-600 dark:text-blue-400",
    badgeBg: "bg-blue-600",
    border: "border-blue-500/20",
  },
  "51job": {
    key: "51job",
    name: "51job",
    bg: "bg-amber-500/10",
    text: "text-amber-600 dark:text-amber-400",
    badgeBg: "bg-amber-500",
    border: "border-amber-500/20",
  },
  xiaohongshu: {
    key: "xiaohongshu",
    name: "小红书",
    bg: "bg-rose-500/10",
    text: "text-rose-600 dark:text-rose-400",
    badgeBg: "bg-rose-500",
    border: "border-rose-500/20",
  },
}

export function getPlatformTheme(platformRaw?: string): PlatformTheme {
  const p = (platformRaw || "").toLowerCase()
  if (p.includes("boss") || p.includes("直聘")) return PLATFORM_THEMES_CONFIG.boss
  if (p.includes("liepin") || p.includes("猎聘")) return PLATFORM_THEMES_CONFIG.liepin
  if (p.includes("zhilian") || p.includes("智联") || p.includes("zhaopin")) return PLATFORM_THEMES_CONFIG.zhilian
  if (p.includes("51") || p.includes("前程")) return PLATFORM_THEMES_CONFIG["51job"]
  if (p.includes("xiaohongshu") || p.includes("红书") || p.includes("xhs")) return PLATFORM_THEMES_CONFIG.xiaohongshu

  return {
    key: "unknown",
    name: platformRaw || "通用平台",
    bg: "bg-zinc-500/10",
    text: "text-zinc-600 dark:text-zinc-400",
    badgeBg: "bg-zinc-600",
    border: "border-zinc-500/20",
  }
}

export const GRADE_COLOR_MAP: Record<string, { bg: string; text: string; border: string }> = {
  A: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400", border: "border-emerald-500/20" },
  B: { bg: "bg-blue-500/10", text: "text-blue-600 dark:text-blue-400", border: "border-blue-500/20" },
  C: { bg: "bg-amber-500/10", text: "text-amber-600 dark:text-amber-400", border: "border-amber-500/20" },
  D: { bg: "bg-zinc-500/10", text: "text-zinc-600 dark:text-zinc-400", border: "border-zinc-500/20" },
  E: { bg: "bg-rose-500/10", text: "text-rose-600 dark:text-rose-400", border: "border-rose-500/20" },
  F: { bg: "bg-red-500/10", text: "text-red-600 dark:text-red-400", border: "border-red-500/20" },
}

/**
 * 格式化时间字符串，展示紧凑而完整的日期与时间（例如："08-27 14:30"）
 */
export function formatFullDateTime(timeStr?: string): string {
  if (!timeStr) return ""
  try {
    const trimmed = timeStr.trim()
    const parts = trimmed.split(" ")
    if (parts.length === 2) {
      const [d, t] = parts
      const datePart = d.length > 5 ? d.slice(5) : d
      return `${datePart} ${t.slice(0, 5)}`
    }
    if (trimmed.includes("T")) {
      return `${trimmed.slice(5, 10)} ${trimmed.slice(11, 16)}`
    }
    return trimmed.slice(5, 16)
  } catch {
    return timeStr
  }
}

