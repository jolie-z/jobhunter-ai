/**
 * Job51 Tab 常量与类型（机械搬迁自 51job-tab.tsx）
 */
import { createContext, useContext } from "react"
import { Lock, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ChangedBadge, ModuleReportNotice } from "../agent-report-shared"

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

export interface Job51TabProps {
  data: ResumeData | null
  loading: boolean
  onRefresh: () => void
  reportVersion?: number
}

export interface DeleteConfirmTarget {
  fieldName: string
  index: number
  title: string
  description?: string
}

export interface FeedbackDetail {
  module: string
  success: boolean
  message: string
  suggestion?: string
  diagnosis?: string
}

export interface WritebackFeedbackState {
  msg: string
  ok: boolean
  time?: string
  details?: FeedbackDetail[]
  output?: string
}

// ========== 模块级子组件（定义在组件外部，避免每次渲染重建导致弹窗重挂载闪烁） ==========

export const BRAND = "#FF6B00"

// ========== 51job 回写模块清单（key 与后端 job51_write_back ALL_MODULES 对应） ==========
export const JOB51_MODULES = [
  { key: "basic_info", label: "基本信息", anchor: "section-baseInfo" },
  { key: "self_introduction", label: "个人优势", anchor: "section-selfEval" },
  { key: "intentions", label: "求职意向", anchor: "section-intentions" },
  { key: "works", label: "工作经历", anchor: "section-workExp" },
  { key: "projects", label: "项目经历", anchor: "section-projects" },
  { key: "educations", label: "教育经历", anchor: "section-education" },
  { key: "language", label: "语言能力", anchor: "section-languages" },
  { key: "skills", label: "专业技能", anchor: "section-skills" },
  { key: "certifications", label: "资格证书", anchor: "section-certifications" },
] as const

export const JOB51_MODULE_DEFAULT_SELECTED = Object.fromEntries(JOB51_MODULES.map(m => [m.key, true])) as Record<string, boolean>
export const JOB51_MODULE_MAP = Object.fromEntries(JOB51_MODULES.map(m => [m.key, m.label])) as Record<string, string>

// 从映射报告中计算变更模块列表（useMemo 避免重复计算）
export function _computeChangedModuleKeys(report?: any): Set<string> {
  const keys: string[] = []
  // ① 报告字段变更对比（应用前预览）
  for (const f of report?.fields || []) {
    if (f.changed) {
      const modKey = f.path.includes('.') ? f.path.split('.')[0] : f.path
      if (!keys.includes(modKey)) keys.push(modKey)
    }
  }
  // ② 「已修改」标识：apply 成功写入后后端持久化的 applied_paths（刷新不丢）
  for (const p of report?.applied_paths || []) {
    const modKey = String(p).includes('.') ? String(p).split('.')[0] : String(p)
    if (!keys.includes(modKey)) keys.push(modKey)
  }
  return new Set(keys)
}

// 职位类目需手动调整的警告提示（解析 agent-map 报告的 warnings）
export function JobFunctionWarningBar({ warnings }: { warnings?: string[] }) {
  const jobWarnings = (warnings || []).filter(w => w.includes("工作经历") && w.includes("职位") && (w.includes("无一模一样的匹配") || w.includes("手动调整")))
  if (jobWarnings.length === 0) return null
  return (
    <div className="mb-3 px-3 py-2 rounded-lg bg-amber-50 border border-amber-300 text-xs text-amber-700">
      请调整以下工作经历的职位类目：
      <ul className="ml-3 mt-1 list-disc space-y-0.5">
        {jobWarnings.slice(0, 3).map((w, i) => (
          <li key={i}>{w.replace(/⚠/g, "")}</li>
        ))}
        {jobWarnings.length > 3 && <li>...共{jobWarnings.length}条，请点击编辑调整</li>}
      </ul>
    </div>
  )
}

// Section 标题（增加 changed 徽章显示）
export function SectionHeader({ title, onEdit, changed }: { title: string; onEdit?: () => void; changed?: boolean }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-base font-bold text-gray-900">{title}{changed && <span className="ml-2"><ChangedBadge /></span>}</h3>
      {onEdit && (
        <button
          onClick={onEdit}
          className="text-sm text-[#FF6B00] hover:text-[e5-5f00] cursor-pointer"
        >
          编辑
        </button>
      )}
    </div>
  )
}

// 卡片容器
// 模块级警告分发：SectionCard id → 关键词/标题（警告由组件根 Provider 提供）
export const JOB51_REPORT_WARNINGS_CONTEXT = createContext<string[] | undefined>(undefined)
export const JOB51_NOTICE_MAP: Record<string, { keywords: string[]; title: string }> = {
  "basic-info": { keywords: ["basic_info", "基本信息"], title: "「基本信息」相关注意事项" },
  "self-introduction": { keywords: ["self_introduction", "selfIntroduction", "自我介绍", "个人优势", "summary"], title: "「个人优势」相关注意事项" },
  intentions: { keywords: ["intentions", "求职意向"], title: "「求职意向」相关注意事项" },
  "work-experience": { keywords: ["works数组", "workFunction", "workIndustry", "workType"], title: "「工作经历」相关注意事项" },
  "project-experience": { keywords: ["projects", "项目经历"], title: "「项目经历」相关注意事项" },
  education: { keywords: ["educations", "教育经历", "education"], title: "「教育经历」相关注意事项" },
  "language-ability": { keywords: ["language", "语言"], title: "「语言能力」相关注意事项" },
  skills: { keywords: ["skills数组", "专业技能"], title: "「专业技能」相关注意事项" },
  certifications: { keywords: ["certifications", "证书"], title: "「资格证书」相关注意事项" },
}

export function SectionCard({ children, id, changed }: { children: React.ReactNode; id?: string; changed?: boolean }) {
  const reportWarnings = useContext(JOB51_REPORT_WARNINGS_CONTEXT)
  const notice = id ? JOB51_NOTICE_MAP[id] : undefined
  return (
    <div id={id} className="bg-white border border-[#e8e8e8] rounded-lg p-5 mb-4 scroll-mt-28 relative">
      {notice && reportWarnings && reportWarnings.length > 0 && (
        <ModuleReportNotice warnings={reportWarnings} matchKeywords={notice.keywords} title={notice.title} />
      )}
      {changed && (
        <div className="absolute top-4 right-4">
          <ChangedBadge />
        </div>
      )}
      {children}
    </div>
  )
}

// Dialog 按钮组
export function DialogActions({ onCancel, onConfirm, disabled, saving }: { onCancel: () => void; onConfirm: () => void; disabled?: boolean; saving?: boolean }) {
  return (
    <div className="flex justify-end gap-3 mt-5">
      <Button
        variant="outline"
        onClick={onCancel}
        className="border-gray-300 text-gray-600"
      >
        取消
      </Button>
      <Button
        onClick={onConfirm}
        disabled={disabled || saving}
        className="bg-[#FF6B00] hover:bg-[#e55f00] text-white"
      >
        {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : null}
        确定
      </Button>
    </div>
  )
}

// 只读字段标注
export function ReadOnlyNote() {
  return (
    <span className="inline-flex items-center gap-0.5 text-[11px] text-gray-400">
      <Lock className="w-3 h-3" />
      仅可通过官网修改
    </span>
  )
}

// 语言能力等级选项
export const LANGUAGE_ABILITY_LEVELS = [
  { code: "4", label: "简单沟通/读写" },
  { code: "5", label: "读写熟练" },
  { code: "6", label: "听说读写流利" },
]



