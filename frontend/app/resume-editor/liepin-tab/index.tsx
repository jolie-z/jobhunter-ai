/**
 * LiepinTab 主组件（机械拆分，行为零变化）
 */
"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect, useContext, createContext } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Loader2, Plus, Trash2, User, Lock, ChevronDown, Sparkles, Save, Upload } from "lucide-react"
import { cn } from "@/lib/utils"
import { LIEPIN_MODULES, LIEPIN_MODULE_MAP, LIEPIN_NOTICE_MAP, SectionHeader, LiepinReportWarningsContext, type ResumeData, type ResumeField, type LiepinTabProps } from "./constants"
import { LiepinCitySelector, LiepinCityMultiSelector } from "@/components/ui/liepin-city-selector"
import { LiepinJobSelector } from "@/components/ui/liepin-job-selector"
import { LiepinIndustrySelector } from "@/components/ui/liepin-industry-selector"
import { LiepinSalarySelector } from "@/components/ui/liepin-salary-selector"
import { LiepinYearMonthPicker } from "@/components/ui/liepin-year-month-picker"
import { LiepinCertSelector } from "@/components/ui/liepin-cert-selector"
import { LiepinSkillSelector } from "@/components/ui/liepin-skill-selector"
import { LiepinCatalogue } from "@/components/ui/liepin-catalogue"
import { LIEPIN_WORK_STATUS, LIEPIN_POLITICAL_STATUS, LIEPIN_DEGREE_OPTIONS, LIEPIN_LANGUAGES, LIEPIN_PROFICIENCY_LEVELS, LIEPIN_LANG_LEVELS } from "@/lib/liepin-options"
import { ReportWarnings, ReportUnfilled, ChangedBadge, ModuleChangeSummary, ModuleReportNotice, type PlatformReport } from "../agent-report-shared"
import { savePlatformData, fetchPlatformReport } from "../api-client"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"

import { LiepinCtx } from "./context"
import { useLiepinTabState } from "./state"
import { LiepinAgentModal } from "./agent-modal"
import { SnapshotPicker } from "../snapshot-picker"
import { LiepinAgentReport } from "./sections/LiepinAgentReport"
import { LiepinBasicInfo } from "./sections/LiepinBasicInfo"
import { LiepinSelfAssessment } from "./sections/LiepinSelfAssessment"
import { LiepinExpectations } from "./sections/LiepinExpectations"
import { LiepinWorkExperience } from "./sections/LiepinWorkExperience"
import { LiepinProjects } from "./sections/LiepinProjects"
import { LiepinEducation } from "./sections/LiepinEducation"
import { LiepinCertificates } from "./sections/LiepinCertificates"
import { LiepinSkillTags } from "./sections/LiepinSkillTags"
import { LiepinLanguages } from "./sections/LiepinLanguages"
import { LiepinAdditionalInfo } from "./sections/LiepinAdditionalInfo"

export function LiepinTab(props: LiepinTabProps) {
  const s = useLiepinTabState(props)
  const {
    localData,
    setLocalData,
    saving,
    setSaving,
    toast,
    setToast,
    report,
    setReport,
    reportLoading,
    setReportLoading,
    applyConfirmOpen,
    setApplyConfirmOpen,
    applying,
    setApplying,
    applyFeedback,
    setApplyFeedback,
    savingSnapshot,
    setSavingSnapshot,
    snapshotFeedback,
    setSnapshotFeedback,
    selectedModules,
    setSelectedModules,
    writebackConfirm,
    setWritebackConfirm,
    writebacking,
    setWritebacking,
    writebackFeedback,
    setWritebackFeedback,
    showWritebackDetails,
    setShowWritebackDetails,
    basicInfoDialogOpen,
    setBasicInfoDialogOpen,
    basicInfoForm,
    setBasicInfoForm,
    selfAssessmentEditing,
    setSelfAssessmentEditing,
    selfAssessmentValue,
    setSelfAssessmentValue,
    expectationDialogOpen,
    setExpectationDialogOpen,
    expectationsForm,
    setExpectationsForm,
    editingExpectationIdx,
    setEditingExpectationIdx,
    workExpDialogOpen,
    setWorkExpDialogOpen,
    workExpForm,
    setWorkExpForm,
    editingWorkExpIdx,
    setEditingWorkExpIdx,
    showOptional,
    setShowOptional,
    projectDialogOpen,
    setProjectDialogOpen,
    projectForm,
    setProjectForm,
    editingProjectIdx,
    setEditingProjectIdx,
    educationDialogOpen,
    setEducationDialogOpen,
    educationForm,
    setEducationForm,
    editingEducationIdx,
    setEditingEducationIdx,
    certSelectorOpen,
    setCertSelectorOpen,
    skillSelectorOpen,
    setSkillSelectorOpen,
    languageDialogOpen,
    setLanguageDialogOpen,
    languageForm,
    setLanguageForm,
    editingLanguageIdx,
    setEditingLanguageIdx,
    additionalInfoEditing,
    setAdditionalInfoEditing,
    additionalInfoValue,
    setAdditionalInfoValue,
    deleteTarget,
    setDeleteTarget,
    liepinAgentDiagnosing,
    setLiepinAgentDiagnosing,
    liepinAgentReport,
    setLiepinAgentReport,
    liepinAgentModalOpen,
    setLiepinAgentModalOpen,
    liepinAgentApplying,
    setLiepinAgentApplying,
    liepinRollbackFeedback,
    setLiepinRollbackFeedback,
    liepinRollingBack,
    setLiepinRollingBack,
    handleDispatchLiepinHealerAgent,
    handleLiepinAgentApplyHeal,
    handleRollbackLiepinSnapshot,
    confirmDelete,
    showToast,
    fetchReport,
    fieldChanged,
    itemChanged,
    getNowTime,
    handleApplyReport,
    handleSaveWritebackSource,
    selectedModuleKeys,
    scrollToModule,
    handleWritebackModules,
    persistData,
    updateField,
    handleDeleteItem,
    handleAddItem,
    handleUpdateItem,
    getVal,
    getLabel,
    normalizeIndustries,
    migrateExpectationItem,
    getExpectations,
    emptyExpectationItem,
    openAddExpectation,
    openEditExpectation,
    handleDeleteExpectation,
    updateExpectationField,
    handleSaveExpectation,
    isExpectationValid,
    toggleAllModules,
  } = s

  return (
    <LiepinCtx.Provider value={s}>
      {/* ========== 主渲染 ========== */}
  return (
    <LiepinReportWarningsContext.Provider value={report?.warnings}>
    <div className="flex gap-6 items-start">
      {/* 左侧导航栏 - 简历目录 */}
      <div className="sticky top-6">
        <LiepinCatalogue />
      </div>

      {/* 右侧内容区 */}
      <div className="flex-1 space-y-4 min-w-0">
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

        {/* 0. 主简历映射报告（顶部操作区生成；两步确认应用） */}
        {<LiepinAgentReport />}

        {/* 0.5 模块导航 + 勾选回写（部分模块/全部模块 → 猎聘官网） */}
        <div className="sticky top-0 z-40 bg-white/95 backdrop-blur border border-[#e8e8e8] rounded-lg p-3 mb-4 shadow-sm">
          <div className="flex items-center justify-between gap-2 mb-2">
            <h3 className="text-sm font-bold text-gray-900 shrink-0">猎聘模块回写</h3>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={toggleAllModules}
                className="text-xs text-gray-500 hover:text-[#FF6B00] cursor-pointer"
              >
                {LIEPIN_MODULES.every(m => selectedModules[m.key]) ? "全不选" : "全选"}
              </button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleSaveWritebackSource}
                disabled={savingSnapshot}
                className="h-7 text-xs border-[#FF6B00]/40 text-[#FF6B00] hover:bg-[#FF6B00]/5"
              >
                {savingSnapshot ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}
                {savingSnapshot ? "保存中..." : "保存快照"}
              </Button>
              <SnapshotPicker platform="liepin" onRollback={handleRollbackLiepinSnapshot} rollingBack={liepinRollingBack} />
              {!writebackConfirm ? (
                <Button
                  size="sm"
                  className="h-7 text-xs bg-[#FF6B00] hover:bg-[#e55f00] text-white"
                  onClick={() => setWritebackConfirm(true)}
                  disabled={writebacking}
                >
                  {writebacking ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Upload className="w-3 h-3 mr-1" />}
                  {writebacking ? "回写中..." : `回写选中模块（${selectedModuleKeys().length}）`}
                </Button>
              ) : (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200">
                  <span className="text-xs text-amber-700">将把勾选的 {selectedModuleKeys().length} 个模块写入猎聘官网在线简历，确认？</span>
                  <button type="button" onClick={handleWritebackModules} disabled={writebacking} className="text-xs px-2 py-0.5 rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50">
                    {writebacking ? "回写中..." : "确认回写"}
                  </button>
                  <button type="button" onClick={() => setWritebackConfirm(false)} className="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {LIEPIN_MODULES.map(m => (
              <div key={m.key} className={`flex items-center gap-1 px-2 py-1 rounded-md border text-xs cursor-pointer select-none transition-colors ${
                selectedModules[m.key] ? "border-[#FF6B00]/50 bg-[#FFF7F0] text-[#FF6B00]" : "border-gray-200 bg-white text-gray-500"
              }`}>
                <Checkbox
                  checked={selectedModules[m.key]}
                  onCheckedChange={(v: any) => setSelectedModules(prev => ({ ...prev, [m.key]: !!v }))}
                  className="w-3.5 h-3.5"
                />
                <button type="button" onClick={() => scrollToModule(m.anchor)} className="hover:text-[#e55f00]">
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
                <div className="mt-2 pt-2 border-t border-black/5 space-y-1">
                  {writebackFeedback.details.map((m: any, idx: any) => (
                    <div key={idx} className="flex items-start gap-1.5 text-[11px]">
                      <span className={m.success ? "text-emerald-600 font-bold" : "text-rose-600 font-bold"}>
                        {m.success ? "✓" : "✗"}
                      </span>
                      <span className="font-medium text-gray-700">
                        {LIEPIN_MODULE_MAP[m.module] || m.module}:
                      </span>
                      <span className={m.success ? "text-gray-600" : "text-rose-700 font-medium"}>
                        {m.message}
                      </span>
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

          {/* 猎聘 智能分级诊断与自愈 Agent 行动卡片 */}
          {writebackFeedback && !writebackFeedback.ok && (() => {
            const failedDetails = (writebackFeedback.details || []).filter((d: any) => !d.success)
            const targetModKey = failedDetails.length > 0 ? failedDetails[0].module : (selectedModuleKeys()[0] || "languages")
            const targetModLabel = LIEPIN_MODULE_MAP[targetModKey] || targetModKey

            return (
              <div className="mt-2.5 rounded-lg border border-[#FF6B00]/30 bg-gradient-to-r from-orange-50/90 via-rose-50/70 to-amber-50/60 p-3.5 shadow-sm text-xs">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-[#FF6B00]/15 text-[#FF6B00] border border-[#FF6B00]/30">
                        🤖 猎聘 自愈 Agent 待命
                      </span>
                      <span className="font-medium text-amber-950">
                        检测到【{targetModLabel}】回写复核存在差异或异常
                      </span>
                    </div>
                    <p className="text-[11px] text-amber-900/80 leading-relaxed">
                      若数据实际已在猎聘官网生效，刷新官网即可；若确未生效或遭遇 语言熟练度码值/三级职位级联/1000字限制，可立即派出猎聘自愈 Agent 进行现场深度取证与自愈修复。
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
                      onClick={() => handleDispatchLiepinHealerAgent(targetModKey)}
                      disabled={liepinAgentDiagnosing}
                      className="px-3 py-1.5 rounded-md bg-gradient-to-r from-[#FF6B00] to-rose-600 hover:from-[#e55f00] hover:to-rose-700 text-white font-semibold text-[11px] transition-all cursor-pointer shadow-sm hover:shadow flex items-center gap-1.5 disabled:opacity-50"
                    >
                      {liepinAgentDiagnosing ? "Agent 诊断中..." : `🤖 派出自愈 Agent 深度排查「${targetModLabel}」`}
                    </button>
                  </div>
                </div>
              </div>
            )
          })()}

          {/* 猎聘 自愈备份与撤销条 */}
          {liepinRollbackFeedback && (
            <div className="mt-2.5 flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-xs bg-emerald-50 border border-emerald-200 text-emerald-900 shadow-xs">
              <span className="font-medium">
                ✅ {liepinRollbackFeedback.msg}
              </span>
              <button
                type="button"
                onClick={() => handleRollbackLiepinSnapshot(liepinRollbackFeedback.snapshotId)}
                disabled={liepinRollingBack}
                className="px-2.5 py-1 rounded bg-white hover:bg-gray-50 text-gray-700 font-semibold text-[11px] border border-gray-200 shadow-xs transition-all cursor-pointer shrink-0"
              >
                {liepinRollingBack ? "正在恢复..." : "↩️ 撤销本次自愈 / 恢复备份"}
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
        <div id="section-baseInfo" className="scroll-mt-[260px]">{<LiepinBasicInfo />}</div>

        {/* 2. 优势亮点 */}
        <div id="section-selfEval" className="scroll-mt-[260px]">{<LiepinSelfAssessment />}</div>

        {/* 3. 求职期望 */}
        <div id="section-expectations" className="scroll-mt-[260px]">{<LiepinExpectations />}</div>

        {/* 4. 工作经历 */}
        <div id="section-workExp" className="scroll-mt-[260px]">{<LiepinWorkExperience />}</div>

        {/* 5. 项目经历 */}
        <div id="section-projects" className="scroll-mt-[260px]">{<LiepinProjects />}</div>

        {/* 6. 教育经历 */}
        <div id="section-education" className="scroll-mt-[260px]">{<LiepinEducation />}</div>

        {/* 7. 资格证书 */}
        <div id="section-certificates" className="scroll-mt-[260px]">{<LiepinCertificates />}</div>

        {/* 8. 技能标签 */}
        <div id="section-skillTags" className="scroll-mt-[260px]">{<LiepinSkillTags />}</div>

        {/* 9. 语言能力 */}
        <div id="section-languages" className="scroll-mt-[260px]">{<LiepinLanguages />}</div>

        {/* 10. 附加信息 */}
        <div id="section-additionalInfo" className="scroll-mt-[260px]">{<LiepinAdditionalInfo />}</div>

        <LiepinAgentModal />

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
      </div>
    </div>
    </LiepinReportWarningsContext.Provider>

    </LiepinCtx.Provider>
  )
}
