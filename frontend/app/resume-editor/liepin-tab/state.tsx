/**
 * 猎聘 Tab 状态与业务逻辑中枢（机械搬迁自 liepin-tab.tsx，行为零变化）
 */
"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect, useContext, createContext } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import {
} from "@/components/ui/dialog"
import {
} from "@/components/ui/alert-dialog"
import { Loader2, Plus, Trash2, User, Lock, ChevronDown, Sparkles, Save, Upload } from "lucide-react"
import { cn } from "@/lib/utils"
import { LiepinCitySelector, LiepinCityMultiSelector } from "@/components/ui/liepin-city-selector"
import { LiepinJobSelector } from "@/components/ui/liepin-job-selector"
import { LiepinIndustrySelector } from "@/components/ui/liepin-industry-selector"
import { LiepinSalarySelector } from "@/components/ui/liepin-salary-selector"
import { LiepinYearMonthPicker } from "@/components/ui/liepin-year-month-picker"
import { LiepinCertSelector } from "@/components/ui/liepin-cert-selector"
import { LiepinSkillSelector } from "@/components/ui/liepin-skill-selector"
import { LiepinCatalogue } from "@/components/ui/liepin-catalogue"
import { LIEPIN_WORK_STATUS, LIEPIN_POLITICAL_STATUS, LIEPIN_DEGREE_OPTIONS, LIEPIN_LANGUAGES, LIEPIN_PROFICIENCY_LEVELS, LIEPIN_LANG_LEVELS } from "@/lib/liepin-options"
import { ReportWarnings, ReportUnfilled, ChangedBadge, ModuleChangeSummary, ModuleReportNotice, type PlatformReport } from "../agent-report-shared"
import { savePlatformData, fetchPlatformReport } from "../api-client"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"

import { LIEPIN_MODULES, LIEPIN_MODULE_MAP, LIEPIN_NOTICE_MAP, SectionHeader, LiepinReportWarningsContext, type ResumeData, type ResumeField, type LiepinTabProps, type WritebackFeedbackState, type DeleteConfirmTarget, MODULE_DEFAULT_SELECTED,
} from "./constants"
import { useLiepinWritebackHandlers } from "./state-writeback"
import { useLiepinHealHandlers } from "./state-heal"
import { useLiepinReportHandlers } from "./state-report"

export function useLiepinTabState(props: LiepinTabProps) {
  const { data, onRefresh, reportVersion = 0 } = props

  // —— state 全集（机械搬迁） ——
  const [localData, setLocalData] = useState<ResumeData | null>(data)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null)
  const [report, setReport] = useState<PlatformReport | null>(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [applyConfirmOpen, setApplyConfirmOpen] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyFeedback, setApplyFeedback] = useState<{ msg: string; ok: boolean; time?: string } | null>(null)
  const [savingSnapshot, setSavingSnapshot] = useState(false)
  const [snapshotFeedback, setSnapshotFeedback] = useState<{ msg: string; ok: boolean; time?: string } | null>(null)
  const [selectedModules, setSelectedModules] = useState<Record<string, boolean>>(MODULE_DEFAULT_SELECTED)
  const [writebackConfirm, setWritebackConfirm] = useState(false)
  const [writebacking, setWritebacking] = useState(false)
  const [writebackFeedback, setWritebackFeedback] = useState<WritebackFeedbackState | null>(null)
  const [showWritebackDetails, setShowWritebackDetails] = useState(false)
  const [basicInfoDialogOpen, setBasicInfoDialogOpen] = useState(false)
  const [basicInfoForm, setBasicInfoForm] = useState<any>({})
  const [selfAssessmentEditing, setSelfAssessmentEditing] = useState(false)
  const [selfAssessmentValue, setSelfAssessmentValue] = useState("")
  const [expectationDialogOpen, setExpectationDialogOpen] = useState(false)
  const [expectationsForm, setExpectationsForm] = useState<any[]>([])
  const [editingExpectationIdx, setEditingExpectationIdx] = useState<number | null>(null)
  const [workExpDialogOpen, setWorkExpDialogOpen] = useState(false)
  const [workExpForm, setWorkExpForm] = useState<any>({})
  const [editingWorkExpIdx, setEditingWorkExpIdx] = useState<number | null>(null)
  const [showOptional, setShowOptional] = useState(false)
  const [projectDialogOpen, setProjectDialogOpen] = useState(false)
  const [projectForm, setProjectForm] = useState<any>({})
  const [editingProjectIdx, setEditingProjectIdx] = useState<number | null>(null)
  const [educationDialogOpen, setEducationDialogOpen] = useState(false)
  const [educationForm, setEducationForm] = useState<any>({})
  const [editingEducationIdx, setEditingEducationIdx] = useState<number | null>(null)
  const [certSelectorOpen, setCertSelectorOpen] = useState(false)
  const [skillSelectorOpen, setSkillSelectorOpen] = useState(false)
  const [languageDialogOpen, setLanguageDialogOpen] = useState(false)
  const [languageForm, setLanguageForm] = useState<any>({})
  const [editingLanguageIdx, setEditingLanguageIdx] = useState<number | null>(null)
  const [additionalInfoEditing, setAdditionalInfoEditing] = useState(false)
  const [additionalInfoValue, setAdditionalInfoValue] = useState("")
  const [deleteTarget, setDeleteTarget] = useState<DeleteConfirmTarget | null>(null)
  const [liepinAgentDiagnosing, setLiepinAgentDiagnosing] = useState(false)
  const [liepinAgentReport, setLiepinAgentReport] = useState<any | null>(null)
  const [liepinAgentModalOpen, setLiepinAgentModalOpen] = useState(false)
  const [liepinAgentApplying, setLiepinAgentApplying] = useState(false)
  const [liepinRollbackFeedback, setLiepinRollbackFeedback] = useState<{ msg: string; ok: boolean; snapshotId?: string } | null>(null)
  const [liepinRollingBack, setLiepinRollingBack] = useState(false)


  const confirmDelete = async () => {
    if (!deleteTarget) return
    const { fieldName, index } = deleteTarget
    if (fieldName === "expectations") {
      await handleDeleteExpectation(index)
    } else {
      await handleDeleteItem(fieldName, index)
    }
    setDeleteTarget(null)
  }

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 2000)
  }

  const fieldChanged = (path: string): boolean => {
    if (!report) return false
    if ((report.applied_paths || []).includes(path)) return true
    return report.fields.some(f => f.path === path && f.changed === true)
  }

  const itemChanged = (path: string, idx: number): boolean => {
    if (!report) return false
    if ((report.applied_paths || []).includes(path)) return true
    const f = report.fields.find(x => x.path === path)
    return !!f && Array.isArray(f.changed_items) && f.changed_items.includes(idx)
  }

  const getNowTime = () => {
    const d = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  }

  // —— handler 簇组合（定义在 state-writeback.ts / state-heal.ts / state-report.ts，行为零变化）——
  const { handleSaveWritebackSource, selectedModuleKeys, toggleAllModules, scrollToModule, handleWritebackModules } = useLiepinWritebackHandlers({
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
  const { fetchReport, handleApplyReport } = useLiepinReportHandlers({
    report,
    setReport,
    setReportLoading,
    setApplyConfirmOpen,
    setApplying,
    setApplyFeedback,
    getNowTime,
    onRefresh,
  })
  const { handleDispatchLiepinHealerAgent, handleLiepinAgentApplyHeal, handleRollbackLiepinSnapshot } = useLiepinHealHandlers({
    writebackFeedback,
    selectedModuleKeys,
    showToast,
    liepinAgentReport,
    setLiepinAgentDiagnosing,
    setLiepinAgentReport,
    setLiepinAgentModalOpen,
    setLiepinAgentApplying,
    setLiepinRollbackFeedback,
    setLiepinRollingBack,
    handleWritebackModules,
  })

  const persistData = async (updatedData: ResumeData): Promise<boolean> => {
    setSaving(true)
    try {
      const { ok, message } = await savePlatformData(API_BASE, "liepin", updatedData)
      if (ok) {
        setLocalData(updatedData)
        showToast("保存成功")
      } else {
        showToast(`保存失败: ${message}`, "error")
      }
      return ok
    } finally {
      setSaving(false)
    }
  }

  const updateField = async (fieldName: string, value: any): Promise<boolean> => {
    if (!localData?.[fieldName]) return false
    const updatedData = {
      ...localData,
      [fieldName]: {
        ...localData[fieldName],
        current_value: value,
      },
    }
    return persistData(updatedData)
  }

  const handleDeleteItem = async (fieldName: string, index: number): Promise<boolean> => {
    if (!Array.isArray(localData?.[fieldName]?.current_value)) return false
    const updatedValue = [...localData![fieldName].current_value]
    updatedValue.splice(index, 1)
    const updatedData = {
      ...localData!,
      [fieldName]: {
        ...localData![fieldName],
        current_value: updatedValue,
      },
    }
    return persistData(updatedData)
  }

  const handleAddItem = async (fieldName: string, newItem: any): Promise<boolean> => {
    if (!localData?.[fieldName]) return false
    const fieldValue = Array.isArray(localData[fieldName].current_value) ? localData[fieldName].current_value : []
    const updatedValue = [...fieldValue, newItem]
    const updatedData = {
      ...localData!,
      [fieldName]: {
        ...localData![fieldName],
        current_value: updatedValue,
      },
    }
    return persistData(updatedData)
  }

  const handleUpdateItem = async (fieldName: string, index: number, updatedItem: any): Promise<boolean> => {
    if (!Array.isArray(localData?.[fieldName]?.current_value)) return false
    const fieldValue = [...localData![fieldName].current_value]
    fieldValue[index] = updatedItem
    const updatedData = {
      ...localData!,
      [fieldName]: {
        ...localData![fieldName],
        current_value: fieldValue,
      },
    }
    return persistData(updatedData)
  }

  const getVal = (fieldName: string) => {
    return localData?.[fieldName]?.current_value ?? null
  }

  const getLabel = (fieldName: string, fallback: string) => {
    return localData?.[fieldName]?.label ?? fallback
  }

  const normalizeIndustries = (raw: any): string[] => {
    if (Array.isArray(raw)) return raw.filter(Boolean).map(String)
    if (typeof raw === "string" && raw.trim()) {
      const trimmed = raw.trim()
      if (trimmed === "全部行业" || trimmed === "不限") return ["全部行业"]
      return trimmed.split(/[、,，/]+/).map((s: string) => s.trim()).filter(Boolean)
    }
    return []
  }

  const migrateExpectationItem = (item: any): any => {
    // 如果已经是新格式，确保数组属性被严格归一化
    if (item.salary_min !== undefined || item.salary_max !== undefined || item.industries !== undefined || item.other_cities !== undefined) {
      return {
        position: item.position || item.expected_position || "",
        city: item.city || item.expected_city || "",
        other_cities: Array.isArray(item.other_cities) ? item.other_cities : (item.other_cities ? [String(item.other_cities)] : []),
        industries: normalizeIndustries(item.industries || item.industry || item.expected_industry),
        salary_min: item.salary_min || "",
        salary_max: item.salary_max || "",
        salary_months: item.salary_months || 12,
      }
    }
    const result: any = {
      position: item.position || item.expected_position || "",
      city: "",
      other_cities: [] as string[],
      industries: [] as string[],
      salary_min: "",
      salary_max: "",
      salary_months: 12,
    }
    // city: 按"、"拆分，第一个为 city，其余为 other_cities
    const cityStr = item.city || item.expected_city || ""
    if (cityStr) {
      const parts = cityStr.split("、").filter(Boolean)
      result.city = parts[0] || ""
      result.other_cities = parts.slice(1)
    }
    // industry: 统一归一化
    const indStr = item.industry || item.expected_industry || item.industries || ""
    if (indStr) {
      result.industries = normalizeIndustries(indStr)
    }
    // salary: 解析 "15k - 25k × 14薪" 格式
    const salStr = item.salary || item.expected_salary || ""
    if (salStr) {
      const salMatch = salStr.match(/(\d+[kK])\s*[-–—~]\s*(\d+[kK])/)
      if (salMatch) {
        result.salary_min = salMatch[1].toLowerCase()
        result.salary_max = salMatch[2].toLowerCase()
      }
      const monthsMatch = salStr.match(/(\d+)\s*薪/)
      if (monthsMatch) {
        result.salary_months = parseInt(monthsMatch[1])
      }
    }
    return result
  }

  const getExpectations = (): any[] => {
    const raw = getVal("expectations")
    if (!raw) return []
    // 兼容旧格式：如果是单个对象（非数组），包装为数组
    const arr = Array.isArray(raw) ? raw : [raw]
    return arr.map(migrateExpectationItem)
  }

  const emptyExpectationItem = (): any => ({
    position: "",
    city: "",
    other_cities: [],
    industries: [],
    salary_min: "",
    salary_max: "",
    salary_months: 12,
  })

  const openAddExpectation = () => {
    const items = getExpectations()
    if (items.length >= 3) return
    const updated = [...items, emptyExpectationItem()]
    setExpectationsForm(updated)
    setEditingExpectationIdx(updated.length - 1)
    setExpectationDialogOpen(true)
  }

  const openEditExpectation = (index: number) => {
    const items = getExpectations()
    setExpectationsForm(items)
    setEditingExpectationIdx(index)
    setExpectationDialogOpen(true)
  }

  const handleDeleteExpectation = async (index: number) => {
    const items = getExpectations()
    items.splice(index, 1)
    await updateField("expectations", items)
  }

  const updateExpectationField = (field: string, value: any) => {
    if (editingExpectationIdx === null) return
    const updated = [...expectationsForm]
    updated[editingExpectationIdx] = { ...updated[editingExpectationIdx], [field]: value }
    setExpectationsForm(updated)
  }

  const handleSaveExpectation = async () => {
    const ok = await updateField("expectations", expectationsForm)
    if (!ok) return
    setExpectationDialogOpen(false)
    setEditingExpectationIdx(null)
  }

  const isExpectationValid = (): boolean => {
    if (editingExpectationIdx === null) return false
    const item = expectationsForm[editingExpectationIdx]
    if (!item) return false
    return !!(item.position && item.city && item.industries && item.industries.length > 0 && item.salary_min && item.salary_max)
  }

  useEffect(() => {
    if (!data) { setLocalData(null); return }
    // 如果数据已经是结构化格式（含 basic_info），直接使用
    if (data["basic_info"]) { setLocalData(data); return }
    // 将 API 平铺字段转换为组件期望的结构化格式
    const v = (key: string) => data[key]?.current_value ?? ""
    const field = (key: string, label: string, value: any): ResumeField => ({
      label: data[key]?.label || label,
      required: data[key]?.required ?? false,
      type: data[key]?.type || "text",
      current_value: value,
    })
    // 组装 basic_info
    const basicInfo: any = {
      name: v("name"),
      phone: v("phone"),
      email: v("email"),
      job_status: v("job_status"),
      age: v("age"),
      work_years: v("work_years"),
      education_degree: v("education_degree"),
      gender: v("gender"),
      city: v("city"),
      wechat: v("wechat"),
      birth: v("birth"),
      avatar: v("avatar"),
    }
    // 组装 expectations（从平铺的 expected_* 字段）
    const expectations: any[] = []
    if (v("expected_job") || v("expected_city") || v("expected_salary")) {
      expectations.push({
        position: v("expected_job"),
        city: v("expected_city"),
        salary_min: v("expected_salary"),
        salary_max: "",
        salary_months: 12,
        industries: [],
        other_cities: [],
      })
    }
    const transformed: ResumeData = {
      basic_info: field("name", "基本信息", basicInfo),
      self_assessment: field("self_evaluation", "优势亮点", v("self_evaluation")),
      expectations: field("expected_job", "求职期望", expectations.length > 0 ? expectations : (data["expectations"]?.current_value || [])),
      work_experience: field("work_experience", "工作经历", v("work_experience") || []),
      education: field("education", "教育经历", v("education") || []),
      projects: field("projects", "项目经历", v("projects") || []),
      skill_tags: field("skill_tags", "技能标签", v("skill_tags") || []),
      certificates: field("certificates", "证书", v("certificates") || []),
      languages: field("languages", "语言能力", v("languages") || []),
      additional_info: field("additional_info", "附加信息", v("additional_info")),
    }
    setLocalData(transformed)
  }, [data])

  useEffect(() => {
    fetchReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportVersion])

  return {
    data, loading: props.loading, onRefresh, reportVersion,
    localData, setLocalData,
    saving, setSaving,
    toast, setToast,
    report, setReport,
    reportLoading, setReportLoading,
    applyConfirmOpen, setApplyConfirmOpen,
    applying, setApplying,
    applyFeedback, setApplyFeedback,
    savingSnapshot, setSavingSnapshot,
    snapshotFeedback, setSnapshotFeedback,
    selectedModules, setSelectedModules,
    writebackConfirm, setWritebackConfirm,
    writebacking, setWritebacking,
    writebackFeedback, setWritebackFeedback,
    showWritebackDetails, setShowWritebackDetails,
    basicInfoDialogOpen, setBasicInfoDialogOpen,
    basicInfoForm, setBasicInfoForm,
    selfAssessmentEditing, setSelfAssessmentEditing,
    selfAssessmentValue, setSelfAssessmentValue,
    expectationDialogOpen, setExpectationDialogOpen,
    expectationsForm, setExpectationsForm,
    editingExpectationIdx, setEditingExpectationIdx,
    workExpDialogOpen, setWorkExpDialogOpen,
    workExpForm, setWorkExpForm,
    editingWorkExpIdx, setEditingWorkExpIdx,
    showOptional, setShowOptional,
    projectDialogOpen, setProjectDialogOpen,
    projectForm, setProjectForm,
    editingProjectIdx, setEditingProjectIdx,
    educationDialogOpen, setEducationDialogOpen,
    educationForm, setEducationForm,
    editingEducationIdx, setEditingEducationIdx,
    certSelectorOpen, setCertSelectorOpen,
    skillSelectorOpen, setSkillSelectorOpen,
    languageDialogOpen, setLanguageDialogOpen,
    languageForm, setLanguageForm,
    editingLanguageIdx, setEditingLanguageIdx,
    additionalInfoEditing, setAdditionalInfoEditing,
    additionalInfoValue, setAdditionalInfoValue,
    deleteTarget, setDeleteTarget,
    liepinAgentDiagnosing, setLiepinAgentDiagnosing,
    liepinAgentReport, setLiepinAgentReport,
    liepinAgentModalOpen, setLiepinAgentModalOpen,
    liepinAgentApplying, setLiepinAgentApplying,
    liepinRollbackFeedback, setLiepinRollbackFeedback,
    liepinRollingBack, setLiepinRollingBack,
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
    toggleAllModules,
  }
}