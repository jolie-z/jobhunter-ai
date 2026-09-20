/**
 * Liepin Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { SectionHeader } from "../constants"

import { useLiepinCtx } from "../context"
import { LIEPIN_DEGREE_OPTIONS } from "@/lib/liepin-options"
import { LiepinYearMonthPicker } from "@/components/ui/liepin-year-month-picker"
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


export function LiepinEducation() {
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

    const items = getVal("education") || []

    const emptyEducation = (): any => ({
      school: "",
      degree: "",
      is_tongzhao: false,
      major: "",
      start_date: "",
      end_date: "",
      campus_experience: "",
    })

    const openAdd = () => {
      setEditingEducationIdx(null)
      setEducationForm(emptyEducation())
      setEducationDialogOpen(true)
    }

    const openEdit = (index: number) => {
      const item = items[index]
      setEditingEducationIdx(index)
      setEducationForm({
        ...emptyEducation(),
        ...item,
      })
      setEducationDialogOpen(true)
    }

    const handleSave = async () => {
      if (editingEducationIdx !== null) {
        await handleUpdateItem("education", editingEducationIdx, educationForm)
      } else {
        await handleAddItem("education", educationForm)
      }
      setEducationDialogOpen(false)
    }

    const isEducationValid = (): boolean => {
      return !!(
        educationForm.school &&
        educationForm.degree &&
        educationForm.major &&
        educationForm.start_date &&
        educationForm.end_date
      )
    }

    return (
      <SectionCard moduleKey="education">
        <SectionHeader title={getLabel("education", "教育经历")} />
        <div className="space-y-4">
          {items.map((item: any, index: number) => (
            <div key={index} className="border-b border-gray-100 pb-4 last:border-0 last:pb-0">
              {/* Row 1: school + tongzhao badge + dates/actions */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900">{item.school || "未知学校"}</span>
                  {item.is_tongzhao && (
                    <span className="text-xs bg-[#FFF3E8] text-[#FF6B00] px-2 py-0.5 rounded">统招</span>
                  )}
                  {itemChanged("education", index) && <ChangedBadge />}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400">
                    {item.start_date || ""} - {item.end_date || ""}
                  </span>
                  <button onClick={() => openEdit(index)} className="text-xs text-[#FF6B00] hover:text-[#e55f00] cursor-pointer">编辑</button>
                  <button
                    onClick={() => {
                      const item = items[index]
                      const name = `${item?.school || "未知学校"}${item?.major ? ` · ${item.major}` : ""}`
                      setDeleteTarget({
                        fieldName: "education",
                        index,
                        title: `确认删除教育经历「${name}」？`,
                        description: "删除后本地教育经历将移除该条目，保存快照或回写官网后生效。",
                      })
                    }}
                    className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  >
                    删除
                  </button>
                </div>
              </div>
              {/* Row 2: degree | major */}
              <div className="text-sm text-gray-600 mt-1">
                {[item.degree, item.major].filter(Boolean).join(" | ")}
              </div>
              {/* Row 3: campus experience preview */}
              {item.campus_experience && (
                <div className="text-sm text-gray-500 mt-2 whitespace-pre-wrap leading-relaxed line-clamp-2">
                  {item.campus_experience}
                </div>
              )}
            </div>
          ))}
        </div>
        <button
          onClick={openAdd}
          className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          添加教育经历
        </button>

        <Dialog open={educationDialogOpen} onOpenChange={setEducationDialogOpen}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editingEducationIdx !== null ? "编辑教育经历" : "添加教育经历"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 max-h-[68vh] overflow-y-auto pr-1">
              {/* 学校名称 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">学校名称 <span className="text-red-500">*</span></label>
                <Input
                  value={educationForm.school || ""}
                  onChange={(e: any) => setEducationForm({ ...educationForm, school: e.target.value })}
                  placeholder="请输入学校名称"
                />
              </div>

              {/* 学历 | 是否统招 */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">学历 <span className="text-red-500">*</span></label>
                  <select
                    value={educationForm.degree || ""}
                    onChange={(e: any) => setEducationForm({ ...educationForm, degree: e.target.value })}
                    className={cn(
                      "w-full h-[40px] rounded-md border bg-background px-3 text-sm transition-colors",
                      "hover:border-[#FF6B00] focus:outline-none focus:border-[#FF6B00]",
                      educationForm.degree ? "text-gray-800" : "text-gray-400"
                    )}
                  >
                    <option value="" className="text-gray-400">请选择</option>
                    {LIEPIN_DEGREE_OPTIONS.map((d: any) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </div>
                <div className="flex items-end pb-2">
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={!!educationForm.is_tongzhao}
                      onChange={(e: any) => setEducationForm({ ...educationForm, is_tongzhao: e.target.checked })}
                      className="w-4 h-4 accent-[#FF6B00]"
                    />
                    是否统招
                  </label>
                </div>
              </div>

              {/* 专业名称 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">专业名称 <span className="text-red-500">*</span></label>
                <Input
                  value={educationForm.major || ""}
                  onChange={(e: any) => setEducationForm({ ...educationForm, major: e.target.value })}
                  placeholder="请输入专业名称"
                />
              </div>

              {/* 开始时间 | 结束时间 */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">开始时间 <span className="text-red-500">*</span></label>
                  <LiepinYearMonthPicker
                    value={educationForm.start_date || ""}
                    onChange={(v: any) => setEducationForm({ ...educationForm, start_date: v })}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">结束时间 <span className="text-red-500">*</span></label>
                  <LiepinYearMonthPicker
                    value={educationForm.end_date || ""}
                    onChange={(v: any) => setEducationForm({ ...educationForm, end_date: v })}
                  />
                </div>
              </div>

              {/* 在校经历 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">在校经历</label>
                <div className="relative">
                  <Textarea
                    value={educationForm.campus_experience || ""}
                    onChange={(e: any) => setEducationForm({ ...educationForm, campus_experience: e.target.value.slice(0, 300) })}
                    rows={4}
                    maxLength={300}
                    placeholder={"1.在校担任职务...\n2.所获荣誉...\n3.主修课程...\n4.组织经历或社团经历..."}
                    className="resize-none pb-6"
                  />
                  <span className="absolute bottom-2 right-3 text-xs text-gray-400">
                    {(educationForm.campus_experience || "").length} / 300
                  </span>
                </div>
              </div>

              <DynamicFieldSlot
                data={educationForm}
                excludeKeys={[
                  // 与猎聘教育经历真实键约定对齐（school/major/is_tongzhao）
                  "school", "degree", "major", "start_date", "end_date",
                  "is_tongzhao", "campus_experience", "path", "id"
                ]}
                onChange={(k: any, v) => setEducationForm((prev: any) => ({ ...prev, [k]: v }))}
                title="教育经历 · 动态扩展字段"
              />

              {!isEducationValid() && (
                <p className="text-xs text-red-500">
                  请填写所有必填项（学校名称、学历、专业名称、开始时间、结束时间）
                </p>
              )}
            </div>
            <DialogActions
              onCancel={() => setEducationDialogOpen(false)}
              onConfirm={handleSave}
              disabled={!isEducationValid()}
              saving={saving}
            />
          </DialogContent>
        </Dialog>
      </SectionCard>
    )
  }
