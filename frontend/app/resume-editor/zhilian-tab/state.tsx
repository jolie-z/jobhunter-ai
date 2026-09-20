/**
 * Zhilian Tab 状态与业务逻辑中枢（机械搬迁，行为零变化）
 */
"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect, useMemo } from "react"
import { fetchPlatformReport, savePlatformData } from "../api-client"
import type { PlatformReport } from "../agent-report-shared"
import { _zhilianChangedModuleKeys, ZHILIAN_MODULE_DEFAULT_SELECTED, type WritebackFeedbackState, type DeleteConfirmTarget, type ZhilianData, type ZhilianTabProps } from "./constants"
import { useZhilianWritebackHandlers } from "./state-writeback"
import { useZhilianHealHandlers } from "./state-heal"
import { useZhilianReportHandlers } from "./state-report"

export function useZhilianTabState({ data, loading, onRefresh, reportVersion = 0 }: ZhilianTabProps) {
  const [localData, setLocalData] = useState<ZhilianData | null>(null)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null)

  // Edit states
  const [editingSection, setEditingSection] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<any>({})
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [profileError, setProfileError] = useState("")
  const [wannaError, setWannaError] = useState("")
  const [workExpError, setWorkExpError] = useState("")
  const [eduError, setEduError] = useState("")
  const [projectError, setProjectError] = useState("")
  const [trainingError, setTrainingError] = useState("")
  const [languageError, setLanguageError] = useState("")
  const [certOptions, setCertOptions] = useState<any[]>([])
  const [certLoading, setCertLoading] = useState(false)
  const [certPickerVisible, setCertPickerVisible] = useState(false)
  const [certPickerIdx, setCertPickerIdx] = useState(0)
  const [certActiveCategory, setCertActiveCategory] = useState(0)

  // 模块级回写：勾选模块 → 两步确认 → 调 write-back 回写智联官网
  const [selectedModules, setSelectedModules] = useState<Record<string, boolean>>(ZHILIAN_MODULE_DEFAULT_SELECTED)
  const [writebackConfirm, setWritebackConfirm] = useState(false)
  const [writebacking, setWritebacking] = useState(false)
  const [writebackFeedback, setWritebackFeedback] = useState<WritebackFeedbackState | null>(null)
  const [showWritebackDetails, setShowWritebackDetails] = useState(false)
  // 「保存为回写数据源」：把当前智联本地数据固化为回写快照（zhilian_writeback.json）
  const [savingSnapshot, setSavingSnapshot] = useState(false)
  const [snapshotFeedback, setSnapshotFeedback] = useState<{ msg: string; ok: boolean; time?: string } | null>(null)

  // 主简历映射报告（顶部操作区「映射」按钮生成；审核后两步确认应用到智联本地数据）
  const [report, setReport] = useState<PlatformReport | null>(null)
  const changedModuleKeys = useMemo(() => _zhilianChangedModuleKeys(report), [report])
  const [reportLoading, setReportLoading] = useState(false)
  const [applyConfirmOpen, setApplyConfirmOpen] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyFeedback, setApplyFeedback] = useState<{ msg: string; ok: boolean; time?: string } | null>(null)

  // 动态 Schema 探针与人机协同自愈状态
  const [probingSchema, setProbingSchema] = useState(false)
  const [diffDrawerOpen, setDiffDrawerOpen] = useState(false)
  const [probeReport, setProbeReport] = useState<any | null>(null)
  const [selectedDiffIndices, setSelectedDiffIndices] = useState<number[]>([])
  const [selfHealing, setSelfHealing] = useState(false)
  const [rollbackFeedback, setRollbackFeedback] = useState<{ msg: string; ok: boolean; snapshotId?: string } | null>(null)
  const [rollingBack, setRollingBack] = useState(false)

  // 智联回写自愈 Agent 状态
  const [agentDiagnosing, setAgentDiagnosing] = useState(false)
  const [agentReport, setAgentReport] = useState<any | null>(null)
  const [agentModalOpen, setAgentModalOpen] = useState(false)
  const [agentApplying, setAgentApplying] = useState(false)

  // 二次确认删除状态机 (Double Check)
  const [deleteTarget, setDeleteTarget] = useState<DeleteConfirmTarget | null>(null)

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 2000)
  }

  useEffect(() => {
    if (!data) { setLocalData(null); return }
    // 如果数据已经是结构化格式（有 profile 字段），直接使用并清洗专业技能
    if (data.profile) {
      const rawSkills = Array.isArray(data.professionalSkills)
        ? data.professionalSkills
        : Array.isArray((data as any).skill_tags?.current_value)
        ? (data as any).skill_tags.current_value
        : []
      const cleanedSkills = rawSkills
        .map((s: any) =>
          typeof s === "string"
            ? { proskillName: s, proskillLevel: "熟练", proskillUseTime: "" }
            : { ...s, proskillName: s.proskillName || s.name || s.skillName || "", proskillLevel: s.proskillLevel || s.level || "熟练" }
        )
        .filter((s: any) => s.proskillName && String(s.proskillName).trim() !== "")
      setLocalData({
        ...data,
        professionalSkills: cleanedSkills,
      })
      return
    }
    // 否则从扁平 fields 格式转换为结构化 ZhilianData
    const val = (key: string) => {
      const f = data[key]
      if (!f) return ""
      return typeof f === "object" ? (f.current_value ?? "") : f
    }
    const listVal = (key: string): any[] => {
      const f = data[key]
      if (!f) return []
      const v = typeof f === "object" ? (f.current_value ?? []) : f
      return Array.isArray(v) ? v : []
    }
    const toStr = (key: string): string => {
      const v = val(key)
      if (v === "" || v === null || v === undefined) return ""
      return String(v)
    }
    // job_status is now {jobStateCode, jobState}
    const jobStatusRaw = data.job_status?.current_value
    const jobStateCode = jobStatusRaw?.jobStateCode ?? ""
    const jobStateLabel = jobStatusRaw?.jobState ?? ""

    const isForeign = toStr("currentProvince") === "480" || toStr("currentCity") === "480" || val("foreign") === true || val("isOverseas") === true || toStr("foreign") === "1" || toStr("isOverseas") === "1"

    const transformed: ZhilianData = {
      profile: {
        name: val("name"),
        gender: toStr("gender"),
        genderTranslation: val("genderTranslation"),
        birthyear: toStr("birthyear"),
        birthmonth: toStr("birthmonth"),
        mobile: val("phone"),
        email: val("email"),
        currentCity: isForeign ? "480" : toStr("currentCity"),
        currentCityTranslation: isForeign ? "国外" : val("currentCityTranslation"),
        currentProvince: isForeign ? "480" : toStr("currentProvince"),
        currentProvinceTranslation: isForeign ? "国外" : val("currentProvinceTranslation"),
        currentCityDistrictId: isForeign ? "0" : toStr("currentCityDistrictId"),
        currentCityDistrictIdTranslation: isForeign ? "" : val("currentCityDistrictIdTranslation"),
        isOverseas: isForeign,
        foreign: isForeign,
        currentIdentity: toStr("currentIdentity"),
        currentIdentityTranslation: val("currentIdentityTranslation"),
        currentStatus: jobStateCode,
        currentStatusTranslation: jobStateLabel,
        eduHighestLevel: val("education_degree"),
        hukouProvinceId: toStr("hukouProvinceId"),
        hukouProvinceIdTranslation: val("hukouProvinceIdTranslation"),
        hukouCityId: toStr("hukouCityId"),
        hukouCityIdTranslation: val("hukouCityIdTranslation"),
        politicalAffiliation: toStr("politicalAffiliation"),
        politicalAffiliationTranslation: val("politicalAffiliationTranslation"),
        maritalStatus: "",
        yearStartWorking: toStr("yearStartWorking"),
        monthStartWorking: toStr("monthStartWorking"),
      },
      jobStatus: { jobState: jobStateLabel, jobStateCode },
      wanna: listVal("wanna").map((w: any) => ({
        preferredJobNature: w.preferredJobNature || "",
        preferredJobNatureTranslation: w.preferredJobNatureTranslation || "",
        pnewPreferredJobType: w.pnewPreferredJobType || "",
        pnewPreferredJobTypeTranslation: w.pnewPreferredJobTypeTranslation || w.title || "",
        pnewPreferredJobTypeFirstTranslation: w.pnewPreferredJobTypeFirstTranslation || "",
        preferredLocation: w.preferredLocation || "",
        preferredLocationTranslation: w.preferredLocationTranslation || "",
        preferredCityDistrict: w.preferredCityDistrict || "",
        preferredCityDistrictTranslation: w.preferredCityDistrictTranslation || "",
        pnewPreferredIndustry: w.pnewPreferredIndustry || "",
        pnewPreferredIndustryTranslation: w.pnewPreferredIndustryTranslation || "",
        preferredSalaryMin: w.preferredSalaryMin || 0,
        preferredSalaryMax: w.preferredSalaryMax || 0,
        preferredSalaryTranslation: w.preferredSalaryTranslation || "",
        preferredIndustrySerialList: w.preferredIndustrySerialList || [],
      })),
      workExperience: listVal("work_experience").map((w: any) => ({
        ...w,
        companyName: w.companyName || w.company_name || w.company || "",
        jobTitle: w.jobTitle || w.job_title || w.position || "",
        startDate: w.startDate || w.start_date || 0,
        endDate: w.endDate || w.end_date || 0,
        workDesc: w.workDesc || w.work_desc || w.description || "",
      })),
      education: listVal("education").map((e: any) => ({
        ...e,
        eduSchoolName: e.eduSchoolName || e.school || e.school_name || "",
        eduMajorV: e.eduMajorV || e.major || "",
        eduBackground: e.eduBackground || e.degree || "",
        eduBackgroundTranslation: e.eduBackgroundTranslation || e.degree || "",
        eduStartDate: e.eduStartDate || e.start_date || 0,
        eduEndDate: e.eduEndDate || e.end_date || 0,
      })),
      project: listVal("projects").map((p: any) => ({
        ...p,
        proExpProjectName: p.proExpProjectName || p.projectName || p.name || "",
        proExpStartDate: p.proExpStartDate || p.startDate || p.start_date || 0,
        proExpEndDate: p.proExpEndDate || p.endDate || p.end_date || 0,
        proExpProjectDesc: p.proExpProjectDesc || p.projectDesc || p.description || "",
      })),
      training: listVal("training").map((t: any) => ({
        ...t,
        trainAgency: t.trainAgency || t.trainName || t.trainOrgName || "",
        trainName: t.trainAgency || t.trainName || t.trainOrgName || "",
        trainCourse: t.trainCourse || t.trainCertName || "",
        trainStartDate: t.trainStartDate || 0,
        trainEndDate: t.trainEndDate || 0,
        trainDesc: t.trainDesc || "",
      })),
      language: listVal("language").map((l: any) => ({
        langLanguageT: l.langTypeTranslation || l.langLanguageT || "",
        langLSProficiency: l.langLSProficiency || "",
        langRWProficiency: l.langRWProficiency || "",
        langCertificatesFormat: l.certificates || l.langCertificatesFormat || [],
      })),
      professionalSkills: (listVal("professionalSkills").length > 0 ? listVal("professionalSkills") : listVal("skill_tags")).map((s: any) =>
        typeof s === "string" ? { proskillName: s, proskillLevel: "", proskillUseTime: "" } : { ...s, proskillName: s.proskillName || s.name || s.skillName || "", proskillLevel: s.proskillLevel || s.level || "" }
      ),
      certificate: (listVal("certificate").length > 0 ? listVal("certificate") : listVal("certificates")).map((c: any) => ({
        certUserdefName: c.certUserdefName || c.name || (typeof c === "string" ? c : ""),
        certDate: c.certDate || 0,
        certDateFormat: c.certDateFormat || "",
        certType: c.certType || "",
        certSubType: c.certSubType || "",
      })),
      selfEvaluation: (() => {
        const text = val("self_evaluation")
        return text ? [{ selfEvaContent: text }] : []
      })(),
    }
    setLocalData(transformed)
  }, [data])

  // 拉取本平台映射报告（挂载时 + 顶部操作区生成后 reportVersion 变化时）

  useEffect(() => {
    fetchReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportVersion])

  // Persist data
  const persistData = async (updatedData: ZhilianData): Promise<boolean> => {
    setSaving(true)
    try {
      const { ok, message } = await savePlatformData(API_BASE, "zhilian", updatedData)
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

  // Generic array helpers
  const handleAddItem = async (field: keyof ZhilianData, newItem: any) => {
    if (!localData) return
    const arr = (localData[field] as any[]) || []
    await persistData({ ...localData, [field]: [...arr, newItem] })
  }

  const handleUpdateItem = async (field: keyof ZhilianData, index: number, updatedItem: any) => {
    if (!localData) return
    const arr = [...((localData[field] as any[]) || [])]
    arr[index] = { ...arr[index], ...updatedItem }
    await persistData({ ...localData, [field]: arr })
  }

  const handleDeleteItem = async (field: keyof ZhilianData, index: number) => {
    if (!localData) return
    const arr = [...((localData[field] as any[]) || [])]
    arr.splice(index, 1)
    await persistData({ ...localData, [field]: arr })
  }

  // 确认删除并关闭二次确认弹窗
  const confirmDelete = async () => {
    if (!deleteTarget) return
    const { fieldName, index } = deleteTarget
    await handleDeleteItem(fieldName, index)
    setDeleteTarget(null)
  }

  const startEdit = (section: string, form: any, idx?: number) => {
    setEditingSection(section)
    setEditForm(form)
    setEditingIdx(idx ?? null)
  }

  const cancelEdit = () => {
    setEditingSection(null)
    setEditForm({})
    setEditingIdx(null)
  }

  const getNowTime = () => {
    const d = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  }


  // —— handler 簇组合（定义在 state-writeback.ts / state-heal.ts / state-report.ts，行为零变化）——
  const { handleSaveWritebackSource, selectedModuleKeys, toggleAllModules, scrollToModule, handleWritebackModules } = useZhilianWritebackHandlers({
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
  const { fetchReport, handleApplyReport } = useZhilianReportHandlers({
    report,
    setReport,
    setReportLoading,
    setApplyConfirmOpen,
    setApplying,
    setApplyFeedback,
    getNowTime,
    onRefresh,
  })
  const { handleOpenSchemaProbe, handleConfirmSelfHeal, handleRollbackSnapshot, handleDispatchHealerAgent, handleAgentApplyHeal } = useZhilianHealHandlers({
    probeReport,
    selectedDiffIndices,
    writebackFeedback,
    agentReport,
    selectedModuleKeys,
    showToast,
    setProbingSchema,
    setProbeReport,
    setSelectedDiffIndices,
    setDiffDrawerOpen,
    setSelfHealing,
    setRollbackFeedback,
    setRollingBack,
    setAgentDiagnosing,
    setAgentReport,
    setAgentModalOpen,
    setAgentApplying,
    handleWritebackModules,
  })


  return {
    // props 透传
    data, loading, onRefresh, reportVersion,
    // 核心数据与保存
    localData, setLocalData, saving, setSaving, toast, setToast, persistData, showToast,
    // 编辑态
    editingSection, setEditingSection, editForm, setEditForm, editingIdx, setEditingIdx,
    profileError, setProfileError, wannaError, setWannaError, workExpError, setWorkExpError,
    eduError, setEduError, projectError, setProjectError, trainingError, setTrainingError, languageError, setLanguageError,
    // 数组条目操作
    handleAddItem, handleUpdateItem, handleDeleteItem, confirmDelete, deleteTarget, setDeleteTarget,
    startEdit, cancelEdit, getNowTime,
    // 证书选择（语言能力）
    certOptions, setCertOptions, certLoading, setCertLoading, certPickerVisible, setCertPickerVisible,
    certPickerIdx, setCertPickerIdx, certActiveCategory, setCertActiveCategory,
    // 模块勾选回写
    selectedModules, setSelectedModules, writebackConfirm, setWritebackConfirm, writebacking, setWritebacking,
    writebackFeedback, setWritebackFeedback, showWritebackDetails, setShowWritebackDetails,
    handleSaveWritebackSource, selectedModuleKeys, toggleAllModules, scrollToModule, handleWritebackModules,
    savingSnapshot, setSavingSnapshot, snapshotFeedback, setSnapshotFeedback,
    // 映射报告与应用
    report, setReport, changedModuleKeys, reportLoading, setReportLoading, fetchReport,
    applyConfirmOpen, setApplyConfirmOpen, applying, setApplying, applyFeedback, setApplyFeedback,
    handleApplyReport,
    // 结构探针与自愈
    probingSchema, setProbingSchema, diffDrawerOpen, setDiffDrawerOpen, probeReport, setProbeReport,
    selectedDiffIndices, setSelectedDiffIndices, selfHealing, setSelfHealing,
    rollbackFeedback, setRollbackFeedback, rollingBack, setRollingBack,
    handleOpenSchemaProbe, handleConfirmSelfHeal, handleRollbackSnapshot,
    // 自愈 Agent
    agentDiagnosing, setAgentDiagnosing, agentReport, setAgentReport, agentModalOpen, setAgentModalOpen,
    agentApplying, setAgentApplying, handleDispatchHealerAgent, handleAgentApplyHeal,
  }
}
