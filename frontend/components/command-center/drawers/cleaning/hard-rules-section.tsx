"use client"

import { useState } from "react"
import { Briefcase, MapPin, GraduationCap, X, Plus, Info, ShieldCheck } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface HardRulesSectionProps {
  minSalary: number | ""
  maxSalary: number | ""
  maxExp: number | ""
  cities: string[]
  educationRequire: string[]
  educationExclude: string[]
  onMinSalaryChange: (val: number | "") => void
  onMaxSalaryChange: (val: number | "") => void
  onMaxExpChange: (val: number | "") => void
  onCitiesChange: (cities: string[]) => void
  onEducationRequireChange: (edu: string[]) => void
  onEducationExcludeChange: (edu: string[]) => void
}

export function HardRulesSection({
  minSalary,
  maxSalary,
  maxExp,
  cities,
  educationRequire,
  educationExclude,
  onMinSalaryChange,
  onMaxSalaryChange,
  onMaxExpChange,
  onCitiesChange,
  onEducationRequireChange,
  onEducationExcludeChange,
}: HardRulesSectionProps) {
  const [newCity, setNewCity] = useState("")
  const [newEduReq, setNewEduReq] = useState("")
  const [newEduEx, setNewEduEx] = useState("")

  const handleAddCity = () => {
    const val = newCity.trim()
    if (val && !cities.includes(val)) {
      onCitiesChange([...cities, val])
      setNewCity("")
    }
  }

  const handleAddEduReq = () => {
    const val = newEduReq.trim()
    if (val && !educationRequire.includes(val)) {
      onEducationRequireChange([...educationRequire, val])
      setNewEduReq("")
    }
  }

  const handleAddEduEx = () => {
    const val = newEduEx.trim()
    if (val && !educationExclude.includes(val)) {
      onEducationExcludeChange([...educationExclude, val])
      setNewEduEx("")
    }
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3.5">
      {/* 极简顶栏 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-blue-500/10 text-blue-600 dark:text-blue-400 font-bold text-[11px]">
            T1
          </div>
          <span className="text-xs font-semibold text-foreground tracking-tight">
            Tier 1 物理硬规则清洗
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors cursor-help p-0.5 rounded-full hover:bg-muted"
              >
                <Info className="h-3.5 w-3.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
              根据薪资、工作经验、目标城市与学历指标前置物理拦截，不符合硬条件的岗位立即丢弃，大幅节省后续大模型 Token 消耗与计算耗时。
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[11px] text-muted-foreground">
          前置物理阻断 · 节省 Token 算力
        </span>
      </div>

      {/* 1. 薪资与经验单行控制条 */}
      <div className="rounded-xl border border-border/60 bg-background/60 p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        {/* 薪资门槛 */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-xs font-medium text-foreground shrink-0">
            <span className="text-amber-500 font-semibold font-mono">¥</span>
            <span>薪资门槛</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground hover:text-foreground">
                  <Info className="h-3 w-3 text-zinc-400" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2">
                岗位最高薪资低于此下限，或最低薪资高于此上限将被过滤（单位：K/月）。
              </TooltipContent>
            </Tooltip>
          </div>
          <div className="flex items-center gap-1.5">
            <input
              type="number"
              placeholder="最低"
              value={minSalary}
              onChange={(e) => onMinSalaryChange(e.target.value === "" ? "" : Number(e.target.value))}
              className="h-7 w-16 rounded-lg border border-border bg-background px-1.5 text-center text-xs font-mono font-semibold text-foreground focus:border-violet-500 focus:outline-none"
            />
            <span className="text-xs text-muted-foreground">—</span>
            <input
              type="number"
              placeholder="最高"
              value={maxSalary}
              onChange={(e) => onMaxSalaryChange(e.target.value === "" ? "" : Number(e.target.value))}
              className="h-7 w-16 rounded-lg border border-border bg-background px-1.5 text-center text-xs font-mono font-semibold text-foreground focus:border-violet-500 focus:outline-none"
            />
            <span className="text-xs text-muted-foreground">K</span>
          </div>
        </div>

        {/* 经验要求上限 */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-xs font-medium text-foreground shrink-0">
            <Briefcase className="h-3.5 w-3.5 text-violet-500" />
            <span>经验上限</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground hover:text-foreground">
                  <Info className="h-3 w-3 text-zinc-400" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2">
                过滤要求工作年限超过此值的岗位（例如填 10 则过滤 10 年以上专家岗；留空代表不限）。
              </TooltipContent>
            </Tooltip>
          </div>
          <div className="flex items-center gap-1.5">
            <input
              type="number"
              placeholder="不限"
              value={maxExp}
              onChange={(e) => onMaxExpChange(e.target.value === "" ? "" : Number(e.target.value))}
              className="h-7 w-16 rounded-lg border border-border bg-background px-1.5 text-center text-xs font-mono font-semibold text-foreground focus:border-violet-500 focus:outline-none"
            />
            <span className="text-xs text-muted-foreground">年以内</span>
          </div>
        </div>
      </div>

      {/* 2. 目标城市列表 */}
      <div className="rounded-xl border border-border/60 bg-background/60 p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
            <MapPin className="h-3.5 w-3.5 text-emerald-500" />
            <span>允许目标城市 (白名单)</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground hover:text-foreground">
                  <Info className="h-3 w-3 text-zinc-400" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2">
                只有属于这些城市的岗位才会被放行进入后续 AI 初评。
              </TooltipContent>
            </Tooltip>
          </div>

          {/* 行内轻量输入 */}
          <div className="flex items-center gap-1">
            <input
              type="text"
              placeholder="输入城市回车"
              value={newCity}
              onChange={(e) => setNewCity(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleAddCity()
              }}
              className="h-6 w-28 rounded-md border border-border bg-background px-2 text-[11px] focus:border-emerald-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={handleAddCity}
              className="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-600 text-white hover:bg-emerald-500 transition-all shrink-0 cursor-pointer"
            >
              <Plus className="h-3 w-3" />
            </button>
          </div>
        </div>

        {/* 城市 Pills */}
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {cities.map((c) => (
            <span
              key={c}
              className="inline-flex items-center gap-1 rounded-md bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20 px-2 py-0.5 text-xs font-medium"
            >
              <span>{c}</span>
              <button
                type="button"
                onClick={() => onCitiesChange(cities.filter((x) => x !== c))}
                className="text-emerald-700/60 hover:text-emerald-900 dark:text-emerald-300/60 dark:hover:text-emerald-100 cursor-pointer"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
        </div>
      </div>

      {/* 3. 学历正反双向过滤 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {/* 目标学历 */}
        <div className="rounded-xl border border-border/60 bg-background/60 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
              <GraduationCap className="h-3.5 w-3.5 text-sky-500" />
              <span>要求的学历 (白名单)</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" className="text-muted-foreground hover:text-foreground">
                    <Info className="h-3 w-3 text-zinc-400" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2">
                  符合任一目标学历的岗位均可放行；留空代表不限学历。
                </TooltipContent>
              </Tooltip>
            </div>

            <div className="flex items-center gap-1">
              <input
                type="text"
                placeholder="加学历"
                value={newEduReq}
                onChange={(e) => setNewEduReq(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleAddEduReq()
                }}
                className="h-6 w-20 rounded-md border border-border bg-background px-1.5 text-[11px] focus:border-sky-500 focus:outline-none"
              />
              <button
                type="button"
                onClick={handleAddEduReq}
                className="flex h-6 w-6 items-center justify-center rounded-md bg-sky-600 text-white hover:bg-sky-500 transition-all shrink-0 cursor-pointer"
              >
                <Plus className="h-3 w-3" />
              </button>
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5 min-h-[24px]">
            {educationRequire.length === 0 ? (
              <span className="text-[11px] text-muted-foreground/70">默认不限学历要求</span>
            ) : (
              educationRequire.map((e) => (
                <span
                  key={e}
                  className="inline-flex items-center gap-1 rounded-md bg-sky-500/10 text-sky-700 dark:text-sky-300 border border-sky-500/20 px-2 py-0.5 text-xs font-medium"
                >
                  <span>{e}</span>
                  <button
                    type="button"
                    onClick={() => onEducationRequireChange(educationRequire.filter((x) => x !== e))}
                    className="text-sky-700/60 hover:text-sky-900 cursor-pointer"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </span>
              ))
            )}
          </div>
        </div>

        {/* 一票否决学历 */}
        <div className="rounded-xl border border-border/60 bg-background/60 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
              <GraduationCap className="h-3.5 w-3.5 text-rose-500" />
              <span>否决学历 (黑名单)</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" className="text-muted-foreground hover:text-foreground">
                    <Info className="h-3 w-3 text-zinc-400" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2">
                  岗位明确要求这些学历时将一票淘汰。
                </TooltipContent>
              </Tooltip>
            </div>

            <div className="flex items-center gap-1">
              <input
                type="text"
                placeholder="加学历"
                value={newEduEx}
                onChange={(e) => setNewEduEx(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleAddEduEx()
                }}
                className="h-6 w-20 rounded-md border border-border bg-background px-1.5 text-[11px] focus:border-rose-500 focus:outline-none"
              />
              <button
                type="button"
                onClick={handleAddEduEx}
                className="flex h-6 w-6 items-center justify-center rounded-md bg-rose-600 text-white hover:bg-rose-500 transition-all shrink-0 cursor-pointer"
              >
                <Plus className="h-3 w-3" />
              </button>
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5 min-h-[24px]">
            {educationExclude.length === 0 ? (
              <span className="text-[11px] text-muted-foreground/70">暂无一票否决学历</span>
            ) : (
              educationExclude.map((e) => (
                <span
                  key={e}
                  className="inline-flex items-center gap-1 rounded-md bg-rose-500/10 text-rose-700 dark:text-rose-300 border border-rose-500/20 px-2 py-0.5 text-xs font-medium"
                >
                  <span>{e}</span>
                  <button
                    type="button"
                    onClick={() => onEducationExcludeChange(educationExclude.filter((x) => x !== e))}
                    className="text-rose-700/60 hover:text-rose-900 cursor-pointer"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </span>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
