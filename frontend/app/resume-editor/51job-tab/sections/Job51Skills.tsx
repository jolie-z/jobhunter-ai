/**
 * Job51 Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { Job51SkillPicker } from "@/components/ui/51job-skill-picker"
import { JOB51_SKILL_ABILITIES } from "@/lib/51job-options"
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


export function Job51Skills() {
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

    const items = getVal("skills") || []

    const existingSkills = items.filter((_: any, idx: number) => idx !== editingSkillIdx)
    const disabledCodes = existingSkills.map((item: any) => String(item.skillType || "")).filter(Boolean)
    const disabledNames = existingSkills.map((item: any) => String(item.skillName || item.skillTypeString || "")).filter(Boolean)

    const openAdd = () => {
      setEditingSkillIdx(null)
      setSkillForm({ skillType: "", skillName: "", skillCategory: "", ability: "", abilityString: "" })
      setSkillErrors({})
      setSkillEditing(true)
    }

    const openEdit = (index: number) => {
      setEditingSkillIdx(index)
      setSkillForm({ ...items[index] })
      setSkillErrors({})
      setSkillEditing(true)
    }

    const handleCancel = () => {
      setSkillEditing(false)
      setSkillPickerOpen(false)
      setSkillErrors({})
    }

    const handleSave = async () => {
      const errors: Record<string, string> = {}
      const skillVal = (skillForm.skillName || skillForm.skillTypeString || "").trim()
      if (!skillVal && !skillForm.skillType) errors.skillType = "请选择或输入技能"
      if (!skillForm.ability) errors.ability = "请选择熟练程度"

      // 互斥校验：同一技能不可重复添加
      const skillCode = String(skillForm.skillType || "").trim()
      const isDuplicate = items.some((item: any, idx: number) => {
        if (editingSkillIdx !== null && idx === editingSkillIdx) return false
        const existingName = (item.skillName || item.skillTypeString || "").trim().toLowerCase()
        const existingCode = String(item.skillType || "").trim()
        if (skillCode && existingCode && skillCode === existingCode) return true
        if (skillVal && existingName && skillVal.toLowerCase() === existingName) return true
        return false
      })
      if (isDuplicate) {
        errors.skillType = `技能「${skillVal || skillCode}」已存在，不可重复添加`
      }

      if (Object.keys(errors).length > 0) {
        setSkillErrors(errors)
        return
      }
      setSkillErrors({})
      const found = JOB51_SKILL_ABILITIES.find((a: any) => a.code === String(skillForm.ability))
      const payload = {
        ...skillForm,
        skillName: skillVal,
        skillTypeString: skillVal,
        ability: String(skillForm.ability),
        abilityString: found ? found.value : (skillForm.abilityString || "熟练"),
        isEnglish: false,
      }
      let ok: boolean
      if (editingSkillIdx !== null) {
        ok = await handleUpdateItem("skills", editingSkillIdx, payload)
      } else {
        ok = await handleAddItem("skills", payload)
      }
      if (!ok) return
      setSkillEditing(false)
    }

    // ===== 编辑模式（内联展开） =====
    if (skillEditing) {
      return (
        <SectionCard id="skills" changed={changedModuleKeys.has("skills")}>
          <SectionHeader title="专业技能" changed={changedModuleKeys.has("skills")} />

          <div className="space-y-5">
            {/* 技能 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>技能
              </label>
              <div
                onClick={() => setSkillPickerOpen(true)}
                className={`w-full h-[40px] rounded-md border bg-white px-3 flex items-center justify-between text-sm cursor-pointer hover:border-[#FF6B00] transition-colors ${skillErrors.skillType ? "border-red-400" : "border-gray-300"}`}
              >
                {skillForm.skillName || skillForm.skillTypeString ? (
                  <span className="text-gray-900 font-medium">{skillForm.skillName || skillForm.skillTypeString}</span>
                ) : (
                  <span className="text-gray-400">请选择 51job 官方标准技能</span>
                )}
                <span className="text-xs text-[#FF6B00]">选择技能库</span>
              </div>
              {skillErrors.skillType && <p className="text-xs text-red-500 mt-1">{skillErrors.skillType}</p>}
            </div>

            {/* 熟练程度 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>熟练程度
              </label>
              <select
                value={skillForm.ability || ""}
                onChange={(e) => {
                  const found = JOB51_SKILL_ABILITIES.find((a: any) => a.code === e.target.value)
                  setSkillForm({ ...skillForm, ability: e.target.value, abilityString: found?.value || "" })
                }}
                className={`w-full h-[40px] rounded-md border bg-white px-3 text-sm focus:outline-none focus:border-[#FF6B00] ${skillErrors.ability ? "border-red-400" : "border-gray-300"}`}
              >
                <option value="">请选择</option>
                {JOB51_SKILL_ABILITIES.map((o: any) => (
                  <option key={o.code} value={o.code}>{o.value}</option>
                ))}
              </select>
              {skillErrors.ability && <p className="text-xs text-red-500 mt-1">{skillErrors.ability}</p>}
            </div>
          </div>

          {/* 底部按钮 */}
          <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-gray-100">
            <Button variant="outline" onClick={handleCancel} className="border-gray-300 text-gray-600 min-w-[80px]">
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving} className="bg-[#FF6B00] hover:bg-[#e55f00] text-white min-w-[80px]">
              {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : null}
              完成
            </Button>
          </div>

          {/* 技能选择弹窗 */}
          <Job51SkillPicker
            open={skillPickerOpen}
            onClose={() => setSkillPickerOpen(false)}
            selectedCode={skillForm.skillType || ""}
            disabledCodes={disabledCodes}
            disabledNames={disabledNames}
            onConfirm={(code, name, categoryName) => {
              setSkillForm({ ...skillForm, skillType: code, skillName: name, skillTypeString: name, skillCategory: categoryName })
              setSkillPickerOpen(false)
            }}
          />
        </SectionCard>
      )
    }

    // ===== 展示模式 =====
    return (
      <SectionCard id="skills" changed={changedModuleKeys.has("skills")}>
        <SectionHeader title="专业技能" changed={changedModuleKeys.has("skills")} />
        <div className="flex flex-wrap gap-2">
          {items.length > 0 ? items.map((item: any, index: number) => {
            const skillTitle = item.skillName || item.skillTypeString || "未知技能"
            const abilityText = item.abilityString || (JOB51_SKILL_ABILITIES.find((a: any) => a.code === String(item.ability))?.value) || ""
            return (
              <span
                key={index}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#f8f9fa] border border-gray-200 text-[#333] text-xs rounded-full group cursor-default hover:border-[#FF6B00]/40 transition-colors"
              >
                <span className="font-medium">{skillTitle}</span>
                {abilityText && (
                  <span className="text-[#FF6B00] font-normal bg-[#FFF7F0] px-1.5 py-0.5 rounded text-[11px]">{abilityText}</span>
                )}
                <button
                  onClick={() => openEdit(index)}
                  className="hidden group-hover:inline text-[#FF6B00] hover:text-[#e55f00] ml-1 font-medium cursor-pointer"
                >
                  编辑
                </button>
                <button
                  onClick={() => setDeleteTarget({ fieldName: "skills", index, title: `确认删除专业技能「${skillTitle}」？`, description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。" })}
                  className="hidden group-hover:inline text-red-400 hover:text-red-500 cursor-pointer ml-0.5"
                >
                  ×
                </button>
              </span>
            )
          }) : (
            <span className="text-sm text-gray-400">暂无专业技能</span>
          )}
        </div>
        <button
          onClick={openAdd}
          className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          添加专业技能
        </button>
      </SectionCard>
    )
  }
