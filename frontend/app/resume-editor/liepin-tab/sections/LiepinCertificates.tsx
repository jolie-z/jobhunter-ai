/**
 * Liepin Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { SectionHeader } from "../constants"

import { useLiepinCtx } from "../context"
import { LiepinCertSelector } from "@/components/ui/liepin-cert-selector"
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


export function LiepinCertificates() {
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

    const items: string[] = getVal("certificates") || []

    const handleCertChange = async (certs: string[]) => {
      await updateField("certificates", certs)
    }

    return (
      <SectionCard moduleKey="certificates">
        <SectionHeader
          title={getLabel("certificates", "资格证书")}
          onEdit={() => setCertSelectorOpen(true)}
          badge={fieldChanged("certificates") ? <ChangedBadge /> : undefined}
        />
        <div className="flex flex-wrap gap-2">
          {items.length > 0 ? (
            items.map((cert: string, index: number) => (
              <span
                key={index}
                className="inline-block px-3 py-1 bg-[#f5f5f5] text-[#666] text-xs rounded-full"
              >
                {cert}
              </span>
            ))
          ) : (
            <span className="text-sm text-gray-400">暂无证书</span>
          )}
        </div>

        <LiepinCertSelector
          value={items}
          onChange={handleCertChange}
          open={certSelectorOpen}
          onOpenChange={setCertSelectorOpen}
          hideTrigger
        />
      </SectionCard>
    )
  }
