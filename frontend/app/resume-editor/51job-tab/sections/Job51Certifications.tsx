/**
 * Job51 Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { Job51CertPicker } from "@/components/ui/51job-cert-picker"
import { useJob51Ctx } from "../context"
import { SectionCard, SectionHeader } from "../constants"
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


export function Job51Certifications() {
  const {
    localData,
    setLocalData,
    saving,
    setSaving,
    toast,
    setToast,
    activeNav,
    setActiveNav,
    selfIntroEditing,
    setSelfIntroEditing,
    selfIntroValue,
    setSelfIntroValue,
    intentionEditing,
    setIntentionEditing,
    intentionForm,
    setIntentionForm,
    editingIntentionIdx,
    setEditingIntentionIdx,
    cityPickerOpen,
    setCityPickerOpen,
    funtypePickerOpen,
    setFuntypePickerOpen,
    industryPickerOpen,
    setIndustryPickerOpen,
    workExpEditing,
    setWorkExpEditing,
    workExpForm,
    setWorkExpForm,
    editingWorkExpIdx,
    setEditingWorkExpIdx,
    workFuntypePickerOpen,
    setWorkFuntypePickerOpen,
    workIndustryPickerOpen,
    setWorkIndustryPickerOpen,
    workSkillInput,
    setWorkSkillInput,
    projectEditing,
    setProjectEditing,
    projectForm,
    setProjectForm,
    editingProjectIdx,
    setEditingProjectIdx,
    educationEditing,
    setEducationEditing,
    educationForm,
    setEducationForm,
    editingEducationIdx,
    setEditingEducationIdx,
    majorPickerOpen,
    setMajorPickerOpen,
    educationErrors,
    setEducationErrors,
    languageEditing,
    setLanguageEditing,
    languageForm,
    setLanguageForm,
    editingLanguageIdx,
    setEditingLanguageIdx,
    langCertsData,
    setLangCertsData,
    langCertPickerOpen,
    setLangCertPickerOpen,
    skillEditing,
    setSkillEditing,
    skillForm,
    setSkillForm,
    editingSkillIdx,
    setEditingSkillIdx,
    skillPickerOpen,
    setSkillPickerOpen,
    skillErrors,
    setSkillErrors,
    certPickerOpen,
    setCertPickerOpen,
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
    savingSnapshot,
    setSavingSnapshot,
    snapshotFeedback,
    setSnapshotFeedback,
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
    job51AgentDiagnosing,
    setJob51AgentDiagnosing,
    job51AgentReport,
    setJob51AgentReport,
    job51AgentModalOpen,
    setJob51AgentModalOpen,
    job51AgentApplying,
    setJob51AgentApplying,
    job51RollbackFeedback,
    setJob51RollbackFeedback,
    job51RollingBack,
    setJob51RollingBack,
    deleteTarget,
    setDeleteTarget,
    certNameMap,
    setCertNameMap,
    contentRef,
    changedModuleKeys,
    handleDispatchJob51HealerAgent,
    handleJob51AgentApplyHeal,
    handleRollbackJob51Snapshot,
    fetchReport,
    handleNavClick,
    getNowTime,
    handleSaveWritebackSource,
    selectedModuleKeys,
    handleApplyReport,
    handleWritebackModules,
    persistData,
    updateField,
    handleDeleteItem,
    confirmDelete,
    handleAddItem,
    handleUpdateItem,
    getVal,
    getLabel,
  } = useJob51Ctx()

    const items = getVal("certifications") || []
    // items 可能是 string[] (codes) 或 object[] (from API)
    const certEntries: { code: string; displayName: string }[] = Array.isArray(items)
      ? items.map((item: any) => {
          if (typeof item === "string") {
            return { code: item, displayName: certNameMap[item] || item }
          }
          const code = item.cert || item.code || ""
          const displayName = certNameMap[code] || item.certString || item.certName || code
          return { code, displayName }
        })
      : []

    const handleCertConfirm = async (codes: string[]) => {
      if (!localData) return
      const field = localData["certifications"] || { label: "资格证书", required: false, type: "array", current_value: [] }
      const updatedField = { ...field, current_value: codes }
      const updated = { ...localData, certifications: updatedField }
      await persistData(updated)
    }
    return (
      <SectionCard id="certifications" changed={changedModuleKeys.has("certifications")}>
        <SectionHeader title="资格证书" changed={changedModuleKeys.has("certifications")} />
        <div className="flex flex-wrap gap-2">
          {certEntries.length > 0 ? certEntries.map((entry, index: number) => (
            <span
              key={index}
              className="inline-flex items-center px-3 py-1.5 bg-[#f5f5f5] text-[#666] text-xs rounded-full"
            >
              {entry.displayName}
            </span>
          )) : (
            <span className="text-sm text-gray-400">暂无资格证书</span>
          )}
        </div>
        <button
          onClick={() => setCertPickerOpen(true)}
          className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          {certEntries.length > 0 ? "编辑资格证书" : "添加资格证书"}
        </button>

        <Job51CertPicker
          open={certPickerOpen}
          onClose={() => setCertPickerOpen(false)}
          selected={certEntries.map(e => e.code)}
          onConfirm={handleCertConfirm}
          maxSelect={20}
        />
      </SectionCard>
    )
  }
