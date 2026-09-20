"use client"

import { Cpu, Zap, Sliders, Info, Globe } from "lucide-react"
import { cn } from "@/lib/utils"
import { Switch } from "@/components/ui/switch"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface ModelConcurrencyCardProps {
  modelName: string
  concurrency: number
  onConcurrencyChange: (val: number) => void
  threshold: string
  onThresholdChange: (val: string) => void
  enableCompanySearch?: boolean
  onEnableCompanySearchChange?: (val: boolean) => void
}

const CONCURRENCY_PRESETS = [3, 5, 8, 10]

const THRESHOLD_OPTIONS = [
  {
    key: "A",
    title: "仅 A 级",
    score: "≥90分",
    desc: "极高匹配度才自动改写并推进（最省 Token，命中精准）",
  },
  {
    key: "B",
    title: "A + B 级",
    score: "≥75分",
    desc: "良好及以上匹配岗位均自动改写并推进",
  },
  {
    key: "C",
    title: "A + B + C 级",
    score: "≥60分",
    desc: "及格即自动改写并推进（宽泛海投模式）",
  },
]

export function ModelConcurrencyCard({
  modelName,
  concurrency,
  onConcurrencyChange,
  threshold,
  onThresholdChange,
  enableCompanySearch = true,
  onEnableCompanySearchChange,
}: ModelConcurrencyCardProps) {
  return (
    <div className="rounded-2xl border border-border/70 bg-gradient-to-b from-card to-muted/10 p-4.5 space-y-3.5 shadow-xs">
      {/* 顶栏：模型基座与 Serper 实时企业背调 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 border-b border-border/50 pb-3">
        {/* 左侧：模型 */}
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-violet-500/10 text-violet-600 dark:text-violet-400 border border-violet-500/20 font-bold shadow-xs">
            <Cpu className="h-4 w-4" />
          </div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-foreground text-xs tracking-tight">
              AI 初评推理模型
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/25 px-2 py-0.5 text-[10px] font-medium font-mono">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              {modelName || "mimo-v2.5-pro"}
            </span>

            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors">
                  <Info className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                初评将基于该推理大模型对岗位进行八维深度打分、抽取关键事实依据并计算综合评级。
              </TooltipContent>
            </Tooltip>
          </div>
        </div>

        {/* 右侧：Serper 实时企业背调 */}
        <div className="flex items-center gap-2 rounded-xl bg-muted/30 border border-border/60 px-2.5 py-1 text-xs self-start sm:self-auto">
          <Globe className="h-3.5 w-3.5 text-sky-500 shrink-0" />
          <div className="flex items-center gap-1">
            <span className="text-[11px] font-medium text-foreground">
              Serper 企业联网背调
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors">
                  <Info className="h-3 w-3" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs space-y-1.5 p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl">
                <p className="font-semibold text-zinc-100 flex items-center gap-1">
                  <span>🌐</span> 外部情报自动注入：
                </p>
                <p className="text-zinc-300 text-[11px] leading-relaxed">
                  通过 Serper（Google 搜索）4 路并发侦察：核心业务、竞品地位、AI 技术布局、近一个月融资/裁员/财报新闻，再由 LLM 汇总成情报简报，赋能「公司阶段」与「赛道前景」客观打分。
                </p>
                <p className="text-zinc-400 text-[10px] leading-relaxed">
                  💡 未配置 Serper Key 或请求失败时自动降级 Tavily 备用引擎；匿名企业自动触发 3 分中性保底，不产生倒扣分。
                </p>
              </TooltipContent>
            </Tooltip>
          </div>

          {onEnableCompanySearchChange && (
            <Switch
              checked={enableCompanySearch}
              onCheckedChange={onEnableCompanySearchChange}
            />
          )}
        </div>
      </div>

      {/* 并发通道数 + 自动化流转阀门 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* 1. 并发通道 */}
        <div className="space-y-2 p-3 rounded-xl bg-muted/20 border border-border/50 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Zap className="h-3.5 w-3.5 text-amber-500" />
              <span className="text-xs font-medium text-foreground">并行评估通道</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" className="text-muted-foreground/50 hover:text-foreground transition-colors">
                    <Info className="h-3 w-3" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                  控制同一时间向大模型发起的并发请求数，建议 3~8，防止突发流量触发服务商限流。
                </TooltipContent>
              </Tooltip>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center bg-background rounded-lg border border-border p-0.5">
              {CONCURRENCY_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => onConcurrencyChange(preset)}
                  className={cn(
                    "px-2.5 py-0.8 text-[11px] font-mono rounded transition-all",
                    concurrency === preset
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
                min={1}
                max={20}
                value={concurrency}
                onChange={(e) => onConcurrencyChange(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
                className="w-12 rounded-lg border border-border bg-background px-1.5 py-0.8 text-xs font-mono text-center focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
              <span>并发</span>
            </div>
          </div>
        </div>

        {/* 2. 自动化流转阀门 */}
        <div className="space-y-2 p-3 rounded-xl bg-muted/20 border border-border/50 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Sliders className="h-3.5 w-3.5 text-violet-500" />
              <span className="text-xs font-medium text-foreground">自动改写流转门槛</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" className="text-muted-foreground/50 hover:text-foreground transition-colors">
                    <Info className="h-3 w-3" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                  初评综合得分达到该评级时，系统将自动进入「深度画像 ➔ 简历改写 ➔ 老板审批」后续阶段。
                </TooltipContent>
              </Tooltip>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-1.5">
            {THRESHOLD_OPTIONS.map((opt) => {
              const active = threshold === opt.key
              return (
                <button
                  key={opt.key}
                  type="button"
                  onClick={() => onThresholdChange(opt.key)}
                  className={cn(
                    "px-2 py-1.2 rounded-lg border text-[11px] font-medium transition-all text-center flex flex-col items-center justify-center gap-0.5",
                    active
                      ? "bg-violet-600/10 border-violet-500/40 text-violet-700 dark:text-violet-300 font-bold shadow-2xs"
                      : "border-border/60 bg-background text-muted-foreground hover:text-foreground hover:bg-muted/40"
                  )}
                  title={opt.desc}
                >
                  <span>{opt.title}</span>
                  <span className="text-[9px] font-mono text-muted-foreground/80">{opt.score}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
