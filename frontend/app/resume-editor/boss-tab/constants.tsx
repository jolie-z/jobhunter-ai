/**
 * BOSS Tab 常量、类型与原子组件（拆分自 boss-tab.tsx，机械搬迁零行为变化）
 */
import { Loader2 } from "lucide-react"

export const BOSS_PRIMARY = "#00beab"

// ========== BOSS 回写模块清单（key 与后端 boss_write_back 模块集合对应；name/phone/email/微信号/工作年限为 HARD_SKIP 不可回写） ==========
export const BOSS_MODULES = [
  { key: "personal_advantage", label: "个人优势" },
  { key: "expectations", label: "求职期望" },
  { key: "work_experience", label: "工作经历" },
  { key: "projects", label: "项目经历" },
  { key: "education", label: "教育经历" },
  { key: "certificates", label: "资格证书" },
  { key: "overseas", label: "驻外选项" },
  { key: "baseinfo", label: "基本信息" },
] as const

export const BOSS_MODULE_DEFAULT_SELECTED = Object.fromEntries(BOSS_MODULES.map(m => [m.key, true])) as Record<string, boolean>
export const BOSS_MODULE_MAP = Object.fromEntries(BOSS_MODULES.map(m => [m.key, m.label])) as Record<string, string>
// 模块变动汇总用：报告 path 的 root 键 → 中文名（boss 顶层散键统一归基本信息/期望行业）
export const BOSS_MODULE_LABELS: Record<string, string> = {
  ...BOSS_MODULE_MAP,
  basic_info: "基本信息",
  industry: "期望行业",
  job_status: "求职状态",
}

export interface FeedbackDetail {
  module: string
  success: boolean
  message: string
}

export interface WritebackFeedbackState {
  msg: string
  ok: boolean
  time?: string
  details?: FeedbackDetail[]
  output?: string
}

// 基本信息卡片覆盖的字段 path（任一被映射写入即整体标「已修改」）
export const BASE_INFO_PATHS = ["name", "phone", "email", "wechat", "gender", "job_status", "birth_month", "work_start_date", "experience_years", "education_degree"]

// 「已修改」徽章：成功应用主简历映射的板块标识（数据源为 report.applied_paths，后端持久化刷新不丢）
export function ModifiedBadge({ show }: { show: boolean }) {
  if (!show) return null
  return (
    <span
      title="该板块内容曾因应用主简历映射而被修改"
      className="ml-2 inline-flex items-center align-middle px-1.5 py-0.5 rounded bg-green-100 text-green-700 border border-green-200 text-[10px] leading-tight font-medium"
    >
      已修改
    </span>
  )
}

export interface ResumeField {
  label: string
  required: boolean
  type: string
  options?: string[]
  max_length?: number
  current_value: any
  fields?: Record<string, ResumeField>
}

export interface ResumeData {
  [key: string]: ResumeField
}

export interface BossTabProps {
  data: ResumeData | null
  loading: boolean
  onRefresh: () => void
  onSave?: (data: ResumeData) => void
  /** 顶部操作区生成映射报告后 +1，触发本 Tab 重新拉取报告 */
  reportVersion?: number
}

export interface BossOptions {
  job_titles: string[]
  salary_ranges: string[]
  cities: string[]
  job_statuses: string[]
  education_levels: string[]
  work_years: string[]
}

// 默认框架骨架：清空数据后仍保留完整的板块结构（值为空）
export const DEFAULT_BOSS_FRAMEWORK: ResumeData = {
  name: { label: "姓名", required: true, type: "text", current_value: "" },
  phone: { label: "电话", required: true, type: "text", current_value: "" },
  email: { label: "邮箱", required: false, type: "text", current_value: "" },
  wechat: { label: "微信号", required: false, type: "text", current_value: "" },
  gender: { label: "性别", required: true, type: "radio", options: ["男", "女"], current_value: "" },
  job_status: { label: "求职状态", required: true, type: "select", current_value: "" },
  birth_month: { label: "出生年月", required: false, type: "yearmonth", current_value: "" },
  work_start_date: { label: "参加工作时间", required: false, type: "yearmonth", current_value: "" },
  experience_years: { label: "工作年限", required: false, type: "text", current_value: "" },
  education_degree: { label: "学历", required: false, type: "text", current_value: "" },
  personal_advantage: { label: "个人优势", required: false, type: "textarea", max_length: 1000, current_value: "" },
  expectations: { label: "求职期望", required: true, type: "array", current_value: [] },
  work_experience: { label: "工作经历", required: true, type: "array", current_value: [] },
  projects: { label: "项目经历", required: false, type: "array", current_value: [] },
  education: { label: "教育经历", required: true, type: "array", current_value: [] },
  certificates: { label: "资格证书", required: false, type: "array", current_value: [] },
  overseas: { label: "驻外选项", required: false, type: "object", current_value: {} },
}
