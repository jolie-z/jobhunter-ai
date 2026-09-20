/**
 * Liepin Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { SectionHeader } from "../constants"

import { useLiepinCtx } from "../context"
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


export function LiepinProjects() {
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

    const items = getVal("projects") || []

    const emptyProject = (): any => ({
      project_name: "",
      company: "",
      role: "",
      start_date: "",
      end_date: "",
      description: "",
      responsibilities: "",
      achievements: "",
    })

    // 格式化项目时间显示：若只有单点时间（如 2026.01），结束时间等于开始时间；若显式为"至今"则显示"至今"
    const formatProjectPeriod = (item: any) => {
      const start = item.start_date || ""
      const rawEnd = item.end_date
      if (!start && !rawEnd) return ""
      if (rawEnd === "至今" || rawEnd === "999999") {
        return `${start || ""} - 至今`
      }
      const end = (rawEnd && rawEnd.trim() !== "") ? rawEnd : start
      if (start && end) {
        return `${start} - ${end}`
      }
      return start || end || ""
    }

    const openAdd = () => {
      setEditingProjectIdx(null)
      setProjectForm(emptyProject())
      setProjectDialogOpen(true)
    }

    const openEdit = (index: number) => {
      const item = items[index]
      setEditingProjectIdx(index)
      const start = item.start_date || ""
      let end = item.end_date
      if (end === "至今" || end === "999999") {
        end = "至今"
      } else if (!end || end.trim() === "") {
        // 核心规则：当读取到的时间只有单点时间（如 2026.01），代表开始和结束时间都是 2026.01
        end = start
      }
      setProjectForm({
        ...emptyProject(),
        ...item,
        start_date: start,
        end_date: end,
        // Data migration: keep description, drop tech_stack/link
        description: item.description || "",
      })
      setProjectDialogOpen(true)
    }

    const handleSave = async () => {
      const formToSave = { ...projectForm }
      if (!formToSave.end_date && formToSave.start_date) {
        formToSave.end_date = formToSave.start_date
      }
      if (editingProjectIdx !== null) {
        await handleUpdateItem("projects", editingProjectIdx, formToSave)
      } else {
        await handleAddItem("projects", formToSave)
      }
      setProjectDialogOpen(false)
    }

    return (
      <SectionCard moduleKey="projects">
        <SectionHeader title={getLabel("projects", "项目经历")} />
        <div className="space-y-4">
          {items.map((item: any, index: number) => (
            <div key={index} className="border-b border-gray-100 pb-4 last:border-0 last:pb-0">
              {/* Row 1: project name + dates/actions */}
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium text-gray-900 flex items-center gap-2">
                  {item.project_name || "未知项目"}
                  {itemChanged("projects", index) && <ChangedBadge />}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400">
                    {formatProjectPeriod(item)}
                  </span>
                  <button onClick={() => openEdit(index)} className="text-xs text-[#FF6B00] hover:text-[#e55f00] cursor-pointer">编辑</button>
                  <button
                    onClick={() => {
                      const item = items[index]
                      const name = item?.project_name || item?.name || "未知项目"
                      setDeleteTarget({
                        fieldName: "projects",
                        index,
                        title: `确认删除项目经历「${name}」？`,
                        description: "删除后本地项目经历将移除该条目，保存快照或回写官网后生效。",
                      })
                    }}
                    className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  >
                    删除
                  </button>
                </div>
              </div>
              {/* Row 2: company · role */}
              {(item.company || item.role) && (
                <div className="text-sm text-gray-600 mt-1">
                  {[item.company, item.role].filter(Boolean).join(" · ")}
                </div>
              )}
              {/* Row 3: description preview */}
              {item.description && (
                <div className="text-sm text-gray-500 mt-2 whitespace-pre-wrap leading-relaxed line-clamp-2">
                  {item.description}
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
          添加项目经历
        </button>

        <Dialog open={projectDialogOpen} onOpenChange={setProjectDialogOpen}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editingProjectIdx !== null ? "编辑项目经历" : "添加项目经历"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 max-h-[68vh] overflow-y-auto pr-1">
              {/* 项目名称 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">项目名称 <span className="text-red-500">*</span></label>
                <Input
                  value={projectForm.project_name || ""}
                  onChange={(e: any) => setProjectForm({ ...projectForm, project_name: e.target.value })}
                  placeholder="请输入项目名称"
                />
              </div>

              {/* 公司名称 | 项目职务 */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">公司名称</label>
                  <Input
                    value={projectForm.company || ""}
                    onChange={(e: any) => setProjectForm({ ...projectForm, company: e.target.value })}
                    placeholder="请输入公司名称"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">项目职务</label>
                  <Input
                    value={projectForm.role || ""}
                    onChange={(e: any) => setProjectForm({ ...projectForm, role: e.target.value })}
                    placeholder="请输入项目职务"
                  />
                </div>
              </div>

              {/* 开始时间 | 结束时间 (+ 至今 toggle) */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">开始时间</label>
                  <LiepinYearMonthPicker
                    value={projectForm.start_date || ""}
                    onChange={(v: any) => setProjectForm({ ...projectForm, start_date: v })}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">结束时间</label>
                  <div className="flex items-center gap-2">
                    <div className="flex-1">
                      <LiepinYearMonthPicker
                        value={projectForm.end_date === "至今" ? "" : (projectForm.end_date || "")}
                        onChange={(v: any) => setProjectForm({ ...projectForm, end_date: v })}
                        placeholder={projectForm.start_date || "请选择"}
                      />
                    </div>
                    <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer select-none whitespace-nowrap">
                      <input
                        type="checkbox"
                        checked={projectForm.end_date === "至今"}
                        onChange={(e: any) => setProjectForm({ ...projectForm, end_date: e.target.checked ? "至今" : (projectForm.start_date || "") })}
                        className="accent-[#FF6B00]"
                      />
                      至今
                    </label>
                  </div>
                </div>
              </div>

              {/* 项目描述 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">项目描述</label>
                <div className="relative">
                  <Textarea
                    value={projectForm.description || ""}
                    onChange={(e: any) => setProjectForm({ ...projectForm, description: e.target.value.slice(0, 1000) })}
                    rows={4}
                    maxLength={1000}
                    placeholder={"描述该项目，展示你的项目经验立刻打动招聘方~\n例如：\n1.项目背景\n2.项目目标\n3.项目概述"}
                    className="resize-none pb-6"
                  />
                  <span className="absolute bottom-2 right-3 text-xs text-gray-400">
                    {(projectForm.description || "").length} / 1000
                  </span>
                </div>
              </div>

              {/* 项目职责 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">项目职责</label>
                <div className="relative">
                  <Textarea
                    value={projectForm.responsibilities || ""}
                    onChange={(e: any) => setProjectForm({ ...projectForm, responsibilities: e.target.value.slice(0, 1000) })}
                    rows={4}
                    maxLength={1000}
                    placeholder={"描述你在项目中的职责，是时候展示你的工作能力了~\n例如：\n1.项目中担任的角色\n2.项目有哪些痛点、难点\n3.解决问题的方法"}
                    className="resize-none pb-6"
                  />
                  <span className="absolute bottom-2 right-3 text-xs text-gray-400">
                    {(projectForm.responsibilities || "").length} / 1000
                  </span>
                </div>
              </div>

              {/* 项目业绩 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">项目业绩</label>
                <div className="relative">
                  <Textarea
                    value={projectForm.achievements || ""}
                    onChange={(e: any) => setProjectForm({ ...projectForm, achievements: e.target.value.slice(0, 1000) })}
                    rows={4}
                    maxLength={1000}
                    placeholder={"描述你的项目业绩，用业绩说话让招聘方快速记住你~\n例如：\n1.目标达成情况\n2.我的贡献\n3.我的收获"}
                    className="resize-none pb-6"
                  />
                  <span className="absolute bottom-2 right-3 text-xs text-gray-400">
                    {(projectForm.achievements || "").length} / 1000
                  </span>
                </div>
              </div>

              <DynamicFieldSlot
                data={projectForm}
                excludeKeys={[
                  // 与猎聘项目经历真实键约定对齐（company/role/description）
                  "project_name", "company", "role", "start_date", "end_date",
                  "description", "responsibilities", "achievements", "path", "id"
                ]}
                onChange={(k: any, v) => setProjectForm((prev: any) => ({ ...prev, [k]: v }))}
                title="项目经历 · 动态扩展字段"
              />
            </div>
            <DialogActions onCancel={() => setProjectDialogOpen(false)} onConfirm={handleSave} saving={saving} />
          </DialogContent>
        </Dialog>
      </SectionCard>
    )
  }
