/**
 * Liepin Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { SectionHeader } from "../constants"

import { useLiepinCtx } from "../context"
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


export function LiepinSelfAssessment() {
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

    const content = getVal("self_assessment") || ""

    const openEdit = () => {
      setSelfAssessmentValue(content)
      setSelfAssessmentEditing(true)
    }

    const handleSave = async () => {
      const ok = await updateField("self_assessment", selfAssessmentValue)
      if (!ok) return
      setSelfAssessmentEditing(false)
    }

    return (
      <SectionCard moduleKey="self_assessment">
        <SectionHeader
          title={getLabel("self_assessment", "优势亮点")}
          onEdit={openEdit}
          badge={fieldChanged("self_assessment") ? <ChangedBadge /> : undefined}
        />
        <div className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
          {content || <span className="text-gray-400">暂无内容</span>}
        </div>

        <Dialog open={selfAssessmentEditing} onOpenChange={setSelfAssessmentEditing}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>编辑优势亮点</DialogTitle>
            </DialogHeader>
            <div>
              <Textarea
                value={selfAssessmentValue}
                onChange={(e: any) => setSelfAssessmentValue(e.target.value.slice(0, 1000))}
                rows={8}
                placeholder="请输入优势亮点"
                className="resize-none"
              />
              <div className="text-xs text-gray-400 text-right mt-1">
                {selfAssessmentValue.length}/1000
              </div>
            </div>
            <DialogActions onCancel={() => setSelfAssessmentEditing(false)} onConfirm={handleSave} saving={saving} />
          </DialogContent>
        </Dialog>
      </SectionCard>
    )
  }
