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



export function BossWorkExperience({ field }: { field: ResumeField }) {
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
    const experiences = field.current_value || []
    const isEditingWorkExp = editingWorkExpIdx !== null

    // 打开添加弹窗
    const openAddWorkExp = () => {
      setEditingWorkExpIdx(null)
      setWorkExpForm({
        company: "",
        industry: [],
        department: "",
        position: "",
        startYear: "",
        startMonth: "",
        endYear: "",
        endMonth: "",
        content: "",
        achievement: "",
        skills: [],
        hideResume: false,
      })
      setWorkExpDialogOpen(true)
    }

    // 打开编辑弹窗（预填数据）
    const openEditWorkExp = (index: number) => {
      const item = experiences[index]
      setEditingWorkExpIdx(index)
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
      // 🐛 Fix #3: Ensure skills are loaded correctly from backend data
      setWorkExpForm({
        company: item.company || "",
        industry: item.industry ? [item.industry] : (item.industries || []),
        department: item.department || "",
        position: item.position || "",
        startYear: sy,
        startMonth: sm,
        endYear: ey,
        endMonth: em,
        content: item.content || item.description || "",
        achievement: item.achievement || "",
        // 🐛 处理两种可能的技能格式：对象数组或纯字符串数组
        skills: Array.isArray(item.skills)
          ? item.skills.map((s: any) => (typeof s === 'string' ? s : s.name || '')).filter(Boolean)
          : [],
        hideResume: item.hideResume || false,
      })
      setWorkExpDialogOpen(true)
    }

    // 保存（添加或更新）
    const handleSaveWorkExp = async () => {
      if (!workExpForm.company?.trim()) {
        showToast("请输入公司名称", "error")
        return
      }
      if (!workExpForm.position) {
        showToast("请选择职位名称", "error")
        return
      }
      if (!workExpForm.startYear || !workExpForm.startMonth) {
        showToast("请选择入职时间", "error")
        return
      }
      if (!workExpForm.content?.trim()) {
        showToast("请填写工作内容", "error")
        return
      }

      // 🐛 Fix #3: Protect skills field - use flat string array format
      const newItem = {
        company: workExpForm.company.trim(),
        industry: workExpForm.industry?.[0] || "",
        department: workExpForm.department?.trim() || "",
        position: workExpForm.position,
        startYear: workExpForm.startYear,
        startMonth: workExpForm.startMonth,
        endYear: workExpForm.endYear,
        endMonth: workExpForm.endMonth,
        content: workExpForm.content || "",
        achievement: workExpForm.achievement || "",
        // 🐛 关键：保持 skills 为字符串数组，不要转换成对象结构
        skills: Array.isArray(workExpForm.skills) 
          ? workExpForm.skills.map((s: any) => ({ name: String(s) })) // Convert to expected format
          : [],
        hideResume: workExpForm.hideResume || false,
      }

      if (isEditingWorkExp && editingWorkExpIdx !== null) {
        const updatedValue = [...experiences]
        updatedValue[editingWorkExpIdx] = newItem
        const updatedData = buildModuleUpdate("work_experience", updatedValue)
        if (!updatedData) return
        const ok = await persistData(updatedData)
        if (!ok) return
        setLocalData(updatedData)
        setWorkExpDialogOpen(false)
        setEditingWorkExpIdx(null)
        setWorkExpForm({})
        if (onSave) onSave(updatedData)
      } else {
        const updatedValue = [...experiences, newItem]
        const updatedData = buildModuleUpdate("work_experience", updatedValue)
        if (!updatedData) return
        const ok = await persistData(updatedData)
        if (!ok) return
        setLocalData(updatedData)
        setWorkExpDialogOpen(false)
        setWorkExpForm({})
        if (onSave) onSave(updatedData)
      }
    }

    // 删除工作经历
    const handleDeleteWorkExp = async (index: number) => {
      const updatedValue = [...experiences]
      updatedValue.splice(index, 1)
      const updatedData = buildModuleUpdate("work_experience", updatedValue)
      if (!updatedData) return
      const ok = await persistData(updatedData)
      if (!ok) return
      setLocalData(updatedData)
      if (onSave) onSave(updatedData)
    }

    // 格式化时间显示
    const formatPeriod = (item: any) => {
      const start = item.startYear ? `${item.startYear}.${(item.startMonth || "").padStart(2, "0")}` : ""
      const end = item.endYear ? `${item.endYear}.${(item.endMonth || "").padStart(2, "0")}` : "至今"
      if (!start) return item.period || ""
      return `${start} - ${end}`
    }

    return (
      <Card className="mb-4">
        {report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["work_experience", "工作经历"]} title="「工作经历」相关注意事项" />)}
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              {field.label}
              <ModifiedBadge show={isSectionModified("work_experience")} />
              <Badge variant="secondary" className="ml-2">
                {experiences.length}条
              </Badge>
            </CardTitle>
            <Button variant="outline" size="sm" onClick={openAddWorkExp}>
              <Plus className="w-4 h-4 mr-1" />
              添加工作经历
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {experiences.map((item: any, index: number) => (
              <div key={index} className="p-4 border rounded-lg">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="font-medium text-base">{item.company}</div>
                    <div className="text-sm text-gray-600 mt-0.5">
                      {item.position}
                      {item.department && <span className="text-gray-400"> · {item.department}</span>}
                    </div>
                    <div className="text-xs text-gray-400 mt-0.5">{formatPeriod(item)}</div>
                    {item.industry && (
                      <div className="text-xs text-gray-400 mt-0.5">行业：{item.industry}</div>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => openEditWorkExp(index)}>
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
                            确定要删除这段工作经历吗？此操作无法撤销。
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>取消</AlertDialogCancel>
                          <AlertDialogAction onClick={() => handleDeleteWorkExp(index)}>
                            删除
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </div>
                {(item.content || item.description) && (
                  <div className="text-sm text-gray-700 mt-2 line-clamp-3">{item.content || item.description}</div>
                )}
              </div>
            ))}
          </div>
        </CardContent>

        {/* 添加/编辑工作经历弹窗 */}
        <Dialog open={workExpDialogOpen} onOpenChange={(open) => {
          setWorkExpDialogOpen(open)
          if (!open) {
            setEditingWorkExpIdx(null)
            setWorkExpForm({})
          }
        }}>
          <DialogContent className="max-w-[560px] max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{isEditingWorkExp ? "编辑工作经历" : "添加工作经历"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              {/* 公司名称 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  公司名称 <span className="text-red-500">*</span>
                </label>
                <Input
                  value={workExpForm.company || ""}
                  onChange={(e) => setWorkExpForm({ ...workExpForm, company: e.target.value })}
                  placeholder="请输入公司名称"
                />
              </div>

              {/* 所属行业 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">所属行业</label>
                <IndustrySelector
                  value={workExpForm.industry || []}
                  onChange={(value) => setWorkExpForm({ ...workExpForm, industry: value })}
                  placeholder="请选择所属行业"
                  max={1}
                />
              </div>

              {/* 所属部门（选填） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  所属部门 <span className="text-gray-400 font-normal">（选填）</span>
                </label>
                <Input
                  value={workExpForm.department || ""}
                  onChange={(e) => setWorkExpForm({ ...workExpForm, department: e.target.value })}
                  placeholder="请输入所属部门"
                />
              </div>

              {/* 职位名称 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  职位名称 <span className="text-red-500">*</span>
                </label>
                <JobTitleSelector
                  value={workExpForm.position || ""}
                  onChange={(value) => setWorkExpForm({ ...workExpForm, position: value })}
                  placeholder="请选择职位名称"
                  jobType="fulltime"
                />
              </div>

              {/* 在职时间 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  在职时间 <span className="text-red-500">*</span>
                </label>
                <DateRangePicker
                  startYear={workExpForm.startYear || ""}
                  startMonth={workExpForm.startMonth || ""}
                  endYear={workExpForm.endYear || ""}
                  endMonth={workExpForm.endMonth || ""}
                  onChange={(sy, sm, ey, em) => setWorkExpForm({ ...workExpForm, startYear: sy, startMonth: sm, endYear: ey, endMonth: em })}
                />
              </div>

              {/* 工作内容 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  工作内容 <span className="text-red-500">*</span>
                </label>
                <Textarea
                  value={workExpForm.content || ""}
                  onChange={(e) => {
                    if (e.target.value.length <= 3000) {
                      setWorkExpForm({ ...workExpForm, content: e.target.value })
                    }
                  }}
                  placeholder="请描述你的工作内容"
                  rows={5}
                />
                <div className="text-right text-xs text-gray-400 mt-1">
                  {(workExpForm.content || "").length}/3000
                </div>
              </div>

              {/* 工作业绩（选填） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  工作业绩 <span className="text-gray-400 font-normal">（选填）</span>
                </label>
                <Textarea
                  value={workExpForm.achievement || ""}
                  onChange={(e) => {
                    if (e.target.value.length <= 1000) {
                      setWorkExpForm({ ...workExpForm, achievement: e.target.value })
                    }
                  }}
                  placeholder="请描述你取得的工作业绩"
                  rows={3}
                />
                <div className="text-right text-xs text-gray-400 mt-1">
                  {(workExpForm.achievement || "").length}/1000
                </div>
              </div>

              {/* 拥有技能（选填）- 回车添加标签 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  拥有技能 <span className="text-gray-400 font-normal">（选填）</span>
                </label>
                <div className="rounded-md border border-input bg-background px-3 py-2">
                  {(workExpForm.skills || []).length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {(workExpForm.skills || []).map((skill: string, idx: number) => (
                        <span key={idx} className="inline-flex items-center gap-1 rounded bg-[#00beab]/10 px-2 py-0.5 text-xs text-[#00beab]">
                          {skill}
                          <button
                            type="button"
                            onClick={() => setWorkExpForm({ ...workExpForm, skills: (workExpForm.skills || []).filter((_: string, i: number) => i !== idx) })}
                            className="text-[#00beab]/60 hover:text-[#00beab] leading-none"
                          >
                            ✕
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                  <input
                    type="text"
                    placeholder={(workExpForm.skills || []).length >= 6 ? "已达上限（最多6个）" : "输入技能后按回车添加（最多6个）"}
                    disabled={(workExpForm.skills || []).length >= 6}
                    className="w-full text-sm outline-none bg-transparent placeholder:text-muted-foreground disabled:cursor-not-allowed"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault()
                        const val = (e.target as HTMLInputElement).value.trim()
                        if ((workExpForm.skills || []).length >= 6) {
                          showToast("最多添加6个技能", "error")
                          return
                        }
                        if (val && !(workExpForm.skills || []).includes(val)) {
                          setWorkExpForm({ ...workExpForm, skills: [...(workExpForm.skills || []), val] })
                        }
                        ;(e.target as HTMLInputElement).value = ""
                      }
                    }}
                  />
                </div>
              </div>

              {/* 对该公司隐藏我的简历 */}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="hideResume"
                  checked={workExpForm.hideResume || false}
                  onChange={(e) => setWorkExpForm({ ...workExpForm, hideResume: e.target.checked })}
                  className="h-4 w-4 rounded border-gray-300 text-[#00beab] accent-[#00beab]"
                />
                <label htmlFor="hideResume" className="text-sm text-gray-700 cursor-pointer">
                  对该公司隐藏我的简历
                </label>
              </div>

              <DynamicFieldSlot
                data={workExpForm}
                excludeKeys={[
                  "company", "industry", "department", "position", "startYear", "startMonth", "endYear", "endMonth",
                  "soFar", "content", "work_content", "workContent", "workDesc", "achievement", "performance",
                  "skills", "hideResume", "path", "id", "subType"
                ]}
                onChange={(k, v) => setWorkExpForm((prev: any) => ({ ...prev, [k]: v }))}
                title="工作经历 · 动态扩展字段"
              />

              {/* 操作按钮 */}
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setWorkExpDialogOpen(false)}>
                  取消
                </Button>
                <Button
                  className="bg-[#00beab] hover:bg-[#00a99a] text-white"
                  onClick={handleSaveWorkExp}
                >
                  {isEditingWorkExp ? "完成" : "添加"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </Card>
    )
  }
