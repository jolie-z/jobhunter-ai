/**
 * 岗位卡片展示层的数据模型与适配器。
 *
 * 这一层负责把后端归一化后的 `JobData`（55+ 字段、平台为中文、状态为动态中文）
 * 适配成 v0 设计稿所使用的展示模型（精简的 `JobCardData`，平台/状态为枚举）。
 * 仅服务于岗位列表卡片渲染，不改动 `types/job.ts` 中的真实业务类型。
 */

import type { JobData } from "@/types/job"

/* -------------------------------------------------------------------------- */
/*                              展示层枚举与类型                              */
/* -------------------------------------------------------------------------- */

export type Platform = "liepin" | "boss" | "job51" | "zhilian" | "xiaohongshu" | "other"
export type ScoreGrade = "A" | "B" | "C" | "D" | "F"
export type StatusType = "new" | "evaluated" | "applied" | "interview"

/** 岗位卡片渲染所需的精简展示模型 */
export interface JobCardData {
  id: string
  platform: Platform
  company: string
  companySize: string
  industry: string
  title: string
  salary: string
  location: string
  education: string
  experience: string
  /** 10 维度评分求和（满 50） */
  score: number
  maxScore: number
  scoreGrade: ScoreGrade | null
  status: StatusType
  /** 技能标签数组（最多展示 3 个） */
  tags: string[]
  postedAt: string
}

/* -------------------------------------------------------------------------- */
/*                              平台映射（中文→枚举）                          */
/* -------------------------------------------------------------------------- */

const PLATFORM_ALIAS: Record<Platform, string[]> = {
  liepin: ["猎聘"],
  boss: ["boss直聘", "boss", "boos直聘"],
  job51: ["51job", "前程无忧"],
  zhilian: ["智联招聘", "智联"],
  xiaohongshu: ["小红书"],
  other: ["其他", "其他平台"],
}

export const PLATFORM_CONFIG: Record<Platform, { name: string; short: string }> = {
  liepin: { name: "猎聘", short: "猎" },
  boss: { name: "BOSS直聘", short: "B" },
  job51: { name: "51job", short: "51" },
  zhilian: { name: "智联招聘", short: "智" },
  xiaohongshu: { name: "小红书", short: "小" },
  other: { name: "其他平台", short: "他" },
}

/** 把后端的中文平台名映射为枚举（未命中归为 other） */
export function normalizePlatform(raw?: string): Platform {
  const key = (raw ?? "").trim().toLowerCase()
  if (!key) return "other"
  for (const p of Object.keys(PLATFORM_ALIAS) as Platform[]) {
    if (PLATFORM_ALIAS[p].some((alias) => key === alias.toLowerCase())) return p
  }
  return "other"
}

/* -------------------------------------------------------------------------- */
/*                              状态映射（中文→枚举）                          */
/* -------------------------------------------------------------------------- */

/** 状态文本到枚举的归一映射；未命中时返回 null（卡片会回退显示原始中文） */
export function normalizeStatus(raw?: string): StatusType | null {
  const s = (raw ?? "").trim()
  if (!s) return null
  if (s === "新线索" || s === "待人工评估" || s === "不合适" || s === "已下架" || s === "已拒绝") return "new"
  if (s.includes("评估")) return "evaluated"
  if (s.includes("投递")) return "applied"
  if (s.includes("面试") || s.includes("Offer") || s.includes("offer")) return "interview"
  return null
}

/* -------------------------------------------------------------------------- */
/*                              适配器：JobData → 卡片模型                     */
/* -------------------------------------------------------------------------- */

/** 计算 8 维度评分总和（满 40）；任一字段缺失按 0 计 */
export function calcDimTotal(job: JobData): number {
  return (
    (job.roleMatch ?? 0) +
    (job.skillsAlign ?? 0) +
    (job.seniority ?? 0) +
    (job.compensation ?? 0) +
    (job.interviewProb ?? 0) +
    (job.companyStage ?? 0) +
    (job.marketFit ?? 0) +
    (job.growth ?? 0)
  )
}

/** 把 `job.skillReq` 这类逗号/斜杠分隔的字符串拆成标签数组 */
function splitTags(raw?: string): string[] {
  if (!raw) return []
  return raw
    .split(/[,，、/\/\|；;]+/)
    .map((t) => t.trim())
    .filter(Boolean)
    .slice(0, 3)
}

/** 优先取抓取时间，缺失则回退到发布时间 */
function resolvePostedAt(job: JobData): string {
  return job.captureTime || job.publishDate || "—"
}

export function jobDataToJobCard(job: JobData): JobCardData {
  const grade = (job.grade ?? "").trim()
  return {
    id: job.id,
    platform: normalizePlatform(job.platform),
    company: job.companyName || "未知公司",
    companySize: job.companyScale || "—",
    industry: job.industry || "—",
    title: job.jobTitle || "未知岗位",
    salary: job.salary || "—",
    location: job.location || "—",
    education: job.education || "—",
    experience: job.experience || "—",
    score: calcDimTotal(job),
    maxScore: 40,
    scoreGrade: (["A", "B", "C", "D", "F"].includes(grade) ? grade : null) as ScoreGrade | null,
    status: normalizeStatus(job.followStatus) ?? "new",
    tags: splitTags(job.skillReq),
    postedAt: resolvePostedAt(job),
  }
}
