/**
 * Zhilian Tab 常量、类型与原子组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { Button } from "@/components/ui/button"
import { Loader2, Plus } from "lucide-react"
import { cn } from "@/lib/utils"
import type { PlatformReport } from "../agent-report-shared"

export const PRIMARY = "#2A7BFF"
export const PRIMARY_HOVER = "#1a6ae8"

// ========== 智联回写模块清单（key 与后端 zhilian_write_back ALL_MODULES 对应） ==========
export const ZHILIAN_MODULES = [
  { key: "basic_info", label: "基本信息", anchor: "section-baseInfo" },
  { key: "self_evaluation", label: "自我评价", anchor: "section-selfEval" },
  { key: "job_status", label: "求职状态", anchor: "section-jobStatus" },
  { key: "wanna", label: "求职意向", anchor: "section-wanna" },
  { key: "work_experience", label: "工作经历", anchor: "section-workExp" },
  { key: "education", label: "教育经历", anchor: "section-education" },
  { key: "projects", label: "项目经历", anchor: "section-projects" },
  { key: "training", label: "培训经历", anchor: "section-training" },
  { key: "language", label: "语言能力", anchor: "section-languages" },
  { key: "skill_tags", label: "专业技能", anchor: "section-skills" },
  { key: "certificates", label: "资格证书", anchor: "section-certificates" },
] as const

export const ZHILIAN_MODULE_DEFAULT_SELECTED = Object.fromEntries(ZHILIAN_MODULES.map(m => [m.key, true])) as Record<string, boolean>

export const ZHILIAN_MODULE_MAP: Record<string, string> = {
  basic_info: "基本信息",
  self_evaluation: "自我评价",
  job_status: "求职状态",
  wanna: "求职意向",
  work_experience: "工作经历",
  education: "教育经历",
  projects: "项目经历",
  training: "培训经历",
  language: "语言能力",
  skill_tags: "专业技能",
  certificates: "资格证书",
}

export interface FeedbackDetail {
  module: string
  success: boolean
  message: string
}

export interface DiagnosticInfo {
  type?: string
  title?: string
  root_cause?: string
  suggestion?: string
  items?: Array<{
    module?: string
    module_label?: string
    field_label?: string
    current_len?: number
    max_len?: number
    overflow?: number
    reason?: string
    suggestion?: string
  }>
}

export interface WritebackFeedbackState {
  msg: string
  ok: boolean
  time?: string
  details?: FeedbackDetail[]
  output?: string
  diagnostic?: DiagnosticInfo
  overflow_violations?: any[]
}

// ========== Types ==========

export interface ZhilianProfile {
  name: string
  gender: string
  genderTranslation?: string
  birthyear: string
  birthmonth: string
  mobile?: string
  email: string
  currentCity: string
  currentCityTranslation?: string
  currentProvince: string
  currentProvinceTranslation?: string
  currentIdentity: string
  currentIdentityTranslation?: string
  currentStatus: string
  currentStatusTranslation?: string
  eduHighestLevel: string
  eduHighestLevelTranslation?: string
  maritalStatus: string
  maritalStatusTranslation?: string
  politicalAffiliation?: string
  politicalAffiliationTranslation?: string
  addressCampus?: string
  yearStartWorking?: string
  monthStartWorking?: string
  height?: string
  weight?: string
  nationality?: string
  fullPhotoUrl?: string
  [key: string]: any
}

export interface ZhilianWanna {
  title?: string
  preferredJobNature: string
  preferredJobNatureTranslation?: string
  pnewPreferredJobType: string
  pnewPreferredJobTypeTranslation?: string
  preferredLocation: string
  preferredLocationTranslation?: string
  pnewPreferredIndustry: string
  pnewPreferredIndustryTranslation?: string
  preferredSalaryMin: number
  preferredSalaryMax: number
  preferredSalaryTranslation?: string
  [key: string]: any
}

export interface ZhilianWorkExp {
  companyName: string
  jobTitle: string
  wnewJobTypeTranslation?: string
  wnewJobSubTypeTranslation?: string
  wnewIndustryTranslation?: string
  startDate: number
  endDate: number
  startDateFormat?: string
  endDateFormat?: string
  workDesc: string
  skillTagsTranslation?: string
  salaryTranslation?: string
  internshipWork?: string
  [key: string]: any
}

export interface ZhilianEduExp {
  eduSchoolName: string
  eduDepartment?: string
  eduMajorV: string
  eduBackground: string
  eduBackgroundTranslation?: string
  eduStartDate: number
  eduEndDate: number
  eduStartDateFormat?: string
  eduEndDateFormat?: string
  eduFullTime?: string
  [key: string]: any
}

export interface ZhilianProjectExp {
  proExpProjectName: string
  proExpPosition?: string
  proExpStartDate: number
  proExpEndDate: number
  proExpStartDateFormat?: string
  proExpEndDateFormat?: string
  proExpProjectDesc?: string
  proExpProjectDuty?: string
  affiliatedCompany?: string
  [key: string]: any
}

export interface ZhilianTraining {
  trainName?: string
  trainCourse?: string
  trainStartDate?: number
  trainEndDate?: number
  [key: string]: any
}

export interface ZhilianLanguage {
  langLanguageT: string
  langLSProficiency: string
  langRWProficiency: string
  langCertificates?: string
  langCertificatesFormat?: { certificateId: string; certificateName: string; certificateScore: string }[]
  [key: string]: any
}

export interface ZhilianSkill {
  proskillName: string
  proskillLevel: string
  proskillType?: string
  proskillUseTime?: string
  [key: string]: any
}

export interface ZhilianCert {
  certUserdefName: string
  certDate: number
  certDateFormat?: string
  certType?: string
  certSubType?: string
  [key: string]: any
}

export interface ZhilianSelfEval {
  selfEvaContent: string
  selfEvaTitle?: string
  [key: string]: any
}

export interface ZhilianData {
  profile: ZhilianProfile
  jobStatus: { jobState: string; jobStateCode: string }
  wanna: ZhilianWanna[]
  workExperience: ZhilianWorkExp[]
  education: ZhilianEduExp[]
  project: ZhilianProjectExp[]
  training: ZhilianTraining[]
  language: ZhilianLanguage[]
  professionalSkills: ZhilianSkill[]
  certificate: ZhilianCert[]
  selfEvaluation: ZhilianSelfEval[]
}

export interface DeleteConfirmTarget {
  fieldName: keyof ZhilianData
  index: number
  title: string
  description?: string
}

export interface ZhilianTabProps {
  data: any | null
  loading: boolean
  onRefresh: () => void
  /** 顶部操作区生成映射报告后 +1，触发本 Tab 重新拉取报告 */
  reportVersion?: number
}

// ========== Helper functions ==========

export function formatTimestamp(ts: number): string {
  if (!ts) return ""
  const d = new Date(ts)
  return `${d.getFullYear()}.${d.getMonth() + 1}`
}

export function formatPeriod(start: number, end: number, isCurrent?: boolean | string): string {
  const s = formatTimestamp(start)
  const isNow = isCurrent === true || isCurrent === "true" || !end || end === 0
  const e = isNow ? "至今" : formatTimestamp(end)
  return `${s}-${e}`
}

// ========== Module-level sub-components ==========

// 个人信息板块对应的映射 path 集合（其余顶层 path 即板块 key）
export const _ZHILIAN_BASIC_PATHS = new Set([
  "name", "gender", "currentIdentity", "birthyear", "birthmonth",
  "yearStartWorking", "monthStartWorking", "hukouProvinceId", "hukouCityId",
  "currentProvince", "currentCity", "currentCityDistrictId", "politicalAffiliation",
  "phone", "email", "age", "education_degree", "work_years", "profile",
])

export function _zhilianModuleKey(path: string): string {
  const head = path.includes(".") ? path.split(".")[0] : path
  if (head === "job_status" || head === "jobStatus") return "job_status"
  if (head === "workExperience") return "work_experience"
  if (head === "selfEvaluation") return "self_evaluation"
  if (head === "project" || head === "projectExperience") return "projects"
  if (_ZHILIAN_BASIC_PATHS.has(head)) return "basic_info"
  return head
}

// 「已修改」标识数据源：报告字段变更 + apply 后持久化的 applied_paths（刷新不丢）
export function _zhilianChangedModuleKeys(report?: PlatformReport | null): Set<string> {
  const keys = new Set<string>()
  for (const f of report?.fields || []) {
    if (f.changed) keys.add(_zhilianModuleKey(f.path))
  }
  for (const p of report?.applied_paths || []) {
    keys.add(_zhilianModuleKey(String(p)))
  }
  return keys
}

export function SectionHeader({ title, required, onAdd, onEdit, editLabel, changed }: {
  title: string
  required?: boolean
  onAdd?: () => void
  onEdit?: () => void
  editLabel?: string
  changed?: boolean
}) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-base font-bold text-gray-900 flex items-center gap-1">
        {title}
        {required && <span className="text-xs text-gray-400 font-normal">必填</span>}
        {changed && (
          <span className="text-[10px] font-normal px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 border border-emerald-200">
            已修改
          </span>
        )}
      </h3>
      <div className="flex items-center gap-3">
        {onEdit && (
          <button onClick={onEdit} className="text-sm cursor-pointer" style={{ color: PRIMARY }}>
            {editLabel || "编辑"}
          </button>
        )}
        {onAdd && (
          <button onClick={onAdd} className="text-sm cursor-pointer flex items-center gap-0.5" style={{ color: PRIMARY }}>
            <Plus className="w-3.5 h-3.5" />
            添加
          </button>
        )}
      </div>
    </div>
  )
}

export function SectionCard({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("bg-white border border-gray-200 rounded-lg p-5 mb-4", className)}>
      {children}
    </div>
  )
}

export function InlineEditActions({ onCancel, onSave, saving }: { onCancel: () => void; onSave: () => void; saving?: boolean }) {
  return (
    <div className="flex gap-3 mt-4 pt-3 border-t border-gray-100">
      <Button
        size="sm"
        onClick={onSave}
        disabled={saving}
        className="text-white"
        style={{ backgroundColor: PRIMARY }}
      >
        {saving ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : null}
        保存并更新
      </Button>
      <Button size="sm" variant="outline" onClick={onCancel} className="border-gray-300 text-gray-600">
        取消
      </Button>
    </div>
  )
}

export function FormRow({ label, children, required }: { label: string; children: React.ReactNode; required?: boolean }) {
  return (
    <div className="flex items-start gap-3 mb-3">
      <label className="w-24 shrink-0 text-sm text-gray-600 pt-2 text-right">
        {label}{required && <span className="text-red-500 ml-0.5">*</span>}:
      </label>
      <div className="flex-1">{children}</div>
    </div>
  )
}

export function RadioGroup({ options, value, onChange }: {
  options: { code: string; label: string }[] | string[]
  value: string
  onChange: (v: string) => void
}) {
  const items = options.map(o => typeof o === "string" ? { code: o, label: o } : o)
  return (
    <div className="flex flex-wrap gap-2">
      {items.map(item => (
        <button
          key={item.code}
          onClick={() => onChange(item.code)}
          className={cn(
            "px-3 py-1.5 text-sm rounded border transition-colors",
            value === item.code
              ? "border-current text-white"
              : "border-gray-300 text-gray-600 hover:border-gray-400"
          )}
          style={value === item.code ? { backgroundColor: PRIMARY, borderColor: PRIMARY } : {}}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

export function SimpleSelect({ options, value, onChange, placeholder }: {
  options: { code: string; label: string }[] | string[]
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  const items = options.map(o => typeof o === "string" ? { code: o, label: o } : o)
  return (
    <select
      className="w-full h-9 px-3 text-sm border border-gray-300 rounded-md bg-white focus:outline-none focus:ring-1"
      style={{ ["--tw-ring-color" as any]: PRIMARY }}
      value={value}
      onChange={e => onChange(e.target.value)}
    >
      <option value="">{placeholder || "请选择"}</option>
      {items.map(item => (
        <option key={item.code} value={item.code}>{item.label}</option>
      ))}
    </select>
  )
}
