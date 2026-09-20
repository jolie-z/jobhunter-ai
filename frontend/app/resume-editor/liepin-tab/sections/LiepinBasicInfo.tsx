/**
 * Liepin Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { useLiepinCtx } from "../context"
import { User } from "lucide-react"
import { LIEPIN_WORK_STATUS, LIEPIN_POLITICAL_STATUS, LIEPIN_DEGREE_OPTIONS, LIEPIN_LANGUAGES, LIEPIN_PROFICIENCY_LEVELS, LIEPIN_LANG_LEVELS } from "@/lib/liepin-options"
import { LiepinCitySelector } from "@/components/ui/liepin-city-selector"
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


export function LiepinBasicInfo() {
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

    const info = getVal("basic_info") || {}
    // 基本信息可编辑字段清单（用于变更徽章判断）
    const BASIC_EDITABLE_PATHS = ["city", "birth", "job_status", "political_status", "work_start_date",
      "current_salary_month", "current_salary_months", "wechat", "avatar", "education_degree",
      "work_years", "age", "gender", "show_gender_suffix", "salary_confidential"]
    const basicFieldChanged = (sub: string) => fieldChanged(`basic_info.${sub}`)
    const anyBasicChanged = BASIC_EDITABLE_PATHS.some(basicFieldChanged)
    const name = info.name || ""
    const gender = info.gender || ""
    const genderSuffix = gender === "女" ? "女士" : gender === "男" ? "先生" : ""
    const age = info.age || ""
    const workYears = info.work_years || ""
    const city = info.city || ""
    const jobStatus = info.job_status || ""
    const phone = info.phone || ""
    const email = info.email || ""
    const wechat = info.wechat || ""

    const openEdit = () => {
      setBasicInfoForm({ ...info })
      setBasicInfoDialogOpen(true)
    }

    const handleSave = async () => {
      const ok = await updateField("basic_info", basicInfoForm)
      if (!ok) return
      setBasicInfoDialogOpen(false)
    }

    return (
      <SectionCard moduleKey="basic_info">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-4">
            {/* 头像 */}
            <div className="w-20 h-20 rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center flex-shrink-0 overflow-hidden">
              {info.avatar ? (
                <img src={info.avatar} alt="头像" className="w-full h-full object-cover" />
              ) : (
                <User className="w-10 h-10 text-gray-300" />
              )}
            </div>
            {/* 信息 */}
            <div className="flex-1 min-w-0">
              <div className="text-lg font-bold text-gray-900 flex items-center gap-2">
                {name}{genderSuffix && <span className="text-sm font-normal text-gray-500 ml-1">{genderSuffix}</span>}
                {anyBasicChanged && <ChangedBadge />}
              </div>
              <div className="text-sm text-gray-600 mt-1">
                {[age && `${age}岁`, workYears && `工作${workYears}年`, city, jobStatus].filter(Boolean).join(" | ")}
              </div>
              <div className="text-sm text-gray-500 mt-1">
                {[phone, email, wechat && `微信: ${wechat}`].filter(Boolean).join(" | ")}
              </div>
            </div>
          </div>
          <button
            onClick={openEdit}
            className="text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer flex-shrink-0"
          >
            编辑
          </button>
        </div>

        {/* 编辑 Dialog */}
        <Dialog open={basicInfoDialogOpen} onOpenChange={setBasicInfoDialogOpen}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>编辑基本信息</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 max-h-[68vh] overflow-y-auto pr-1">
              {/* 真实姓名（只读，已实名） */}
              <div>
                <label className="text-xs text-gray-500 mb-1 flex items-center gap-2">
                  真实姓名
                  <span className="text-[11px] text-[#FF6B00] bg-[#FF6B00]/10 px-1.5 py-0.5 rounded">已实名</span>
                  <ReadOnlyNote />
                </label>
                <Input value={basicInfoForm.name || ""} readOnly className="bg-gray-50 text-gray-400 cursor-not-allowed" />
                <label className="flex items-center gap-2 mt-2 text-xs text-gray-600 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={!!basicInfoForm.show_gender_suffix}
                    onChange={(e: any) => setBasicInfoForm({ ...basicInfoForm, show_gender_suffix: e.target.checked })}
                    className="accent-[#FF6B00]"
                  />
                  显示先生/女士
                </label>
              </div>

              {/* 性别 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-2">
                  性别
                  {basicFieldChanged("gender") && <ChangedBadge />}
                </label>
                <div className="flex gap-4">
                  {["男", "女"].map((g) => (
                    <label key={g} className="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer">
                      <input
                        type="radio"
                        name="liepin-gender"
                        checked={basicInfoForm.gender === g}
                        onChange={() => setBasicInfoForm({ ...basicInfoForm, gender: g })}
                        className="accent-[#FF6B00]"
                      />
                      {g}
                    </label>
                  ))}
                </div>
              </div>

              {/* 当前城市 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-2">
                  当前城市
                  {basicFieldChanged("city") && <ChangedBadge />}
                </label>
                <LiepinCitySelector
                  value={basicInfoForm.city || ""}
                  onChange={(v: any) => setBasicInfoForm({ ...basicInfoForm, city: v })}
                />
              </div>

              {/* 出生日期 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-2">
                  出生日期
                  {basicFieldChanged("birth") && <ChangedBadge />}
                </label>
                <LiepinYearMonthPicker
                  value={basicInfoForm.birth || ""}
                  onChange={(v: any) => setBasicInfoForm({ ...basicInfoForm, birth: v })}
                />
              </div>

              {/* 目前状态 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-2">
                  目前状态
                  {basicFieldChanged("job_status") && <ChangedBadge />}
                </label>
                <select
                  value={basicInfoForm.job_status || ""}
                  onChange={(e: any) => setBasicInfoForm({ ...basicInfoForm, job_status: e.target.value })}
                  className="w-full h-[40px] rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
                >
                  <option value="">请选择</option>
                  {LIEPIN_WORK_STATUS.map((o: any) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                </select>
              </div>

              {/* 政治面貌 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-2">
                  政治面貌
                  {basicFieldChanged("political_status") && <ChangedBadge />}
                </label>
                <select
                  value={basicInfoForm.political_status || ""}
                  onChange={(e: any) => setBasicInfoForm({ ...basicInfoForm, political_status: e.target.value })}
                  className="w-full h-[40px] rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
                >
                  <option value="">请选择</option>
                  {LIEPIN_POLITICAL_STATUS.map((o: any) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                </select>
              </div>

              {/* 参加工作时间 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-2">
                  参加工作时间
                  {basicFieldChanged("work_start_date") && <ChangedBadge />}
                </label>
                <LiepinYearMonthPicker
                  value={basicInfoForm.work_start_date || ""}
                  onChange={(v: any) => setBasicInfoForm({ ...basicInfoForm, work_start_date: v })}
                />
              </div>

              {/* 目前薪资 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-2">
                  目前薪资
                  {(basicFieldChanged("current_salary_month") || basicFieldChanged("current_salary_months")) && <ChangedBadge />}
                </label>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={0}
                    value={basicInfoForm.current_salary_month ?? ""}
                    onChange={(e: any) => setBasicInfoForm({ ...basicInfoForm, current_salary_month: e.target.value })}
                    placeholder="月薪（选填）"
                    className="flex-1"
                  />
                  <span className="text-sm text-gray-400 whitespace-nowrap">元 ×</span>
                  <Input
                    type="number"
                    min={0}
                    value={basicInfoForm.current_salary_months ?? ""}
                    onChange={(e: any) => setBasicInfoForm({ ...basicInfoForm, current_salary_months: e.target.value })}
                    placeholder="月数"
                    className="w-24"
                  />
                  <span className="text-sm text-gray-400 whitespace-nowrap">个月</span>
                </div>
                <div className="flex items-center justify-between mt-2">
                  <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={!!basicInfoForm.salary_confidential}
                      onChange={(e: any) => setBasicInfoForm({ ...basicInfoForm, salary_confidential: e.target.checked })}
                      className="accent-[#FF6B00]"
                    />
                    薪资显示为保密
                    {basicFieldChanged("salary_confidential") && <ChangedBadge />}
                  </label>
                  {(() => {
                    const m = parseFloat(basicInfoForm.current_salary_month) || 0
                    const n = parseFloat(basicInfoForm.current_salary_months) || 0
                    if (!m || !n) return null
                    return (
                      <span className="text-xs text-gray-500 flex items-center gap-1">
                        <span className="text-[#FF6B00]">🧮</span>
                        目前年薪：{(m * n / 10000).toFixed(1)}万
                      </span>
                    )
                  })()}
                </div>
              </div>

              {/* 手机号码（只读） */}
              <div>
                <label className="text-xs text-gray-500 mb-1 flex items-center justify-between">
                  手机号码
                  <ReadOnlyNote />
                </label>
                <Input value={basicInfoForm.phone || ""} readOnly className="bg-gray-50 text-gray-400 cursor-not-allowed" />
              </div>

              {/* 邮箱（只读） */}
              <div>
                <label className="text-xs text-gray-500 mb-1 flex items-center justify-between">
                  邮箱
                  <ReadOnlyNote />
                </label>
                <Input value={basicInfoForm.email || ""} readOnly className="bg-gray-50 text-gray-400 cursor-not-allowed" />
              </div>

              {/* 我的身份（只读） */}
              <div>
                <label className="text-xs text-gray-500 mb-1 flex items-center justify-between">
                  我的身份
                  <ReadOnlyNote />
                </label>
                <Input value={basicInfoForm.identity || ""} readOnly className="bg-gray-50 text-gray-400 cursor-not-allowed" />
              </div>

              {/* 微信号（可编辑） */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-2">
                  微信号
                  {basicFieldChanged("wechat") && <ChangedBadge />}
                </label>
                <Input
                  value={basicInfoForm.wechat || ""}
                  onChange={(e: any) => setBasicInfoForm({ ...basicInfoForm, wechat: e.target.value })}
                  placeholder="请填写微信号"
                />
              </div>
            </div>
            <DialogActions onCancel={() => setBasicInfoDialogOpen(false)} onConfirm={handleSave} saving={saving} />
          </DialogContent>
        </Dialog>
      </SectionCard>
    )
  }
