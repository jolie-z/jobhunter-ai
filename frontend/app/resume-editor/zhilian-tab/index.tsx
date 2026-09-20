/**
 * ZhilianTab 主组件（机械拆分，行为零变化）
 */
"use client"

import { Button } from "@/components/ui/button"
import { Loader2, Trash2 } from "lucide-react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { ModuleReportNotice } from "../agent-report-shared"
import { ZhilianCatalogue } from "@/components/ui/zhilian-catalogue"
import { PRIMARY, type ZhilianTabProps } from "./constants"
import { ZhilianCtx } from "./context"
import { useZhilianTabState } from "./state"
import { ZhilianWritebackPanel } from "./writeback-panel"
import { ZhilianAgentModal } from "./agent-modal"
import {
  ZhilianProfile, ZhilianSelfEval, ZhilianJobStatus, ZhilianWanna, ZhilianWorkExperience,
  ZhilianEducation, ZhilianProjects, ZhilianTraining, ZhilianLanguages, ZhilianSkills,
  ZhilianCertificates, ZhilianWorks, ZhilianAgentReport,
} from "./sections-loader"

export function ZhilianTab({ data, loading, onRefresh, reportVersion = 0 }: ZhilianTabProps) {
  const s = useZhilianTabState({ data, loading, onRefresh, reportVersion })
  const {
    localData, toast, report, deleteTarget, setDeleteTarget, confirmDelete,
    diffDrawerOpen, setDiffDrawerOpen, probeReport, selectedDiffIndices, setSelectedDiffIndices,
    selfHealing, handleConfirmSelfHeal,
  } = s

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin" style={{ color: PRIMARY }} />
        <span className="ml-2 text-gray-600">加载中...</span>
      </div>
    )
  }

  if (!data || !localData) {
    return (
      <div className="text-center py-12 text-gray-500">
        <div className="text-4xl mb-4">📭</div>
        <div>暂无智联招聘数据</div>
        <div className="text-sm mt-2">请先运行采集脚本</div>
        <Button onClick={onRefresh} className="mt-4 text-white" style={{ backgroundColor: PRIMARY }}>
          刷新数据
        </Button>
      </div>
    )
  }

  return (
    <ZhilianCtx.Provider value={s}>
    <div className="flex gap-6 items-start">
      {/* 左侧导航栏 - 简历目录 */}
      <div className="sticky top-6">
        <ZhilianCatalogue />
      </div>

      {/* 右侧内容区 */}
      <div className="flex-1 space-y-4 min-w-0">
        {/* Toast */}
        {toast && (
          <div className={cn(
            "fixed top-4 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-md text-sm text-white shadow-lg transition-all",
            toast.type === "success" ? "bg-green-500" : "bg-red-500"
          )}>
            {toast.message}
          </div>
        )}

        {/* 0a. 主简历映射报告（顶部操作区「映射」生成；审核后应用到本地数据） */}
        <ZhilianAgentReport />

        <ZhilianWritebackPanel />


        {/* 1. 基本信息 */}
        <div id="section-baseInfo" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["profile", "基本信息", "hukou", "currentProvince", "currentCity", "politicalAffiliation"]} title="「基本信息」相关注意事项" />)}<ZhilianProfile /></div>

        {/* 2. 自我评价 */}
        <div id="section-selfEval" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["self_evaluation", "自我评价", "selfEvaluation", "summary"]} title="「自我评价」相关注意事项" />)}<ZhilianSelfEval /></div>

        {/* 3. 求职状态 */}
        <div id="section-jobStatus" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["job_status", "jobStatus", "求职状态"]} title="「求职状态」相关注意事项" />)}<ZhilianJobStatus /></div>

        {/* 4. 求职意向 */}
        <div id="section-wanna" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["wanna", "求职意向"]} title="「求职意向」相关注意事项" />)}<ZhilianWanna /></div>

        {/* 5. 工作经历 */}
        <div id="section-workExp" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["work_experience", "workExperience", "工作经历"]} title="「工作经历」相关注意事项" />)}<ZhilianWorkExperience /></div>

        {/* 6. 教育经历 */}
        <div id="section-education" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["education", "教育经历"]} title="「教育经历」相关注意事项" />)}<ZhilianEducation /></div>

        {/* 7. 项目经历 */}
        <div id="section-projects" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["projects", "项目经历", "projectExperience"]} title="「项目经历」相关注意事项" />)}<ZhilianProjects /></div>

        {/* 8. 培训经历 */}
        <div id="section-training" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["training", "培训经历"]} title="「培训经历」相关注意事项" />)}<ZhilianTraining /></div>

        {/* 9. 语言能力 */}
        <div id="section-languages" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["language", "语言能力"]} title="「语言能力」相关注意事项" />)}<ZhilianLanguages /></div>

        {/* 10. 专业技能 */}
        <div id="section-skills" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["skill_tags", "professionalSkills", "专业技能", "技能"]} title="「专业技能」相关注意事项" />)}<ZhilianSkills /></div>

        {/* 11. 资格证书 */}
        <div id="section-certificates" className="scroll-mt-[260px]">{report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["certificate", "证书"]} title="「资格证书」相关注意事项" />)}<ZhilianCertificates /></div>

        {/* 12. 作品展示 */}
        <div id="section-works" className="scroll-mt-[260px]"><ZhilianWorks /></div>

        {/* 二次确认删除弹窗 (Double Check Alert Dialog) */}
        <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
          <AlertDialogContent className="sm:max-w-[425px]">
            <AlertDialogHeader>
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-600 mt-0.5">
                  <Trash2 className="h-4 w-4" />
                </div>
                <div className="flex-1">
                  <AlertDialogTitle className="text-sm font-semibold text-gray-900 leading-snug">
                    {deleteTarget?.title || "确认删除？"}
                  </AlertDialogTitle>
                  <AlertDialogDescription className="text-xs text-gray-500 mt-1.5 leading-relaxed">
                    {deleteTarget?.description || "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。"}
                  </AlertDialogDescription>
                </div>
              </div>
            </AlertDialogHeader>
            <AlertDialogFooter className="mt-4 flex gap-2 sm:justify-end">
              <AlertDialogCancel
                onClick={() => setDeleteTarget(null)}
                className="h-8 text-xs border-gray-200 text-gray-700 hover:bg-gray-50 hover:text-gray-900 cursor-pointer"
              >
                取消
              </AlertDialogCancel>
              <AlertDialogAction
                onClick={confirmDelete}
                className="h-8 text-xs bg-red-500 hover:bg-red-600 text-white font-medium shadow-sm transition-all active:scale-[0.98] cursor-pointer"
              >
                确认删除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* 官网结构差分审核抽屉 (Diff Drawer) */}
        {diffDrawerOpen && probeReport && (
          <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-200">
            <div className="bg-white rounded-xl shadow-2xl border border-gray-200 w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
              {/* Drawer Header */}
              <div className="px-5 py-4 border-b border-gray-100 bg-gray-50/70 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-base font-bold text-gray-900">🔍 智联官网数据结构探测报告</span>
                  <span className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                    probeReport.is_synced ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
                  }`}>
                    {probeReport.is_synced ? "已完全对齐" : "检测到结构差异"}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setDiffDrawerOpen(false)}
                  className="text-gray-400 hover:text-gray-600 text-sm p-1 rounded-md hover:bg-gray-100 cursor-pointer"
                >
                  ✕
                </button>
              </div>

              {/* Drawer Body */}
              <div className="p-5 overflow-y-auto space-y-4 flex-1 text-xs">
                {/* 概览统计卡片 */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="p-3 rounded-lg bg-blue-50/60 border border-blue-100">
                    <div className="text-gray-500 text-[11px]">正常对齐模块</div>
                    <div className="text-base font-bold text-blue-900 mt-0.5">
                      {probeReport.modules?.intact?.length || 0} 个
                    </div>
                  </div>
                  <div className="p-3 rounded-lg bg-amber-50/60 border border-amber-100">
                    <div className="text-gray-500 text-[11px]">字段变动发现</div>
                    <div className="text-base font-bold text-amber-900 mt-0.5">
                      {probeReport.fields?.diffs?.length || 0} 项
                    </div>
                  </div>
                  <div className="p-3 rounded-lg bg-emerald-50/60 border border-emerald-100">
                    <div className="text-gray-500 text-[11px]">资格证书标准字典</div>
                    <div className="text-base font-bold text-emerald-900 mt-0.5">
                      {probeReport.dictionaries?.[0]?.official_count || 155} 项
                    </div>
                  </div>
                </div>

                {/* 字段变动明细列表 */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-semibold text-gray-800">
                      待同步字段列表 ({probeReport.fields?.diffs?.length || 0})
                    </span>
                    {probeReport.fields?.diffs?.length > 0 && (
                      <button
                        type="button"
                        onClick={() => {
                          if (selectedDiffIndices.length === probeReport.fields.diffs.length) {
                            setSelectedDiffIndices([])
                          } else {
                            setSelectedDiffIndices(probeReport.fields.diffs.map((_: any, i: number) => i))
                          }
                        }}
                        className="text-blue-600 hover:text-blue-700 text-[11px] font-medium cursor-pointer"
                      >
                        {selectedDiffIndices.length === probeReport.fields.diffs.length ? "取消全选" : "全选"}
                      </button>
                    )}
                  </div>

                  {!probeReport.fields?.diffs || probeReport.fields.diffs.length === 0 ? (
                    <div className="py-6 text-center text-gray-400 bg-gray-50 rounded-lg border border-dashed border-gray-200">
                      🎉 官网全部模块与字段结构与本地完全一致，无需自愈！
                    </div>
                  ) : (
                    <div className="space-y-2 max-h-64 overflow-y-auto border border-gray-200 rounded-lg p-2 bg-gray-50/40">
                      {probeReport.fields.diffs.map((diff: any, idx: number) => {
                        const isChecked = selectedDiffIndices.includes(idx)
                        return (
                          <div
                            key={idx}
                            onClick={() => {
                              setSelectedDiffIndices(prev =>
                                prev.includes(idx) ? prev.filter(i => i !== idx) : [...prev, idx]
                              )
                            }}
                            className={`p-2.5 rounded-md border flex items-center justify-between gap-3 cursor-pointer transition-all ${
                              isChecked
                                ? "bg-white border-blue-300 shadow-xs"
                                : "bg-gray-50/60 border-gray-200 text-gray-400 opacity-75"
                            }`}
                          >
                            <div className="flex items-center gap-2.5">
                              <Checkbox checked={isChecked} className="w-3.5 h-3.5" />
                              <div>
                                <div className="font-medium text-gray-900 flex items-center gap-1.5">
                                  <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-100 text-gray-700 font-mono">
                                    {diff.module_label || diff.module}
                                  </span>
                                  <span>{diff.field_label || diff.field}</span>
                                  <span className="text-[10px] text-gray-400 font-mono">({diff.field})</span>
                                </div>
                                <div className="text-[10px] text-gray-500 mt-0.5">
                                  {diff.description}
                                </div>
                              </div>
                            </div>
                            <span className="text-[10px] font-semibold text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200/60 shrink-0">
                              + 新增字段
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>

              {/* Drawer Footer */}
              <div className="px-5 py-3 border-t border-gray-100 bg-gray-50/70 flex items-center justify-between">
                <span className="text-[11px] text-gray-400">
                  点击自愈前将自动生成时间戳安全备份，支持随时一键回滚
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setDiffDrawerOpen(false)}
                    className="px-3 py-1.5 rounded-md border border-gray-300 bg-white hover:bg-gray-50 text-gray-700 font-medium text-xs cursor-pointer"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmSelfHeal}
                    disabled={selfHealing || selectedDiffIndices.length === 0}
                    className="px-4 py-1.5 rounded-md bg-blue-600 hover:bg-blue-700 text-white font-semibold text-xs shadow-sm hover:shadow transition-all disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
                  >
                    {selfHealing ? "正在自愈同步..." : `确认同步 (${selectedDiffIndices.length}) 项结构`}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        <ZhilianAgentModal />
      </div>
    </div>
    </ZhilianCtx.Provider>
  )
}
