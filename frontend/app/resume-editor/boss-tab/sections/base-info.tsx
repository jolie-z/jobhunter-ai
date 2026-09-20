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
import { ModifiedBadge, BOSS_PRIMARY, BOSS_MODULE_LABELS, BOSS_MODULES, BOSS_MODULE_MAP, BASE_INFO_PATHS } from "../constants"



export function BossBaseInfo() {
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
    if (!displayData) return null
    const name = displayData.name?.current_value || ""
    const phone = displayData.phone?.current_value || ""
    const email = displayData.email?.current_value || ""
    const wechat = displayData.wechat?.current_value || ""
    const jobStatus = displayData.job_status?.current_value || ""
    const expYears = displayData.experience_years?.current_value || ""
    const degree = displayData.education_degree?.current_value || ""
    const gender = displayData.gender?.current_value || ""
    const birthMonth = displayData.birth_month?.current_value || ""
    const workStartDate = displayData.work_start_date?.current_value || ""

    const jobStatusOptions = displayData.job_status?.options || ["离职-随时到岗", "在职-暂不考虑", "在职-考虑机会", "在职-月内到岗"]

    // 打开编辑弹窗
    const openBaseInfoDialog = () => {
      setBaseInfoForm({
        name: name as string,
        job_status: jobStatus as string,
        gender: gender as string,
        birth_month: birthMonth as string,
        work_start_date: workStartDate as string,
        wechat: wechat as string,
        email: email as string,
      })
      setBaseInfoDialogOpen(true)
    }

    // 保存
    const saveBaseInfo = async () => {
      if (!baseInfoForm.name?.trim()) {
        showToast("请输入姓名", "error")
        return
      }
      if (!localData) return

      const updatedData = { ...localData }
      if (updatedData.name) updatedData.name = { ...updatedData.name, current_value: baseInfoForm.name.trim() }
      if (updatedData.job_status) updatedData.job_status = { ...updatedData.job_status, current_value: baseInfoForm.job_status }
      if (updatedData.wechat) updatedData.wechat = { ...updatedData.wechat, current_value: baseInfoForm.wechat?.trim() || "" }
      if (updatedData.email) updatedData.email = { ...updatedData.email, current_value: baseInfoForm.email?.trim() || "" }
      // 新字段：性别、出生年月、参加工作时间
      if (!updatedData.gender) updatedData.gender = { label: "性别", required: false, type: "radio", options: ["男", "女"], current_value: "" }
      updatedData.gender = { ...updatedData.gender, current_value: baseInfoForm.gender }
      if (!updatedData.birth_month) updatedData.birth_month = { label: "出生年月", required: false, type: "yearmonth", current_value: "" }
      updatedData.birth_month = { ...updatedData.birth_month, current_value: baseInfoForm.birth_month }
      if (!updatedData.work_start_date) updatedData.work_start_date = { label: "参加工作时间", required: false, type: "yearmonth", current_value: "" }
      updatedData.work_start_date = { ...updatedData.work_start_date, current_value: baseInfoForm.work_start_date }

      const ok = await persistData(updatedData)
      if (!ok) return
      setLocalData(updatedData)
      setBaseInfoDialogOpen(false)
      showToast("保存成功")
      if (onSave) onSave(updatedData)
    }


    return (
      <>
        <Card className="mb-4">
          {report?.warnings && report.warnings.length > 0 && (<ModuleReportNotice warnings={report.warnings} matchKeywords={["job_status", "birth_month", "work_start_date", "基本信息"]} title="「基本信息」相关注意事项" />)}
          <CardContent className="p-5">
            <div className="flex items-start justify-between">
              {/* 左侧：用户信息 */}
              <div className="flex-1">
                {/* 姓名行（映射写入基本信息任一字段时标「已修改」） */}
                <p className="text-lg font-semibold text-gray-900 mb-2">
                  {name || "未设置"}
                  <ModifiedBadge show={isSectionModified(...BASE_INFO_PATHS)} />
                </p>
                {/* 标签行：经验、学历、状态 */}
                <div className="flex flex-wrap gap-3 mb-3 text-sm text-gray-600">
                  {expYears && (
                    <span className="flex items-center gap-1">
                      <span className="text-gray-400">⏱</span>{expYears}
                    </span>
                  )}
                  {degree && (
                    <span className="flex items-center gap-1">
                      <span className="text-gray-400">🎓</span>{degree}
                    </span>
                  )}
                  {jobStatus && (
                    <span className="flex items-center gap-1">
                      <span className="text-gray-400">📋</span>{jobStatus}
                    </span>
                  )}
                </div>
                {/* 联系方式行 */}
                <div className="flex flex-wrap gap-4 text-sm text-gray-500">
                  {phone && (
                    <span className="flex items-center gap-1">
                      <span className="text-gray-400">📱</span>{phone}
                    </span>
                  )}
                  {wechat && (
                    <span className="flex items-center gap-1">
                      <span className="text-gray-400">💬</span>{wechat}
                    </span>
                  )}
                  {email && (
                    <span className="flex items-center gap-1">
                      <span className="text-gray-400">✉️</span>{email}
                    </span>
                  )}
                </div>
              </div>
              {/* 右侧：编辑按钮 */}
              <Button variant="ghost" size="sm" className="text-[#00beab] hover:text-[#00beab]" onClick={openBaseInfoDialog}>
                <Edit className="w-4 h-4 mr-1" />
                编辑
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* 编辑个人信息弹窗 */}
        <Dialog open={baseInfoDialogOpen} onOpenChange={setBaseInfoDialogOpen}>
          <DialogContent className="max-w-[520px] max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>编辑个人信息</DialogTitle>
            </DialogHeader>
            <div className="space-y-5">
              {/* 姓名 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">姓名 <span className="text-red-500">*</span></label>
                <Input
                  value={baseInfoForm.name || ""}
                  onChange={(e) => setBaseInfoForm({ ...baseInfoForm, name: e.target.value })}
                  placeholder="请输入您的姓名"
                  maxLength={24}
                />
              </div>

              {/* 当前求职状态 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">当前求职状态</label>
                <Select value={baseInfoForm.job_status || ""} onValueChange={(v) => setBaseInfoForm({ ...baseInfoForm, job_status: v })}>
                  <SelectTrigger><SelectValue placeholder="请选择" /></SelectTrigger>
                  <SelectContent>
                    {jobStatusOptions.map((opt: string) => (
                      <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* 性别 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">性别</label>
                <div className="flex gap-2">
                  {["男", "女"].map((g) => (
                    <button
                      key={g}
                      onClick={() => setBaseInfoForm({ ...baseInfoForm, gender: g })}
                      className={`px-6 py-1.5 rounded-md text-sm border transition-colors ${
                        baseInfoForm.gender === g
                          ? "border-[#00beab] bg-[#00beab]/10 text-[#00beab] font-medium"
                          : "border-gray-200 text-gray-600 hover:border-gray-300"
                      }`}
                    >
                      {g}
                    </button>
                  ))}
                </div>
              </div>

              {/* 我的牛人身份（只读） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">我的牛人身份</label>
                <div className="w-full h-[40px] rounded-md border border-input bg-gray-50 px-3 text-sm text-gray-400 flex items-center">
                  职场人
                </div>
                <p className="text-xs text-gray-400 mt-1">牛人身份需要到BOSS直聘APP中修改</p>
              </div>

              {/* 出生年月 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">出生年月</label>
                <YearMonthPicker
                  value={baseInfoForm.birth_month || ""}
                  onChange={(v) => setBaseInfoForm({ ...baseInfoForm, birth_month: v })}
                  label="出生年月"
                  yearRange={[1960, 2026]}
                />
              </div>

              {/* 电话（只读） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">电话</label>
                <Input
                  value={phone as string}
                  disabled
                  className="bg-gray-50 text-gray-400"
                />
                <p className="text-xs text-gray-400 mt-1">
                  电话即为登录账号，如需修改可直接在账号设置中修改
                </p>
              </div>

              {/* 参加工作时间 */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">参加工作时间</label>
                <YearMonthPicker
                  value={baseInfoForm.work_start_date || ""}
                  onChange={(v) => setBaseInfoForm({ ...baseInfoForm, work_start_date: v })}
                  label="参加工作时间"
                  yearRange={[1990, new Date().getFullYear()]}
                />
              </div>

              {/* 微信号（选填） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">微信号 <span className="text-gray-400 font-normal">(选填)</span></label>
                <Input
                  value={baseInfoForm.wechat || ""}
                  onChange={(e) => setBaseInfoForm({ ...baseInfoForm, wechat: e.target.value })}
                  placeholder="请输入您的微信号"
                  maxLength={100}
                />
              </div>

              {/* 邮箱（选填） */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">邮箱 <span className="text-gray-400 font-normal">(选填)</span></label>
                <Input
                  value={baseInfoForm.email || ""}
                  onChange={(e) => setBaseInfoForm({ ...baseInfoForm, email: e.target.value })}
                  placeholder="请输入您的邮箱"
                  maxLength={80}
                />
              </div>
            </div>

            {/* 底部按钮 */}
            <div className="flex justify-end gap-3 pt-4 border-t">
              <Button variant="outline" onClick={() => setBaseInfoDialogOpen(false)}>取消</Button>
              <Button className="bg-[#00beab] hover:bg-[#00a99a] text-white" onClick={saveBaseInfo}>完成</Button>
            </div>
          </DialogContent>
        </Dialog>
      </>
    )
  }
