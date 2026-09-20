/**
 * Job51 Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { Job51YearMonthPicker } from "@/components/ui/51job-year-month-picker"
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


export function Job51Projects() {
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

    const items = getVal("projects") || []
    // 从工作经历中提取公司名称列表（去重）
    const works = getVal("works") || []
    const companyOptions = [...new Set(works.map((w: any) => w.companyName).filter(Boolean))] as string[]

    const openAdd = () => {
      setEditingProjectIdx(null)
      setProjectForm({ projectName: "", startTime: "", endTime: "", company: "", companyName: "", functionDescribe: "", describe: "" })
      setProjectEditing(true)
    }

    const openEdit = (index: number) => {
      setEditingProjectIdx(index)
      const item = items[index]
      const comp = item.companyName || item.company || ""
      const endTime = item.endTimeString === "至今" || item.endTime === "至今" ? "至今" : (item.endTime || "")
      setProjectForm({ ...item, company: comp, companyName: comp, endTime })
      setProjectEditing(true)
    }

    const handleCancel = () => setProjectEditing(false)

    const handleSave = async () => {
      const comp = projectForm.companyName || projectForm.company || ""
      const payload = {
        ...projectForm,
        company: comp,
        companyName: comp,
        isEnglish: false,
      }
      let ok: boolean
      if (editingProjectIdx !== null) {
        ok = await handleUpdateItem("projects", editingProjectIdx, payload)
      } else {
        ok = await handleAddItem("projects", payload)
      }
      if (!ok) return
      setProjectEditing(false)
    }

    // ===== 编辑模式（内联展开） =====
    if (projectEditing) {
      return (
        <SectionCard id="project-experience" changed={changedModuleKeys.has("projects")}>
          <SectionHeader title="项目经历" changed={changedModuleKeys.has("projects")} />

          <div className="space-y-5">
            {/* 项目名称 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>项目名称
              </label>
              <Input
                value={projectForm.projectName || ""}
                onChange={(e) => setProjectForm({ ...projectForm, projectName: e.target.value })}
                placeholder="请填写"
                className="h-[40px]"
              />
            </div>

            {/* 项目时间 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>项目时间
              </label>
              <div className="flex items-center gap-2">
                <Job51YearMonthPicker
                  value={projectForm.startTime || ""}
                  onChange={(v) => setProjectForm({ ...projectForm, startTime: v })}
                />
                <span className="text-gray-400 text-sm flex-shrink-0">至</span>
                {projectForm.endTime === "至今" ? (
                  <div className="flex items-center gap-2 flex-1">
                    <span className="h-[40px] px-3 flex items-center text-sm text-[#FF6B00] bg-[#FFF3E8] rounded-md border border-[#FF6B00]/30">至今</span>
                  </div>
                ) : (
                  <Job51YearMonthPicker
                    value={projectForm.endTime || ""}
                    onChange={(v) => setProjectForm({ ...projectForm, endTime: v })}
                    placeholder="至今"
                    allowPresent
                  />
                )}
                <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer flex-shrink-0 select-none">
                  <input
                    type="checkbox"
                    checked={projectForm.endTime === "至今"}
                    onChange={(e) => setProjectForm({ ...projectForm, endTime: e.target.checked ? "至今" : "" })}
                    className="w-4 h-4 rounded border-gray-300 text-[#FF6B00] accent-[#FF6B00] cursor-pointer"
                  />
                  至今
                </label>
              </div>
            </div>

            {/* 所属公司（选填） */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">所属公司（选填）</label>
              <select
                value={projectForm.companyName || projectForm.company || ""}
                onChange={(e) => setProjectForm({ ...projectForm, company: e.target.value, companyName: e.target.value })}
                className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
              >
                <option value="">无</option>
                {companyOptions.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>

            {/* 项目描述 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>项目描述
              </label>
              <Textarea
                value={projectForm.describe || ""}
                onChange={(e) => setProjectForm({ ...projectForm, describe: e.target.value.slice(0, 2000) })}
                rows={6}
                placeholder="介绍该项目，展示你的成果，如：1.项目背景；2.你在项目中的职责；3.项目业绩"
                className="resize-none border-gray-300 focus:border-[#FF6B00]"
              />
              <div className="text-xs text-gray-400 text-right mt-1">
                {(projectForm.describe || "").length}/2000
              </div>
            </div>

            <DynamicFieldSlot
              data={projectForm}
              excludeKeys={[
                "projectName", "startTime", "endTime", "companyName", "company",
                "functionDescribe", "projectRole", "describe", "projectUrl", "position",
                "projectType", "projectTypeString", "path", "id"
              ]}
              onChange={(k, v) => setProjectForm((prev: any) => ({ ...prev, [k]: v }))}
              title="项目经历 · 动态扩展字段"
            />
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
        </SectionCard>
      )
    }

    // ===== 展示模式 =====
    return (
      <SectionCard id="project-experience" changed={changedModuleKeys.has("projects")}>
        <SectionHeader title="项目经历" changed={changedModuleKeys.has("projects")} />
        {items.length === 0 ? (
          <div className="text-sm text-gray-400">暂无项目经历</div>
        ) : (
          <div className="space-y-4">
            {items.map((item: any, index: number) => {
              const compName = item.companyName || item.company
              return (
                <div key={index} className="border-b border-gray-100 pb-4 last:border-0 last:pb-0 group">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium text-gray-900">{item.projectName || "未知项目"}</div>
                    <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => openEdit(index)} className="text-xs text-[#FF6B00] hover:text-[#e55f00] cursor-pointer">编辑</button>
                      <button onClick={() => setDeleteTarget({ fieldName: "projects", index, title: `确认删除项目经历「${item.projectName || '项目经历'}」？`, description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。" })} className="text-xs text-red-400 hover:text-red-500 cursor-pointer">删除</button>
                    </div>
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    {item.startTime || ""} - {item.endTime || "至今"}
                    {compName ? ` · ${compName}` : ""}
                  </div>
                  {item.describe && (
                    <div className="text-sm text-gray-500 mt-2 whitespace-pre-wrap leading-relaxed line-clamp-4">
                      {item.describe}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
        <button
          onClick={openAdd}
          className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          添加项目经历
        </button>
      </SectionCard>
    )
  }
