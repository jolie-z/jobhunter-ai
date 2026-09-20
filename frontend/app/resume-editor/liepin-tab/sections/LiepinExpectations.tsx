/**
 * Liepin Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { SectionHeader } from "../constants"

import { useLiepinCtx } from "../context"
import { LiepinCitySelector as LiepinCityMultiSelector } from "@/components/ui/liepin-city-selector"
import { LiepinCitySelector } from "@/components/ui/liepin-city-selector"
import { LiepinJobSelector } from "@/components/ui/liepin-job-selector"
import { LiepinIndustrySelector } from "@/components/ui/liepin-industry-selector"
import { LiepinSalarySelector } from "@/components/ui/liepin-salary-selector"
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


export function LiepinExpectations() {
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

    const items = getExpectations()
    const currentItem = editingExpectationIdx !== null ? expectationsForm[editingExpectationIdx] : null
    const canSave = isExpectationValid()

    // 构建薪资摘要文本
    const salarySummary = (item: any) => {
      if (!item.salary_min && !item.salary_max) return "面议"
      const parts = []
      if (item.salary_min && item.salary_max) {
        parts.push(`${item.salary_min} - ${item.salary_max}`)
      } else if (item.salary_min) {
        parts.push(`${item.salary_min} 起`)
      } else if (item.salary_max) {
        parts.push(`最高 ${item.salary_max}`)
      }
      if (item.salary_months && item.salary_months !== 12) {
        parts.push(`× ${item.salary_months}薪`)
      }
      return parts.join(" ") || "面议"
    }

    // 构建城市摘要
    const citySummary = (item: any) => {
      const parts = []
      if (item.city) parts.push(item.city)
      if (item.other_cities && item.other_cities.length > 0) {
        parts.push(...item.other_cities)
      }
      return parts.join("、") || "不限"
    }

    // 构建行业摘要
    const industrySummary = (item: any) => {
      const inds = normalizeIndustries(item.industries || item.industry || item.expected_industry)
      if (inds.length === 0 || inds.includes("不限") || inds.includes("全部行业")) return "不限"
      return inds.join("、")
    }

    return (
      <SectionCard moduleKey="expectations">
        <SectionHeader title={getLabel("expectations", "求职期望")} />
        <div className="space-y-3">
          {items.length === 0 && (
            <div className="text-sm text-gray-400 py-2">暂无求职期望</div>
          )}
          {items.map((item: any, index: number) => (
            <div
              key={index}
              className="border border-gray-100 rounded-lg p-4 bg-gray-50/50"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-900 mb-1.5 flex items-center gap-2">
                    {item.position || "未设置职位"}
                    {itemChanged("expectations", index) && <ChangedBadge />}
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500">
                    <div>
                      <span className="text-gray-400">城市：</span>
                      {citySummary(item)}
                    </div>
                    <div>
                      <span className="text-gray-400">薪资：</span>
                      {salarySummary(item)}
                    </div>
                    <div className="col-span-2">
                      <span className="text-gray-400">行业：</span>
                      {industrySummary(item)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                  <button
                    onClick={() => openEditExpectation(index)}
                    className="text-xs text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
                  >
                    编辑
                  </button>
                  <button
                    onClick={() => {
                      const item = items[index]
                      const pos = item?.position || "当前求职期望"
                      setDeleteTarget({
                        fieldName: "expectations",
                        index,
                        title: `确认删除求职期望「${pos}」？`,
                        description: "删除后本地期望列表将移除该条目，保存快照或回写官网后生效。",
                      })
                    }}
                    className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
        {items.length < 3 && (
          <button
            onClick={openAddExpectation}
            className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            添加求职期望
          </button>
        )}

        <Dialog open={expectationDialogOpen} onOpenChange={setExpectationDialogOpen}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>编辑求职期望</DialogTitle>
            </DialogHeader>
            {currentItem && (
              <div className="space-y-4 max-h-[68vh] overflow-y-auto pr-1">
                {/* 期望职位 */}
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">
                    期望职位 <span className="text-red-500">*</span>
                  </label>
                  <LiepinJobSelector
                    value={currentItem.position || ""}
                    onChange={(v: any) => updateExpectationField("position", v)}
                  />
                </div>
                {/* 期望地点 */}
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">
                    期望地点 <span className="text-red-500">*</span>
                  </label>
                  <LiepinCitySelector
                    value={currentItem.city || ""}
                    onChange={(v: any) => updateExpectationField("city", v)}
                  />
                </div>
                {/* 其他感兴趣的地点 */}
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">
                    其他感兴趣的地点 <span className="text-gray-400">（选填，最多5个）</span>
                  </label>
                  <LiepinCityMultiSelector
                    value={currentItem.other_cities || []}
                    onChange={(v: any) => updateExpectationField("other_cities", v)}
                  />
                </div>
                {/* 期望行业 */}
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">
                    期望行业 <span className="text-red-500">*</span>
                  </label>
                  <LiepinIndustrySelector
                    value={currentItem.industries || []}
                    onChange={(v: any) => updateExpectationField("industries", v)}
                  />
                </div>
                {/* 期望薪资 */}
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">
                    期望薪资 <span className="text-red-500">*</span>
                  </label>
                  <LiepinSalarySelector
                    salaryMin={currentItem.salary_min || ""}
                    salaryMax={currentItem.salary_max || ""}
                    salaryMonths={currentItem.salary_months || 12}
                    onMinChange={(v: any) => updateExpectationField("salary_min", v)}
                    onMaxChange={(v: any) => updateExpectationField("salary_max", v)}
                    onMonthsChange={(v: any) => updateExpectationField("salary_months", v)}
                  />
                </div>
                {!canSave && (
                  <p className="text-xs text-red-500">
                    请填写所有必填项（期望职位、期望地点、期望行业、期望薪资）
                  </p>
                )}
              </div>
            )}
            <DialogActions
              onCancel={() => { setExpectationDialogOpen(false); setEditingExpectationIdx(null) }}
              onConfirm={handleSaveExpectation}
              disabled={!canSave}
              saving={saving}
            />
          </DialogContent>
        </Dialog>
      </SectionCard>
    )
  }
