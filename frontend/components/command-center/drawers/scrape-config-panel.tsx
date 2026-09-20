"use client"

import { useState, useEffect, useCallback } from "react"
import {
  Save,
  Plus,
  Trash2,
  Sparkles,
  Archive,
  RotateCcw,
  Play,
  Info,
} from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { usePipelineStore } from "@/store/pipeline-store"
import { CitySelectorPopover } from "./city-selector-popover"
import { SalaryMappingPopover } from "./salary-mapping-popover"
import { PlatformSessionBar } from "./platform-session-bar"
import { ScrapeLiveProgressBanner } from "./scrape-live-progress-banner"
import { ScrapeHistorySection, HistoryItem } from "./scrape-history-drawer"
import { PLATFORM_NAMES } from "../types"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"

interface ConditionItem {
  id: string
  keyword: string
  city: string
  salary: string
}

interface ScrapeConfigPanelProps {
  onSaved: () => void
}

const MAX_QUEUE_COUNT = 10

export function ScrapeConfigPanel({ onSaved }: ScrapeConfigPanelProps) {
  const [queue, setQueue] = useState<ConditionItem[]>([])
  const [defaultCity, setDefaultCity] = useState("广州")
  const [defaultSalary, setDefaultSalary] = useState("不限")
  const [newKeyword, setNewKeyword] = useState("")
  const [newCity, setNewCity] = useState("")
  const [newSalary, setNewSalary] = useState("")

  const [platforms, setPlatforms] = useState<Record<string, { enabled: boolean; limit: number }>>({
    boss: { enabled: true, limit: 20 },
    liepin: { enabled: true, limit: 20 },
    "51job": { enabled: true, limit: 20 },
    zhilian: { enabled: true, limit: 20 },
  })

  const [condProgress, setCondProgress] = useState<
    Record<string, Record<string, { scraped: number; predicted: number; last_page?: number }>>
  >({})

  const [history, setHistory] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [saveMsg, setSaveMsg] = useState("")
  const [suggesting, setSuggesting] = useState(false)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [runningScrapeOnly, setRunningScrapeOnly] = useState(false)

  // 1. 加载抓取配置
  const loadConfig = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/scrape-config`)
      const data = await res.json()
      if (data.code === 0 && data.data) {
        const d = data.data
        if (Array.isArray(d.keywords) && d.keywords.length > 0) {
          setQueue(
            d.keywords.map((k: string | { keyword?: string; city?: string; salary?: string }, idx: number) => ({
              id: `kw_${Date.now()}_${idx}`,
              keyword: typeof k === "string" ? k : k.keyword || "",
              city: (typeof k === "object" ? k.city : "") || d.default_city || "广州",
              salary: (typeof k === "object" ? k.salary : "") || d.default_salary || "不限",
            }))
          )
        }
        if (d.default_city) setDefaultCity(d.default_city)
        if (d.default_salary) setDefaultSalary(d.default_salary)
        if (d.platforms && typeof d.platforms === "object") {
          setPlatforms((prev) => ({ ...prev, ...d.platforms }))
        }
      }
    } catch {
      // 降级使用本地默认值
    }
  }, [])

  // 2. 加载台账与断点进度
  const loadProgress = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/condition-progress`)
      const data = await res.json()
      if (data.code === 0 && Array.isArray(data.data)) {
        // 后端返回扁平行（keyword/city/salary/platform/scraped_count/predicted_total），
        // 前端按「条件|平台」折叠成台账 UI 需要的嵌套结构
        const map: Record<string, Record<string, { scraped: number; predicted: number; last_page?: number }>> = {}
        for (const row of data.data) {
          if (!row || !row.keyword) continue
          const key = `${row.keyword}|${row.city || ""}|${row.salary || ""}`
          if (!map[key]) map[key] = {}
          map[key][row.platform] = {
            scraped: Number(row.scraped_count) || 0,
            predicted: Number(row.predicted_total) || 0,
            ...(row.last_page !== undefined ? { last_page: Number(row.last_page) || 0 } : {}),
          }
        }
        setCondProgress(map)
      }
    } catch {}
  }, [])

  // 3. 加载历史记录
  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/keyword-history?limit=100`)
      const data = await res.json()
      if (data.code === 0 && Array.isArray(data.data)) {
        setHistory(data.data)
      }
    } catch {}
  }, [])

  useEffect(() => {
    void (async () => {
      await Promise.all([loadConfig(), loadProgress(), loadHistory()])
    })()
  }, [loadConfig, loadProgress, loadHistory])

  // 添加条件
  const handleAddCondition = async () => {
    const kw = newKeyword.trim()
    if (!kw) {
      toast.error("请输入岗位关键词")
      return
    }
    if (queue.length >= MAX_QUEUE_COUNT) {
      toast.warning(`条件队列最多只能设置 ${MAX_QUEUE_COUNT} 组`)
      return
    }

    try {
      const res = await fetch(
        `${API_BASE}/api/pipeline/keyword-history/check?keyword=${encodeURIComponent(kw)}`
      )
      const data = await res.json()
      if (data.code === 0 && Array.isArray(data.data) && data.data.length > 0) {
        const last = data.data[0]
        toast.info(`提示：曾抓取过「${kw}」(${last.city || "广州"} · 累计+${last.jobs_added}条)，已为您并入队列`)
      }
    } catch {}

    const newItem: ConditionItem = {
      id: `kw_${Date.now()}`,
      keyword: kw,
      city: newCity || defaultCity || "广州",
      salary: newSalary || defaultSalary || "不限",
    }
    setQueue((prev) => [...prev, newItem])
    setNewKeyword("")
  }

  // AI 推荐关键词
  const handleSuggest = async () => {
    setSuggesting(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/suggest-keywords`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: 5 }),
      })
      const data = await res.json()
      if (data.code === 0 && Array.isArray(data.data)) {
        setSuggestions(data.data)
        toast.success("已根据简历与求职偏好生成推荐关键词")
      } else {
        toast.error(data.detail || data.msg || "AI 推荐失败，请稍后重试")
      }
    } catch {
      toast.error("AI 推荐服务连接失败")
    } finally {
      setSuggesting(false)
    }
  }

  // 保存规则
  // 把给定队列持久化到后端；返回是否成功（试跑/归档都依赖保存结果决策后续动作）
  const saveQueue = async (nextQueue: ConditionItem[], silent = false): Promise<boolean> => {
    setLoading(true)
    setSaveMsg("")
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/scrape-config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          keywords: nextQueue.map((k) => ({
            keyword: k.keyword,
            city: k.city || defaultCity,
            salary: k.salary || defaultSalary,
          })),
          platforms,
          default_city: defaultCity,
          default_salary: defaultSalary,
        }),
      })
      const data = await res.json()
      if (res.ok && data.code === 0) {
        if (!silent) {
          setSaveMsg("✓ 抓取规则已保存")
          toast.success("抓取规则已成功保存")
        }
        onSaved()
        return true
      }
      setSaveMsg(data.detail || "保存失败")
      toast.error(data.detail || "保存失败")
      return false
    } catch {
      setSaveMsg("保存失败：网络错误")
      toast.error("网络错误，保存失败")
      return false
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async (): Promise<boolean> => {
    if (queue.length === 0) {
      toast.error("条件队列不能为空，请至少添加 1 组搜索条件")
      return false
    }
    return saveQueue(queue)
  }

  // 单独试跑抓取
  const handleRunScrapeOnly = async () => {
    if (queue.length === 0) {
      toast.error("请先添加至少 1 组抓取条件")
      return
    }
    setRunningScrapeOnly(true)
    try {
      // 保存失败（如超过队列上限）时必须中止试跑，否则跑的是旧配置
      const saved = await handleSave()
      if (!saved) return
      const res = await fetch(`${API_BASE}/api/pipeline/run-scrape-only`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platforms_limit: 10 }),
      })
      const data = await res.json()
      if (res.ok && data.data?.task_id) {
        toast.success("🚀 抓取模块单独试跑已启动！数据正实时入池")
        usePipelineStore.getState().startPipeline(data.data.task_id)
      } else {
        toast.error("启动失败：" + (data.detail || data.msg || "未知错误"))
      }
    } catch {
      toast.error("网络异常，无法启动抓取")
    } finally {
      setRunningScrapeOnly(false)
    }
  }

  // 归档与重置
  const handleArchive = async (item: ConditionItem) => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/keyword-history/archive`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword: item.keyword, city: item.city, salary: item.salary }),
      })
      const data = await res.json()
      if (res.ok && data.code === 0) {
        const remaining = queue.filter((k) => k.id !== item.id)
        setQueue(remaining)
        loadHistory()
        // 必须把剩余队列回存后端，否则刷新后已归档条件会被配置重新装回
        const saved = await saveQueue(remaining, true)
        if (saved) {
          toast.success(`已将「${item.keyword}」移入历史归档`)
        } else {
          toast.warning(`已记录归档，但剩余队列保存失败，刷新后可能恢复，请手动保存一次`)
        }
      } else {
        toast.error(data.detail || data.msg || "归档失败")
      }
    } catch {
      toast.error("归档失败")
    }
  }

  const handleResetProgress = async (item: ConditionItem) => {
    if (!window.confirm(`确定重置「${item.keyword}」在所有平台的续抓记录与累积进度吗？`)) return
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/condition-progress/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword: item.keyword, city: item.city, salary: item.salary }),
      })
      const data = await res.json()
      if (data.code === 0) {
        loadProgress()
        toast.success(`已重置「${item.keyword}」的抓取台账`)
      }
    } catch {
      toast.error("重置异常")
    }
  }

  const handleDeleteHistory = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/keyword-history/${id}`, { method: "DELETE" })
      const data = await res.json()
      if (res.ok && data.code === 0) {
        setHistory((prev) => prev.filter((h) => h.id !== id))
      } else {
        toast.error(data.detail || data.msg || "删除历史记录失败")
      }
    } catch {
      toast.error("网络错误，删除历史记录失败")
    }
  }

  return (
    <div className="space-y-4 text-xs">
      {/* 1. 4 平台会话状态与生命周期 */}
      <PlatformSessionBar
        excludePlatforms={["xiaohongshu", "xhs"]}
        gridClassName="grid-cols-2 sm:grid-cols-4"
      />

      {/* 2. 本轮任务实时流水 */}
      <ScrapeLiveProgressBanner />

      {/* 3. 默认搜索参数 */}
      <div className="rounded-xl border border-border/80 bg-card p-3 space-y-2">
        <span className="font-semibold text-foreground">⚙️ 默认搜索参数</span>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-[11px] text-muted-foreground">默认目标城市</label>
            <CitySelectorPopover value={defaultCity} onChange={setDefaultCity} buttonClassName="w-full" />
          </div>
          <div className="space-y-1">
            <label className="text-[11px] text-muted-foreground">默认薪资档位</label>
            <SalaryMappingPopover value={defaultSalary} onChange={setDefaultSalary} buttonClassName="w-full" />
          </div>
        </div>
      </div>

      {/* 4. 条件队列管理 */}
      <div className="space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <label className="font-semibold text-foreground">条件队列 ({queue.length}/{MAX_QUEUE_COUNT})</label>
            <span className="text-[10px] text-muted-foreground">多条件自动轮巡与独立推进</span>
          </div>

          <button
            type="button"
            onClick={handleSuggest}
            disabled={suggesting}
            className="flex items-center gap-1 text-[11px] text-violet-600 dark:text-violet-400 hover:underline font-medium disabled:opacity-50"
          >
            <Sparkles className="h-3 w-3" />
            {suggesting ? "AI分析中…" : "AI 推荐关键词"}
          </button>
        </div>

        {/* 新增输入条 */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 rounded-xl border border-border/80 bg-card p-2 shadow-xs">
          <input
            type="text"
            placeholder="岗位关键词 (如: AI Agent)"
            value={newKeyword}
            onChange={(e) => setNewKeyword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAddCondition()
            }}
            className="flex-1 rounded-lg border border-border bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
          />

          <CitySelectorPopover value={newCity || defaultCity} onChange={setNewCity} buttonClassName="w-28 shrink-0" />
          <SalaryMappingPopover value={newSalary || defaultSalary} onChange={setNewSalary} buttonClassName="w-28 shrink-0" />

          <button
            type="button"
            onClick={handleAddCondition}
            disabled={queue.length >= MAX_QUEUE_COUNT}
            className="flex items-center justify-center gap-1 rounded-lg bg-foreground px-3 py-1.5 text-background font-medium hover:opacity-90 active:scale-95 transition-all shrink-0 disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
            加入队列
          </button>
        </div>

        {/* AI 推荐结果 */}
        {suggestions.length > 0 && (
          <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-2.5 space-y-1.5">
            <div className="flex items-center justify-between text-[11px] font-semibold text-violet-700 dark:text-violet-300">
              <span className="flex items-center gap-1">
                <Sparkles className="h-3.5 w-3.5" />
                AI 推荐岗位方向
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((kw) => (
                <button
                  key={kw}
                  type="button"
                  onClick={() => {
                    setQueue((prev) =>
                      prev.length < MAX_QUEUE_COUNT
                        ? [...prev, { id: `kw_${Date.now()}_${kw}`, keyword: kw, city: defaultCity, salary: defaultSalary }]
                        : prev
                    )
                  }}
                  className="rounded-md border border-violet-500/30 bg-background px-2 py-0.5 text-[11px] text-foreground hover:bg-violet-600 hover:text-white transition-colors"
                >
                  + {kw}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 队列卡片 */}
        <div className="space-y-2 max-h-60 overflow-y-auto pr-0.5">
          {queue.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border py-6 text-center text-muted-foreground">
              暂无抓取条件，请在上方添加关键词
            </div>
          ) : (
            queue.map((item, idx) => {
              const progressKey = `${item.keyword}|${item.city}|${item.salary}`
              const progMap = condProgress[progressKey] || {}

              return (
                <div key={item.id} className="rounded-xl border border-border/80 bg-card p-2.5 shadow-xs space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-muted text-[10px] font-mono font-bold text-muted-foreground shrink-0">
                        {idx + 1}
                      </span>
                      <span className="font-semibold text-foreground truncate">{item.keyword}</span>
                      <span className="rounded bg-muted px-1.5 py-0.2 text-[10px] text-muted-foreground shrink-0">
                        {item.city}
                      </span>
                      <span className="rounded bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/20 px-1.5 py-0.2 text-[10px] font-medium shrink-0">
                        {item.salary}
                      </span>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        onClick={() => handleResetProgress(item)}
                        title="重置本条件进度"
                        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <RotateCcw className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleArchive(item)}
                        title="移入历史归档"
                        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <Archive className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setQueue((prev) => prev.filter((k) => k.id !== item.id))}
                        title="删除条件"
                        className="rounded p-1 text-muted-foreground hover:text-rose-500"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>

                  {/* 4 平台历史累积台账 */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                    {["boss", "liepin", "51job", "zhilian"].map((platKey) => {
                      const pProg = progMap[platKey]
                      const scraped = pProg?.scraped || 0
                      const predicted = pProg?.predicted || 0
                      const isExhausted = predicted > 0 && scraped >= predicted

                      return (
                        <div
                          key={platKey}
                          className={cn(
                            "flex items-center justify-between rounded-lg px-2 py-1 text-[10px] border font-mono",
                            isExhausted
                              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
                              : scraped > 0
                              ? "bg-muted/40 border-border/70 text-foreground"
                              : "bg-muted/20 border-border/40 text-muted-foreground/60"
                          )}
                        >
                          <span className="font-sans font-medium">{PLATFORM_NAMES[platKey]?.replace("招聘", "").replace("直聘", "")}:</span>
                          <span>
                            {scraped > 0 ? `${scraped}${predicted > 0 ? `/${predicted}` : ""}${isExhausted ? " ✓" : ""}` : "待抓"}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })
          )}
        </div>

        {/* 历史归档区 */}
        <ScrapeHistorySection history={history} onDeleteHistory={handleDeleteHistory} />
      </div>

      {/* 5. 平台任务计划上限设置 (硬上限 50 条) */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <label className="font-semibold text-foreground text-xs">各平台单轮计划上限</label>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground p-0.5 rounded-full"
                >
                  <Info className="h-3.5 w-3.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                为了保护各招聘平台爬虫的稳定性、防封控与长期有效使用，系统设置单平台单轮最大计划上限为 50 个岗位。填入大于 50 的数值将自动限制为 50。
              </TooltipContent>
            </Tooltip>
          </div>
          <span className="text-[10px] text-muted-foreground font-mono">
            单平台单轮上限 ≤ 50 条 (防封控硬保护)
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {["boss", "liepin", "51job", "zhilian"].map((plat) => {
            const p = platforms[plat] || { enabled: true, limit: 20 }
            return (
              <div key={plat} className="rounded-xl border border-border/80 bg-muted/20 p-2.5 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-foreground text-xs">{PLATFORM_NAMES[plat] || plat}</span>
                  <input
                    type="checkbox"
                    checked={p.enabled}
                    onChange={(e) => setPlatforms({ ...platforms, [plat]: { ...p, enabled: e.target.checked } })}
                    className="rounded text-violet-600 focus:ring-violet-500"
                  />
                </div>
                <div className="flex items-center justify-between gap-1 pt-1 border-t border-border/40">
                  <span className="text-[11px] text-muted-foreground">计划:</span>
                  <div className="flex items-center gap-1">
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={p.limit}
                      onChange={(e) => {
                        const rawVal = Number(e.target.value) || 0
                        const clamped = Math.min(Math.max(rawVal, 0), 50)
                        setPlatforms({ ...platforms, [plat]: { ...p, limit: clamped } })
                      }}
                      className="w-12 rounded border border-border bg-background px-1.5 py-0.5 text-xs text-center font-mono font-semibold text-foreground focus:border-violet-500 focus:outline-none"
                    />
                    <span className="text-[10px] text-muted-foreground">条</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* 6. 底部操作栏 */}
      <div className="pt-3 border-t border-border flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2.5">
        <span className="text-emerald-600 dark:text-emerald-400 font-medium text-xs truncate max-w-xs">{saveMsg}</span>
        <div className="flex items-center gap-2 justify-end">
          <button
            type="button"
            onClick={handleRunScrapeOnly}
            disabled={runningScrapeOnly || queue.length === 0}
            className="flex items-center gap-1.5 rounded-lg border border-violet-500/40 bg-violet-500/10 px-3.5 py-2 text-violet-700 dark:text-violet-300 font-medium hover:bg-violet-600 hover:text-white active:scale-95 transition-all shadow-xs disabled:opacity-50 text-xs"
          >
            <Play className="h-3.5 w-3.5 fill-current" />
            {runningScrapeOnly ? "启动中…" : "🚀 单独试跑抓取 (单平台10条)"}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg bg-foreground px-4 py-2 text-background font-medium hover:opacity-90 active:scale-95 transition-all shadow-xs disabled:opacity-50 text-xs"
          >
            <Save className="h-3.5 w-3.5" />
            {loading ? "保存中…" : "保存抓取规则"}
          </button>
        </div>
      </div>
    </div>
  )
}
