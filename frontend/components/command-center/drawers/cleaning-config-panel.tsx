"use client"

import { useState, useEffect, useCallback } from "react"
import { Save,  RefreshCw } from "lucide-react"
import { HardRulesSection } from "./cleaning/hard-rules-section"
import { AIScoutRulesTable, AIScoutRule } from "./cleaning/ai-scout-rules-table"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"

interface CleaningConfigPanelProps {
  onSaved: () => void
}

export function CleaningConfigPanel({ onSaved }: CleaningConfigPanelProps) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState("")

  // Tier 1 状态
  const [minSalary, setMinSalary] = useState<number | "">(10)
  const [maxSalary, setMaxSalary] = useState<number | "">(30)
  const [maxExp, setMaxExp] = useState<number | "">(10)
  const [cities, setCities] = useState<string[]>(["广州", "深圳", "远程", "全国"])
  const [educationRequire, setEducationRequire] = useState<string[]>([])
  const [educationExclude, setEducationExclude] = useState<string[]>(["高中", "中专"])
  const [rawSafePhrases, setRawSafePhrases] = useState<string[]>([])
  const [rawKeywordRules, setRawKeywordRules] = useState<any[]>([])

  // Tier 2 状态
  const [aiScoutRules, setAiScoutRules] = useState<AIScoutRule[]>([])

  // 加载当前策略
  const fetchStrategy = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/active`)
      if (res.ok) {
        const data = await res.json()
        if (data) {
          // 只认精确哨兵值（999/99/0）为「不限」：用户真实设置的 100K 薪资上限、
          // 20 年经验上限都是合法值，用 >= 100 之类的范围判断会在保存→读取→再保存
          // 的往返中把合法值静默篡改回「不限」
          setMinSalary(!data.min_salary_k || data.min_salary_k === 0 ? "" : data.min_salary_k)
          setMaxSalary(
            !data.max_salary_k || data.max_salary_k === 999 ? "" : data.max_salary_k
          )
          setMaxExp(
            !data.experience_years_max || data.experience_years_max === 99
              ? ""
              : data.experience_years_max
          )
          setCities(Array.from(new Set(data.allowed_cities || [])))
          setEducationRequire(Array.from(new Set(data.require_education || [])))
          setEducationExclude(Array.from(new Set(data.exclude_education || [])))
          setRawSafePhrases(Array.isArray(data.safe_phrases) ? data.safe_phrases : [])
          setRawKeywordRules(Array.isArray(data.keyword_rules) ? data.keyword_rules : [])
          setAiScoutRules(Array.isArray(data.ai_scout_rules) ? data.ai_scout_rules : [])
        }
      }
    } catch {
      toast.error("加载求职策略配置失败，已使用本地默认值")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void (async () => {
      await fetchStrategy()
    })()
  }, [fetchStrategy])

  // 保存策略
  const handleSave = async () => {
    setSaving(true)
    setSaveMsg("")
    try {
      const payloadMinSal = minSalary === "" ? 0 : Number(minSalary)
      const payloadMaxSal = maxSalary === "" ? 999 : Number(maxSalary)
      const payloadMaxExp = maxExp === "" ? 99 : Number(maxExp)

      const res = await fetch(`${API_BASE}/api/strategy/active`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          min_salary_k: payloadMinSal,
          max_salary_k: payloadMaxSal,
          experience_years_max: payloadMaxExp,
          exclude_education: educationExclude,
          require_education: educationRequire,
          allowed_cities: cities,
          safe_phrases: rawSafePhrases,
          keyword_rules: rawKeywordRules,
          ai_scout_rules: aiScoutRules,
        }),
      })
      const result = await res.json()
      if (res.ok && (result.status === "success" || result.code === 0)) {
        setSaveMsg("✓ 清洗规则已生效并持久化同步")
        toast.success("清洗规则已成功保存并实时生效！")
        onSaved()
      } else {
        const errorMsg = result.message || result.detail || "保存失败"
        setSaveMsg(`保存失败: ${errorMsg}`)
        toast.error(`保存失败: ${errorMsg}`)
      }
    } catch {
      setSaveMsg("保存失败：网络请求异常")
      toast.error("网络请求异常，保存失败")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-xs text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin mr-2" />
        正在读取激活策略与清洗规则表...
      </div>
    )
  }

  return (
    <div className="space-y-6 text-xs">
      {/* 1. Tier 1 硬规则清洗 */}
      <HardRulesSection
        minSalary={minSalary}
        maxSalary={maxSalary}
        maxExp={maxExp}
        cities={cities}
        educationRequire={educationRequire}
        educationExclude={educationExclude}
        onMinSalaryChange={setMinSalary}
        onMaxSalaryChange={setMaxSalary}
        onMaxExpChange={setMaxExp}
        onCitiesChange={setCities}
        onEducationRequireChange={setEducationRequire}
        onEducationExcludeChange={setEducationExclude}
      />

      {/* 2. Tier 2 AI 侦察兵大模型初筛规则表 */}
      <AIScoutRulesTable rules={aiScoutRules} onChange={setAiScoutRules} />

      {/* 3. 底部操作栏 */}
      <div className="pt-3 border-t border-border flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2.5">
        <span className="text-emerald-600 dark:text-emerald-400 font-medium text-xs truncate max-w-xs">
          {saveMsg}
        </span>
        <div className="flex items-center gap-2 justify-end">
          <button
            type="button"
            onClick={fetchStrategy}
            disabled={loading || saving}
            className="flex items-center gap-1 rounded-lg border border-border bg-background px-3 py-2 text-muted-foreground hover:text-foreground active:scale-95 transition-all text-xs"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            重载配置
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-lg bg-foreground px-4 py-2 text-background font-medium hover:opacity-90 active:scale-95 transition-all shadow-xs disabled:opacity-50 text-xs"
          >
            <Save className="h-3.5 w-3.5" />
            {saving ? "保存中…" : "保存清洗规则"}
          </button>
        </div>
      </div>
    </div>
  )
}
