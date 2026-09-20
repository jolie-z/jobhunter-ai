/**
 * Job51 Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { Job51YearMonthPicker } from "@/components/ui/51job-year-month-picker"
import { Job51Cascader } from "@/components/ui/51job-cascader"
import { JOB51_SEX_OPTIONS } from "@/lib/51job-options"
import { JOB51_NEW_JOB_STATUSES } from "@/lib/51job-options"
import { JOB51_POLITICAL_STATUSES } from "@/lib/51job-options"
import { JOB51_IDENTITY_OPTIONS } from "@/lib/51job-options"
import { useJob51Ctx } from "../context"
import { SectionCard, ReadOnlyNote } from "../constants"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Loader2, Plus, Edit, Trash2, Save, X, Upload, Sparkles, Lock, User } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { ReportWarnings, ReportUnfilled, ModuleChangeSummary, ModuleReportNotice, ChangedBadge } from "../../agent-report-shared"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"


export function Job51BasicInfo() {
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
    setBasicInfoEditing,
    basicInfoForm,
    basicInfoEditing,
    setBasicInfoForm,
  } = useJob51Ctx()

    const info = getVal("basic_info") || {}
    const cName = info.cName || ""
    const sex = info.sex ?? ""
    const sexString = sex === "0" ? "男" : sex === "1" ? "女" : info.sexString || ""
    const birthday = info.birthday || ""
    const areaObj = info.area || {}
    const areaString = typeof areaObj === "object" ? (areaObj.label || "") : (info.areaString || "")
    const mobile = info.mobile || ""
    const email = info.email || ""
    const workYearMonth = info.workYearMonth || ""
    const workYearString = info.workYearString || info.workExperienceDuration || ""
    const newCurrentSituation = info.newCurrentSituation ?? ""
    const newCurrentSituationString = info.newCurrentSituationString || ""
    const topDegreeString = info.topDegreeString || ""
    const age = info.age || ""
    const wechatId = info.wechatId || ""
    const isVerify = info.isVerify !== false
    const personAsLabel = info.personAsLabel || ""
    const personAsLabelString = info.personAsLabelString || ""
    const politicsStatus = info.politicsStatus || ""
    const politicsStatusString = info.politicsStatusString || ""
    const householdObj = info.household || {}
    const householdString = typeof householdObj === "object" ? (householdObj.label || "") : (info.householdString || "")

    const openEdit = () => {
      // 初始化表单，area/household 统一为 {id, label} 格式
      const areaInit = typeof areaObj === "object" && areaObj.id
        ? { ...areaObj }
        : { id: typeof areaObj === "string" ? areaObj : "", label: areaString }
      const householdInit = typeof householdObj === "object" && householdObj.id
        ? { ...householdObj }
        : { id: typeof householdObj === "string" ? householdObj : "", label: householdString }
      setBasicInfoForm({
        ...info,
        area: areaInit,
        household: householdInit,
      })
      setBasicInfoEditing(true)
    }

    const handleSave = async () => {
      const ok = await updateField("basic_info", basicInfoForm)
      if (!ok) return
      setBasicInfoEditing(false)
    }

    const handleCancel = () => {
      setBasicInfoEditing(false)
    }

    // 根据身份类型过滤求职状态选项
    const identityType = basicInfoForm.personAsLabel || "1"
    const filteredStatuses = JOB51_NEW_JOB_STATUSES.filter((s) => s.typeCode === identityType)

    // 计算工作年限
    const calcWorkYears = (ym: string) => {
      if (!ym) return ""
      const [y, m] = ym.split("-").map(Number)
      if (!y) return ""
      const now = new Date()
      let years = now.getFullYear() - y
      if (now.getMonth() + 1 < m) years--
      return years >= 0 ? `${years}年经验` : ""
    }

    // ===== 编辑模式：内联展开表单 =====
    if (basicInfoEditing) {
      return (
        <SectionCard id="basic-info">
          <div className="text-base font-bold text-gray-900 mb-5">编辑基本信息</div>

          {/* 两列表单 */}
          <div className="grid grid-cols-2 gap-x-8 gap-y-5">
            {/* 姓名（只读） */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 flex items-center gap-2">
                姓名
                {isVerify && <span className="text-[11px] text-[#FF6B00] bg-[#FF6B00]/10 px-1.5 py-0.5 rounded">已实名</span>}
              </label>
              <Input value={basicInfoForm.cName || ""} readOnly className="bg-gray-50 text-gray-400 cursor-not-allowed" />
            </div>

            {/* 当前求职状态 */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 block">当前求职状态</label>
              <select
                value={basicInfoForm.newCurrentSituation ?? ""}
                onChange={(e) => {
                  const found = JOB51_NEW_JOB_STATUSES.find((s) => s.code === e.target.value)
                  setBasicInfoForm({ ...basicInfoForm, newCurrentSituation: e.target.value, newCurrentSituationString: found?.value || "" })
                }}
                className="w-full h-[40px] rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
              >
                <option value="">请选择</option>
                {filteredStatuses.map((o) => (
                  <option key={o.code} value={o.code}>{o.value}</option>
                ))}
              </select>
            </div>

            {/* 性别（只读/锁定） */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 flex items-center justify-between">
                性别
                <ReadOnlyNote />
              </label>
              <div className="flex gap-0 h-[40px]">
                {JOB51_SEX_OPTIONS.map((g, i) => (
                  <button
                    key={g.code}
                    type="button"
                    disabled
                    aria-disabled="true"
                    className={`px-6 text-sm border cursor-not-allowed transition-colors ${
                      i === 0 ? "rounded-l-md" : "rounded-r-md -ml-px"
                    } ${
                      basicInfoForm.sex === g.code
                        ? "bg-[#FF6B00]/70 text-white border-[#FF6B00]/70 font-medium z-10"
                        : "bg-gray-50 text-gray-400 border-gray-200"
                    }`}
                  >
                    {g.value}
                  </button>
                ))}
              </div>
            </div>

            {/* 你的身份 */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 block">你的身份</label>
              <select
                value={basicInfoForm.personAsLabel || ""}
                onChange={(e) => {
                  const found = JOB51_IDENTITY_OPTIONS.find((o) => o.lable === e.target.value)
                  // 切换身份时重置求职状态（不同身份对应不同选项）
                  setBasicInfoForm({ ...basicInfoForm, personAsLabel: e.target.value, personAsLabelString: found?.value || "", newCurrentSituation: "", newCurrentSituationString: "" })
                }}
                className="w-full h-[40px] rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
              >
                <option value="">请选择</option>
                {JOB51_IDENTITY_OPTIONS.map((o) => (
                  <option key={o.lable} value={o.lable}>{o.value}</option>
                ))}
              </select>
            </div>

            {/* 出生年月（只读） */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 flex items-center justify-between">
                出生年月
                <ReadOnlyNote />
              </label>
              <Input value={basicInfoForm.birthday || ""} readOnly className="bg-gray-50 text-gray-400 cursor-not-allowed" />
            </div>

            {/* 参加工作时间 */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 block">
                参加工作时间
                {basicInfoForm.workYearMonth && (
                  <span className="text-gray-400 ml-1">（{calcWorkYears(basicInfoForm.workYearMonth)}）</span>
                )}
              </label>
              <Job51YearMonthPicker
                value={basicInfoForm.workYearMonth || ""}
                onChange={(v) => setBasicInfoForm({ ...basicInfoForm, workYearMonth: v })}
              />
            </div>

            {/* 居住地（省→市→区 三级级联） */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 block">居住地</label>
              <Job51Cascader
                level={3}
                dataUrl="/51job_area_3level.json"
                value={basicInfoForm.area || null}
                onChange={(code: any, name: any) => setBasicInfoForm({ ...basicInfoForm, area: { id: code, label: name } })}
              />
            </div>

            {/* 手机（只读） */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 flex items-center justify-between">
                手机
                <ReadOnlyNote />
              </label>
              <Input value={basicInfoForm.mobile || ""} readOnly className="bg-gray-50 text-gray-400 cursor-not-allowed" />
            </div>

            {/* 政治面貌（选填） */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 block">政治面貌<span className="text-gray-400">(选填)</span></label>
              <select
                value={basicInfoForm.politicsStatus || ""}
                onChange={(e) => {
                  const found = JOB51_POLITICAL_STATUSES.find((o) => o.code === e.target.value)
                  setBasicInfoForm({ ...basicInfoForm, politicsStatus: e.target.value, politicsStatusString: found?.value || "" })
                }}
                className="w-full h-[40px] rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
              >
                <option value="">请选择</option>
                {JOB51_POLITICAL_STATUSES.map((o) => (
                  <option key={o.code} value={o.code}>{o.value}</option>
                ))}
              </select>
            </div>

            {/* 微信号（选填） */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 block">微信号<span className="text-gray-400">(选填)</span></label>
              <Input
                value={basicInfoForm.wechatId || ""}
                onChange={(e) => setBasicInfoForm({ ...basicInfoForm, wechatId: e.target.value })}
                placeholder="请填写微信号"
              />
            </div>

            {/* 邮箱（只读，选填） */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 flex items-center justify-between">
                邮箱<span className="text-gray-400">(选填)</span>
                <ReadOnlyNote />
              </label>
              <Input value={basicInfoForm.email || ""} readOnly className="bg-gray-50 text-gray-400 cursor-not-allowed" />
            </div>

            {/* 户口所在地（省→市 两级级联，选填） */}
            <div>
              <label className="text-sm text-gray-600 mb-1.5 block">户口所在地<span className="text-gray-400">(选填)</span></label>
              <Job51Cascader
                level={2}
                dataUrl="/51job_hukou_2level.json"
                value={basicInfoForm.household || null}
                onChange={(code: any, name: any) => setBasicInfoForm({ ...basicInfoForm, household: { id: code, label: name } })}
              />
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
        </SectionCard>
      )
    }

    // ===== 展示模式 =====
    return (
      <SectionCard id="basic-info">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-4">
            {/* 头像 */}
            <div className="w-16 h-16 rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center flex-shrink-0 overflow-hidden">
              {info.avatarUrl ? (
                <img src={info.avatarUrl} alt="头像" className="w-full h-full object-cover" />
              ) : (
                <User className="w-8 h-8 text-gray-300" />
              )}
            </div>
            {/* 信息 */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-gray-900">{cName}</span>
                {changedModuleKeys.has("basic_info") && <ChangedBadge className="ml-1" />}
                {isVerify && (
                  <span className="text-[11px] text-[#FF6B00] bg-[#FF6B00]/10 px-1.5 py-0.5 rounded">已实名</span>
                )}
              </div>
              <div className="text-sm text-gray-600 mt-1">
                {[
                  workYearString,
                  age && `${age}岁`,
                  topDegreeString,
                  newCurrentSituationString,
                ].filter(Boolean).join(" | ")}
              </div>
              <div className="text-sm text-gray-500 mt-1">
                {[mobile, email].filter(Boolean).join(" | ")}
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
      </SectionCard>
    )
  }
