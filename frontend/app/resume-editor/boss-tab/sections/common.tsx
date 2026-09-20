/**
 * BOSS Tab 分区组件（机械搬迁自 boss-tab.tsx，行为零变化）
 */
"use client"

import { useBossCtx } from "../context"
import { countryRegions, durationOptions, COUNTRY_MAX_SELECT, LANGUAGE_MAX_SELECT } from "@/lib/overseas-options"

import type { ResumeField } from "../constants"
import { BossExpectations } from "./expectations"
import { BossWorkExperience } from "./work-experience"
import { BossProjects } from "./projects"
import { BossEducation } from "./education"
import { BossOverseas } from "./expectations"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Loader2, Plus, Edit, Trash2, Save, X, Upload, Sparkles, Lock } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { ReportWarnings, ReportUnfilled, ModuleChangeSummary, ModuleReportNotice, ReportFieldEdits } from "../../agent-report-shared"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"
import { JobTitleSelector } from "@/components/ui/job-title-selector"
import { IndustrySelector } from "@/components/ui/industry-selector"
import { CitySelector } from "@/components/ui/city-selector"
import { SalarySelector } from "@/components/ui/salary-selector"
import { OtherCitySelector } from "@/components/ui/other-city-selector"
import { DateRangePicker } from "@/components/ui/date-range-picker"
import { DegreeSelector } from "@/components/ui/degree-selector"
import { YearRangePicker } from "@/components/ui/year-range-picker"
import { CertificateSelector } from "@/components/ui/certificate-selector"
import { CountrySelector } from "@/components/ui/country-selector"
import { LanguageSelector } from "@/components/ui/language-selector"
import { YearMonthPicker } from "@/components/ui/year-month-picker"
import { ExpectationEditor } from "@/components/ui/expectation-editor"
import { ModifiedBadge, BOSS_PRIMARY, BOSS_MODULE_LABELS, BOSS_MODULES, BOSS_MODULE_MAP } from "../constants"



export function BossJobStatus({ field }: { field: ResumeField }) {
  const {
    data, localData, bossOptions, saving, report, reportLoading, showToast,
    editingField, editValue, setEditingField, setEditValue, setLocalData,
    deletingItem, setDeletingItem, handleDelete, parsePeriod, fetchReport,
    handleApplyReport, handleSaveWritebackSource, handleWritebackModules,
    handleRollbackBossSnapshot, handleBossAgentApplyHeal, handleDispatchBossHealerAgent,
    selectedModules, setSelectedModules, selectedModuleKeys, toggleAllModules,
    writebacking, writebackConfirm, setWritebackConfirm, writebackFeedback,
    showWritebackDetails, setShowWritebackDetails, savingSnapshot, snapshotFeedback,
    bossAgentDiagnosing, bossAgentReport, bossAgentModalOpen, setBossAgentModalOpen,
    bossAgentApplying, bossRollbackFeedback, bossRollingBack,
    editingExpectationIdx, setEditingExpectationIdx, expectationDialogOpen, setExpectationDialogOpen,
    editingWorkExpIdx, setEditingWorkExpIdx, workExpDialogOpen, setWorkExpDialogOpen, workExpForm, setWorkExpForm,
    editingProjectIdx, setEditingProjectIdx, projectDialogOpen, setProjectDialogOpen, projectForm, setProjectForm,
    editingEducationIdx, setEditingEducationIdx, educationDialogOpen, setEducationDialogOpen, educationForm, setEducationForm,
    certSelectorOpen, setCertSelectorOpen,
    overseasDialogOpen, setOverseasDialogOpen, overseasForm, setOverseasForm,
    countrySelectorOpen, setCountrySelectorOpen, languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen, baseInfoForm, setBaseInfoForm,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying,
    persistData, buildModuleUpdate, isSectionModified, displayData, applyFeedback,
    startEdit, saveEdit, cancelEdit,
    overseasModified,
    onRefresh, onSave, reportVersion,
  } = useBossCtx()
    const isEditing = editingField === "job_status"

    return (
      <Card className="mb-4">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">{field.label}<ModifiedBadge show={isSectionModified("job_status")} /></CardTitle>
            {!isEditing && (
              <Button variant="ghost" size="sm" onClick={() => startEdit("job_status", field.current_value)}>
                <Edit className="w-4 h-4 mr-1" />
                编辑
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {isEditing ? (
            <div className="flex items-center gap-2">
              <Select value={editValue} onValueChange={setEditValue}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="请选择求职状态" />
                </SelectTrigger>
                <SelectContent>
                  {field.options?.map((opt) => (
                    <SelectItem key={opt} value={opt}>
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button size="sm" onClick={() => saveEdit("job_status")}>
                <Save className="w-4 h-4" />
              </Button>
              <Button size="sm" variant="outline" onClick={cancelEdit}>
                <X className="w-4 h-4" />
              </Button>
            </div>
          ) : (
            <div className="text-lg">{field.current_value || "未设置"}</div>
          )}
        </CardContent>
      </Card>
    )
  }


export function BossCertificates({ field }: { field: ResumeField }) {
  const {
    data, localData, bossOptions, saving, report, reportLoading, showToast,
    editingField, editValue, setEditingField, setEditValue, setLocalData,
    deletingItem, setDeletingItem, handleDelete, parsePeriod, fetchReport,
    handleApplyReport, handleSaveWritebackSource, handleWritebackModules,
    handleRollbackBossSnapshot, handleBossAgentApplyHeal, handleDispatchBossHealerAgent,
    selectedModules, setSelectedModules, selectedModuleKeys, toggleAllModules,
    writebacking, writebackConfirm, setWritebackConfirm, writebackFeedback,
    showWritebackDetails, setShowWritebackDetails, savingSnapshot, snapshotFeedback,
    bossAgentDiagnosing, bossAgentReport, bossAgentModalOpen, setBossAgentModalOpen,
    bossAgentApplying, bossRollbackFeedback, bossRollingBack,
    editingExpectationIdx, setEditingExpectationIdx, expectationDialogOpen, setExpectationDialogOpen,
    editingWorkExpIdx, setEditingWorkExpIdx, workExpDialogOpen, setWorkExpDialogOpen, workExpForm, setWorkExpForm,
    editingProjectIdx, setEditingProjectIdx, projectDialogOpen, setProjectDialogOpen, projectForm, setProjectForm,
    editingEducationIdx, setEditingEducationIdx, educationDialogOpen, setEducationDialogOpen, educationForm, setEducationForm,
    certSelectorOpen, setCertSelectorOpen,
    overseasDialogOpen, setOverseasDialogOpen, overseasForm, setOverseasForm,
    countrySelectorOpen, setCountrySelectorOpen, languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen, baseInfoForm, setBaseInfoForm,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying,
    persistData, buildModuleUpdate, isSectionModified, displayData, applyFeedback,
    startEdit, saveEdit, cancelEdit,
    overseasModified,
    onRefresh, onSave, reportVersion,
  } = useBossCtx()
    // 兼容旧数据格式：可能是字符串数组或对象数组
    const rawValue = field.current_value || []
    const certificates: string[] = rawValue.map((item: any) =>
      typeof item === "string" ? item : (item.cert_name || item.name || "")
    ).filter(Boolean)

    const handleChange = async (newValue: string[]) => {
      if (!localData) return
      const updatedData = buildModuleUpdate("certificates", newValue)
      if (!updatedData) return
      const ok = await persistData(updatedData)
      if (!ok) return
      setLocalData(updatedData)
      if (onSave) onSave(updatedData)
    }

    return (
      <Card className="mb-4">
        {report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["certificates", "证书"]} title="「资格证书」相关注意事项" />)}
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              {field.label}
            </CardTitle>
            <Button variant="outline" size="sm" onClick={() => setCertSelectorOpen(true)}>
              <Plus className="w-4 h-4 mr-1" />
              添加
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <CertificateSelector
            value={certificates}
            onChange={handleChange}
            externalOpen={certSelectorOpen}
            onExternalClose={() => setCertSelectorOpen(false)}
          />
        </CardContent>
      </Card>
    )
  }


export function BossIndustry({ field }: { field: ResumeField }) {
  const {
    data, localData, bossOptions, saving, report, reportLoading, showToast,
    editingField, editValue, setEditingField, setEditValue, setLocalData,
    deletingItem, setDeletingItem, handleDelete, parsePeriod, fetchReport,
    handleApplyReport, handleSaveWritebackSource, handleWritebackModules,
    handleRollbackBossSnapshot, handleBossAgentApplyHeal, handleDispatchBossHealerAgent,
    selectedModules, setSelectedModules, selectedModuleKeys, toggleAllModules,
    writebacking, writebackConfirm, setWritebackConfirm, writebackFeedback,
    showWritebackDetails, setShowWritebackDetails, savingSnapshot, snapshotFeedback,
    bossAgentDiagnosing, bossAgentReport, bossAgentModalOpen, setBossAgentModalOpen,
    bossAgentApplying, bossRollbackFeedback, bossRollingBack,
    editingExpectationIdx, setEditingExpectationIdx, expectationDialogOpen, setExpectationDialogOpen,
    editingWorkExpIdx, setEditingWorkExpIdx, workExpDialogOpen, setWorkExpDialogOpen, workExpForm, setWorkExpForm,
    editingProjectIdx, setEditingProjectIdx, projectDialogOpen, setProjectDialogOpen, projectForm, setProjectForm,
    editingEducationIdx, setEditingEducationIdx, educationDialogOpen, setEducationDialogOpen, educationForm, setEducationForm,
    certSelectorOpen, setCertSelectorOpen,
    overseasDialogOpen, setOverseasDialogOpen, overseasForm, setOverseasForm,
    countrySelectorOpen, setCountrySelectorOpen, languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen, baseInfoForm, setBaseInfoForm,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying,
    persistData, buildModuleUpdate, isSectionModified, displayData, applyFeedback,
    startEdit, saveEdit, cancelEdit,
    overseasModified,
    onRefresh, onSave, reportVersion,
  } = useBossCtx()
    const currentValue = Array.isArray(field.current_value) ? field.current_value : []

    return (
      <Card className="mb-4">
        {report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["industry", "期望行业"]} title="「期望行业」相关注意事项" />)}
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              {field.label}
              <ModifiedBadge show={isSectionModified("industry")} />
              {field.required && <span className="text-red-500 ml-1">*</span>}
              <Badge variant="secondary" className="ml-2">
                {currentValue.length}个
              </Badge>
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <IndustrySelector
            value={currentValue}
            onChange={async (newValue) => {
              // 更新本地数据（同步落盘，否则刷新后丢失）
              if (localData) {
                const updatedData = buildModuleUpdate("industry", newValue)
                if (!updatedData) return
                const ok = await persistData(updatedData)
                if (!ok) return
                setLocalData(updatedData)
                if (onSave) onSave(updatedData)
              }
            }}
            placeholder="请选择期望行业"
          />
        </CardContent>
      </Card>
    )
  }


export function BossTextField({ fieldName, field }: { fieldName: string; field: ResumeField }) {
  const {
    data, localData, bossOptions, saving, report, reportLoading, showToast,
    editingField, editValue, setEditingField, setEditValue, setLocalData,
    deletingItem, setDeletingItem, handleDelete, parsePeriod, fetchReport,
    handleApplyReport, handleSaveWritebackSource, handleWritebackModules,
    handleRollbackBossSnapshot, handleBossAgentApplyHeal, handleDispatchBossHealerAgent,
    selectedModules, setSelectedModules, selectedModuleKeys, toggleAllModules,
    writebacking, writebackConfirm, setWritebackConfirm, writebackFeedback,
    showWritebackDetails, setShowWritebackDetails, savingSnapshot, snapshotFeedback,
    bossAgentDiagnosing, bossAgentReport, bossAgentModalOpen, setBossAgentModalOpen,
    bossAgentApplying, bossRollbackFeedback, bossRollingBack,
    editingExpectationIdx, setEditingExpectationIdx, expectationDialogOpen, setExpectationDialogOpen,
    editingWorkExpIdx, setEditingWorkExpIdx, workExpDialogOpen, setWorkExpDialogOpen, workExpForm, setWorkExpForm,
    editingProjectIdx, setEditingProjectIdx, projectDialogOpen, setProjectDialogOpen, projectForm, setProjectForm,
    editingEducationIdx, setEditingEducationIdx, educationDialogOpen, setEducationDialogOpen, educationForm, setEducationForm,
    certSelectorOpen, setCertSelectorOpen,
    overseasDialogOpen, setOverseasDialogOpen, overseasForm, setOverseasForm,
    countrySelectorOpen, setCountrySelectorOpen, languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen, baseInfoForm, setBaseInfoForm,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying,
    persistData, buildModuleUpdate, isSectionModified, displayData, applyFeedback,
    startEdit, saveEdit, cancelEdit,
    overseasModified,
    onRefresh, onSave, reportVersion,
  } = useBossCtx()
    const isEditing = editingField === fieldName
    const isTextarea = field.type === "textarea"

    return (
      <Card className="mb-4">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              {field.label}
              <ModifiedBadge show={isSectionModified(fieldName)} />
              {field.required && <span className="text-red-500 ml-1">*</span>}
            </CardTitle>
            {!isEditing && (
              <Button variant="ghost" size="sm" onClick={() => startEdit(fieldName, field.current_value)}>
                <Edit className="w-4 h-4 mr-1" />
                编辑
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {isEditing ? (
            <div className="space-y-2">
              {isTextarea ? (
                <>
                  <Textarea
                    value={editValue || ""}
                    onChange={(e) => {
                      if (!field.max_length || e.target.value.length <= field.max_length) {
                        setEditValue(e.target.value)
                      }
                    }}
                    placeholder={`请输入${field.label}`}
                    rows={6}
                    maxLength={field.max_length}
                  />
                  {field.max_length && (
                    <div className="text-xs text-gray-400 text-right">
                      {(editValue || "").length}/{field.max_length}
                    </div>
                  )}
                </>
              ) : (
                <Input
                  value={editValue || ""}
                  onChange={(e) => setEditValue(e.target.value)}
                  placeholder={`请输入${field.label}`}
                />
              )}
              <div className="flex gap-2">
                <Button size="sm" onClick={() => saveEdit(fieldName)}>
                  <Save className="w-4 h-4 mr-1" />
                  保存
                </Button>
                <Button size="sm" variant="outline" onClick={cancelEdit}>
                  <X className="w-4 h-4 mr-1" />
                  取消
                </Button>
              </div>
            </div>
          ) : (
            <div className="text-gray-700 whitespace-pre-wrap">{field.current_value || "未设置"}</div>
          )}
        </CardContent>
      </Card>
    )
  }


export function BossAgentReport() {
  const {
    data, localData, bossOptions, saving, report, reportLoading, showToast,
    editingField, editValue, setEditingField, setEditValue, setLocalData,
    deletingItem, setDeletingItem, handleDelete, parsePeriod, fetchReport,
    handleApplyReport, handleSaveWritebackSource, handleWritebackModules,
    handleRollbackBossSnapshot, handleBossAgentApplyHeal, handleDispatchBossHealerAgent,
    selectedModules, setSelectedModules, selectedModuleKeys, toggleAllModules,
    writebacking, writebackConfirm, setWritebackConfirm, writebackFeedback,
    showWritebackDetails, setShowWritebackDetails, savingSnapshot, snapshotFeedback,
    bossAgentDiagnosing, bossAgentReport, bossAgentModalOpen, setBossAgentModalOpen,
    bossAgentApplying, bossRollbackFeedback, bossRollingBack,
    editingExpectationIdx, setEditingExpectationIdx, expectationDialogOpen, setExpectationDialogOpen,
    editingWorkExpIdx, setEditingWorkExpIdx, workExpDialogOpen, setWorkExpDialogOpen, workExpForm, setWorkExpForm,
    editingProjectIdx, setEditingProjectIdx, projectDialogOpen, setProjectDialogOpen, projectForm, setProjectForm,
    editingEducationIdx, setEditingEducationIdx, educationDialogOpen, setEducationDialogOpen, educationForm, setEducationForm,
    certSelectorOpen, setCertSelectorOpen,
    overseasDialogOpen, setOverseasDialogOpen, overseasForm, setOverseasForm,
    countrySelectorOpen, setCountrySelectorOpen, languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen, baseInfoForm, setBaseInfoForm,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying,
    persistData, buildModuleUpdate, isSectionModified, displayData, applyFeedback,
    startEdit, saveEdit, cancelEdit,
    overseasModified,
    onRefresh, onSave, reportVersion,
  } = useBossCtx()
    if (reportLoading) {
      return (
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <Loader2 className="w-3 h-3 animate-spin" />检查映射报告...
        </div>
      )
    }
    if (!report || !report.success) return null
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-base font-bold text-gray-900 flex items-center gap-1.5">
            <Sparkles className="w-4 h-4" style={{ color: BOSS_PRIMARY }} />主简历映射报告
          </h3>
          {report.generated_at && (
            <span className="text-[11px] text-gray-400">生成于 {report.generated_at.replace("T", " ").slice(0, 16)}</span>
          )}
        </div>

        <ReportWarnings warnings={report.warnings} className="mb-3" />

        <ModuleChangeSummary report={report} moduleLabelMap={BOSS_MODULE_LABELS} />

        <div className="text-xs text-gray-500 mb-1.5">
          将把主简历中的 {report.fields.length} 个字段应用到 BOSS 本地数据；主简历未提及的字段保留官网原值。应用后点「保存快照」即可作为回写数据源
        </div>

        {/* 应用按钮（两步确认：选中 → 黄色确认栏 → 执行） */}
        <div className="mt-3">
          {!applyConfirmOpen ? (
            <Button
              onClick={() => setApplyConfirmOpen(true)}
              disabled={applying}
              className="text-white text-sm"
              style={{ backgroundColor: BOSS_PRIMARY }}
            >
              {applying && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}
              {applying ? "应用中..." : `应用映射到 BOSS直聘（${report.fields.length} 个字段）`}
            </Button>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200">
              <span className="text-xs text-amber-700">将覆盖 BOSS直聘 本地 {report.fields.length} 个字段，未提及字段保留原值，确认？</span>
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
        <ReportFieldEdits platform="boss" report={report} onSaved={fetchReport} />
      </div>
    )
  }


export function BossField({ fieldName, field }: { fieldName: string; field: ResumeField }) {
  const {
    data, localData, bossOptions, saving, report, reportLoading, showToast,
    editingField, editValue, setEditingField, setEditValue, setLocalData,
    deletingItem, setDeletingItem, handleDelete, parsePeriod, fetchReport,
    handleApplyReport, handleSaveWritebackSource, handleWritebackModules,
    handleRollbackBossSnapshot, handleBossAgentApplyHeal, handleDispatchBossHealerAgent,
    selectedModules, setSelectedModules, selectedModuleKeys, toggleAllModules,
    writebacking, writebackConfirm, setWritebackConfirm, writebackFeedback,
    showWritebackDetails, setShowWritebackDetails, savingSnapshot, snapshotFeedback,
    bossAgentDiagnosing, bossAgentReport, bossAgentModalOpen, setBossAgentModalOpen,
    bossAgentApplying, bossRollbackFeedback, bossRollingBack,
    editingExpectationIdx, setEditingExpectationIdx, expectationDialogOpen, setExpectationDialogOpen,
    editingWorkExpIdx, setEditingWorkExpIdx, workExpDialogOpen, setWorkExpDialogOpen, workExpForm, setWorkExpForm,
    editingProjectIdx, setEditingProjectIdx, projectDialogOpen, setProjectDialogOpen, projectForm, setProjectForm,
    editingEducationIdx, setEditingEducationIdx, educationDialogOpen, setEducationDialogOpen, educationForm, setEducationForm,
    certSelectorOpen, setCertSelectorOpen,
    overseasDialogOpen, setOverseasDialogOpen, overseasForm, setOverseasForm,
    countrySelectorOpen, setCountrySelectorOpen, languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen, baseInfoForm, setBaseInfoForm,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying,
    persistData, buildModuleUpdate, isSectionModified, displayData, applyFeedback,
    startEdit, saveEdit, cancelEdit,
    overseasModified,
    onRefresh, onSave, reportVersion,
  } = useBossCtx()
    switch (fieldName) {
      case "job_status":
        return <BossJobStatus field={field} />
      case "expectations":
        return <BossExpectations field={field} />
      case "industry":
        return <BossIndustry field={field} />
      case "work_experience":
        return <BossWorkExperience field={field} />
      case "projects":
        return <BossProjects field={field} />
      case "education":
        return <BossEducation field={field} />
      case "certificates":
        return <BossCertificates field={field} />
      case "overseas":
        return <BossOverseas field={field} />
      default:
        return <BossTextField fieldName={fieldName} field={field} />
    }
  }
