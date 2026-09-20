/**
 * Job51 Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { useJob51Ctx } from "../context"
import { SectionCard, SectionHeader, DialogActions } from "../constants"
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


export function Job51SelfIntroduction() {
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

    const raw = getVal("self_introduction") || {}
    const content = typeof raw === "string" ? raw : raw.selfIntroduction || ""

    const openEdit = () => {
      setSelfIntroValue(content)
      setSelfIntroEditing(true)
    }

    const handleSave = async () => {
      const ok = await updateField("self_introduction", { ...raw, selfIntroduction: selfIntroValue })
      if (!ok) return
      setSelfIntroEditing(false)
    }

    return (
      <SectionCard id="self-introduction">
        <SectionHeader title={getLabel("self_introduction", "个人优势")} onEdit={openEdit} changed={changedModuleKeys.has("self_introduction")} />
        <div className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
          {content || <span className="text-gray-400">暂无内容</span>}
        </div>

        <Dialog open={selfIntroEditing} onOpenChange={setSelfIntroEditing}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>编辑个人优势</DialogTitle>
            </DialogHeader>
            <div>
              <Textarea
                value={selfIntroValue}
                onChange={(e) => setSelfIntroValue(e.target.value.slice(0, 500))}
                rows={10}
                placeholder="请输入个人优势"
                className="resize-none"
              />
              <div className="text-xs text-gray-400 text-right mt-1">
                {selfIntroValue.length}/500
              </div>
            </div>
            <DialogActions onCancel={() => setSelfIntroEditing(false)} onConfirm={handleSave} saving={saving} />
          </DialogContent>
        </Dialog>
      </SectionCard>
    )
  }
