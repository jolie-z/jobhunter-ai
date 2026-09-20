"use client"

import { useEffect, useState, useCallback } from "react"
import { Database, Zap, Clock, Activity, AlertCircle, TrendingUp, ChevronLeft, ChevronRight } from "lucide-react"
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from "recharts"

// --- Types ---

interface TokenLog {
  id: string
  action_name: string
  display_name: string
  caller: string
  job_id: string | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  model_name: string
  cost_cny: number
  estimated: number
  created_at: string
}

interface ActionBreakdown {
  action_name: string
  display_name: string
  call_count: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_cny: number
}

interface ModelBreakdown {
  model_name: string
  call_count: number
  total_tokens: number
  cost_cny: number
}

interface DailyTrend {
  date: string
  total_tokens: number
  cost_cny: number
  call_count: number
}

interface TokenStats {
  today_tokens: number
  month_tokens: number
  total_tokens: number
  today_cost_cny: number
  month_cost_cny: number
  total_cost_cny: number
  by_action: ActionBreakdown[]
  by_model: ModelBreakdown[]
  daily_trend: DailyTrend[]
  logs: TokenLog[]
  logs_total: number
  page: number
  page_size: number
}

type RangeFilter = "today" | "month" | "all"

// --- Chart colors ---
const CHART_COLORS = ["#6366f1", "#8b5cf6", "#10b981", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899", "#84cc16"]

// --- Date helpers ---
function getTodayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function getMonthStr(): string {
  const d = new Date()
  return `${d.getFullYear()}年${d.getMonth() + 1}月`
}

// --- Component ---

export function TokenAuditTable() {
  const [stats, setStats] = useState<TokenStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [range, setRange] = useState<RangeFilter>("all")
  const [page, setPage] = useState(1)
  const pageSize = 10

  const fetchData = useCallback((r: RangeFilter, p: number) => {
    setLoading(true)
    fetch(`http://localhost:8000/api/analytics/tokens?range=${r}&page=${p}&page_size=${pageSize}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.code === 0) setStats(data.data)
      })
      .catch((err) => console.error("Failed to load token stats:", err))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetchData(range, page)
  }, [range, page, fetchData])

  const handleRangeChange = (r: RangeFilter) => {
    setRange(r)
    setPage(1)
  }

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center h-48 bg-card rounded-xl border border-border">
        <Activity className="h-6 w-6 text-muted-foreground animate-pulse" />
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-48 bg-card rounded-xl border border-border">
        <AlertCircle className="h-6 w-6 text-red-500/50" />
        <span className="ml-2 text-sm text-muted-foreground">无法加载 Token 数据</span>
      </div>
    )
  }

  const { today_tokens, month_tokens, total_tokens, today_cost_cny, month_cost_cny, total_cost_cny, by_action, by_model, daily_trend, logs, logs_total } = stats

  const maxActionTokens = by_action.length > 0
    ? Math.max(...by_action.map(a => a.total_tokens), 1)
    : 1

  const totalPages = Math.max(1, Math.ceil(logs_total / pageSize))

  return (
    <div className="space-y-6">
      {/* === Summary Cards === */}
      <div className="grid grid-cols-3 gap-4">
        <SummaryCard
          label="今日消耗"
          subLabel={getTodayStr()}
          tokens={today_tokens}
          cost={today_cost_cny}
          icon={<Zap className="h-4 w-4" />}
          color="indigo"
        />
        <SummaryCard
          label="本月消耗"
          subLabel={getMonthStr()}
          tokens={month_tokens}
          cost={month_cost_cny}
          icon={<Clock className="h-4 w-4" />}
          color="purple"
        />
        <SummaryCard
          label="累计消耗"
          subLabel=""
          tokens={total_tokens}
          cost={total_cost_cny}
          icon={<Database className="h-4 w-4" />}
          color="emerald"
        />
      </div>

      {/* === Daily Trend Chart === */}
      {daily_trend.length > 0 && (
        <div className="rounded-2xl border border-border bg-card shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-border bg-muted/20">
            <h3 className="font-semibold text-sm flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-primary" />
              近 14 天 Token 消耗趋势
            </h3>
          </div>
          <div className="p-5 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={daily_trend} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                <defs>
                  <linearGradient id="tokenGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v: string) => v.slice(5)}
                  className="text-xs"
                  tick={{ fontSize: 11 }}
                />
                <YAxis
                  tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v)}
                  tick={{ fontSize: 11 }}
                />
                <Tooltip
                  formatter={(value: number, name: string) => [
                    name === "total_tokens" ? `${value.toLocaleString()} tokens` : `¥${value.toFixed(4)}`,
                    name === "total_tokens" ? "Token 消耗" : "成本",
                  ]}
                  labelFormatter={(label: string) => `日期: ${label}`}
                />
                <Area
                  type="monotone"
                  dataKey="total_tokens"
                  stroke="#6366f1"
                  strokeWidth={2}
                  fill="url(#tokenGradient)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* === Range Filter === */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground mr-1">筛选:</span>
        {(["today", "month", "all"] as RangeFilter[]).map((r) => (
          <button
            key={r}
            onClick={() => handleRangeChange(r)}
            className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
              range === r
                ? "bg-primary text-primary-foreground shadow-sm"
                : "bg-muted/50 text-muted-foreground hover:bg-muted"
            }`}
          >
            {r === "today" ? "今日" : r === "month" ? "本月" : "全部"}
          </button>
        ))}
      </div>

      {/* === Action Ranking + Model Distribution (side by side) === */}
      <div className="grid grid-cols-3 gap-4">
        {/* Action Ranking (2/3 width) */}
        <div className="col-span-2 rounded-2xl border border-border bg-card shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-border bg-muted/20">
            <h3 className="font-semibold text-sm">各场景 Token 消耗排行</h3>
            <p className="text-xs text-muted-foreground mt-1">按功能模块统计，含精确成本</p>
          </div>
          <div className="p-5 space-y-3">
            {by_action.map((action) => {
              const pct = Math.round((action.total_tokens / maxActionTokens) * 100)
              return (
                <div key={action.action_name} className="group">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-primary/10 text-primary">
                        {action.display_name}（{action.action_name}）
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {action.call_count} 次
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      <span className="text-muted-foreground">
                        入 <span className="text-indigo-400 font-medium">{action.prompt_tokens.toLocaleString()}</span>
                      </span>
                      <span className="text-muted-foreground">
                        出 <span className="text-emerald-400 font-medium">{action.completion_tokens.toLocaleString()}</span>
                      </span>
                      <span className="font-bold text-foreground">
                        {action.total_tokens.toLocaleString()}
                      </span>
                      <span className="text-amber-500 font-medium w-16 text-right">
                        ¥{action.cost_cny.toFixed(4)}
                      </span>
                    </div>
                  </div>
                  <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-primary/60 to-primary rounded-full transition-all duration-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              )
            })}
            {by_action.length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-4">暂无数据</p>
            )}
          </div>
        </div>

        {/* Model Distribution (1/3 width) */}
        <div className="rounded-2xl border border-border bg-card shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-border bg-muted/20">
            <h3 className="font-semibold text-sm">模型分布</h3>
            <p className="text-xs text-muted-foreground mt-1">累计 Token 与预估费用</p>
          </div>
          <div className="p-5">
            {by_model.length > 0 ? (
              <>
                <div className="h-40">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={by_model}
                        dataKey="total_tokens"
                        nameKey="model_name"
                        cx="50%"
                        cy="50%"
                        outerRadius={60}
                        innerRadius={35}
                        paddingAngle={2}
                      >
                        {by_model.map((_, idx) => (
                          <Cell key={idx} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value: number, name: string) => [`${value.toLocaleString()} tokens`, name]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-3 space-y-2">
                  {by_model.map((m, idx) => (
                    <div key={m.model_name} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span
                          className="w-2.5 h-2.5 rounded-full"
                          style={{ backgroundColor: CHART_COLORS[idx % CHART_COLORS.length] }}
                        />
                        <span className="text-muted-foreground truncate max-w-[100px]">{m.model_name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{m.total_tokens.toLocaleString()}</span>
                        <span className="text-amber-500">¥{m.cost_cny.toFixed(4)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">暂无数据</p>
            )}
          </div>
        </div>
      </div>

      {/* === Detail Table with Pagination === */}
      <div className="rounded-2xl border border-border bg-card shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-border bg-muted/20 flex items-center justify-between">
          <h3 className="font-semibold text-sm">Token 消耗明细（最近 50 条）</h3>
          <span className="text-xs text-muted-foreground">共 {logs_total} 条</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-muted/40 text-muted-foreground text-xs uppercase tracking-wider">
              <tr>
                <th className="px-4 py-3 font-medium">执行动作</th>
                <th className="px-4 py-3 font-medium">来源</th>
                <th className="px-4 py-3 font-medium">模型</th>
                <th className="px-4 py-3 font-medium text-right">输入</th>
                <th className="px-4 py-3 font-medium text-right">输出</th>
                <th className="px-4 py-3 font-medium text-right">总计</th>
                <th className="px-4 py-3 font-medium text-right">成本</th>
                <th className="px-4 py-3 font-medium text-right">时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {logs.map((log) => (
                <tr key={log.id} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-primary/10 text-primary">
                      {log.display_name || log.action_name}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-muted-foreground">
                    {log.caller || "-"}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-muted-foreground">
                    {log.model_name || "未知"}
                    {log.estimated === 1 && (
                      <span className="ml-1 text-[10px] text-amber-500" title="本地估算值">~</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right text-indigo-400 text-xs">
                    {log.prompt_tokens.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right text-emerald-400 text-xs">
                    {log.completion_tokens.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right font-bold text-xs">
                    {log.total_tokens.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right text-amber-500 text-xs font-medium">
                    ¥{log.cost_cny.toFixed(4)}
                  </td>
                  <td className="px-4 py-2.5 text-right text-muted-foreground text-[11px] font-mono">
                    {log.created_at}
                  </td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-5 py-8 text-center text-muted-foreground">
                    暂无消耗记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {/* Pagination */}
        {totalPages > 1 && (
          <div className="px-5 py-3 border-t border-border flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              第 {page} / {totalPages} 页
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="p-1.5 rounded-lg hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                <button
                  key={p}
                  onClick={() => setPage(p)}
                  className={`w-7 h-7 rounded-lg text-xs font-medium transition-colors ${
                    p === page
                      ? "bg-primary text-primary-foreground"
                      : "hover:bg-muted text-muted-foreground"
                  }`}
                >
                  {p}
                </button>
              ))}
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="p-1.5 rounded-lg hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// --- Sub-components ---

function SummaryCard({ label, subLabel, tokens, cost, icon, color }: {
  label: string
  subLabel: string
  tokens: number
  cost: number
  icon: React.ReactNode
  color: "indigo" | "purple" | "emerald"
}) {
  const colorMap = {
    indigo: {
      gradient: "from-indigo-500/10 to-indigo-900/5",
      hover: "from-indigo-500/10",
      iconBg: "bg-indigo-500/10 text-indigo-500",
      text: "text-indigo-500",
    },
    purple: {
      gradient: "from-purple-500/10 to-purple-900/5",
      hover: "from-purple-500/10",
      iconBg: "bg-purple-500/10 text-purple-500",
      text: "text-purple-500",
    },
    emerald: {
      gradient: "from-emerald-500/10 to-emerald-900/5",
      hover: "from-emerald-500/10",
      iconBg: "bg-emerald-500/10 text-emerald-500",
      text: "text-emerald-500",
    },
  }
  const c = colorMap[color]

  return (
    <div className={`relative group overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br ${c.gradient} p-5 backdrop-blur-xl`}>
      <div className={`absolute inset-0 bg-gradient-to-r ${c.hover} to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500`} />
      <div className="relative z-10 flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-muted-foreground">{label}</span>
          {subLabel && (
            <span className="text-[11px] text-muted-foreground/60 bg-muted/40 px-1.5 py-0.5 rounded">{subLabel}</span>
          )}
        </div>
        <div className={`p-2 rounded-xl ${c.iconBg}`}>{icon}</div>
      </div>
      <div className="relative z-10 flex items-baseline gap-2">
        <span className={`text-3xl font-black ${c.text} tracking-tight`}>{tokens.toLocaleString()}</span>
        <span className="text-xs text-muted-foreground">Tokens</span>
      </div>
      <div className="relative z-10 mt-1 text-xs text-muted-foreground">
        ≈ ¥{cost.toFixed(4)}
      </div>
    </div>
  )
}
