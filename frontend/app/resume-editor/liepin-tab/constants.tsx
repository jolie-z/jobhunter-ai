/**
 * Liepin Tab 常量与类型（机械搬迁自 liepin-tab.tsx）
 */
import { createContext, useContext, type ReactNode } from "react"

export function SectionHeader({ title, onEdit, badge }: { title: string; onEdit?: () => void; badge?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
        {title}
        {badge}
      </h3>
      {onEdit && (
        <button
          onClick={onEdit}
          className="text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
        >
          编辑
        </button>
      )}
    </div>
  )
}

import { Button } from "@/components/ui/button"
import { Lock, Loader2 } from "lucide-react"
import { ReportWarnings, ModuleReportNotice } from "../agent-report-shared"

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

export interface LiepinTabProps {
  data: ResumeData | null
  loading: boolean
  onRefresh: () => void
  /** 顶部操作区生成映射报告后 +1，触发本 Tab 重新拉取报告 */
  reportVersion?: number
}

export interface DeleteConfirmTarget {
  fieldName: string
  index: number
  title: string
  description?: string
}

// ========== 模块级子组件（定义在组件外部，避免每次渲染重建导致弹窗重挂载闪烁） ==========

// Section 标题

export const LIEPIN_NOTICE_MAP: Record<string, { keywords: string[]; title: string }> = {
  basic_info: { keywords: ["basic_info", "基本信息"], title: "「基本信息」相关注意事项" },
  self_assessment: { keywords: ["self_assessment", "优势亮点", "自我评价", "summary"], title: "「自我评价」相关注意事项" },
  expectations: { keywords: ["expectations", "求职期望"], title: "「求职期望」相关注意事项" },
  work_experience: { keywords: ["work_experience", "工作经历"], title: "「工作经历」相关注意事项" },
  projects: { keywords: ["projects", "项目经历"], title: "「项目经历」相关注意事项" },
  education: { keywords: ["education", "教育经历"], title: "「教育经历」相关注意事项" },
  certificates: { keywords: ["certificates", "证书"], title: "「资格证书」相关注意事项" },
  skill_tags: { keywords: ["skill_tags", "技能标签"], title: "「技能标签」相关注意事项" },
  languages: { keywords: ["languages", "语言能力"], title: "「语言能力」相关注意事项" },
  additional_info: { keywords: ["additional_info", "附加信息"], title: "「附加信息」相关注意事项" },
}

// 报告警告上下文：组件根提供，SectionCard 按 moduleKey 就地分发
export const LiepinReportWarningsContext = createContext<string[] | undefined>(undefined)


// Dialog 按钮组
function DialogActions({ onCancel, onConfirm, disabled, saving }: { onCancel: () => void; onConfirm: () => void; disabled?: boolean; saving?: boolean }) {
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
function ReadOnlyNote() {
  return (
    <span className="inline-flex items-center gap-0.5 text-[11px] text-gray-400">
      <Lock className="w-3 h-3" />
      仅可通过官网修改
    </span>
  )
}

// ========== 猎聘回写模块清单（key 与后端 liepin_pusher ALL_MODULES 对应） ==========
export const LIEPIN_MODULES = [
  { key: "basic_info", label: "基本信息", anchor: "section-baseInfo" },
  { key: "self_assessment", label: "自我评价", anchor: "section-selfEval" },
  { key: "expectations", label: "求职期望", anchor: "section-expectations" },
  { key: "work_experience", label: "工作经历", anchor: "section-workExp" },
  { key: "projects", label: "项目经历", anchor: "section-projects" },
  { key: "education", label: "教育经历", anchor: "section-education" },
  { key: "certificates", label: "资格证书", anchor: "section-certificates" },
  { key: "skill_tags", label: "技能标签", anchor: "section-skillTags" },
  { key: "languages", label: "语言能力", anchor: "section-languages" },
  { key: "additional_info", label: "附加信息", anchor: "section-additionalInfo" },
] as const

export const MODULE_DEFAULT_SELECTED = Object.fromEntries(LIEPIN_MODULES.map(m => [m.key, true])) as Record<string, boolean>
export const LIEPIN_MODULE_MAP = Object.fromEntries(LIEPIN_MODULES.map(m => [m.key, m.label])) as Record<string, string>

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

