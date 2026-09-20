/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { Button } from "@/components/ui/button"
import { Loader2, Sparkles } from "lucide-react"
import { PRIMARY } from "../constants"
import { ReportWarnings, ReportUnfilled, ReportFieldEdits } from "../../agent-report-shared"

import { useZhilianCtx } from "../context"

export function ZhilianAgentReport() {
  const {
    reportLoading,
    report,
    applyConfirmOpen,
    setApplyConfirmOpen,
    applying,
    applyFeedback,
    fetchReport,
    handleApplyReport,
  } = useZhilianCtx()
    if (reportLoading) {
      return (
        <div className="mb-4 flex items-center gap-1.5 text-xs text-gray-400">
          <Loader2 className="w-3 h-3 animate-spin" />检查映射报告...
        </div>
      )
    }
    if (!report || !report.success) return null
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-5 mb-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-base font-bold text-gray-900 flex items-center gap-1.5">
            <Sparkles className="w-4 h-4" style={{ color: PRIMARY }} />主简历映射报告
          </h3>
          {report.generated_at && (
            <span className="text-[11px] text-gray-400">生成于 {report.generated_at.replace("T", " ").slice(0, 16)}</span>
          )}
        </div>

        <ReportWarnings warnings={report.warnings} className="mb-3" />

        <div className="text-xs text-gray-500 mb-1.5">
          将把主简历中的 {report.fields.length} 个字段应用到智联本地数据；主简历未提及的字段保留官网原值。应用后点「保存快照」即可作为回写数据源
        </div>

        {/* 应用按钮（两步确认：选中 → 黄色确认栏 → 执行） */}
        <div className="mt-3">
          {!applyConfirmOpen ? (
            <Button
              onClick={() => setApplyConfirmOpen(true)}
              disabled={applying}
              className="text-white text-sm"
              style={{ backgroundColor: PRIMARY }}
            >
              {applying && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}
              {applying ? "应用中..." : `应用映射到智联（${report.fields.length} 个字段）`}
            </Button>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200">
              <span className="text-xs text-amber-700">将覆盖智联本地 {report.fields.length} 个字段，未提及字段保留原值，确认？</span>
              <button type="button" onClick={handleApplyReport} className="text-xs px-2 py-0.5 rounded bg-amber-500 text-white hover:bg-amber-600">确认应用</button>
              <button type="button" onClick={() => setApplyConfirmOpen(false)} className="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
            </div>
          )}
          {/* 就地反馈：常驻展示执行时间戳，直至下一次执行覆盖 */}
          {applyFeedback && (
            <div
              role="status"
              className={`mt-2 flex items-start gap-1.5 px-2.5 py-1.5 rounded-md text-xs border ${
                applyFeedback.ok
                  ? "bg-emerald-50/90 border-emerald-200 text-emerald-800"
                  : "bg-rose-50/90 border-rose-200 text-rose-800"
              }`}
            >
              {applyFeedback.time && (
                <span className="font-mono text-[11px] px-1 py-0.5 rounded bg-black/5 font-semibold shrink-0 select-none">
                  [{applyFeedback.time}]
                </span>
              )}
              <span className="leading-tight flex-1 break-all">{applyFeedback.msg}</span>
            </div>
          )}
        </div>

        <ReportUnfilled unfilled={report.unfilled} />
        <ReportFieldEdits platform="zhilian" report={report} onSaved={fetchReport} />

        {/* 变更汇总 */}
        {report?.fields && report.fields.some(f => f.changed) && (
          <div className="mb-3 px-3 py-2 rounded-lg bg-blue-50 border border-blue-300 text-xs text-blue-700">
            本次映射有以下模块发生变动：
            <ul className="ml-3 mt-1 list-disc space-y-0.5">
              {[...new Set(report.fields.filter(f => f.changed).map(f => f.path.split('.')[0]))].map(modKey => {
                const labelMap: Record<string, string> = {
                  self_evaluation: "自我评价", profile: "个人优势",
                  wanna: "求职意向", jobStatus: "求职状态",
                  work_experience: "工作经历", projects: "项目经历",
                  education: "教育经历", training: "培训经历",
                  language: "语言能力", professionalSkills: "专业技能",
                  certificate: "资格证书"
                }
                return <li key={modKey}>{labelMap[modKey] || modKey}</li>
              })}
            </ul>
          </div>
        )}
      </div>
    )
}
