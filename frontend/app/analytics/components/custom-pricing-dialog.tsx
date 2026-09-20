"use client"

import { useState, useEffect, useCallback } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { Settings2, RotateCcw, Check, Sparkles, AlertCircle, CopyCheck } from "lucide-react"
import { API_BASE } from "@/lib/api"

interface ConfiguredModelItem {
  role: string
  key: string
  model_name: string
  is_mimo: boolean
  has_custom_pricing: boolean
  pricing?: {
    prompt_rate?: number
    cached_prompt_rate?: number
    completion_rate?: number
  } | null
}

interface MimoOfficialItem {
  series: string
  model_name: string
  cached_prompt_rate: number
  prompt_rate: number
  completion_rate: number
}

interface CustomPricingDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentModel?: string
  onSaved?: () => void
}

const DEFAULT_MIMO_OFFICIAL: MimoOfficialItem[] = [
  {
    series: "MiMo-V2.5 系列",
    model_name: "mimo-v2.5-pro",
    cached_prompt_rate: 0.025,
    prompt_rate: 3.0,
    completion_rate: 6.0,
  },
  {
    series: "MiMo-V2.5 系列",
    model_name: "mimo-v2.5",
    cached_prompt_rate: 0.02,
    prompt_rate: 1.0,
    completion_rate: 2.0,
  },
]

export function CustomPricingDialog({
  open,
  onOpenChange,
  currentModel,
  onSaved,
}: CustomPricingDialogProps) {
  const [modelName, setModelName] = useState(currentModel || "mimo-v2.5-pro")
  const [promptRate, setPromptRate] = useState<string>("")
  const [cachedPromptRate, setCachedPromptRate] = useState<string>("")
  const [completionRate, setCompletionRate] = useState<string>("")
  const [isMimo, setIsMimo] = useState(false)
  const [hasCustom, setHasCustom] = useState(false)
  const [recalculateHistory, setRecalculateHistory] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ type: "success" | "error"; text: string } | null>(null)

  // 多模型与官方资费列表
  const [configuredModels, setConfiguredModels] = useState<ConfiguredModelItem[]>([])
  const [officialList, setOfficialList] = useState<MimoOfficialItem[]>(DEFAULT_MIMO_OFFICIAL)

  const loadConfigForModel = useCallback(async (targetModel: string) => {
    setLoading(true)
    setMsg(null)
    try {
      const query = targetModel ? `?model=${encodeURIComponent(targetModel)}` : ""
      const res = await fetch(`${API_BASE}/api/v2/analytics/model-pricing-config${query}`).then((r) => r.json())
      if (res?.code === 0 && res.data) {
        const d = res.data
        const customExists = Boolean(d.has_custom_pricing)
        setModelName(d.active_model || targetModel)
        setIsMimo(Boolean(d.is_mimo))
        setHasCustom(customExists)
        // 动态默认值：此前未配置（首次录入）默认勾选重算纠偏；此前已配置（调价）默认不勾选，防误改昨日账单
        setRecalculateHistory(!customExists)

        if (Array.isArray(d.configured_models) && d.configured_models.length > 0) {
          setConfiguredModels(d.configured_models)
        }
        if (Array.isArray(d.mimo_official_list) && d.mimo_official_list.length > 0) {
          setOfficialList(d.mimo_official_list)
        }

        if (d.custom_pricing) {
          setPromptRate(String(d.custom_pricing.prompt_rate ?? ""))
          setCachedPromptRate(String(d.custom_pricing.cached_prompt_rate ?? "0"))
          setCompletionRate(String(d.custom_pricing.completion_rate ?? ""))
        } else {
          // 根据模型类型预填参考值
          const matchedOfficial = (d.mimo_official_list || DEFAULT_MIMO_OFFICIAL).find(
            (m: MimoOfficialItem) => m.model_name.toLowerCase() === targetModel.toLowerCase()
          )
          if (matchedOfficial) {
            setPromptRate(String(matchedOfficial.prompt_rate))
            setCachedPromptRate(String(matchedOfficial.cached_prompt_rate))
            setCompletionRate(String(matchedOfficial.completion_rate))
          } else {
            setPromptRate(String(d.mimo_defaults?.prompt_rate ?? "3.00"))
            setCachedPromptRate(String(d.mimo_defaults?.cached_prompt_rate ?? "0.025"))
            setCompletionRate(String(d.mimo_defaults?.completion_rate ?? "6.00"))
          }
        }
      }
    } catch (err) {
      console.error("加载模型计价配置失败:", err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) {
      setMsg(null)
      return
    }
    loadConfigForModel(currentModel || "mimo-v2.5-pro")
  }, [open, currentModel, loadConfigForModel])

  // 快速套用官方基准资费
  const applyOfficialRate = (official: MimoOfficialItem) => {
    if (isMimo) {
      setMsg({
        type: "error",
        text: `[${modelName}] 是 MiMo 官方模型，系统已按官方标准直接计费，无需修改`,
      })
      return
    }
    setPromptRate(String(official.prompt_rate))
    setCachedPromptRate(String(official.cached_prompt_rate))
    setCompletionRate(String(official.completion_rate))
    setMsg({
      type: "success",
      text: `已快速套用 [${official.model_name}] 资费到当前模型 [${modelName}]，确认后点击保存`,
    })
  }

  const handleSave = async (isReset = false) => {
    if (isMimo) {
      setMsg({ type: "error", text: "官方 MiMo 模型采用内置标准资费，无需也不允许自定义覆盖" })
      return
    }
    setSaving(true)
    setMsg(null)
    try {
      const payload = {
        model_name: modelName,
        prompt_rate: parseFloat(promptRate) || 0,
        cached_prompt_rate: parseFloat(cachedPromptRate) || 0,
        completion_rate: parseFloat(completionRate) || 0,
        reset: isReset,
        recalculate_history: recalculateHistory,
      }
      const res = await fetch(`${API_BASE}/api/v2/analytics/model-pricing-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then((r) => r.json())

      if (res?.code === 0) {
        setMsg({
          type: "success",
          text: res.msg || (isReset ? `已重置模型 [${modelName}] 自定义计价` : `已保存 [${modelName}] 自定义单价`),
        })
        setHasCustom(!isReset)
        if (onSaved) onSaved()
        // 刷新配置列表
        loadConfigForModel(modelName)
        setTimeout(() => {
          onOpenChange(false)
        }, 1400)
      } else {
        setMsg({ type: "error", text: res?.msg || "保存失败，请稍后重试" })
      }
    } catch {
      setMsg({ type: "error", text: "网络请求异常，保存失败" })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg p-5 sm:p-6 rounded-2xl bg-card border-border/70 shadow-xl max-h-[90vh] overflow-y-auto">
        <DialogHeader className="space-y-1.5 text-left">
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Settings2 className="size-4" />
            </div>
            <DialogTitle className="text-base font-semibold text-foreground">
              模型计价与资费配置
            </DialogTitle>
          </div>
          <DialogDescription className="text-xs text-muted-foreground leading-relaxed">
            支持对推理主模型、数据清洗等多个模型分别配置专属 Token 单价，系统自动扣减 Prompt Cache 优惠精确核算账单。
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="py-8 text-center text-xs text-muted-foreground animate-pulse">
            正在读取系统多模型计价信息...
          </div>
        ) : (
          <div className="space-y-4 py-1">
            {/* 1. 系统当前配置的角色模型（可切换） */}
            {configuredModels.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-[11px] font-medium text-muted-foreground">系统当前配置模型</span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {configuredModels.map((m) => {
                    const isSelected = m.model_name.toLowerCase() === modelName.toLowerCase()
                    return (
                      <button
                        key={m.key}
                        type="button"
                        onClick={() => loadConfigForModel(m.model_name)}
                        className={`text-left p-2.5 rounded-xl border transition-all text-xs ${
                          isSelected
                            ? "border-primary bg-primary/5 shadow-2xs"
                            : "border-border/60 bg-muted/20 hover:bg-muted/40"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] text-muted-foreground font-medium">{m.role}</span>
                          {m.is_mimo ? (
                            <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-0.5">
                              <Sparkles className="size-2.5" /> 官方标准
                            </span>
                          ) : m.has_custom_pricing ? (
                            <span className="text-[10px] text-primary font-medium flex items-center gap-0.5">
                              <Check className="size-2.5" /> 自定义
                            </span>
                          ) : (
                            <span className="text-[10px] text-amber-600 dark:text-amber-400 font-medium flex items-center gap-0.5">
                              <AlertCircle className="size-2.5" /> 待录入
                            </span>
                          )}
                        </div>
                        <div className="font-mono text-xs font-semibold text-foreground truncate mt-0.5">
                          {m.model_name}
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* 2. 官方国内定价基准参考表（完全对齐截图 2） */}
            <div className="space-y-1.5 rounded-xl border border-border/60 bg-muted/20 p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-foreground">模型国内定价 (MiMo-V2.5 官方标准)</span>
                <span className="text-[10px] text-muted-foreground font-mono">单位: 元 / 1M Tokens</span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-border/40 text-[10px] text-muted-foreground">
                      <th className="pb-1.5 font-medium">MiMo-V2.5 系列</th>
                      <th className="pb-1.5 text-right font-medium">输入（命中缓存）</th>
                      <th className="pb-1.5 text-right font-medium">输入（未命中缓存）</th>
                      <th className="pb-1.5 text-right font-medium">输出</th>
                      <th className="pb-1.5 text-right font-medium">快捷</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20">
                    {officialList.map((item) => {
                      const isCurrent = modelName.toLowerCase() === item.model_name.toLowerCase()
                      return (
                        <tr
                          key={item.model_name}
                          className={`transition-colors ${isCurrent ? "bg-primary/10 font-medium" : "hover:bg-muted/40"}`}
                        >
                          <td className="py-1.5 pr-2">
                            <span className="font-mono px-1.5 py-0.5 rounded bg-muted/60 text-[11px] text-foreground">
                              {item.model_name}
                            </span>
                            {isCurrent && (
                              <span className="ml-1 text-[9px] text-primary font-medium">当前</span>
                            )}
                          </td>
                          <td className="py-1.5 text-right font-mono text-emerald-600 dark:text-emerald-400">
                            ¥{item.cached_prompt_rate.toFixed(3).replace(/\.?0+$/, "")}
                          </td>
                          <td className="py-1.5 text-right font-mono text-foreground">
                            ¥{item.prompt_rate.toFixed(2)}
                          </td>
                          <td className="py-1.5 text-right font-mono text-foreground">
                            ¥{item.completion_rate.toFixed(2)}
                          </td>
                          <td className="py-1.5 text-right">
                            <button
                              type="button"
                              onClick={() => applyOfficialRate(item)}
                              className="text-[10px] text-primary hover:underline font-medium inline-flex items-center gap-0.5"
                              title="将此套资费填入下方表单"
                            >
                              <CopyCheck className="size-2.5" /> 套用
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 3. 当前配置对象与表单 */}
            <div className="space-y-3 pt-1">
              <div className="flex items-center justify-between p-2.5 rounded-xl border border-border/50 bg-muted/30">
                <div className="flex flex-col">
                  <span className="text-[10px] text-muted-foreground font-medium">当前核算目标模型</span>
                  <span className="font-mono text-xs font-semibold text-foreground">{modelName}</span>
                </div>
                {isMimo ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                    <Sparkles className="size-3" /> 官方精准资费内置
                  </span>
                ) : hasCustom ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-primary/10 text-primary">
                    <Check className="size-3" /> 用户自定义资费生效中
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/10 text-amber-600 dark:text-amber-400">
                    <AlertCircle className="size-3" /> 暂按 MiMo 预估
                  </span>
                )}
              </div>

              {/* 输入框组 */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-foreground block">
                    输入（未命中缓存）
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    disabled={isMimo}
                    value={promptRate}
                    onChange={(e) => setPromptRate(e.target.value)}
                    placeholder="如: 3.00"
                    className="w-full rounded-lg border border-border/70 bg-background px-2.5 py-1.5 font-mono text-xs text-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60 disabled:cursor-not-allowed disabled:bg-muted/30"
                  />
                  <span className="text-[10px] text-muted-foreground">元 / 100万 Tokens</span>
                </div>

                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-foreground block">
                    输入（命中缓存）
                  </label>
                  <input
                    type="number"
                    step="0.0001"
                    min="0"
                    disabled={isMimo}
                    value={cachedPromptRate}
                    onChange={(e) => setCachedPromptRate(e.target.value)}
                    placeholder="如: 0.025"
                    className="w-full rounded-lg border border-border/70 bg-background px-2.5 py-1.5 font-mono text-xs text-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60 disabled:cursor-not-allowed disabled:bg-muted/30"
                  />
                  <span className="text-[10px] text-muted-foreground">无缓存与未命中一致</span>
                </div>

                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-foreground block">
                    输出单价（生成）
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    disabled={isMimo}
                    value={completionRate}
                    onChange={(e) => setCompletionRate(e.target.value)}
                    placeholder="如: 6.00"
                    className="w-full rounded-lg border border-border/70 bg-background px-2.5 py-1.5 font-mono text-xs text-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60 disabled:cursor-not-allowed disabled:bg-muted/30"
                  />
                  <span className="text-[10px] text-muted-foreground">元 / 100万 Tokens</span>
                </div>
              </div>

              {/* 用户可勾选的 Double-Check 历史重算选项（仅限自定义模型） */}
              {!isMimo && (
                <div className="flex items-start gap-2 pt-1 px-1">
                  <input
                    type="checkbox"
                    id="recalc-history-check"
                    checked={recalculateHistory}
                    onChange={(e) => setRecalculateHistory(e.target.checked)}
                    className="mt-0.5 rounded border-border/70 text-primary focus:ring-primary h-3.5 w-3.5 cursor-pointer"
                  />
                  <label
                    htmlFor="recalc-history-check"
                    className="text-[11px] text-muted-foreground select-none cursor-pointer leading-snug"
                  >
                    同时重算 <span className="font-mono text-foreground font-semibold">[{modelName}]</span> 的历史账单（首次录入=纠偏暂估价；恢复默认=刷回预估价）
                  </label>
                </div>
              )}
            </div>

            {msg && (
              <div
                className={`p-2 rounded-lg text-xs font-medium ${
                  msg.type === "success"
                    ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    : "bg-destructive/10 text-destructive"
                }`}
              >
                {msg.text}
              </div>
            )}
          </div>
        )}

        <DialogFooter className="flex items-center justify-between sm:justify-between gap-2 pt-2 border-t border-border/40">
          {isMimo ? (
            <div className="text-[11px] text-muted-foreground flex items-center gap-1">
              <Sparkles className="size-3.5 text-emerald-500" />
              <span>官方标准模型内置计费，无需修改</span>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => handleSave(true)}
              disabled={saving || loading || !hasCustom}
              className="inline-flex items-center gap-1 rounded-lg border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/50 transition-colors disabled:opacity-40 cursor-pointer"
            >
              <RotateCcw className="size-3" />
              恢复默认
            </button>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={saving}
              className="rounded-lg px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/50 transition-colors cursor-pointer"
            >
              {isMimo ? "关闭" : "取消"}
            </button>
            {!isMimo && (
              <button
                type="button"
                onClick={() => handleSave(false)}
                disabled={saving || loading || !promptRate || !completionRate}
                className="rounded-lg bg-primary px-3.5 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-all active:scale-[0.98] disabled:opacity-50 cursor-pointer"
              >
                {saving ? "保存中..." : recalculateHistory ? "保存并重算" : "保存配置"}
              </button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
