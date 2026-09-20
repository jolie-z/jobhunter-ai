"use client"

import { useState, useEffect, useCallback } from "react"
import {
  Cpu,
  Zap,
  Clock,
  Database,
  TrendingUp,
  Percent,
  ChevronDown,
  ChevronUp,
  Coins,
  ChevronLeft,
  ChevronRight,
  Settings2,
} from "lucide-react"
import { API_BASE } from "@/lib/api"
import type { TokenSummary, ByAction, ByModel, DailyTrend, LogRow } from "../types"
import { CustomPricingDialog } from "./custom-pricing-dialog"
import {
  MODEL_COLORS,
  actionLabel,
  fmtDateTime,
  fmtNum,
  fmtCost,
  fmtK,
} from "../lib/action-labels"

export function TokenMonitorSection() {
  const [open, setOpen] = useState(true)
  const [range, setRange] = useState("all")
  const [page, setPage] = useState(1)
  const [summary, setSummary] = useState<TokenSummary | null>(null)
  const [byAction, setByAction] = useState<ByAction[]>([])
  const [byModel, setByModel] = useState<ByModel[]>([])
  const [trend, setTrend] = useState<DailyTrend[]>([])
  const [logs, setLogs] = useState<LogRow[]>([])
  const [logsTotal, setLogsTotal] = useState(0)

  // 自定义计价与预估状态
  const [pricingOpen, setPricingOpen] = useState(false)
  const [activeModel, setActiveModel] = useState("")
  const [needPricingTip, setNeedPricingTip] = useState(false)
  const [unconfiguredModels, setUnconfiguredModels] = useState<string[]>([])

  const pageSize = 10

  const load = useCallback(async () => {
    try {
      const r = await fetch(
        `${API_BASE}/api/v2/analytics/tokens?range=${range}&page=${page}&page_size=${pageSize}`
      ).then((res) => res.json())
      if (r?.code === 0 && r.data) {
        const d = r.data
        setActiveModel(d.active_model || "")
        setNeedPricingTip(Boolean(d.need_pricing_tip))
        setUnconfiguredModels(Array.isArray(d.unconfigured_models) ? d.unconfigured_models : [])
        setSummary({
          today_tokens: d.today_tokens || 0,
          month_tokens: d.month_tokens || 0,
          total_tokens: d.total_tokens || 0,
          today_cost_cny: d.today_cost_cny || 0,
          month_cost_cny: d.month_cost_cny || 0,
          total_cost_cny: d.total_cost_cny || 0,
          today_cached_tokens: d.today_cached_tokens || 0,
          month_cached_tokens: d.month_cached_tokens || 0,
          total_cached_tokens: d.total_cached_tokens || 0,
          today_cache_hit_rate: d.today_cache_hit_rate || 0,
          month_cache_hit_rate: d.month_cache_hit_rate || 0,
          total_cache_hit_rate: d.total_cache_hit_rate || 0,
        })
        setByAction(d.by_action || [])
        setByModel(d.by_model || [])
        setTrend(d.daily_trend || [])
        setLogs(d.logs || [])
        setLogsTotal(d.logs_total || 0)
      }
    } catch (e) {
      console.error("[TokenMonitor] load failed:", e)
    }
  }, [range, page])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  useEffect(() => {
    setPage(1)
  }, [range])

  const totalModelTokens = byModel.reduce((s, m) => s + (m.total_tokens || 0), 0)
  const totalPages = Math.ceil(logsTotal / pageSize)

  return (
    <section id="section-token" className="scroll-mt-20 space-y-4">
      <div className="rounded-2xl border border-border/70 bg-card shadow-xs transition-all">
        {/* 顶部标题栏（支持折叠） */}
        <button
          onClick={() => setOpen(!open)}
          className="flex w-full items-center justify-between p-5 text-left transition-colors hover:bg-muted/40 rounded-2xl"
        >
          <div className="flex items-center gap-3">
            <div className="flex size-8 items-center justify-center rounded-lg bg-amber-500/10 text-amber-500">
              <Coins className="size-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold tracking-tight text-foreground">
                  大模型 Token 算力与成本审计中心
                </h2>
                {summary && (
                  <span className="hidden sm:inline-flex items-center rounded-md bg-amber-500/10 px-2 py-0.5 font-mono text-[11px] font-medium text-amber-600 dark:text-amber-400">
                    今日 {fmtNum(summary.today_tokens)} Tokens ({fmtCost(summary.today_cost_cny)})
                  </span>
                )}
              </div>
              <p className="text-[11px] text-muted-foreground">
                全链路调用场景、模型分布与请求级别的 Token 消耗审计
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="text-xs hidden sm:inline">{open ? "收起审计" : "展开审计"}</span>
            {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
          </div>
        </button>

        {/* 折叠内容 */}
        {open && summary && (
          <div className="border-t border-border/50 p-5 space-y-5">
            {/* 1. 核心指标卡 */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">今日消耗</span>
                  <Zap className="size-3.5 text-amber-500" />
                </div>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className="font-mono text-xl font-bold tracking-tight text-foreground tabular-nums">
                    {fmtNum(summary.today_tokens)}
                  </span>
                  <span className="text-xs text-muted-foreground">Tokens</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  预估支出 <span className="font-mono font-medium text-foreground">{fmtCost(summary.today_cost_cny)}</span>
                </p>
              </div>

              <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">本月消耗</span>
                  <Clock className="size-3.5 text-blue-500" />
                </div>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className="font-mono text-xl font-bold tracking-tight text-foreground tabular-nums">
                    {fmtNum(summary.month_tokens)}
                  </span>
                  <span className="text-xs text-muted-foreground">Tokens</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  预估支出 <span className="font-mono font-medium text-foreground">{fmtCost(summary.month_cost_cny)}</span>
                </p>
              </div>

              <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">累计总消耗</span>
                  <Database className="size-3.5 text-indigo-500" />
                </div>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className="font-mono text-xl font-bold tracking-tight text-foreground tabular-nums">
                    {fmtNum(summary.total_tokens)}
                  </span>
                  <span className="text-xs text-muted-foreground">Tokens</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  预估支出 <span className="font-mono font-medium text-foreground">{fmtCost(summary.total_cost_cny)}</span>
                </p>
              </div>

              <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">全局缓存命中率</span>
                  <Percent className="size-3.5 text-emerald-500" />
                </div>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className="font-mono text-xl font-bold tracking-tight text-emerald-600 dark:text-emerald-400 tabular-nums">
                    {summary.total_cache_hit_rate}%
                  </span>
                  <span className="text-xs text-muted-foreground">节省算力</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted/60">
                  <div
                    className="h-full rounded-full bg-emerald-500 transition-all"
                    style={{ width: `${Math.min(summary.total_cache_hit_rate, 100)}%` }}
                  />
                </div>
              </div>
            </div>

            {/* 2. 筛选胶囊与场景/模型视图 */}
            <div className="flex items-center justify-between pt-2">
              <span className="text-xs font-semibold text-foreground">模块与模型消耗分布</span>
              <div className="flex items-center gap-1 rounded-lg border border-border/60 bg-muted/50 p-0.5">
                {[
                  { key: "today", label: "今日" },
                  { key: "month", label: "本月" },
                  { key: "all", label: "全周期" },
                ].map((o) => (
                  <button
                    key={o.key}
                    onClick={() => setRange(o.key)}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium transition-all ${
                      range === o.key
                        ? "bg-card text-foreground shadow-xs font-semibold"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
              {/* 场景排行 */}
              <div className="lg:col-span-3 rounded-xl border border-border/60 bg-muted/10 p-4">
                <h3 className="text-xs font-semibold text-foreground mb-3">各场景消耗排行</h3>
                {byAction.length === 0 ? (
                  <p className="py-6 text-center text-xs text-muted-foreground">暂无场景消耗记录</p>
                ) : (
                  <div className="space-y-3">
                    {byAction.map((s) => {
                      const maxAct = Math.max(...byAction.map((a) => a.total_tokens), 1)
                      return (
                        <div key={s.action_name} className="space-y-1">
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-medium text-foreground truncate max-w-[200px]">
                              {actionLabel(s.action_name)}
                            </span>
                            <div className="flex items-center gap-2 font-mono">
                              <span className="text-muted-foreground text-[11px]">{s.call_count} 次</span>
                              <span className="font-semibold text-foreground">{fmtNum(s.total_tokens)}</span>
                              <span className="text-amber-600 dark:text-amber-400 text-[11px]">
                                {fmtCost(s.cost_cny)}
                              </span>
                            </div>
                          </div>
                          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/60">
                            <div
                              className="h-full rounded-full bg-primary transition-all duration-300"
                              style={{ width: `${(s.total_tokens / maxAct) * 100}%` }}
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              {/* 模型分布 */}
              <div className="lg:col-span-2 rounded-xl border border-border/60 bg-muted/10 p-4 flex flex-col justify-between">
                <div>
                  <h3 className="text-xs font-semibold text-foreground mb-3">模型 Token 与成本占比</h3>
                  {byModel.length === 0 ? (
                    <p className="py-6 text-center text-xs text-muted-foreground">暂无模型调用数据</p>
                  ) : (
                    <div className="space-y-2.5">
                      {byModel.map((m, idx) => {
                        const color = MODEL_COLORS[idx % MODEL_COLORS.length]
                        const ratio = totalModelTokens > 0 ? ((m.total_tokens / totalModelTokens) * 100).toFixed(1) : "0"
                        return (
                          <div key={m.model_name} className="flex items-center justify-between text-xs">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="size-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                              <span className="truncate font-medium text-foreground" title={m.model_name}>
                                {m.model_name}
                              </span>
                            </div>
                            <div className="flex items-center gap-2 font-mono shrink-0">
                              <span className="text-muted-foreground text-[11px]">{ratio}%</span>
                              <span className="font-semibold text-foreground">{fmtNum(m.total_tokens)}</span>
                              <span className="text-amber-600 dark:text-amber-400 text-[11px] font-medium">
                                {fmtCost(m.cost_cny)}
                              </span>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>

                <div className="mt-4 pt-3 border-t border-border/40 text-[11px] text-muted-foreground flex justify-between">
                  <span>模型类型: {byModel.length} 个</span>
                  <span className="font-mono">计费基于官方 Token 定价</span>
                </div>
              </div>
            </div>

            {/* 3. 详细审计明细表 */}
            <div className="rounded-xl border border-border/60 bg-muted/10 p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-xs font-semibold text-foreground">实时调用审计明细</h3>
                  <button
                    type="button"
                    onClick={() => setPricingOpen(true)}
                    className="group relative inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-[11px] font-semibold text-white bg-gradient-to-r from-violet-600 via-indigo-600 to-sky-500 shadow-sm shadow-indigo-500/25 hover:shadow-md hover:shadow-indigo-500/40 hover:brightness-110 active:scale-[0.98] transition-all duration-300 cursor-pointer"
                    title={
                      needPricingTip
                        ? `存在待录入模型（${unconfiguredModels.length > 0 ? unconfiguredModels.join("、") : "非官方模型"}），当前正以官方价暂估，点击配置专属单价`
                        : "配置模型单价与资费"
                    }
                  >
                    <span className="absolute -inset-0.5 rounded-lg bg-gradient-to-r from-violet-600 to-sky-500 opacity-40 blur-xs group-hover:opacity-75 transition duration-300 animate-pulse" />
                    <Settings2 className="relative size-3 transition-transform duration-300 group-hover:rotate-45" />
                    <span className="relative">配置单价</span>
                    {needPricingTip && (
                      <span className="relative flex h-2 w-2 ml-0.5" title="待录入模型正以官方价暂估">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-300 opacity-85" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400 ring-1 ring-white/60" />
                      </span>
                    )}
                  </button>
                </div>
                <span className="text-[11px] text-muted-foreground font-mono">
                  共 {logsTotal} 条记录 · 当前第 {page} / {Math.max(totalPages, 1)} 页
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-border/40 text-[11px] text-muted-foreground">
                      <th className="pb-2 font-medium">业务动作</th>
                      <th className="pb-2 font-medium">模型</th>
                      <th className="pb-2 text-right font-medium">输入</th>
                      <th className="pb-2 text-right font-medium">缓存命中</th>
                      <th className="pb-2 text-right font-medium">输出</th>
                      <th className="pb-2 text-right font-medium">总消耗</th>
                      <th className="pb-2 text-right font-medium">成本</th>
                      <th className="pb-2 text-right font-medium">请求时间</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20">
                    {logs.map((d) => (
                      <tr key={d.id} className="transition-colors hover:bg-muted/40">
                        <td className="py-2 pr-2">
                          <span className="font-medium text-foreground block truncate max-w-[160px]">
                            {actionLabel(d.action_name)}
                          </span>
                        </td>
                        <td className="py-2 font-mono text-muted-foreground text-[11px] truncate max-w-[120px]">
                          {d.model_name}
                        </td>
                        <td className="py-2 text-right font-mono text-primary tabular-nums">
                          {fmtNum(d.prompt_tokens)}
                        </td>
                        <td className="py-2 text-right font-mono text-emerald-600 dark:text-emerald-400 tabular-nums">
                          {d.cached_tokens > 0 ? fmtNum(d.cached_tokens) : "—"}
                        </td>
                        <td className="py-2 text-right font-mono text-foreground tabular-nums">
                          {fmtNum(d.completion_tokens)}
                        </td>
                        <td className="py-2 text-right font-mono font-bold text-foreground tabular-nums">
                          {fmtNum(d.total_tokens)}
                        </td>
                        <td className="py-2 text-right font-mono text-amber-600 dark:text-amber-400 tabular-nums">
                          <div className="inline-flex items-center gap-1 justify-end">
                            <span>{fmtCost(d.cost_cny)}</span>
                            {d.estimated === 1 && (
                              <span
                                className="text-[9px] px-1 py-0.2 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-medium"
                                title="非 MiMo 且未配置自定义单价，按 MiMo 资费暂估"
                              >
                                预估
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-2 text-right font-mono text-[11px] text-muted-foreground tabular-nums">
                          <span title={d.created_at}>{fmtDateTime(d.created_at)}</span>
                        </td>
                      </tr>
                    ))}
                    {logs.length === 0 && (
                      <tr>
                        <td colSpan={8} className="py-8 text-center text-muted-foreground text-xs">
                          暂无审计调用记录
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* 分页控制 */}
              {totalPages > 1 && (
                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    onClick={() => setPage((p) => Math.max(p - 1, 1))}
                    disabled={page <= 1}
                    className="flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-40"
                  >
                    <ChevronLeft className="size-3" />
                    上一页
                  </button>
                  <span className="font-mono text-xs text-muted-foreground px-2">
                    {page} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(p + 1, totalPages))}
                    disabled={page >= totalPages}
                    className="flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-40"
                  >
                    下一页
                    <ChevronRight className="size-3" />
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 自定义模型计价弹窗 */}
      <CustomPricingDialog
        open={pricingOpen}
        onOpenChange={setPricingOpen}
        currentModel={activeModel}
        onSaved={load}
      />
    </section>
  )
}
