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



export function BossEducation({ field }: { field: ResumeField }) {
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
    const education = field.current_value || []
    const isEditingEducation = editingEducationIdx !== null

    // 打开添加弹窗
    const openAddEducation = () => {
      setEditingEducationIdx(null)
      setEducationForm({
        degree: "",
        school: "",
        major: "",
        startYear: "",
        endYear: "",
        campus_experience: "",
        thesisTitle: "",
        thesisDesc: "",
      })
      setEducationDialogOpen(true)
    }

    // 打开编辑弹窗（预填数据）
    const openEditEducation = (index: number) => {
      const item = education[index]
      setEditingEducationIdx(index)
      // 解析旧格式 period → startYear/endYear
      let sy = item.startYear || ""
      let ey = item.endYear || ""
      if (!sy && item.period) {
        const parsed = parsePeriod(item.period)
        sy = parsed.startYear
        ey = parsed.endYear
      }
      setEducationForm({
        degree: item.degree || "",
        school: item.school || "",
        major: item.major || "",
        startYear: sy,
        endYear: ey,
        campus_experience: item.campus_experience || "",
        thesisTitle: item.thesisTitle || "",
        thesisDesc: item.thesisDesc || "",
      })
      setEducationDialogOpen(true)
    }

    // 保存（添加或更新）
    const handleSaveEducation = async () => {
      if (!educationForm.degree) {
        showToast("请选择学历", "error")
        return
      }
      if (!educationForm.school?.trim()) {
        showToast("请输入学校名称", "error")
        return
      }
      if (!educationForm.major?.trim()) {
        showToast("请输入专业", "error")
        return
      }
      if (!educationForm.startYear) {
        showToast("请选择开始年份", "error")
        return
      }

      const newItem = {
        degree: educationForm.degree,
        school: educationForm.school.trim(),
        major: educationForm.major.trim(),
        startYear: educationForm.startYear,
        endYear: educationForm.endYear,
        campus_experience: educationForm.campus_experience || "",
        thesisTitle: educationForm.thesisTitle || "",
        thesisDesc: educationForm.thesisDesc || "",
      }

      if (isEditingEducation && editingEducationIdx !== null) {
        const updatedValue = [...education]
        updatedValue[editingEducationIdx] = newItem
        const updatedData = buildModuleUpdate("education", updatedValue)
        if (!updatedData) return
        const ok = await persistData(updatedData)
        if (!ok) return
        setLocalData(updatedData)
        setEducationDialogOpen(false)
        setEditingEducationIdx(null)
        setEducationForm({})
        if (onSave) onSave(updatedData)
      } else {
        const updatedValue = [...education, newItem]
        const updatedData = buildModuleUpdate("education", updatedValue)
        if (!updatedData) return
        const ok = await persistData(updatedData)
        if (!ok) return
        setLocalData(updatedData)
        setEducationDialogOpen(false)
        setEducationForm({})
        if (onSave) onSave(updatedData)
      }
    }

    // 删除教育经历
    const handleDeleteEducation = async (index: number) => {
      const updatedValue = [...education]
      updatedValue.splice(index, 1)
      const updatedData = buildModuleUpdate("education", updatedValue)
      if (!updatedData) return
      const ok = await persistData(updatedData)
      if (!ok) return
      setLocalData(updatedData)
      if (onSave) onSave(updatedData)
    }

    // 格式化时间显示
    const formatEduPeriod = (item: any) => {
      if (item.startYear) {
        return item.endYear ? `${item.startYear} - ${item.endYear}` : `${item.startYear} - 至今`
      }
      return item.period || ""
    }

    return (
      <Card className="mb-4">
        {report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["education", "教育经历"]} title="「教育经历」相关注意事项" />)}
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              {field.label}
              <ModifiedBadge show={isSectionModified("education")} />
              <Badge variant="secondary" className="ml-2">
                {education.length}条
              </Badge>
            </CardTitle>
            <Button variant="outline" size="sm" onClick={openAddEducation}>
              <Plus className="w-4 h-4 mr-1" />
              添加教育经历
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {education.map((item: any, index: number) => (
              <div key={index} className="flex items-center justify-between p-3 border rounded-lg">
                <div className="flex-1">
                  <div className="font-medium">{item.school}</div>
                  <div className="text-sm text-gray-600 mt-0.5">
                    {item.major} | {item.degree}
                  </div>
                  <div className="text-xs text-gray-400 mt-0.5">{formatEduPeriod(item)}</div>
                </div>
                <div className="flex gap-2">
                  <Button variant="ghost" size="sm" onClick={() => openEditEducation(index)}>
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
                          确定要删除这段教育经历吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => handleDeleteEducation(index)}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>
            ))}
          </div>
        </CardContent>

        {/* 添加/编辑教育经历弹窗 */}
        <Dialog open={educationDialogOpen} onOpenChange={(open) => {
          setEducationDialogOpen(open)
          if (!open) {
            setEditingEducationIdx(null)
            setEducationForm({})
          }
        }}>
          <DialogContent className="max-w-[560px] max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{isEditingEducation ? "编辑教育经历" : "添加教育经历"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              {/* 学历 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  学历 <span className="text-red-500">*</span>
                </label>
                <DegreeSelector
                  value={educationForm.degree || ""}
                  onChange={(value) => setEducationForm({ ...educationForm, degree: value })}
                  placeholder="选择学历/学制类型"
                />
              </div>

              {/* 学校名称 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  学校名称 <span className="text-red-500">*</span>
                </label>
                <Input
                  value={educationForm.school || ""}
                  onChange={(e) => setEducationForm({ ...educationForm, school: e.target.value })}
                  placeholder="例如：北京大学"
                />
              </div>

              {/* 专业 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  专业 <span className="text-red-500">*</span>
                </label>
                <Input
                  value={educationForm.major || ""}
                  onChange={(e) => setEducationForm({ ...educationForm, major: e.target.value })}
                  placeholder="例如：计算机科学与技术"
                />
              </div>

              {/* 时间段 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  时间段 <span className="text-red-500">*</span>
                </label>
                <YearRangePicker
                  startYear={educationForm.startYear || ""}
                  endYear={educationForm.endYear || ""}
                  onChange={(sy, ey) => setEducationForm({ ...educationForm, startYear: sy, endYear: ey })}
                />
              </div>

              {/* 在校经历（选填） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  在校经历 <span className="text-gray-400 font-normal">（选填）</span>
                </label>
                <Textarea
                  value={educationForm.campus_experience || ""}
                  onChange={(e) => {
                    if (e.target.value.length <= 3000) {
                      setEducationForm({ ...educationForm, campus_experience: e.target.value })
                    }
                  }}
                  placeholder={"1、在校担任职务...\n2、获得荣誉...\n3、所学主要课程..."}
                  rows={5}
                />
                <div className="text-right text-xs text-gray-400 mt-1">
                  {(educationForm.campus_experience || "").length}/3000
                </div>
              </div>

              {/* 毕业设计/论文题目（选填） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  毕业设计/论文题目 <span className="text-gray-400 font-normal">（选填）</span>
                </label>
                <Input
                  value={educationForm.thesisTitle || ""}
                  onChange={(e) => setEducationForm({ ...educationForm, thesisTitle: e.target.value })}
                  placeholder="请输入"
                />
              </div>

              {/* 毕业设计/论文描述（选填） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  毕业设计/论文描述 <span className="text-gray-400 font-normal">（选填）</span>
                </label>
                <Textarea
                  value={educationForm.thesisDesc || ""}
                  onChange={(e) => {
                    if (e.target.value.length <= 600) {
                      setEducationForm({ ...educationForm, thesisDesc: e.target.value })
                    }
                  }}
                  placeholder={"描述毕设/论文主要内容，向BOSS展示您的学术能力\n例如：\n1、选题的目的及意义...\n2、摘要及关键词...\n3、论文结论或成果..."}
                  rows={4}
                />
                <div className="text-right text-xs text-gray-400 mt-1">
                  {(educationForm.thesisDesc || "").length}/600
                </div>
              </div>

              <DynamicFieldSlot
                data={educationForm}
                excludeKeys={[
                  "school", "schoolName", "degree", "major", "startYear", "startMonth", "endYear", "endMonth",
                  "fullTime", "campus_experience", "campusExperience", "experience",
                  "thesisTitle", "thesisDesc", "path", "id"
                ]}
                onChange={(k, v) => setEducationForm((prev: any) => ({ ...prev, [k]: v }))}
                title="教育经历 · 动态扩展字段"
              />

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setEducationDialogOpen(false)}>
                  取消
                </Button>
                <Button
                  className="bg-[#00beab] hover:bg-[#00a99a] text-white"
                  onClick={handleSaveEducation}
                >
                  {isEditingEducation ? "完成" : "添加"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </Card>
    )
  }
