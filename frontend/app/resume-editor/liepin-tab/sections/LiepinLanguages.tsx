/**
 * Liepin Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { SectionHeader } from "../constants"

import { useLiepinCtx } from "../context"
import { LIEPIN_DEGREE_OPTIONS, LIEPIN_WORK_STATUS, LIEPIN_POLITICAL_STATUS, LIEPIN_LANGUAGES, LIEPIN_PROFICIENCY_LEVELS, LIEPIN_LANG_LEVELS } from "@/lib/liepin-options"
import { SectionCard, DialogActions, ReadOnlyNote } from "./shared"
import { ChangedBadge } from "../../agent-report-shared"
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
import { ReportWarnings, ReportUnfilled, ModuleChangeSummary, ModuleReportNotice } from "../../agent-report-shared"
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


export function LiepinLanguages() {
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
  } = useLiepinCtx()

    const items = getVal("languages") || []

    // Migrate old field names to new schema
    const migrateItem = (item: any) => ({
      language: item.language || item.name || "",
      proficiency: item.proficiency || item.degreeName || item.listening_speaking || "",
      level: item.level || item.levelName || item.certificate || "",
    })

    const openAdd = () => {
      setEditingLanguageIdx(null)
      setLanguageForm({ language: "", proficiency: "", level: "" })
      setLanguageDialogOpen(true)
    }

    const openEdit = (index: number) => {
      setEditingLanguageIdx(index)
      setLanguageForm(migrateItem(items[index]))
      setLanguageDialogOpen(true)
    }

    const handleSave = async () => {
      const form = { ...languageForm }
      // For 自定义语言, language field is the custom name
      if (!form.language) return
      if (editingLanguageIdx !== null) {
        await handleUpdateItem("languages", editingLanguageIdx, form)
      } else {
        await handleAddItem("languages", form)
      }
      setLanguageDialogOpen(false)
    }

    const isCustom = languageForm.language === "自定义语言"
    const levelOptions = LIEPIN_LANG_LEVELS[languageForm.language] || []
    const hasLevel = !isCustom && levelOptions.length > 0

    return (
      <SectionCard moduleKey="languages">
        <SectionHeader
          title={getLabel("languages", "语言能力")}
          badge={fieldChanged("languages") ? <ChangedBadge /> : undefined}
        />
        <div className="space-y-3">
          {items.map((item: any, index: number) => {
            const m = migrateItem(item)
            return (
              <div key={index} className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                <div className="text-sm text-gray-800 flex items-center gap-2">
                  <span className="font-medium">{m.language}</span>
                  {m.proficiency && <span className="text-gray-500"> | {m.proficiency}</span>}
                  {m.level && <span className="text-gray-500"> | {m.level}</span>}
                  {itemChanged("languages", index) && <ChangedBadge />}
                </div>
                <div className="flex items-center gap-3">
                  <button onClick={() => openEdit(index)} className="text-xs text-[#FF6B00] hover:text-[#e55f00]">编辑</button>
                  <button
                    onClick={() => {
                      const item = items[index]
                      const name = `${item?.language || item?.name || "未知语言"}${item?.proficiency ? ` · ${item.proficiency}` : ""}`
                      setDeleteTarget({
                        fieldName: "languages",
                        index,
                        title: `确认删除语言能力「${name}」？`,
                        description: "删除后本地语言能力将移除该条目，保存快照或回写官网后生效。",
                      })
                    }}
                    className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  >
                    删除
                  </button>
                </div>
              </div>
            )
          })}
        </div>

        {/* Add button */}
        {!languageDialogOpen && (
          <button
            onClick={openAdd}
            className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            添加语言能力
          </button>
        )}

        {/* Inline add/edit form */}
        {languageDialogOpen && (
          <div className="mt-3 rounded-lg border border-gray-200 p-4">
            <h4 className="text-sm font-medium text-gray-800 mb-3">
              {editingLanguageIdx !== null ? "编辑语言能力" : "添加语言能力"}
            </h4>
            <div className={cn("grid gap-3", (isCustom || hasLevel) ? "grid-cols-3" : "grid-cols-2")}>
              {/* 语言 dropdown */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">语言 <span className="text-red-500">*</span></label>
                <select
                  value={languageForm.language || ""}
                  onChange={(e: any) => setLanguageForm({ ...languageForm, language: e.target.value, level: "" })}
                  className={cn(
                    "w-full h-[40px] rounded-md border bg-background px-3 text-sm transition-colors",
                    "hover:border-[#FF6B00] focus:outline-none focus:border-[#FF6B00]",
                    languageForm.language ? "text-gray-800" : "text-gray-400"
                  )}
                >
                  <option value="" className="text-gray-400">请选择</option>
                  {LIEPIN_LANGUAGES.map((l: any) => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
              </div>

              {/* 自定义语言 name input */}
              {isCustom && (
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">语言名称 <span className="text-red-500">*</span></label>
                  <Input
                    value={languageForm.level || ""}
                    onChange={(e: any) => setLanguageForm({ ...languageForm, level: e.target.value })}
                    placeholder="请输入语言名称"
                  />
                </div>
              )}

              {/* 熟练程度 dropdown */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">熟练程度 <span className="text-red-500">*</span></label>
                <select
                  value={languageForm.proficiency || ""}
                  onChange={(e: any) => setLanguageForm({ ...languageForm, proficiency: e.target.value })}
                  className={cn(
                    "w-full h-[40px] rounded-md border bg-background px-3 text-sm transition-colors",
                    "hover:border-[#FF6B00] focus:outline-none focus:border-[#FF6B00]",
                    languageForm.proficiency ? "text-gray-800" : "text-gray-400"
                  )}
                >
                  <option value="" className="text-gray-400">请选择</option>
                  {LIEPIN_PROFICIENCY_LEVELS.map((p) => (
                    <option key={p.value} value={p.value}>{p.value}</option>
                  ))}
                </select>
              </div>

              {/* 语言等级 dropdown (only for major languages) */}
              {hasLevel && (
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">语言等级</label>
                  <select
                    value={languageForm.level || ""}
                    onChange={(e: any) => setLanguageForm({ ...languageForm, level: e.target.value })}
                    className={cn(
                      "w-full h-[40px] rounded-md border bg-background px-3 text-sm transition-colors",
                      "hover:border-[#FF6B00] focus:outline-none focus:border-[#FF6B00]",
                      languageForm.level ? "text-gray-800" : "text-gray-400"
                    )}
                  >
                    <option value="" className="text-gray-400">请选择</option>
                    {levelOptions.map((o: any) => (
                      <option key={o} value={o}>{o}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            {/* Action buttons */}
            <div className="flex justify-end gap-3 mt-4">
              <button
                onClick={() => setLanguageDialogOpen(false)}
                className="rounded border border-[#FF6B00] px-5 py-1.5 text-sm text-[#FF6B00] transition-colors hover:bg-[#FFF7F0]"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={!languageForm.language || !languageForm.proficiency}
                className="rounded bg-[#FF6B00] px-5 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                确定
              </button>
            </div>
          </div>
        )}
      </SectionCard>
    )
  }
