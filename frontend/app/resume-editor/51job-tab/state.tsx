/**
 * Job51 Tab 状态与业务逻辑中枢（机械搬迁，行为零变化）
 */
"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect, useRef, useCallback, useMemo, createContext, useContext } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Loader2, Plus, Trash2, User, Lock, FileText, Settings, Save, Upload, Sparkles } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { Job51YearMonthPicker } from "@/components/ui/51job-year-month-picker"
import { Job51SalaryPicker } from "@/components/ui/51job-salary-picker"
import { Job51AreaSelector } from "@/components/ui/51job-area-selector"
import { Job51Cascader } from "@/components/ui/51job-cascader"
import { Job51CityPicker } from "@/components/ui/51job-city-picker"
import { Job51FuntypePicker } from "@/components/ui/51job-funtype-picker"
import { Job51IndustryPicker } from "@/components/ui/51job-industry-picker"
import { Job51MajorPicker } from "@/components/ui/51job-major-picker"
import { Job51SkillPicker } from "@/components/ui/51job-skill-picker"
import { Job51CertPicker } from "@/components/ui/51job-cert-picker"
import { Job51Catalogue } from "@/components/ui/51job-catalogue"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"
import { ReportWarnings, ReportUnfilled, ChangedBadge, ModuleReportNotice, type PlatformReport } from "../agent-report-shared"
import { savePlatformData } from "../api-client"

import type { Job51TabProps } from "./constants"
import { JOB51_MODULE_DEFAULT_SELECTED, type WritebackFeedbackState, type DeleteConfirmTarget, ResumeData } from "./constants"
import { useJob51WritebackHandlers } from "./state-writeback"
import { useJob51HealHandlers } from "./state-heal"
import { useJob51ReportHandlers } from "./state-report"

export function useJob51TabState(props: Job51TabProps) {
  const { data, onRefresh, reportVersion = 0 } = props
  // —— state 全集（机械搬迁） ——
  const [localData, setLocalData] = useState<ResumeData | null>(data)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null)
  const [activeNav, setActiveNav] = useState("basic-info")
  const [basicInfoEditing, setBasicInfoEditing] = useState(false)
  const [basicInfoForm, setBasicInfoForm] = useState<any>({})
  const [selfIntroEditing, setSelfIntroEditing] = useState(false)
  const [selfIntroValue, setSelfIntroValue] = useState("")
  const [intentionEditing, setIntentionEditing] = useState(false)
  const [intentionForm, setIntentionForm] = useState<any>({})
  const [editingIntentionIdx, setEditingIntentionIdx] = useState<number | null>(null)
  const [cityPickerOpen, setCityPickerOpen] = useState(false)
  const [funtypePickerOpen, setFuntypePickerOpen] = useState(false)
  const [industryPickerOpen, setIndustryPickerOpen] = useState(false)
  const [workExpEditing, setWorkExpEditing] = useState(false)
  const [workExpForm, setWorkExpForm] = useState<any>({})
  const [editingWorkExpIdx, setEditingWorkExpIdx] = useState<number | null>(null)
  const [workFuntypePickerOpen, setWorkFuntypePickerOpen] = useState(false)
  const [workIndustryPickerOpen, setWorkIndustryPickerOpen] = useState(false)
  const [workSkillInput, setWorkSkillInput] = useState("")
  const [projectEditing, setProjectEditing] = useState(false)
  const [projectForm, setProjectForm] = useState<any>({})
  const [editingProjectIdx, setEditingProjectIdx] = useState<number | null>(null)
  const [educationEditing, setEducationEditing] = useState(false)
  const [educationForm, setEducationForm] = useState<any>({})
  const [editingEducationIdx, setEditingEducationIdx] = useState<number | null>(null)
  const [majorPickerOpen, setMajorPickerOpen] = useState(false)
  const [educationErrors, setEducationErrors] = useState<Record<string, string>>({})
  const [languageEditing, setLanguageEditing] = useState(false)
  const [languageForm, setLanguageForm] = useState<any>({})
  const [editingLanguageIdx, setEditingLanguageIdx] = useState<number | null>(null)
  const [langCertsData, setLangCertsData] = useState<Record<string, { name: string; certs: { code: string; value: string }[] }>>({})
  const [langCertPickerOpen, setLangCertPickerOpen] = useState(false)
  const [skillEditing, setSkillEditing] = useState(false)
  const [skillForm, setSkillForm] = useState<any>({})
  const [editingSkillIdx, setEditingSkillIdx] = useState<number | null>(null)
  const [skillPickerOpen, setSkillPickerOpen] = useState(false)
  const [skillErrors, setSkillErrors] = useState<Record<string, string>>({})
  const [certPickerOpen, setCertPickerOpen] = useState(false)
  const [selectedModules, setSelectedModules] = useState<Record<string, boolean>>(JOB51_MODULE_DEFAULT_SELECTED)
  const [writebackConfirm, setWritebackConfirm] = useState(false)
  const [writebacking, setWritebacking] = useState(false)
  const [writebackFeedback, setWritebackFeedback] = useState<WritebackFeedbackState | null>(null)
  const [showWritebackDetails, setShowWritebackDetails] = useState(false)
  const [savingSnapshot, setSavingSnapshot] = useState(false)
  const [snapshotFeedback, setSnapshotFeedback] = useState<{ msg: string; ok: boolean; time?: string } | null>(null)
  const [report, setReport] = useState<PlatformReport | null>(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [applyConfirmOpen, setApplyConfirmOpen] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyFeedback, setApplyFeedback] = useState<{ msg: string; ok: boolean; time?: string } | null>(null)
  const [job51AgentDiagnosing, setJob51AgentDiagnosing] = useState(false)
  const [job51AgentReport, setJob51AgentReport] = useState<any | null>(null)
  const [job51AgentModalOpen, setJob51AgentModalOpen] = useState(false)
  const [job51AgentApplying, setJob51AgentApplying] = useState(false)
  const [job51RollbackFeedback, setJob51RollbackFeedback] = useState<{ msg: string; ok: boolean; snapshotId?: string } | null>(null)
  const [job51RollingBack, setJob51RollingBack] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DeleteConfirmTarget | null>(null)
  const [certNameMap, setCertNameMap] = useState<Record<string, string>>({})

  const contentRef = useRef<HTMLDivElement>(null)


function _computeChangedModuleKeys(report?: any): Set<string> {
  const keys: string[] = []
  // ① 报告字段变更对比（应用前预览）
  for (const f of report?.fields || []) {
    if (f.changed) {
      const modKey = f.path.includes('.') ? f.path.split('.')[0] : f.path
      if (!keys.includes(modKey)) keys.push(modKey)
    }
  }
  // ② 「已修改」标识：apply 成功写入后后端持久化的 applied_paths（刷新不丢）
  for (const p of report?.applied_paths || []) {
    const modKey = String(p).includes('.') ? String(p).split('.')[0] : String(p)
    if (!keys.includes(modKey)) keys.push(modKey)
  }
  return new Set(keys)
}

  const changedModuleKeys = useMemo(() => _computeChangedModuleKeys(report), [report])

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 2000)
  }



  const handleNavClick = useCallback((id: string) => {
    setActiveNav(id)
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [])

  const getNowTime = () => {
    const d = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  }

  // —— handler 簇组合（定义在 state-writeback.ts / state-heal.ts / state-report.ts，行为零变化）——
  const { handleSaveWritebackSource, selectedModuleKeys, toggleAllModules, handleWritebackModules } = useJob51WritebackHandlers({
    getNowTime,
    selectedModules,
    setSelectedModules,
    setSavingSnapshot,
    setSnapshotFeedback,
    setWritebacking,
    setWritebackFeedback,
    setWritebackConfirm,
  })
  const { fetchReport, handleApplyReport } = useJob51ReportHandlers({
    report,
    setReport,
    setReportLoading,
    setApplyConfirmOpen,
    setApplying,
    setApplyFeedback,
    getNowTime,
    onRefresh,
  })
  const { handleDispatchJob51HealerAgent, handleJob51AgentApplyHeal, handleRollbackJob51Snapshot } = useJob51HealHandlers({
    writebackFeedback,
    selectedModuleKeys,
    showToast,
    job51AgentReport,
    setJob51AgentDiagnosing,
    setJob51AgentReport,
    setJob51AgentModalOpen,
    setJob51AgentApplying,
    setJob51RollbackFeedback,
    setJob51RollingBack,
    handleWritebackModules,
  })

  const persistData = async (updatedData: ResumeData): Promise<boolean> => {
    setSaving(true)
    try {
      const { ok, message } = await savePlatformData(API_BASE, "51job", updatedData)
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
    if (!localData) return false
    const field = localData[fieldName] || { label: fieldName, required: false, type: "array", current_value: [] }
    const fieldValue = [...(field.current_value || [])]
    fieldValue.splice(index, 1)
    const updatedData = {
      ...localData,
      [fieldName]: {
        ...field,
        current_value: fieldValue,
      },
    }
    return persistData(updatedData)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    const { fieldName, index } = deleteTarget
    const ok = await handleDeleteItem(fieldName, index)
    if (ok) setDeleteTarget(null)
  }

  const handleAddItem = async (fieldName: string, newItem: any): Promise<boolean> => {
    if (!localData) return false
    const field = localData[fieldName] || { label: fieldName, required: false, type: "array", current_value: [] }
    const fieldValue = field.current_value || []
    const updatedValue = [...fieldValue, newItem]
    const updatedData = {
      ...localData,
      [fieldName]: {
        ...field,
        current_value: updatedValue,
      },
    }
    return persistData(updatedData)
  }

  const handleUpdateItem = async (fieldName: string, index: number, updatedItem: any): Promise<boolean> => {
    if (!localData) return false
    const field = localData[fieldName] || { label: fieldName, required: false, type: "array", current_value: [] }
    const fieldValue = [...(field.current_value || [])]
    fieldValue[index] = updatedItem
    const updatedData = {
      ...localData,
      [fieldName]: {
        ...field,
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

  useEffect(() => {
    setLocalData(data ?? null)
  }, [data])

  useEffect(() => {
    fetch(`${API_BASE}/api/resume-editor/options/51job`)
      .then((r) => r.json())
      .then((res: any) => {
        const certs = res?.data?.language_certifications || {}
        const mapped: Record<string, { name: string; certs: { code: string; value: string }[] }> = {}
        for (const [code, info] of Object.entries(certs) as [string, any][]) {
          mapped[code] = { name: info.languageName, certs: info.items || [] }
        }
        setLangCertsData(mapped)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetch("/51job_certificates.json")
      .then((r) => r.json())
      .then((data: { code: string; name: string; children: { code: string; name: string }[] }[]) => {
        const map: Record<string, string> = {}
        for (const cat of data) {
          for (const cert of cat.children || []) {
            map[cert.code] = cert.name
          }
        }
        setCertNameMap(map)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetchReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportVersion])

  return {
    // props 透传
    data, loading: props.loading, onRefresh, reportVersion,
    localData, setLocalData,
    saving, setSaving,
    activeNav, setActiveNav,
    toast, setToast,
    basicInfoForm, setBasicInfoForm, basicInfoEditing, setBasicInfoEditing,
    selfIntroEditing, setSelfIntroEditing,
    selfIntroValue, setSelfIntroValue,
    intentionEditing, setIntentionEditing,
    intentionForm, setIntentionForm,
    editingIntentionIdx, setEditingIntentionIdx,
    cityPickerOpen, setCityPickerOpen,
    funtypePickerOpen, setFuntypePickerOpen,
    industryPickerOpen, setIndustryPickerOpen,
    workExpEditing, setWorkExpEditing,
    workExpForm, setWorkExpForm,
    editingWorkExpIdx, setEditingWorkExpIdx,
    workFuntypePickerOpen, setWorkFuntypePickerOpen,
    workIndustryPickerOpen, setWorkIndustryPickerOpen,
    workSkillInput, setWorkSkillInput,
    projectEditing, setProjectEditing,
    projectForm, setProjectForm,
    editingProjectIdx, setEditingProjectIdx,
    educationEditing, setEducationEditing,
    educationForm, setEducationForm,
    editingEducationIdx, setEditingEducationIdx,
    majorPickerOpen, setMajorPickerOpen,
    educationErrors, setEducationErrors,
    languageEditing, setLanguageEditing,
    languageForm, setLanguageForm,
    editingLanguageIdx, setEditingLanguageIdx,
    langCertsData, setLangCertsData,
    langCertPickerOpen, setLangCertPickerOpen,
    skillEditing, setSkillEditing,
    skillForm, setSkillForm,
    editingSkillIdx, setEditingSkillIdx,
    skillPickerOpen, setSkillPickerOpen,
    skillErrors, setSkillErrors,
    certPickerOpen, setCertPickerOpen,
    selectedModules, setSelectedModules,
    writebackConfirm, setWritebackConfirm,
    writebacking, setWritebacking,
    writebackFeedback, setWritebackFeedback,
    showWritebackDetails, setShowWritebackDetails,
    savingSnapshot, setSavingSnapshot,
    snapshotFeedback, setSnapshotFeedback,
    report, setReport,
    reportLoading, setReportLoading,
    applyConfirmOpen, setApplyConfirmOpen,
    applying, setApplying,
    applyFeedback, setApplyFeedback,
    job51AgentDiagnosing, setJob51AgentDiagnosing,
    job51AgentReport, setJob51AgentReport,
    job51AgentModalOpen, setJob51AgentModalOpen,
    job51AgentApplying, setJob51AgentApplying,
    job51RollbackFeedback, setJob51RollbackFeedback,
    job51RollingBack, setJob51RollingBack,
    deleteTarget, setDeleteTarget,
    certNameMap, setCertNameMap,
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
    toggleAllModules,
    persistData,
    updateField,
    handleDeleteItem,
    confirmDelete,
    handleAddItem,
    handleUpdateItem,
    getVal,
    getLabel,
  }
}
