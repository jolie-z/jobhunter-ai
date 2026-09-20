"use client"

import { useState, useEffect, useCallback } from "react"
import {
  Save,
  CheckCircle2,
  ExternalLink,
  
  BellRing,
  
  Database,
  
  RefreshCw,
  Loader2,
  Info,
  Sliders,
  
  Zap } from "lucide-react"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { Switch } from "@/components/ui/switch"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { API_BASE } from "@/lib/api"

interface FeishuStatusData {
  is_configured: boolean
  app_id_masked: string
  app_token: string
  table_id: string
  total_records: number
  bitable_url: string
  batch_limit: number
  enable_report: boolean
  enable_alert: boolean
}

interface FeishuConfigPanelProps {
  onSaved: () => void
}

const PRESET_LIMITS = [20, 50, 100, 200]

export function FeishuConfigPanel({ onSaved }: FeishuConfigPanelProps) {
  const [data, setData] = useState<FeishuStatusData | null>(null)
  const [loading, setLoading] = useState(true)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState("")

  const [batchLimit, setBatchLimit] = useState(50)
  const [enableReport, setEnableReport] = useState(true)
  const [enableAlert, setEnableAlert] = useState(true)

  const fetchStatus = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/feishu-status`)
      const result = await res.json()
      if (result.code === 0 && result.data) {
        setData(result.data)
        if (result.data.batch_limit) setBatchLimit(result.data.batch_limit)
        if (result.data.enable_report !== undefined) setEnableReport(result.data.enable_report)
        if (result.data.enable_alert !== undefined) setEnableAlert(result.data.enable_alert)
      }
    } catch {
      toast.error("读取飞书多维表格状态异常")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void (async () => {
      await fetchStatus()
    })()
  }, [fetchStatus])

  // 连通性测试
  const handleTestConnection = async () => {
    setTesting(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/feishu-test`, {
        method: "POST",
      })
      const result = await res.json()
      if (res.ok && result.code === 0) {
        toast.success(result.msg || "飞书多维表格鉴权成功，连接状态健康！")
      } else {
        toast.error(`飞书鉴权失败: ${result.detail || result.msg || "未知错误"}`)
      }
    } catch {
      toast.error("网络异常，无法连接飞书鉴权服务")
    } finally {
      setTesting(false)
    }
  }

  // 保存设置
  const handleSave = async () => {
    setSaving(true)
    setSaveMsg("")
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/feishu-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          batch_limit: Number(batchLimit) || 50,
          enable_report: enableReport,
          enable_alert: enableAlert,
        }),
      })
      const result = await res.json()
      if (res.ok && result.code === 0) {
        setSaveMsg("✓ 配置已生效")
        toast.success("飞书推送配置已成功保存！")
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

  if (loading) {
    return (
      <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin mr-2 text-violet-500" />
        正在探测飞书云端状态...
      </div>
    )
  }

  const isHealthy = data?.is_configured

  return (
    <div className="space-y-4 text-xs select-none">
      {/* 1. 飞书多维表格连通看板 */}
      <div className="rounded-2xl border border-border/70 bg-gradient-to-b from-card to-muted/10 p-4.5 space-y-3.5 shadow-xs">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-xl font-bold shadow-xs transition-colors",
                isHealthy
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                  : "bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20"
              )}
            >
              <Database className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-foreground text-xs tracking-tight">
                  飞书多维表格 · 岗位线索中台
                </span>
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
                    isHealthy
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/25"
                      : "bg-rose-500/10 text-rose-700 dark:text-rose-300 border border-rose-500/25"
                  )}
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full animate-pulse",
                      isHealthy ? "bg-emerald-500" : "bg-rose-500"
                    )}
                  />
                  {isHealthy ? "已连通" : "未连接"}
                </span>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" className="text-muted-foreground/60 hover:text-foreground">
                      <Info className="h-3.5 w-3.5" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs text-xs">
                    清洗合格的岗位会自动写入此表格，作为全生命周期流转与审批的唯一底表。
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>
          </div>

          {/* 右侧快捷动作 */}
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              onClick={handleTestConnection}
              disabled={testing}
              className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 py-1.2 text-[11px] font-medium text-foreground hover:bg-muted active:scale-95 transition-all disabled:opacity-50"
            >
              {testing ? (
                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
              ) : (
                <Zap className="h-3 w-3 text-amber-500" />
              )}
              <span>{testing ? "测试中…" : "连通测试"}</span>
            </button>

            {data?.bitable_url && (
              <a
                href={data.bitable_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-lg bg-violet-600/10 text-violet-700 dark:text-violet-300 hover:bg-violet-600/20 px-2.5 py-1.2 text-[11px] font-medium transition-all"
              >
                <span>打开表格</span>
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </div>

        {/* 极简 3 列指标元数据（无冗余线框） */}
        <div className="grid grid-cols-3 gap-2 pt-3 border-t border-border/50">
          <div className="space-y-0.5">
            <span className="text-[10px] text-muted-foreground block font-medium">线索库总量</span>
            <div className="text-xs font-bold text-foreground font-mono">
              {data?.total_records?.toLocaleString() || 0} <span className="text-[10px] font-normal text-muted-foreground">条</span>
            </div>
          </div>

          <div className="space-y-0.5">
            <span className="text-[10px] text-muted-foreground block font-medium">应用凭证 (App ID)</span>
            <div className="font-mono text-foreground text-[11px] truncate" title={data?.app_id_masked}>
              {data?.app_id_masked || "未配置"}
            </div>
          </div>

          <div className="space-y-0.5">
            <span className="text-[10px] text-muted-foreground block font-medium">数据表 (Table ID)</span>
            <div className="font-mono text-foreground text-[11px] truncate" title={data?.table_id}>
              {data?.table_id || "未配置"}
            </div>
          </div>
        </div>
      </div>

      {/* 2. 推送策略与风控上限 */}
      <div className="rounded-2xl border border-border/70 bg-card p-4 space-y-3.5 shadow-xs">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
            <Sliders className="h-3.5 w-3.5 text-violet-500" />
            <span>推送与流转风控</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground/60 hover:text-foreground">
                  <Info className="h-3 w-3" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs">
                控制单次任务推送到多维表格的记录上限以防接口限流，并保障全局唯一去重。
              </TooltipContent>
            </Tooltip>
          </div>

          <div className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20 px-2 py-0.5 text-[10px] font-medium">
            <CheckCircle2 className="h-3 w-3 text-emerald-500" />
            <span>MD5 + 岗位 URL 唯一去重</span>
          </div>
        </div>

        {/* 批次上限调节 */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 p-3 rounded-xl bg-muted/20 border border-border/50">
          <div>
            <div className="font-medium text-foreground text-xs">单轮推送上限</div>
            <p className="text-[10px] text-muted-foreground mt-0.5">单次任务写入多维表格的最大记录数</p>
          </div>

          <div className="flex items-center gap-1.5">
            {/* 预设快捷药丸 */}
            <div className="flex items-center bg-background rounded-lg border border-border p-0.5">
              {PRESET_LIMITS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setBatchLimit(preset)}
                  className={cn(
                    "px-2 py-0.5 text-[10px] font-mono rounded transition-all",
                    batchLimit === preset
                      ? "bg-foreground text-background font-bold shadow-xs"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {preset}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <input
                type="number"
                value={batchLimit}
                onChange={(e) => setBatchLimit(Math.min(500, Math.max(1, Number(e.target.value) || 1)))}
                className="w-14 rounded-lg border border-border bg-background px-2 py-1 text-xs font-mono text-center focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
              <span>条</span>
            </div>
          </div>
        </div>
      </div>

      {/* 3. 飞书机器人通知 */}
      <div className="rounded-2xl border border-border/70 bg-card p-4 space-y-2.5 shadow-xs">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground mb-1">
          <BellRing className="h-3.5 w-3.5 text-amber-500" />
          <span>飞书机器人与通知</span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="text-muted-foreground/60 hover:text-foreground">
                <Info className="h-3 w-3" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs">
              在任务收工或遇到核心意向岗位时，自动通过飞书卡片或 Webhook 通知到您的手机。
            </TooltipContent>
          </Tooltip>
        </div>

        {/* 选项 1 */}
        <div className="flex items-center justify-between p-3 rounded-xl bg-muted/20 border border-border/50 transition-colors hover:bg-muted/30">
          <div className="space-y-0.5 pr-3">
            <div className="font-medium text-foreground text-xs flex items-center gap-1.5">
              <span>全链路任务收工战报</span>
              <span className="text-[10px] text-muted-foreground font-normal">（自动推送结构化图文卡片）</span>
            </div>
          </div>
          <Switch
            checked={enableReport}
            onCheckedChange={setEnableReport}
          />
        </div>

        {/* 选项 2 */}
        <div className="flex items-center justify-between p-3 rounded-xl bg-muted/20 border border-border/50 transition-colors hover:bg-muted/30">
          <div className="space-y-0.5 pr-3">
            <div className="font-medium text-foreground text-xs flex items-center gap-1.5">
              <span>A/B 级黄金岗位即时提醒</span>
              <span className="text-[10px] text-muted-foreground font-normal">（命中高分或审批断点时提醒）</span>
            </div>
          </div>
          <Switch
            checked={enableAlert}
            onCheckedChange={setEnableAlert}
          />
        </div>
      </div>

      {/* 4. 底部操作栏 */}
      <div className="pt-2 border-t border-border flex items-center justify-between gap-3">
        <span className="text-emerald-600 dark:text-emerald-400 font-medium text-xs truncate">
          {saveMsg}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={fetchStatus}
            disabled={loading || saving}
            className="flex items-center gap-1 rounded-xl border border-border bg-background px-3 py-1.8 text-muted-foreground hover:text-foreground active:scale-95 transition-all text-xs"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>刷新</span>
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-xl bg-foreground px-4 py-1.8 text-background font-medium hover:opacity-90 active:scale-95 transition-all shadow-xs disabled:opacity-50 text-xs"
          >
            <Save className="h-3.5 w-3.5" />
            <span>{saving ? "保存中…" : "保存推送规则"}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
