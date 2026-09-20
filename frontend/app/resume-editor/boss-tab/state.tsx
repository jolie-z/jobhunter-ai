/**
 * BOSS Tab 状态与业务逻辑中枢（机械搬迁自 boss-tab.tsx 单组件作用域，零行为变化）。
 * BossCtx 类型由本 hook 返回值自动推导（context.ts）。
 */
"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect } from "react"
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
import { ReportWarnings, ReportUnfilled, ModuleChangeSummary, ModuleReportNotice, type PlatformReport } from "../agent-report-shared"
import { savePlatformData, fetchPlatformReport } from "../api-client"
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
import { ResumeCatalogue } from "@/components/ui/resume-catalogue"
import { YearMonthPicker } from "@/components/ui/year-month-picker"
import { ExpectationEditor } from "@/components/ui/expectation-editor"
import {
} from "@/lib/overseas-options"
import {
  BOSS_MODULES,
  BOSS_MODULE_DEFAULT_SELECTED,
  type BossTabProps,
  type ResumeData,
  type BossOptions,
  type WritebackFeedbackState,
  type FeedbackDetail,
  DEFAULT_BOSS_FRAMEWORK,
} from "./constants"
import { useBossWritebackHandlers } from "./state-writeback"
import { useBossHealHandlers } from "./state-heal"

export function useBossTabState({ data, loading, onRefresh, onSave, reportVersion = 0 }: BossTabProps) {
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState<any>(null)
  const [localData, setLocalData] = useState<ResumeData | null>(data)
  const [saving, setSaving] = useState(false)
  const [deletingItem, setDeletingItem] = useState<{ field: string; index: number } | null>(null)
  const [bossOptions, setBossOptions] = useState<BossOptions | null>(null)
  // Toast 提示（替代 alert）
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null)
  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 2000)
  }
  const [editingExpectationIdx, setEditingExpectationIdx] = useState<number | null>(null)
  const [expectationDialogOpen, setExpectationDialogOpen] = useState(false)
  const [editingWorkExpIdx, setEditingWorkExpIdx] = useState<number | null>(null)
  const [workExpDialogOpen, setWorkExpDialogOpen] = useState(false)
  const [workExpForm, setWorkExpForm] = useState<any>({})
  const [editingProjectIdx, setEditingProjectIdx] = useState<number | null>(null)
  const [projectDialogOpen, setProjectDialogOpen] = useState(false)
  const [projectForm, setProjectForm] = useState<any>({})
  const [editingEducationIdx, setEditingEducationIdx] = useState<number | null>(null)
  const [educationDialogOpen, setEducationDialogOpen] = useState(false)
  const [educationForm, setEducationForm] = useState<any>({})
  const [certSelectorOpen, setCertSelectorOpen] = useState(false)
  const [overseasDialogOpen, setOverseasDialogOpen] = useState(false)
  const [overseasForm, setOverseasForm] = useState<any>({})

  // 模块勾选回写状态
  const [selectedModules, setSelectedModules] = useState<Record<string, boolean>>(() =>
    BOSS_MODULES.reduce((acc, m) => ({ ...acc, [m.key]: true }), {})
  )
  const [writebacking, setWritebacking] = useState(false)
  const [writebackConfirm, setWritebackConfirm] = useState(false)
  const [writebackFeedback, setWritebackFeedback] = useState<WritebackFeedbackState | null>(null)
  const [showWritebackDetails, setShowWritebackDetails] = useState(false)
  // 「保存为回写数据源」：把当前 BOSS 本地数据固化为回写快照（boss_writeback.json）
  const [savingSnapshot, setSavingSnapshot] = useState(false)
  const [snapshotFeedback, setSnapshotFeedback] = useState<{ msg: string; ok: boolean; time?: string } | null>(null)

  // BOSS 回写自愈 Agent 状态
  const [bossAgentDiagnosing, setBossAgentDiagnosing] = useState(false)
  const [bossAgentReport, setBossAgentReport] = useState<any | null>(null)
  const [bossAgentModalOpen, setBossAgentModalOpen] = useState(false)
  const [bossAgentApplying, setBossAgentApplying] = useState(false)
  const [bossRollbackFeedback, setBossRollbackFeedback] = useState<{ msg: string; ok: boolean; snapshotId?: string } | null>(null)
  const [bossRollingBack, setBossRollingBack] = useState(false)


  const [countrySelectorOpen, setCountrySelectorOpen] = useState(false)
  const [languageSelectorOpen, setLanguageSelectorOpen] = useState(false)
  // 个人信息统一弹窗
  const [baseInfoDialogOpen, setBaseInfoDialogOpen] = useState(false)
  const [baseInfoForm, setBaseInfoForm] = useState<any>({})

  // 主简历映射报告（顶部操作区「映射」按钮生成；审核后两步确认应用到 BOSS 本地数据）
  const [report, setReport] = useState<PlatformReport | null>(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [applyConfirmOpen, setApplyConfirmOpen] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyFeedback, setApplyFeedback] = useState<{ msg: string; ok: boolean; time?: string } | null>(null)

  // —— handler 簇组合（定义在 state-writeback.ts / state-heal.ts，行为零变化）——
  const getNowTime = () => {
    const d = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  }
  const { handleSaveWritebackSource, selectedModuleKeys, toggleAllModules, handleWritebackModules } = useBossWritebackHandlers({
    getNowTime,
    selectedModules,
    setSelectedModules,
    setSavingSnapshot,
    setSnapshotFeedback,
    setWritebacking,
    setWritebackFeedback,
    setShowWritebackDetails,
    setWritebackConfirm,
  })
  const { handleDispatchBossHealerAgent, handleBossAgentApplyHeal, handleRollbackBossSnapshot } = useBossHealHandlers({
    writebackFeedback,
    selectedModuleKeys,
    showToast,
    bossAgentReport,
    setBossAgentDiagnosing,
    setBossAgentReport,
    setBossAgentModalOpen,
    setBossAgentApplying,
    setBossRollbackFeedback,
    setBossRollingBack,
    handleWritebackModules,
  })

  useEffect(() => {
    setLocalData(data ?? null)
  }, [data])

  useEffect(() => {
    loadBossOptions()
  }, [])

  // 当父组件data变化时同步localData（data 被清空为 null 时同步清空，防止旧数据残留显示）
  useEffect(() => {
    setLocalData(data ?? null)
  }, [data])

  // 加载选项数据
  useEffect(() => {
    loadBossOptions()
  }, [])

  // 拉取本平台映射报告（挂载时 + 顶部操作区生成后 reportVersion 变化时）
  const fetchReport = async () => {
    setReportLoading(true)
    try {
      const r = await fetchPlatformReport(API_BASE, "boss")
      if (r.status === "ok") setReport(r.report)
      else if (r.status === "absent") setReport(null)
      // error：后端暂不可用，保留旧报告
    } finally {
      setReportLoading(false)
    }
  }

  useEffect(() => {
    fetchReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportVersion])

  const loadBossOptions = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/resume-editor/options/boss`)
      const result = await response.json()
      if (result.success) {
        setBossOptions(result.data)
      }
    } catch (error) {
      console.error("加载选项数据失败:", error)
    }
  }


  // 空态判断与其他三平台对齐：仅 data 为 null/undefined（从未采集/刚清空）时显示空态；
  // data 为空对象 {}（清空后点了「刷新数据」重新加载）时渲染空框架骨架——
  // 模块与字段元数据保留、值全空，映射报告保留至上一次生成结果被覆盖
  const isEmpty = !data

  const parsePeriod = (period: string): { startYear: string; startMonth: string; endYear: string; endMonth: string } => {
    const result = { startYear: "", startMonth: "", endYear: "", endMonth: "" }
    if (!period) return result
    // 用 - – — 或 "至" 分割
    const parts = period.split(/[-–—]|至/).map((s) => s.trim())
    if (parts.length >= 1) {
      const startMatch = parts[0].match(/(\d{4})[.\-/](\d{1,2})/)
      if (startMatch) {
        result.startYear = startMatch[1]
        result.startMonth = String(parseInt(startMatch[2]))
      } else {
        const yearOnly = parts[0].match(/(\d{4})/)
        if (yearOnly) result.startYear = yearOnly[1]
      }
    }
    if (parts.length >= 2 && !parts[1].includes("今")) {
      const endMatch = parts[1].match(/(\d{4})[.\-/](\d{1,2})/)
      if (endMatch) {
        result.endYear = endMatch[1]
        result.endMonth = String(parseInt(endMatch[2]))
      } else {
        const yearOnly = parts[1].match(/(\d{4})/)
        if (yearOnly) result.endYear = yearOnly[1]
      }
    }
    // "至今" → endYear/endMonth 留空
    return result
  }

  // 渲染工作经历（照搬BOSS官网完整表单）
  const buildModuleUpdate = (moduleName: string, currentValue: any): ResumeData | null => {
    if (!localData) return null
    const fieldMeta = localData[moduleName] || DEFAULT_BOSS_FRAMEWORK[moduleName]
    if (!fieldMeta) return null
    return { ...localData, [moduleName]: { ...fieldMeta, current_value: currentValue } }
  }
  const appliedPathSet = new Set<string>(report?.applied_paths || [])
  const isSectionModified = (...paths: string[]) => paths.some(p => appliedPathSet.has(p))
  const overseasModified = [...appliedPathSet].some(p => p.startsWith("overseas"))

  // 删除项目
  const handleDelete = async (fieldName: string, index: number) => {
    const fieldValue = localData?.[fieldName]?.current_value
    if (!Array.isArray(fieldValue)) return

    setSaving(true)
    try {
      const updatedValue = [...fieldValue]
      updatedValue.splice(index, 1)

      const updatedData = {
        ...localData!,
        [fieldName]: {
          ...localData![fieldName],
          current_value: updatedValue,
        },
      }

      const ok = await persistData(updatedData)
      if (ok) {
        setLocalData(updatedData)
        setDeletingItem(null)
        if (onSave) onSave(updatedData)
        showToast("删除成功")
      }
    } finally {
      setSaving(false)
    }
  }

  // 持久化数据到后端
  const persistData = async (updatedData: ResumeData): Promise<boolean> => {
    const { ok, message } = await savePlatformData(API_BASE, "boss", updatedData)
    if (!ok) showToast(`保存失败: ${message}`, "error")
    return ok
  }
  // 开始编辑
  const startEdit = (fieldName: string, currentValue: any) => {
    setEditingField(fieldName)
    setEditValue(currentValue)
  }

  // 保存编辑
  const saveEdit = async (fieldName: string) => {
    if (!localData) return

    setSaving(true)
    try {
      const updatedData = {
        ...localData,
        [fieldName]: {
          ...localData[fieldName],
          current_value: editValue,
        },
      }

      const response = await fetch(`${API_BASE}/api/resume-editor/save/boss`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updatedData),
      })

      const result = await response.json()
      if (result.success) {
        setLocalData(updatedData)
        setEditingField(null)
        setEditValue(null)
        if (onSave) onSave(updatedData)
        showToast("保存成功")
      } else {
        showToast(`保存失败: ${result.message}`, "error")
      }
    } catch (error) {
      showToast(`保存失败: ${error}`, "error")
    } finally {
      setSaving(false)
    }
  }

  // 取消编辑
  const cancelEdit = () => {
    setEditingField(null)
    setEditValue(null)
  }



  // 应用映射：报告字段覆盖写入 BOSS 本地数据（两步确认；写入后刷新展示）
  const handleApplyReport = async () => {
    if (!report) return
    setApplyConfirmOpen(false)
    setApplying(true)
    setApplyFeedback(null)
    const now = getNowTime()
    try {
      const entries = report.fields.map(f => ({ path: f.path, value: f.value }))
      const res = await fetch(`${API_BASE}/api/agent-map/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: "boss", entries }),
      })
      const result = await res.json()
      if (result.success) {
        // 即时合并「已修改」标识（后端已持久化，此处本地先行，无需等下次拉报告）
        const applied: string[] = result.applied || []
        if (applied.length) {
          setReport(prev => prev ? {
            ...prev,
            applied_paths: Array.from(new Set([...(prev.applied_paths || []), ...applied])),
          } : prev)
        }
        setApplyFeedback({ msg: `✓ ${result.message}；点「保存快照」后可回写官网`, ok: true, time: now })
        onRefresh()
      } else {
        setApplyFeedback({ msg: result.message || "写入失败", ok: false, time: now })
      }
    } catch (e) {
      setApplyFeedback({ msg: "写入失败: " + e, ok: false, time: now })
    } finally {
      setApplying(false)
    }
  }



  // 使用localData实现即时渲染；底层始终保留框架骨架
  const displayData: ResumeData = { ...DEFAULT_BOSS_FRAMEWORK, ...(localData || data || {}) }

  // 计算侧边栏可见项
  const visibleKeys: string[] = []
  if (displayData) {
    if (displayData.name || displayData.phone || displayData.email || displayData.wechat || displayData.job_status || displayData.experience_years || displayData.education_degree) visibleKeys.push("baseInfo")
    if (displayData.personal_advantage) visibleKeys.push("userDesc")
    if (displayData.expectations || displayData.industry) visibleKeys.push("expectList")
    if (displayData.work_experience) visibleKeys.push("workExpList")
    if (displayData.projects) visibleKeys.push("projectExpList")
    if (displayData.education) visibleKeys.push("educationExpList")
    if (displayData.certificates) visibleKeys.push("certificationList")
    if (displayData.overseas) visibleKeys.push("stayAbroad")
  }

  return {
    // props 透传
    data, loading, onRefresh, onSave, reportVersion,
    // state 全集
    editingField, setEditingField,
    editValue, setEditValue,
    localData, setLocalData,
    saving, setSaving,
    deletingItem, setDeletingItem,
    bossOptions, setBossOptions,
    toast, setToast,
    editingExpectationIdx, setEditingExpectationIdx,
    expectationDialogOpen, setExpectationDialogOpen,
    editingWorkExpIdx, setEditingWorkExpIdx,
    workExpDialogOpen, setWorkExpDialogOpen,
    workExpForm, setWorkExpForm,
    editingProjectIdx, setEditingProjectIdx,
    projectDialogOpen, setProjectDialogOpen,
    projectForm, setProjectForm,
    editingEducationIdx, setEditingEducationIdx,
    educationDialogOpen, setEducationDialogOpen,
    educationForm, setEducationForm,
    certSelectorOpen, setCertSelectorOpen,
    overseasDialogOpen, setOverseasDialogOpen,
    overseasForm, setOverseasForm,
    selectedModules, setSelectedModules,
    writebacking, setWritebacking,
    writebackConfirm, setWritebackConfirm,
    writebackFeedback, setWritebackFeedback,
    showWritebackDetails, setShowWritebackDetails,
    savingSnapshot, setSavingSnapshot,
    snapshotFeedback, setSnapshotFeedback,
    bossAgentDiagnosing, setBossAgentDiagnosing,
    bossAgentReport, setBossAgentReport,
    bossAgentModalOpen, setBossAgentModalOpen,
    bossAgentApplying, setBossAgentApplying,
    bossRollbackFeedback, setBossRollbackFeedback,
    bossRollingBack, setBossRollingBack,
    countrySelectorOpen, setCountrySelectorOpen,
    languageSelectorOpen, setLanguageSelectorOpen,
    baseInfoDialogOpen, setBaseInfoDialogOpen,
    baseInfoForm, setBaseInfoForm,
    report, setReport,
    reportLoading, setReportLoading,
    applyConfirmOpen, setApplyConfirmOpen,
    applying, setApplying,
    // handlers
    handleDispatchBossHealerAgent,
    handleBossAgentApplyHeal,
    handleRollbackBossSnapshot,
    fetchReport,
    loadBossOptions,
    handleSaveWritebackSource,
    selectedModuleKeys,
    toggleAllModules,
    handleApplyReport,
    handleWritebackModules,
    handleDelete,
    startEdit, saveEdit, cancelEdit,
    overseasModified,
    showToast,
    parsePeriod,
    setApplyFeedback, applyFeedback,
    persistData,
    buildModuleUpdate,
    isSectionModified,
    displayData,
    visibleKeys,
    isEmpty,
  }
}
