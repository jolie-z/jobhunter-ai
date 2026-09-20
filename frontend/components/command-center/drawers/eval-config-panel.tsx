"use client"

import { useState, useEffect, useCallback } from "react"
import { Save, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { ModelConcurrencyCard } from "./eval/model-concurrency-card"
import { EightDimensionsCard } from "./eval/eight-dimensions-card"
import { BonusPreferencesCard, PreferenceItem } from "./eval/bonus-preferences-card"
import type { ActiveResumeMeta } from "./common/active-resume-banner"
import { API_BASE } from "@/lib/api"

interface EvalConfigPanelProps {
  onSaved: () => void
}

const DEFAULT_WEIGHTS: Record<string, number> = {
  role_match: 1.0,
  skills_align: 1.0,
  seniority: 0.8,
  compensation: 0.8,
  interview_prob: 0.8,
  market_fit: 0.5,
  growth: 0.5,
  company_stage: 0.2,
}

export function EvalConfigPanel({ onSaved }: EvalConfigPanelProps) {
  const [modelName, setModelName] = useState("mimo-v2.5-pro")
  const [concurrency, setConcurrency] = useState(5)
  const [threshold, setThreshold] = useState("A")
  const [enableCompanySearch, setEnableCompanySearch] = useState(true)
  const [activeResume, setActiveResume] = useState<ActiveResumeMeta>({
    title: "默认基准简历",
    status: "启用",
    word_count: 0,
  })
  const [allResumes, setAllResumes] = useState<ActiveResumeMeta[]>([])
  const [weights, setWeights] = useState<Record<string, number>>(DEFAULT_WEIGHTS)
  const [preferences, setPreferences] = useState<PreferenceItem[]>([])

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState("")

  const fetchConfig = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/eval-config`)
      const result = await res.json()
      if (result.code === 0 && result.data) {
        const d = result.data
        if (d.model_name) setModelName(d.model_name)
        if (d.concurrency) setConcurrency(d.concurrency)
        if (d.threshold) setThreshold(d.threshold)
        if (d.enable_company_search !== undefined) setEnableCompanySearch(d.enable_company_search)
        if (d.active_resume) setActiveResume(d.active_resume)
        if (d.all_resumes) setAllResumes(d.all_resumes)
        if (d.weights) setWeights(d.weights)
        if (d.preferences) setPreferences(d.preferences)
      }
    } catch {
      toast.error("读取 AI 初评配置异常")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void (async () => {
      await fetchConfig()
    })()
  }, [fetchConfig])

  // 仅刷新偏好列表：偏好增删改后若走全量 fetchConfig，
  // 会把用户在权重/并发/阈值上尚未保存的调整静默冲掉
  const fetchPreferences = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/eval-config`)
      const result = await res.json()
      if (result.code === 0 && result.data?.preferences) {
        setPreferences(result.data.preferences)
      }
    } catch {}
  }, [])

  // 保存整套权重与配置
  const handleSave = async () => {
    setSaving(true)
    setSaveMsg("")
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/eval-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          concurrency,
          threshold,
          enable_company_search: enableCompanySearch,
          weights,
        }),
      })
      const result = await res.json()
      if (res.ok && result.code === 0) {
        setSaveMsg("✓ 评估规则与权重已生效")
        toast.success("AI 初评配置已保存成功！")
        onSaved()
      } else {
        setSaveMsg("保存失败")
        toast.error(result.detail || result.msg || "保存失败")
      }
    } catch {
      setSaveMsg("保存失败：网络错误")
      toast.error("网络异常，保存失败")
    } finally {
      setSaving(false)
    }
  }

  // 偏好项增删改
  const handleAddPreference = async (type: string, rule: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/eval-preferences`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, rule, status: "启用" }),
      })
      const result = await res.json()
      if (res.ok && result.code === 0) {
        toast.success("偏好加分项已添加！")
        fetchPreferences()
      } else {
        toast.error(result.detail || result.msg || "添加偏好项失败")
      }
    } catch {
      toast.error("添加偏好项失败")
    }
  }

  const handleToggleStatus = async (item: PreferenceItem) => {
    const newStatus = item.status === "启用" ? "停用" : "启用"
    const rollback = () =>
      setPreferences((prev) =>
        prev.map((p) => (p.record_id === item.record_id ? { ...p, status: item.status } : p))
      )
    setPreferences((prev) =>
      prev.map((p) => (p.record_id === item.record_id ? { ...p, status: newStatus } : p))
    )
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/eval-preferences`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_id: item.record_id,
          type: item.type,
          rule: item.rule,
          status: newStatus,
        }),
      })
      const result = await res.json()
      // fetch 对 4xx/5xx 不抛异常，必须显式校验后回滚乐观更新
      if (!(res.ok && result.code === 0)) {
        rollback()
        toast.error(result.detail || result.msg || "更新偏好状态失败")
      }
    } catch {
      rollback()
      toast.error("更新偏好状态失败")
    }
  }

  const handleUpdatePreference = async (item: PreferenceItem) => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/eval-preferences`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_id: item.record_id,
          type: item.type,
          rule: item.rule,
          status: item.status,
        }),
      })
      const result = await res.json()
      if (res.ok && result.code === 0) {
        toast.success("偏好规则已更新！")
        fetchPreferences()
      } else {
        toast.error(result.detail || result.msg || "更新偏好规则失败")
      }
    } catch {
      toast.error("更新偏好规则失败")
    }
  }

  const handleDeletePreference = async (recordId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/eval-preferences/${recordId}`, {
        method: "DELETE",
      })
      const result = await res.json()
      if (res.ok && result.code === 0) {
        toast.success("偏好规则已移除")
        setPreferences((prev) => prev.filter((p) => p.record_id !== recordId))
      } else {
        toast.error(result.detail || result.msg || "删除偏好规则失败")
      }
    } catch {
      toast.error("删除偏好规则失败")
    }
  }

  if (loading) {
    return (
      <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin mr-2 text-violet-500" />
        正在加载 AI 初评矩阵与权重...
      </div>
    )
  }

  return (
    <div className="space-y-4 text-xs select-none">
      {/* 1. 模型基座 + 并发通道 + 流转阀门 + 实时企业背调 */}
      <ModelConcurrencyCard
        modelName={modelName}
        concurrency={concurrency}
        onConcurrencyChange={setConcurrency}
        threshold={threshold}
        onThresholdChange={setThreshold}
        enableCompanySearch={enableCompanySearch}
        onEnableCompanySearchChange={setEnableCompanySearch}
      />

      {/* 2. 八维加权矩阵 */}
      <EightDimensionsCard
        weights={weights}
        onWeightChange={(key, val) => setWeights({ ...weights, [key]: val })}
        onApplyPreset={(preset) => {
          setWeights(preset)
          toast.success("已应用预设权重！")
        }}
      />

      {/* 3. 求职偏好与核心加分项 */}
      <BonusPreferencesCard
        preferences={preferences}
        onAddPreference={handleAddPreference}
        onUpdatePreference={handleUpdatePreference}
        onToggleStatus={handleToggleStatus}
        onDeletePreference={handleDeletePreference}
      />

      {/* 4. 底部操作栏 */}
      <div className="pt-2 border-t border-border flex items-center justify-between gap-3">
        <span className="text-emerald-600 dark:text-emerald-400 font-medium text-xs truncate">
          {saveMsg}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={fetchConfig}
            disabled={loading || saving}
            className="flex items-center gap-1 rounded-xl border border-border bg-background px-3 py-1.8 text-muted-foreground hover:text-foreground active:scale-95 transition-all text-xs"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>重置</span>
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-xl bg-foreground px-4 py-1.8 text-background font-medium hover:opacity-90 active:scale-95 transition-all shadow-xs disabled:opacity-50 text-xs"
          >
            <Save className="h-3.5 w-3.5" />
            <span>{saving ? "保存中…" : "保存评估配置"}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
