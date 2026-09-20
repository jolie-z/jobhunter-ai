"use client"

import { useState, useEffect, useCallback } from "react"
import { Save, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { GreetingPlatformCard } from "./greeting/greeting-platform-card"
import { MassGreetingCard } from "./greeting/mass-greeting-card"
import { GreetingPromptCard } from "./greeting/greeting-prompt-card"
import { API_BASE } from "@/lib/api"

interface GreetingConfigPanelProps {
  onSaved: () => void
  /** 保存进行中状态上报：抽屉据此拦截关闭，防止保存请求被页面级卸载静默丢弃 */
  onSavingChange?: (saving: boolean) => void
}

// 保存失败（超时/网络异常）时把文案暂存 localStorage，重开抽屉可恢复，杜绝「明明保存了却失效」
const GREETING_DRAFT_KEY = "jobhunter:greeting-draft:v1"

interface GreetingDraft {
  text: string
  savedAt: number
}

function readGreetingDraft(): GreetingDraft | null {
  try {
    const raw = localStorage.getItem(GREETING_DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed.text === "string" && parsed.text.trim()) return parsed
  } catch {}
  return null
}

function writeGreetingDraft(text: string) {
  try {
    localStorage.setItem(GREETING_DRAFT_KEY, JSON.stringify({ text, savedAt: Date.now() }))
  } catch {}
}

function clearGreetingDraft() {
  try {
    localStorage.removeItem(GREETING_DRAFT_KEY)
  } catch {}
}

export function GreetingConfigPanel({ onSaved, onSavingChange }: GreetingConfigPanelProps) {
  const [greetingPlatforms, setGreetingPlatforms] = useState<Record<string, boolean>>({
    boss: true,
    liepin: true,
    "51job": false,
    zhilian: true,
  })
  const [massApplyGreeting, setMassApplyGreeting] = useState("")
  const [promptMode, setPromptMode] = useState<"official" | "custom">("official")
  const [customPrompt, setCustomPrompt] = useState("")
  const [officialPrompt, setOfficialPrompt] = useState("")
  const [modelName, setModelName] = useState("mimo-v2.5-pro")

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState("")
  const [draft, setDraft] = useState<GreetingDraft | null>(null)

  const fetchConfig = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/greeting-config`)
      const result = await res.json()
      if (result.code === 0 && result.data) {
        const d = result.data
        if (d.greeting_platforms) setGreetingPlatforms(d.greeting_platforms)
        if (d.mass_apply_greeting !== undefined) setMassApplyGreeting(d.mass_apply_greeting)
        if (d.prompt_mode) setPromptMode(d.prompt_mode === "custom" ? "custom" : "official")
        if (d.custom_prompt !== undefined) setCustomPrompt(d.custom_prompt)
        if (d.official_prompt) setOfficialPrompt(d.official_prompt)
        if (d.model_name) setModelName(d.model_name)

        // 与库中现值一致的草稿视为已落库，直接清掉；不一致的才提示恢复
        const stored = readGreetingDraft()
        if (stored) {
          if (stored.text === (d.mass_apply_greeting ?? "")) {
            clearGreetingDraft()
          } else {
            setDraft(stored)
          }
        }
      }
    } catch {
      toast.error("读取打招呼语规则配置异常")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  const handleTogglePlatform = (key: string) => {
    setGreetingPlatforms((prev) => ({
      ...prev,
      [key]: !prev[key],
    }))
  }

  const handleRestoreDraft = () => {
    if (!draft) return
    setMassApplyGreeting(draft.text)
    clearGreetingDraft()
    setDraft(null)
    toast.success("已恢复草稿，请点击保存写入数据库")
  }

  const handleDiscardDraft = () => {
    clearGreetingDraft()
    setDraft(null)
  }

  const handleSave = async () => {
    setSaving(true)
    onSavingChange?.(true)
    setSaveMsg("")
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/greeting-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // 10 秒无响应即中止：请求可能被浏览器连接池长期排队，拒绝无限转圈
        signal:
          typeof AbortSignal !== "undefined" && "timeout" in AbortSignal
            ? AbortSignal.timeout(10000)
            : undefined,
        body: JSON.stringify({
          greeting_platforms: greetingPlatforms,
          mass_apply_greeting: massApplyGreeting,
          prompt_mode: promptMode,
          custom_prompt: customPrompt,
        }),
      })
      const result = await res.json()
      if (res.ok && result.code === 0) {
        clearGreetingDraft()
        setDraft(null)
        setSaveMsg("打招呼语规则已保存生效")
        toast.success("打招呼语规则已保存生效")
        onSaved()
        setTimeout(() => setSaveMsg(""), 3000)
      } else {
        if (massApplyGreeting.trim()) writeGreetingDraft(massApplyGreeting)
        toast.error(result.msg || result.detail || "保存失败，草稿已本地暂存")
      }
    } catch (err) {
      // 超时/网络异常/连接池排队期间页面被刷新：先把文案落地 localStorage 防丢
      if (massApplyGreeting.trim()) writeGreetingDraft(massApplyGreeting)
      const timedOut = err instanceof DOMException && err.name === "TimeoutError"
      toast.error(
        timedOut
          ? "保存超时（10 秒无响应），草稿已本地暂存，请稍后重试"
          : "网络异常，无法保存打招呼语规则，草稿已本地暂存"
      )
    } finally {
      setSaving(false)
      onSavingChange?.(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin mr-2 text-violet-500" />
        正在加载打招呼语规则与 SOP 配置...
      </div>
    )
  }

  return (
    <div className="space-y-3.5 text-xs select-none">
      {/* 1. 第一分区：生成目标平台选择（默认 BOSS + 猎聘，附带感叹号说明） */}
      <GreetingPlatformCard
        greetingPlatforms={greetingPlatforms}
        onTogglePlatform={handleTogglePlatform}
      />

      {/* 2. 第二分区：海投/通用开场白（快速复用与 AI 一键生成模版） */}
      <MassGreetingCard
        massGreeting={massApplyGreeting}
        onChangeMassGreeting={setMassApplyGreeting}
      />

      {/* 3. 第三分区：Prompt 黄金法则与自定义提示词 */}
      <GreetingPromptCard
        promptMode={promptMode}
        onPromptModeChange={setPromptMode}
        customPrompt={customPrompt}
        onCustomPromptChange={setCustomPrompt}
        officialPrompt={officialPrompt}
        modelName={modelName}
      />

      {/* 未保存草稿恢复横幅：保存超时/网络异常时本地暂存的文案 */}
      {draft && (
        <div className="flex items-center justify-between gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2">
          <span className="text-[11px] leading-relaxed text-amber-600 dark:text-amber-400">
            检测到{" "}
            {new Date(draft.savedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}{" "}
            保存未成功的草稿（{draft.text.length} 字），可能尚未写入数据库。
          </span>
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              onClick={handleRestoreDraft}
              className="rounded-lg bg-amber-500 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-amber-600 transition-colors cursor-pointer"
            >
              恢复草稿
            </button>
            <button
              type="button"
              onClick={handleDiscardDraft}
              className="rounded-lg px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted transition-colors cursor-pointer"
            >
              丢弃
            </button>
          </div>
        </div>
      )}

      {/* 保存操作底栏 */}
      <div className="flex items-center justify-between pt-2 border-t border-border/60">
        <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
          {saveMsg}
        </span>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-700 active:scale-95 transition-all shadow-sm cursor-pointer disabled:opacity-50"
        >
          {saving ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          <span>{saving ? "正在保存..." : "保存打招呼语规则"}</span>
        </button>
      </div>
    </div>
  )
}
