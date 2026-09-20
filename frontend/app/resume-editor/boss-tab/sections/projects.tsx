/**
 * BOSS Tab 分区组件（机械搬迁自 boss-tab.tsx，行为零变化）
 */
"use client"

import { useBossCtx } from "../context"
import { countryRegions, durationOptions, COUNTRY_MAX_SELECT, LANGUAGE_MAX_SELECT } from "@/lib/overseas-options"

import type { ResumeField } from "../constants"
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
import { ModifiedBadge, BOSS_PRIMARY, BOSS_MODULE_LABELS, BOSS_MODULES, BOSS_MODULE_MAP } from "../constants"



export function BossProjects({ field }: { field: ResumeField }) {
  const {
    data, localData, bossOptions, saving, report, reportLoading, showToast,
    editingField, editValue, setEditingField, setEditValue, setLocalData,
    deletingItem, setDeletingItem, handleDelete, parsePeriod, fetchReport,
    handleApplyReport, handleSaveWritebackSource, handleWritebackModules,
    handleRollbackBossSnapshot, handleBossAgentApplyHeal, handleDispatchBossHealerAgent,
    selectedModules, setSelectedModules, selectedModuleKeys, toggleAllModules,
    writebacking, writebackConfirm, setWritebackConfirm, writebackFeedback,
    showWritebackDetails, setShowWritebackDetails, savingSnapshot, snapshotFeedback,
    bossAgentDiagnosing, bossAgentReport, bossAgentModalOpen, setBossAgentModalOpen,
    bossAgentApplying, bossRollbackFeedback, bossRollingBack,
    editingExpectationIdx, setEditingExpectationIdx, expectationDialogOpen, setExpectationDialogOpen,
    editingWorkExpIdx, setEditingWorkExpIdx, workExpDialogOpen, setWorkExpDialogOpen, workExpForm, setWorkExpForm,
    editingProjectIdx, setEditingProjectIdx, projectDialogOpen, setProjectDialogOpen, projectForm, setProjectForm,
    editingEducationIdx, setEditingEducationIdx, educationDialogOpen, setEducationDialogOpen, educationForm, setEducationForm,
    certSelectorOpen, setCertSelectorOpen,
    overseasDialogOpen, setOverseasDialogOpen, overseasForm, setOverseasForm,
    countrySelectorOpen, setCountrySelectorOpen, languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen, baseInfoForm, setBaseInfoForm,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying,
    persistData, buildModuleUpdate, isSectionModified, displayData, applyFeedback,
    startEdit, saveEdit, cancelEdit,
    overseasModified,
    onRefresh, onSave, reportVersion,
  } = useBossCtx()
    const projects = field.current_value || []
    const isEditingProject = editingProjectIdx !== null

    // 打开添加弹窗
    const openAddProject = () => {
      setEditingProjectIdx(null)
      setProjectForm({
        project_name: "",
        project_role: "",
        project_link: "",
        startYear: "",
        startMonth: "",
        endYear: "",
        endMonth: "",
        project_description: "",
        achievement: "",
      })
      setProjectDialogOpen(true)
    }

    // 打开编辑弹窗（预填数据）
    const openEditProject = (index: number) => {
      const item = projects[index]
      setEditingProjectIdx(index)
      // 解析旧格式 period → startYear/startMonth/endYear/endMonth
      let sy = item.startYear || ""
      let sm = item.startMonth || ""
      let ey = item.endYear || ""
      let em = item.endMonth || ""
      if (!sy && item.period) {
        const parsed = parsePeriod(item.period)
        sy = parsed.startYear; sm = parsed.startMonth
        ey = parsed.endYear; em = parsed.endMonth
      }
      setProjectForm({
        project_name: item.project_name || "",
        project_role: item.project_role || "",
        project_link: item.project_link || "",
        startYear: sy,
        startMonth: sm,
        endYear: ey,
        endMonth: em,
        project_description: item.project_description || "",
        achievement: item.achievement || "",
      })
      setProjectDialogOpen(true)
    }

    // 保存（添加或更新）
    const handleSaveProject = async () => {
      if (!projectForm.project_name?.trim()) {
        showToast("请输入项目名称", "error")
        return
      }
      if (!projectForm.project_role?.trim()) {
        showToast("请输入项目角色", "error")
        return
      }
      if (!projectForm.startYear || !projectForm.startMonth) {
        showToast("请选择项目开始时间", "error")
        return
      }
      if (!projectForm.project_description?.trim()) {
        showToast("请填写项目描述", "error")
        return
      }

      const newItem = {
        project_name: projectForm.project_name.trim(),
        project_role: projectForm.project_role.trim(),
        project_link: projectForm.project_link?.trim() || "",
        startYear: projectForm.startYear,
        startMonth: projectForm.startMonth,
        endYear: projectForm.endYear,
        endMonth: projectForm.endMonth,
        project_description: projectForm.project_description || "",
        achievement: projectForm.achievement || "",
      }

      if (isEditingProject && editingProjectIdx !== null) {
        const updatedValue = [...projects]
        updatedValue[editingProjectIdx] = newItem
        const updatedData = buildModuleUpdate("projects", updatedValue)
        if (!updatedData) return
        const ok = await persistData(updatedData)
        if (!ok) return
        setLocalData(updatedData)
        setProjectDialogOpen(false)
        setEditingProjectIdx(null)
        setProjectForm({})
        if (onSave) onSave(updatedData)
      } else {
        const updatedValue = [...projects, newItem]
        const updatedData = buildModuleUpdate("projects", updatedValue)
        if (!updatedData) return
        const ok = await persistData(updatedData)
        if (!ok) return
        setLocalData(updatedData)
        setProjectDialogOpen(false)
        setProjectForm({})
        if (onSave) onSave(updatedData)
      }
    }

    // 删除项目经历
    const handleDeleteProject = async (index: number) => {
      const updatedValue = [...projects]
      updatedValue.splice(index, 1)
      const updatedData = buildModuleUpdate("projects", updatedValue)
      if (!updatedData) return
      const ok = await persistData(updatedData)
      if (!ok) return
      setLocalData(updatedData)
      if (onSave) onSave(updatedData)
    }

    // 格式化时间显示
    const formatProjectPeriod = (item: any) => {
      const start = item.startYear ? `${item.startYear}.${(item.startMonth || "").padStart(2, "0")}` : ""
      const end = item.endYear ? `${item.endYear}.${(item.endMonth || "").padStart(2, "0")}` : "至今"
      if (!start) return item.period || ""
      return `${start} - ${end}`
    }

    return (
      <Card className="mb-4">
        {report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["projects", "项目经历"]} title="「项目经历」相关注意事项" />)}
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              {field.label}
              <ModifiedBadge show={isSectionModified("projects")} />
              <Badge variant="secondary" className="ml-2">
                {projects.length}条
              </Badge>
            </CardTitle>
            <Button variant="outline" size="sm" onClick={openAddProject}>
              <Plus className="w-4 h-4 mr-1" />
              添加项目经历
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {projects.map((item: any, index: number) => (
              <div key={index} className="p-4 border rounded-lg">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="font-medium text-base">{item.project_name}</div>
                    <div className="text-sm text-gray-600 mt-0.5">
                      {item.project_role}
                    </div>
                    <div className="text-xs text-gray-400 mt-0.5">{formatProjectPeriod(item)}</div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => openEditProject(index)}>
                      <Edit className="w-4 h-4" />
                    </Button>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="sm" className="text-red-500">
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>确认删除</AlertDialogTitle>
                          <AlertDialogDescription>
                            确定要删除这个项目经历吗？此操作无法撤销。
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>取消</AlertDialogCancel>
                          <AlertDialogAction onClick={() => handleDeleteProject(index)}>
                            删除
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </div>
                {item.project_description && (
                  <div className="text-sm text-gray-700 mt-2 line-clamp-3">{item.project_description}</div>
                )}
                {item.project_link && (
                  <div className="text-sm text-blue-600 mt-2">
                    <a href={item.project_link} target="_blank" rel="noopener noreferrer">
                      🔗 项目链接
                    </a>
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>

        {/* 添加/编辑项目经历弹窗 */}
        <Dialog open={projectDialogOpen} onOpenChange={(open) => {
          setProjectDialogOpen(open)
          if (!open) {
            setEditingProjectIdx(null)
            setProjectForm({})
          }
        }}>
          <DialogContent className="max-w-[560px] max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{isEditingProject ? "编辑项目经历" : "添加项目经历"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              {/* 项目名称 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  项目名称 <span className="text-red-500">*</span>
                </label>
                <Input
                  value={projectForm.project_name || ""}
                  onChange={(e) => setProjectForm({ ...projectForm, project_name: e.target.value })}
                  placeholder="例如: 直聘网"
                />
              </div>

              {/* 项目角色 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  项目角色 <span className="text-red-500">*</span>
                </label>
                <Input
                  value={projectForm.project_role || ""}
                  onChange={(e) => setProjectForm({ ...projectForm, project_role: e.target.value })}
                  placeholder="例如: UI 设计师"
                />
              </div>

              {/* 项目链接（选填） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  项目链接 <span className="text-gray-400 font-normal">（选填）</span>
                </label>
                <Input
                  value={projectForm.project_link || ""}
                  onChange={(e) => setProjectForm({ ...projectForm, project_link: e.target.value })}
                  placeholder="例如: github.com/erik"
                />
              </div>

              {/* 项目开始时间 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  项目开始时间 <span className="text-red-500">*</span>
                </label>
                <DateRangePicker
                  startYear={projectForm.startYear || ""}
                  startMonth={projectForm.startMonth || ""}
                  endYear={projectForm.endYear || ""}
                  endMonth={projectForm.endMonth || ""}
                  onChange={(sy, sm, ey, em) => setProjectForm({ ...projectForm, startYear: sy, startMonth: sm, endYear: ey, endMonth: em })}
                />
              </div>

              {/* 项目描述 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  项目描述 <span className="text-red-500">*</span>
                </label>
                <Textarea
                  value={projectForm.project_description || ""}
                  onChange={(e) => {
                    if (e.target.value.length <= 3000) {
                      setProjectForm({ ...projectForm, project_description: e.target.value })
                    }
                  }}
                  placeholder={"描述该项目，向招聘者展示您的项目经验\n例如：\n1、项目概述...\n2、人员分工...\n3、我的分工..."}
                  rows={6}
                />
                <div className="text-right text-xs text-gray-400 mt-1">
                  {(projectForm.project_description || "").length}/3000
                </div>
              </div>

              {/* 项目业绩（选填） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  项目业绩 <span className="text-gray-400 font-normal">（选填）</span>
                </label>
                <Textarea
                  value={projectForm.achievement || ""}
                  onChange={(e) => {
                    if (e.target.value.length <= 1000) {
                      setProjectForm({ ...projectForm, achievement: e.target.value })
                    }
                  }}
                  placeholder="请填写内容"
                  rows={4}
                />
                <div className="text-right text-xs text-gray-400 mt-1">
                  {(projectForm.achievement || "").length}/1000
                </div>
              </div>

              <DynamicFieldSlot
                data={projectForm}
                excludeKeys={[
                  "name", "projectName", "project_name", "role", "projectRole", "project_role",
                  "startYear", "startMonth", "endYear", "endMonth",
                  "project_description", "projectDesc", "description",
                  "achievement", "performance",
                  "projectUrl", "project_link", "link", "path", "id"
                ]}
                onChange={(k, v) => setProjectForm((prev: any) => ({ ...prev, [k]: v }))}
                title="项目经历 · 动态扩展字段"
              />

              {/* 操作按钮 */}
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setProjectDialogOpen(false)}>
                  取消
                </Button>
                <Button
                  className="bg-[#00beab] hover:bg-[#00a99a] text-white"
                  onClick={handleSaveProject}
                >
                  {isEditingProject ? "完成" : "添加"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </Card>
    )
  }
