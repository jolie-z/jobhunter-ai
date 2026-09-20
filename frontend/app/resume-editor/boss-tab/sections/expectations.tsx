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



export function BossExpectations({ field }: { field: ResumeField }) {
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
    overseasModified,
    overseasDialogOpen, setOverseasDialogOpen, overseasForm, setOverseasForm,
    countrySelectorOpen, setCountrySelectorOpen, languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen, baseInfoForm, setBaseInfoForm,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying,
    persistData, buildModuleUpdate, isSectionModified, displayData, applyFeedback,
    startEdit, saveEdit, cancelEdit,
    onRefresh, onSave, reportVersion,
  } = useBossCtx()
    const expectations = field.current_value || []
    const fulltimeCount = expectations.filter((e: any) => (e.jobType || "fulltime") === "fulltime").length
    const parttimeCount = expectations.filter((e: any) => e.jobType === "parttime").length
    const isEditing = editingExpectationIdx !== null

    // 打开添加弹窗
    const openAddDialog = () => {
      setEditingExpectationIdx(null)
      setExpectationDialogOpen(true)
    }

    // 打开编辑弹窗（条目预填转换由 ExpectationEditor 内部完成）
    const openEditDialog = (index: number) => {
      setEditingExpectationIdx(index)
      setExpectationDialogOpen(true)
    }

    // 保存（添加或更新）：ExpectationEditor 已返回 BOSS 标准条目并完成上限/必填校验
    const handleSaveExpectation = async (newItem: any) => {
      // 🐛 修复：无论新增/编辑都要基于原数组操作
      const updatedValue = [...expectations]
      if (isEditing && editingExpectationIdx !== null) {
        updatedValue[editingExpectationIdx] = newItem
      } else {
        updatedValue.push(newItem)
      }
      const updatedData = buildModuleUpdate("expectations", updatedValue)
      if (!updatedData) return
      const ok = await persistData(updatedData)
      if (!ok) return
      setLocalData(updatedData)
      setExpectationDialogOpen(false)
      setEditingExpectationIdx(null)
      if (onSave) onSave(updatedData)
    }

    // 是否达到添加上限（总共最多4条：3全职+1兼职）
    const canAddFulltime = fulltimeCount < 3
    const canAddParttime = parttimeCount < 1
    const canAdd = expectations.length < 4 && (canAddFulltime || canAddParttime)

    return (
      <Card className="mb-4">
        {report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["expectations", "求职期望"]} title="「求职期望」相关注意事项" />)}
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              {field.label}
              <ModifiedBadge show={isSectionModified("expectations")} />
              <Badge variant="secondary" className="ml-2">
                {expectations.length}条
              </Badge>
              <span className="ml-2 text-xs text-gray-400 font-normal">
                全职{fulltimeCount}/3 · 兼职{parttimeCount}/1
              </span>
            </CardTitle>
            <Button
              variant="outline"
              size="sm"
              disabled={!canAdd}
              onClick={openAddDialog}
            >
              <Plus className="w-4 h-4 mr-1" />
              添加求职期望
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {expectations.map((item: any, index: number) => (
              <div key={index} className="flex items-center justify-between p-3 border rounded-lg">
                <div className="flex-1">
                  <div className="font-medium">
                    {/* 🐛 修复：positions 可能不是数组 */}
                    {item.jobType === "parttime" && Array.isArray(item.positions) && item.positions.length
                      ? item.positions.join(", ")
                      : item.position}
                    {item.jobType && (
                      <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                        {item.jobType === "fulltime" ? "全职" : "兼职"}
                      </span>
                    )}
                  </div>
                  <div className="text-sm text-gray-600 mt-0.5">
                    {/* 🐛 Fix #1: Display salary information properly */}
                    {(() => {
                      // Simple display logic - show salary if it's valid
                      const displaySalary = (salary: string): string => {
                        if (!salary) return ''
                        // Match patterns like "15k-25k", "15-25K", etc.
                        const validPattern = /^\d+k?-?\d*k?$/i
                        if (!validPattern.test(salary)) return ''
                        // Extract numeric values for validation
                        const parts = salary.split('-')
                        const minNum = parseInt(parts[0].replace(/[kK]/g, '')) || 0
                        return (minNum > 0) ? salary : ''
                      }
                      
                      const displaySal = displaySalary(item.salary)
                      return [displaySal, item.city].filter(Boolean).join(" | ")
                    })()}
                  </div>
                  {/* 🐛 修复：industries 可能不是数组 */}
                  {Array.isArray(item.industries) && item.industries.length > 0 && (
                    <div className="text-xs text-gray-400 mt-0.5">
                      行业：{item.industries.join(", ")} 
                    </div>
                  )}
                  {/* 🐛 修复：otherCities 可能不是数组 */}
                  {Array.isArray(item.otherCities) && item.otherCities.length > 0 && (
                    <div className="text-xs text-gray-400 mt-0.5">
                      其他城市：{item.otherCities.join(", ")} 
                    </div>
                  )}
                  {/* 🐛 修复：parttime_preference 可能不是数组 */}
                  {item.jobType === "parttime" && Array.isArray(item.parttime_preference) && item.parttime_preference.length > 0 && (
                    <div className="text-xs text-gray-400 mt-0.5">
                      兼职偏好：{item.parttime_preference.join(", ")} 
                    </div>
                  )}
                  {/* 🐛 修复：parttime_time 可能不是数组 */}
                  {item.jobType === "parttime" && Array.isArray(item.parttime_time) && item.parttime_time.length > 0 && (
                    <div className="text-xs text-gray-400 mt-0.5">
                      兼职时间：{item.parttime_time.join(", ")} 
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button variant="ghost" size="sm" onClick={() => openEditDialog(index)}>
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
                          确定要删除这个求职期望吗？此操作无法撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => handleDelete("expectations", index)}>
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

        {/* 添加/编辑求职期望弹窗（共享组件 ExpectationEditor：boss-tab 与 agent-tab 同源） */}
        <ExpectationEditor
          open={expectationDialogOpen}
          editing={isEditing}
          fulltimeCount={fulltimeCount}
          parttimeCount={parttimeCount}
          initial={isEditing && editingExpectationIdx !== null ? expectations[editingExpectationIdx] : undefined}
          onOpenChange={(open) => {
            setExpectationDialogOpen(open)
            if (!open) setEditingExpectationIdx(null)
          }}
          onSave={handleSaveExpectation}
        />
      </Card>
    )
  }


export function BossOverseas({ field }: { field: ResumeField }) {
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
    overseasModified,
    overseasDialogOpen, setOverseasDialogOpen, overseasForm, setOverseasForm,
    countrySelectorOpen, setCountrySelectorOpen, languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen, baseInfoForm, setBaseInfoForm,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying,
    persistData, buildModuleUpdate, isSectionModified, displayData, applyFeedback,
    startEdit, saveEdit, cancelEdit,
    onRefresh, onSave, reportVersion,
  } = useBossCtx()
    // 兼容旧数据：current_value 可能是字符串或对象
    const rawValue = field.current_value
    const overseasData = typeof rawValue === "string"
      ? { countries: [], languages: [], duration: "", allowView: false }
      : (rawValue || { countries: [], languages: [], duration: "", allowView: false })

    const selectedCountries: string[] = overseasData.countries || []
    const selectedLanguages: string[] = overseasData.languages || []
    const selectedDuration: string = overseasData.duration || ""
    const allowView: boolean = overseasData.allowView ?? false

    // 获取已选国家对应的大洲codes（用于语言推荐）
    const selectedRegionCodes = countryRegions
      .filter((r) => r.subLevelModelList?.some((item) => selectedCountries.includes(item.name)))
      .map((r) => r.code)

    const updateOverseas = async (patch: Partial<typeof overseasData>) => {
      if (!localData) return
      const newData = { ...overseasData, ...patch }
      const updatedData = buildModuleUpdate("overseas", newData)
      if (!updatedData) return
      const ok = await persistData(updatedData)
      if (!ok) return
      setLocalData(updatedData)
      if (onSave) onSave(updatedData)
    }

    // 构建描述文本
    const buildDesc = () => {
      if (!selectedCountries.length && !selectedLanguages.length) return ""
      const parts: string[] = []
      if (selectedCountries.length) parts.push(`接受${selectedCountries.join("、")}的驻外岗位`)
      if (selectedLanguages.length) parts.push(`${selectedLanguages.join("、")}可作为工作语言`)
      return parts.join("，")
    }

    return (
      <Card className="mb-4">
        {report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["overseas", "驻外"]} title="「驻外选项」相关注意事项" />)}
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              {field.label}
              <ModifiedBadge show={overseasModified} />
              <span className="ml-1 text-xs text-gray-400 font-normal">（仅对驻 外岗位展示）</span>
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 描述文本 */}
          {buildDesc() && (
            <div className="text-sm text-[#00beab] bg-[#00beab]/5 rounded-md px-3 py-2">
              {buildDesc()}
            </div>
          )}

          {/* 国家/地区 */}
          <div>
            <label className="text-sm text-gray-600 mb-1 block">选择愿意接受的国家或地区</label>
            <CountrySelector
              value={selectedCountries}
              onChange={(v) => updateOverseas({ countries: v })}
              externalOpen={countrySelectorOpen}
              onExternalClose={() => setCountrySelectorOpen(false)}
            />
          </div>

          {/* 语言 */}
          <div>
            <label className="text-sm text-gray-600 mb-1 block">你所掌握可用于工作交流的语言</label>
            <LanguageSelector
              value={selectedLanguages}
              onChange={(v) => updateOverseas({ languages: v })}
              selectedRegions={selectedRegionCodes}
              externalOpen={languageSelectorOpen}
              onExternalClose={() => setLanguageSelectorOpen(false)}
            />
          </div>

          {/* 可接受境外工作时长 */}
          <div>
            <label className="text-sm text-gray-600 mb-1 block">
              可接受境外工作的时长
              <span className="text-red-500 ml-0.5">*</span>
            </label>
            <select
              value={selectedDuration}
              onChange={(e) => updateOverseas({ duration: e.target.value })}
              className="w-full h-[40px] rounded-md border border-input bg-background px-3 text-sm transition-colors hover:border-[#00beab] focus:border-[#00beab] focus:outline-none"
            >
              <option value="">请选择</option>
              {durationOptions.map((d) => (
                <option key={d.code} value={d.name}>{d.name}</option>
              ))}
            </select>
          </div>

          {/* 隐私开关 */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={allowView}
              onChange={(e) => updateOverseas({ allowView: e.target.checked })}
              className="h-4 w-4 rounded border-gray-300 text-[#00beab] accent-[#00beab]"
            />
            <span className="text-sm text-gray-700">
              允许发布驻外或境外出差职位的 BOSS，查看我的偏好
            </span>
          </label>
        </CardContent>
      </Card>
    )
  }
