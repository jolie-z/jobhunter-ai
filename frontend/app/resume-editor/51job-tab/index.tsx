/**
 * Job51Tab 主组件（机械拆分，行为零变化）
 */
"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect, useRef, useCallback, useMemo, createContext, useContext } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Loader2, Plus, Trash2, User, Lock, FileText, Settings, Save, Upload, Sparkles, Edit, X } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Job51YearMonthPicker } from "@/components/ui/51job-year-month-picker"
import { Job51SalaryPicker } from "@/components/ui/51job-salary-picker"
import { Job51AreaSelector } from "@/components/ui/51job-area-selector"
import { Job51Cascader } from "@/components/ui/51job-cascader"
import { Job51CityPicker } from "@/components/ui/51job-city-picker"
import { Job51FuntypePicker } from "@/components/ui/51job-funtype-picker"
import { Job51IndustryPicker } from "@/components/ui/51job-industry-picker"
import { Job51MajorPicker } from "@/components/ui/51job-major-picker"
import { Job51SkillPicker } from "@/components/ui/51job-skill-picker"
import { Job51CertPicker } from "@/components/ui/51job-cert-picker"
import { Job51Catalogue } from "@/components/ui/51job-catalogue"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"
import { ReportWarnings, ReportUnfilled, ChangedBadge, ModuleReportNotice, type PlatformReport } from "../agent-report-shared"
import { savePlatformData, fetchPlatformReport } from "../api-client"

import { Job51Ctx } from "./context"
import { JOB51_MODULES, JOB51_MODULE_MAP, JOB51_REPORT_WARNINGS_CONTEXT, JOB51_MODULE_DEFAULT_SELECTED, JOB51_NOTICE_MAP, SectionCard, SectionHeader, ReadOnlyNote, DialogActions, type Job51TabProps } from "./constants"
import { useJob51TabState } from "./state"
import { Job51AgentModal } from "./agent-modal"
import { SnapshotPicker } from "../snapshot-picker"
import { Job51BasicInfo } from "./sections/Job51BasicInfo"
import { Job51SelfIntroduction } from "./sections/Job51SelfIntroduction"
import { Job51Intentions } from "./sections/Job51Intentions"
import { Job51WorkExperience } from "./sections/Job51WorkExperience"
import { Job51Projects } from "./sections/Job51Projects"
import { Job51Education } from "./sections/Job51Education"
import { Job51LanguageAbility } from "./sections/Job51LanguageAbility"
import { Job51Portfolio } from "./sections/Job51Portfolio"
import { Job51Skills } from "./sections/Job51Skills"
import { Job51Certifications } from "./sections/Job51Certifications"
import { Job51AgentReport } from "./sections/Job51AgentReport"

export {
  Job51BasicInfo,
  Job51SelfIntroduction,
  Job51Intentions,
  Job51WorkExperience,
  Job51Projects,
  Job51Education,
  Job51LanguageAbility,
  Job51Portfolio,
  Job51Skills,
  Job51Certifications,
}

export function Job51Tab(props: Job51TabProps) {
  const s = useJob51TabState(props)
  const {
    data,
    loading,
    onRefresh,
    selectedModules,
    toggleAllModules,
    setSelectedModules,
    writebackConfirm,
    setWritebackConfirm,
    writebacking,
    writebackFeedback,
    showWritebackDetails,
    setShowWritebackDetails,
    savingSnapshot,
    snapshotFeedback,
    report,
    job51AgentDiagnosing,
    job51RollbackFeedback,
    job51RollingBack,
    deleteTarget,
    setDeleteTarget,
    contentRef,
    handleDispatchJob51HealerAgent,
    handleRollbackJob51Snapshot,
    handleSaveWritebackSource,
    selectedModuleKeys,
    handleWritebackModules,
    confirmDelete,
    toast,
  } = s

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin text-[#FF6B00]" />
        <span className="ml-2 text-gray-600">加载中...</span>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="text-center py-12 text-gray-500">
        <div className="text-4xl mb-4">📭</div>
        <div>暂无前程无忧数据</div>
        <div className="text-sm mt-2">请先运行采集脚本</div>
        <Button onClick={onRefresh} className="mt-4 bg-[#FF6B00] hover:bg-[#e55f00] text-white">
          刷新数据
        </Button>
      </div>
    )
  }

  return (
    <Job51Ctx.Provider value={s}>
    <JOB51_REPORT_WARNINGS_CONTEXT.Provider value={report?.warnings}>
    <div className="flex gap-6 items-start">
      {/* 左侧导航栏 - 简历目录 (常驻悬浮吸顶) */}
      <div className="sticky top-6">
        <Job51Catalogue />
      </div>

      {/* 右侧内容区 */}
      <div ref={contentRef} className="flex-1 space-y-4 min-w-0">
        {/* Toast 提示 */}
        {toast && (
          <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[9999]">
            <div
              className={`px-4 py-2 rounded-md text-sm text-white shadow-lg ${
                toast.type === "success" ? "bg-green-500" : "bg-red-500"
              }`}
            >
              {toast.message}
            </div>
          </div>
        )}
        {/* 0a. 主简历映射报告（顶部操作区「映射」生成；审核后应用到本地数据） */}
        {<Job51AgentReport />}

        {/* 0. 模块勾选回写（部分模块/全部模块 → 51job 官网；基本信息 HARD_SKIP 仅可通过官网修改） */}
        <div className="sticky top-0 z-40 bg-white/95 backdrop-blur border border-[#e8e8e8] rounded-lg p-3 mb-4 shadow-sm">
          <div className="flex items-center justify-between gap-2 mb-2">
            <h3 className="text-sm font-bold text-gray-900 shrink-0 flex items-center gap-2">
              51job 模块回写
              <span className="text-[10px] text-gray-400 font-normal">(需先保存快照，再点击回写)</span>
            </h3>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={toggleAllModules}
                className="text-xs text-gray-500 hover:text-[#FF6B00] cursor-pointer"
              >
                {JOB51_MODULES.every((m: any) => selectedModules[m.key]) ? "全不选" : "全选"}
              </button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleSaveWritebackSource}
                disabled={savingSnapshot}
                className="h-7 text-xs border-[#FF6B00]/40 text-[#FF6B00] hover:bg-[#FF6B00]/5 cursor-pointer"
              >
                {savingSnapshot ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}
                {savingSnapshot ? "保存中..." : "保存快照"}
              </Button>
              <SnapshotPicker platform="51job" onRollback={handleRollbackJob51Snapshot} rollingBack={job51RollingBack} />
              {!writebackConfirm ? (
                <Button
                  size="sm"
                  className="h-7 text-xs bg-[#FF6B00] hover:bg-[#e55f00] text-white cursor-pointer"
                  onClick={() => setWritebackConfirm(true)}
                  disabled={writebacking}
                >
                  {writebacking ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Upload className="w-3 h-3 mr-1" />}
                  {writebacking ? "回写中..." : `回写选中模块（${selectedModuleKeys().length}）`}
                </Button>
              ) : (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200">
                  <span className="text-xs text-amber-700">将把勾选的 {selectedModuleKeys().length} 个模块写入 51job 官网在线简历，确认？</span>
                  <button type="button" onClick={handleWritebackModules} disabled={writebacking} className="text-xs px-2 py-0.5 rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50 cursor-pointer">
                    {writebacking ? "回写中..." : "确认回写"}
                  </button>
                  <button type="button" onClick={() => setWritebackConfirm(false)} className="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50 cursor-pointer">取消</button>
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {JOB51_MODULES.map((m: any) => (
              <div key={m.key} className={`flex items-center gap-1 px-2 py-1 rounded-md border text-xs cursor-pointer select-none transition-colors ${
                selectedModules[m.key] ? "border-[#FF6B00]/50 bg-[#FFF7F0] text-[#FF6B00]" : "border-gray-200 bg-white text-gray-500"
              }`}>
                <Checkbox
                  checked={selectedModules[m.key]}
                  onCheckedChange={(v: any) => setSelectedModules(prev => ({ ...prev, [m.key]: !!v }))}
                  className="w-3.5 h-3.5"
                />
                <button type="button" onClick={() => {
                  const el = document.getElementById(m.anchor)
                  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
                }} className="hover:text-[#e55f00]">
                  {m.label}
                </button>
              </div>
            ))}
          </div>
          {/* 就地反馈：常驻展示执行时间戳，结构化排版与错误解析 */}
          {writebackFeedback && (
            <div
              role="status"
              className={`mt-2.5 rounded-lg text-xs border p-3 shadow-sm transition-all ${
                writebackFeedback.ok
                  ? "bg-emerald-50/90 border-emerald-200 text-emerald-900"
                  : "bg-rose-50/90 border-rose-200 text-rose-900"
              }`}
            >
              <div className="flex items-center gap-2">
                {writebackFeedback.time && (
                  <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-black/5 font-semibold shrink-0 select-none">
                    [{writebackFeedback.time}]
                  </span>
                )}
                <span className="font-semibold flex-1 leading-snug">
                  {writebackFeedback.ok ? "✓ " : "✗ "}
                  {writebackFeedback.msg}
                </span>
                {writebackFeedback.output && (
                  <button
                    type="button"
                    onClick={() => setShowWritebackDetails(v => !v)}
                    className="text-[11px] text-gray-500 hover:text-gray-900 underline decoration-dotted ml-auto shrink-0 cursor-pointer"
                  >
                    {showWritebackDetails ? "收起日志" : "查看日志"}
                  </button>
                )}
              </div>

              {/* 结构化模块回写状态明细 */}
              {Array.isArray(writebackFeedback.details) && writebackFeedback.details.length > 0 && (
                <div className="mt-2 pt-2 border-t border-black/5 space-y-1.5">
                  {writebackFeedback.details.map((m: any, idx: any) => (
                    <div key={idx} className="text-[11px] space-y-1">
                      <div className="flex items-start gap-1.5">
                        <span className={m.success ? "text-emerald-600 font-bold" : "text-rose-600 font-bold"}>
                          {m.success ? "✓" : "✗"}
                        </span>
                        <span className="font-medium text-gray-700">
                          {JOB51_MODULE_MAP[m.module] || m.module}:
                        </span>
                        <span className={m.success ? "text-gray-600" : "text-rose-700 font-medium"}>
                          {m.message}
                        </span>
                      </div>
                      {/* 智能诊断与调整方向建议 */}
                      {m.suggestion && (
                        <div className="ml-4 px-2.5 py-1 rounded bg-rose-100/80 border border-rose-200/90 text-rose-800 text-[11px] leading-relaxed">
                          {m.suggestion}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* 可折叠底层原始日志输出 */}
              {showWritebackDetails && writebackFeedback.output && (
                <pre className="mt-2.5 p-2 rounded bg-black/85 text-gray-200 text-[10px] font-mono whitespace-pre-wrap max-h-40 overflow-y-auto leading-relaxed border border-black/10 select-text">
                  {writebackFeedback.output}
                </pre>
              )}
            </div>
          )}

          {/* 51job 智能分级诊断与自愈 Agent 行动卡片 */}
          {writebackFeedback && !writebackFeedback.ok && (() => {
            const failedDetails = (writebackFeedback.details || []).filter(d => !d.success)
            const targetModKey = failedDetails.length > 0 ? failedDetails[0].module : (selectedModuleKeys()[0] || "certifications")
            const targetModLabel = JOB51_MODULE_MAP[targetModKey] || targetModKey

            return (
              <div className="mt-2.5 rounded-lg border border-[#FF6B00]/30 bg-gradient-to-r from-orange-50/90 via-amber-50/70 to-rose-50/60 p-3.5 shadow-sm text-xs">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-[#FF6B00]/15 text-[#FF6B00] border border-[#FF6B00]/30">
                        🤖 51job 自愈 Agent 待命
                      </span>
                      <span className="font-medium text-amber-950">
                        检测到【{targetModLabel}】回写复核存在差异或异常
                      </span>
                    </div>
                    <p className="text-[11px] text-amber-900/80 leading-relaxed">
                      若数据实际已在 51job 官网生效，刷新官网页面即可；若确未生效或遭遇 20条配额墙/100004 参数校验，可立即派出 51job 自愈 Agent 进行现场深度取证与自愈修复。
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={handleWritebackModules}
                      disabled={writebacking}
                      className="px-2.5 py-1.5 rounded-md border border-gray-300 bg-white hover:bg-gray-50 text-gray-700 font-medium text-[11px] transition-colors cursor-pointer shadow-xs disabled:opacity-50"
                    >
                      🔄 重新尝试
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDispatchJob51HealerAgent(targetModKey)}
                      disabled={job51AgentDiagnosing}
                      className="px-3 py-1.5 rounded-md bg-gradient-to-r from-[#FF6B00] to-orange-600 hover:from-[#e55f00] hover:to-orange-700 text-white font-semibold text-[11px] transition-all cursor-pointer shadow-sm hover:shadow flex items-center gap-1.5 disabled:opacity-50"
                    >
                      {job51AgentDiagnosing ? "Agent 诊断中..." : `🤖 派出自愈 Agent 深度排查「${targetModLabel}」`}
                    </button>
                  </div>
                </div>
              </div>
            )
          })()}

          {/* 51job 自愈备份与撤销条 */}
          {job51RollbackFeedback && (
            <div className="mt-2.5 flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-xs bg-emerald-50 border border-emerald-200 text-emerald-900 shadow-xs">
              <span className="font-medium">
                ✅ {job51RollbackFeedback.msg}
              </span>
              <button
                type="button"
                onClick={() => handleRollbackJob51Snapshot(job51RollbackFeedback.snapshotId)}
                disabled={job51RollingBack}
                className="px-2.5 py-1 rounded bg-white hover:bg-gray-50 text-gray-700 font-semibold text-[11px] border border-gray-200 shadow-xs transition-all cursor-pointer shrink-0"
              >
                {job51RollingBack ? "正在恢复..." : "↩️ 撤销本次自愈 / 恢复备份"}
              </button>
            </div>
          )}
          {snapshotFeedback && (
            <div
              role="status"
              className={`mt-2 flex items-start gap-1.5 px-2.5 py-1.5 rounded-md text-xs border ${
                snapshotFeedback.ok
                  ? "bg-emerald-50/90 border-emerald-200 text-emerald-800"
                  : "bg-rose-50/90 border-rose-200 text-rose-800"
              }`}
            >
              {snapshotFeedback.time && (
                <span className="font-mono text-[11px] px-1 py-0.5 rounded bg-black/5 font-semibold shrink-0 select-none">
                  [{snapshotFeedback.time}]
                </span>
              )}
              <span className="leading-tight flex-1 break-all">{snapshotFeedback.msg}</span>
            </div>
          )}
        </div>

        {/* 1. 基本信息 */}
        <div id="section-baseInfo" className="scroll-mt-[260px]">{<Job51BasicInfo />}</div>

        {/* 2. 个人优势 */}
        <div id="section-selfEval" className="scroll-mt-[260px]">{<Job51SelfIntroduction />}</div>

        {/* 3. 求职意向 */}
        <div id="section-intentions" className="scroll-mt-[260px]">{<Job51Intentions />}</div>

        {/* 4. 工作经历 */}
        <div id="section-workExp" className="scroll-mt-[260px]">{<Job51WorkExperience />}</div>

        {/* 5. 项目经历 */}
        <div id="section-projects" className="scroll-mt-[260px]">{<Job51Projects />}</div>

        {/* 6. 教育经历 */}
        <div id="section-education" className="scroll-mt-[260px]">{<Job51Education />}</div>

        {/* 7. 语言能力 */}
        <div id="section-languages" className="scroll-mt-[260px]">{<Job51LanguageAbility />}</div>

        {/* 8. 个人作品 */}
        <div id="section-portfolio" className="scroll-mt-[260px]">{<Job51Portfolio />}</div>

        {/* 9. 专业技能 */}
        <div id="section-skills" className="scroll-mt-[260px]">{<Job51Skills />}</div>

        {/* 10. 资格证书 */}
        <div id="section-certifications" className="scroll-mt-[260px]">{<Job51Certifications />}</div>

        {/* 二次确认删除弹窗 (Double Check Alert Dialog) */}
        <AlertDialog open={!!deleteTarget} onOpenChange={(open: any) => { if (!open) setDeleteTarget(null) }}>
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

        <Job51AgentModal />
      </div>

      {/* 右侧栏 */}
    </div>
    </JOB51_REPORT_WARNINGS_CONTEXT.Provider>

    </Job51Ctx.Provider>
  )
}
