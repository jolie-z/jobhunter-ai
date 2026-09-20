/**
 * Job51 Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { Job51YearMonthPicker } from "@/components/ui/51job-year-month-picker"
import { Job51MajorPicker } from "@/components/ui/51job-major-picker"
import { JOB51_DEGREES } from "@/lib/51job-options"
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


export function Job51Education() {
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

    const items = getVal("educations") || []

    const openAdd = () => {
      setEditingEducationIdx(null)
      setEducationForm({
        degree: "", schoolName: "", major: "", majorName: "", majorCategory: "",
        studyType: "全日制", startTime: "", endTime: "",
        isOverseas: false, majorDescribe: "",
      })
      setEducationErrors({})
      setEducationEditing(true)
    }

    const openEdit = (index: number) => {
      setEditingEducationIdx(index)
      const item = items[index]
      const endTime = item.endTime === "至今" ? "" : (item.endTime || "")
      setEducationForm({ ...item, endTime })
      setEducationErrors({})
      setEducationEditing(true)
    }

    const handleCancel = () => {
      setEducationEditing(false)
      setMajorPickerOpen(false)
      setEducationErrors({})
    }

    const handleSave = async () => {
      // 必填校验
      const errors: Record<string, string> = {}
      if (!educationForm.degree) errors.degree = "请选择学历"
      if (!educationForm.schoolName?.trim()) errors.schoolName = "请填写学校名称"
      if (!educationForm.major) errors.major = "请选择专业"
      if (!educationForm.studyType) errors.studyType = "请选择学制类型"
      if (!educationForm.startTime) errors.startTime = "请选择在校时间"
      if (!educationForm.endTime || educationForm.endTime === "至今") errors.endTime = "请选择具体毕业年月（不支持至今）"
      if (Object.keys(errors).length > 0) {
        setEducationErrors(errors)
        return
      }
      setEducationErrors({})
      const degObj = JOB51_DEGREES.find((o: any) => String(o.code) === String(educationForm.degree))
      const toSave = {
        ...educationForm,
        degreeString: degObj ? degObj.value : (educationForm.degreeString || ""),
        isEnglish: false,
        isFullTime: educationForm.studyType === "全日制",
        isOverseas: Boolean(educationForm.isOverseas),
        isMba: false,
      }
      let ok: boolean
      if (editingEducationIdx !== null) {
        ok = await handleUpdateItem("educations", editingEducationIdx, toSave)
      } else {
        ok = await handleAddItem("educations", toSave)
      }
      if (!ok) return
      setEducationEditing(false)
    }

    // ===== 编辑模式（内联展开） =====
    if (educationEditing) {
      return (
        <SectionCard id="education" changed={changedModuleKeys.has("educations")}>
          <SectionHeader title="教育经历" changed={changedModuleKeys.has("educations")} />

          <div className="space-y-5">
            {/* 学历 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>学历
              </label>
              <select
                value={educationForm.degree || ""}
                onChange={(e) => setEducationForm({ ...educationForm, degree: e.target.value })}
                className={`w-full h-[40px] rounded-md border bg-white px-3 text-sm focus:outline-none focus:border-[#FF6B00] ${educationErrors.degree ? "border-red-400" : "border-gray-300"}`}
              >
                <option value="">请选择</option>
                {JOB51_DEGREES.map((o: any) => (
                  <option key={`${o.code}-${o.value}`} value={o.code}>{o.value}</option>
                ))}
              </select>
              {educationErrors.degree && <p className="text-xs text-red-500 mt-1">{educationErrors.degree}</p>}
            </div>

            {/* 学校名称 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>学校名称
              </label>
              <Input
                value={educationForm.schoolName || ""}
                onChange={(e) => setEducationForm({ ...educationForm, schoolName: e.target.value })}
                placeholder="请填写"
                className={`h-[40px] ${educationErrors.schoolName ? "border-red-400" : ""}`}
              />
              {educationErrors.schoolName && <p className="text-xs text-red-500 mt-1">{educationErrors.schoolName}</p>}
            </div>

            {/* 专业 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>专业
              </label>
              <div
                onClick={() => setMajorPickerOpen(true)}
                className={`w-full h-[40px] rounded-md border bg-white px-3 flex items-center text-sm cursor-pointer hover:border-[#FF6B00] transition-colors ${educationErrors.major ? "border-red-400" : "border-gray-300"}`}
              >
                {educationForm.majorName ? (
                  <span className="text-gray-900">{educationForm.majorName}</span>
                ) : (
                  <span className="text-gray-400">请选择</span>
                )}
              </div>
              {educationErrors.major && <p className="text-xs text-red-500 mt-1">{educationErrors.major}</p>}
            </div>

            {/* 学制类型 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>学制类型
              </label>
              <select
                value={educationForm.studyType || "全日制"}
                onChange={(e) => setEducationForm({ ...educationForm, studyType: e.target.value })}
                className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
              >
                <option value="全日制">全日制</option>
                <option value="非全日制">非全日制</option>
              </select>
            </div>

            {/* 在校时间 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>在校时间
              </label>
              <div className="flex items-center gap-2">
                <Job51YearMonthPicker
                  value={educationForm.startTime || ""}
                  onChange={(v) => setEducationForm({ ...educationForm, startTime: v })}
                  placeholder="开始时间"
                  yearRange={[1960, Math.max(new Date().getFullYear() + 5, 2029)]}
                />
                <span className="text-gray-400 text-sm flex-shrink-0">至</span>
                <Job51YearMonthPicker
                  value={educationForm.endTime || ""}
                  onChange={(v) => setEducationForm({ ...educationForm, endTime: v })}
                  placeholder="毕业时间"
                  yearRange={[1960, Math.max(new Date().getFullYear() + 5, 2029)]}
                  allowPresent={false}
                />
              </div>
              {(educationErrors.startTime || educationErrors.endTime) && (
                <p className="text-xs text-red-500 mt-1">{educationErrors.startTime || educationErrors.endTime}</p>
              )}
            </div>

            <DynamicFieldSlot
              data={educationForm}
              excludeKeys={[
                "degree", "degreeString", "schoolName", "major", "majorName", "majorCategory",
                "studyType", "studyTypeString", "startTime", "endTime", "isOverseas", "majorDescribe", "path", "id",
                "is211", "is985", "isMba", "isFullTime", "label", "describe", "logoUrl"
              ]}
              onChange={(k, v) => setEducationForm((prev: any) => ({ ...prev, [k]: v }))}
              title="教育经历 · 动态扩展字段"
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

          {/* 专业选择弹窗 */}
          <Job51MajorPicker
            open={majorPickerOpen}
            onClose={() => setMajorPickerOpen(false)}
            selectedCode={educationForm.major || ""}
            onConfirm={(code, name, categoryName) => {
              setEducationForm({ ...educationForm, major: code, majorName: name, majorCategory: categoryName })
              setMajorPickerOpen(false)
            }}
          />
        </SectionCard>
      )
    }

    // ===== 展示模式 =====
    return (
      <SectionCard id="education">
        <SectionHeader title="教育经历" changed={changedModuleKeys.has("educations")} />
        <div className="space-y-4">
          {items.map((item: any, index: number) => (
            <div key={index} className="border-b border-gray-100 pb-4 last:border-0 last:pb-0 group">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900">{item.schoolName || "未知学校"}</span>
                  {item.studyType && (
                    <span className="text-xs bg-[#FFF3E8] text-[#FF6B00] px-2 py-0.5 rounded">{item.studyType}</span>
                  )}
                  {item.isOverseas && (
                    <span className="text-xs bg-blue-50 text-blue-500 px-2 py-0.5 rounded">留学</span>
                  )}
                </div>
                <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={() => openEdit(index)} className="text-xs text-[#FF6B00] hover:text-[#e55f00] cursor-pointer">编辑</button>
                  <button onClick={() => setDeleteTarget({ fieldName: "educations", index, title: `确认删除教育经历「${item.schoolName || '教育经历'}」？`, description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。" })} className="text-xs text-red-400 hover:text-red-500 cursor-pointer">删除</button>
                </div>
              </div>
              <div className="text-xs text-gray-400 mt-1">
                {item.startTime || ""} - {item.endTime || ""}
              </div>
              <div className="text-sm text-gray-600 mt-1">
                {[
                  item.degreeString || JOB51_DEGREES.find((o: any) => String(o.code) === String(item.degree))?.value || item.degree,
                  item.majorName || item.majorString || item.major
                ].filter(Boolean).join(" | ")}
              </div>
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
      </SectionCard>
    )
  }
