/**
 * 筛选条（移植自 v0 设计 + 复用现有筛选语义）。
 *
 * v0 原型用原生 <select> + Tailwind 样式，这里沿用同一外观，但筛选维度、
 * 选项值与 `JobListView` 原有的中文枚举保持一致（"全部"/"A"/"BOSS直聘"...），
 * 以确保筛选逻辑零改动。共 6 个下拉 + 1 个搜索框。
 */

"use client"

import { Search, ChevronDown, SlidersHorizontal } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { RefreshCw, Plus, Loader2, CheckCircle2 } from "lucide-react"

export interface MacroProgressData {
  totalJobs?: number
  taskType?: string
  currentWave?: number
  totalWaves?: number
  waveName?: string
  waveCurrent?: number
  waveTotal?: number
  statusText?: string
  isWaveDone?: boolean
}

interface FilterOption {
  label: string
  value: string
}

interface FilterSelectProps {
  label: string
  options: FilterOption[]
  value: string
  onChange: (value: string) => void
  width?: string
}

function FilterSelect({ label, options, value, onChange, width = "w-28" }: FilterSelectProps) {
  const isActive = value !== "全部"
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "appearance-none h-8 pl-3 pr-7 text-xs rounded-lg border transition-all cursor-pointer",
          width,
          "focus:outline-none focus:ring-2 focus:ring-blue-500/20",
          isActive
            ? "border-blue-200 bg-blue-50 text-blue-700 font-semibold"
            : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
        )}
      >
        <option value="全部">{label}</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <ChevronDown
        className={cn(
          "absolute right-2 top-1/2 -translate-y-1/2 size-3 pointer-events-none",
          isActive ? "text-blue-500" : "text-slate-400"
        )}
      />
    </div>
  )
}

interface FilterBarProps {
  searchQuery: string
  onSearchChange: (v: string) => void
  statusFilter: string
  onStatusFilterChange: (v: string) => void
  scoreFilter: string
  onScoreFilterChange: (v: string) => void
  eduFilter: string
  onEduFilterChange: (v: string) => void
  expFilter: string
  onExpFilterChange: (v: string) => void
  scaleFilter: string
  onScaleFilterChange: (v: string) => void
  platformFilter: string
  onPlatformFilterChange: (v: string) => void
  dynamicStatuses: string[]
  filteredCount: number
  globalTaskStatus: "idle" | "running" | "completed" | "interrupted"
  macroProgress?: MacroProgressData | null
  isRefreshing: boolean
  refreshed: boolean
  onRefresh: () => void
  onOpenImport: () => void
  sortMode: string
  onSortModeChange: (v: string) => void
}

export function FilterBar({
  searchQuery,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  scoreFilter,
  onScoreFilterChange,
  eduFilter,
  onEduFilterChange,
  expFilter,
  onExpFilterChange,
  scaleFilter,
  onScaleFilterChange,
  platformFilter,
  onPlatformFilterChange,
  dynamicStatuses,
  filteredCount,
  globalTaskStatus,
  macroProgress,
  isRefreshing,
  refreshed,
  onRefresh,
  onOpenImport,
  sortMode,
  onSortModeChange,
}: FilterBarProps) {
  return (
    <div className="border-b border-slate-100 bg-white">
      {/* 第一行：搜索 + 6 个筛选下拉 */}
      <div className="px-6 py-3 flex items-center gap-3 flex-wrap">
        {/* 搜索框 */}
        <div className="relative flex-1 min-w-56 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-slate-400 pointer-events-none" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="搜索职位、公司..."
            className={cn(
              "w-full h-8 pl-9 pr-3 text-xs rounded-lg border border-slate-200 bg-slate-50",
              "placeholder:text-slate-400 text-slate-800",
              "focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 focus:bg-white",
              "transition-all"
            )}
          />
        </div>

        {/* 筛选器分隔 */}
        <div className="flex items-center gap-1.5 text-slate-300 mx-0.5">
          <SlidersHorizontal className="size-3" />
        </div>

        <FilterSelect
          label="排序方式"
          width="w-28"
          value={sortMode}
          onChange={onSortModeChange}
          options={[
            { label: "🕒 按抓取时间", value: "按时间" },
            { label: "⭐ 按评级优先", value: "按评级" },
          ]}
        />
        <FilterSelect
          label="跟进状态"
          width="w-28"
          value={statusFilter}
          onChange={onStatusFilterChange}
          options={dynamicStatuses.map((s) => ({ label: s, value: s }))}
        />
        <FilterSelect
          label="全部评级"
          width="w-28"
          value={scoreFilter}
          onChange={onScoreFilterChange}
          options={[
            { label: "🏆 A级 - 顶级匹配", value: "A" },
            { label: "✅ B级 - 良好", value: "B" },
            { label: "🔵 C级 - 一般", value: "C" },
            { label: "⚠️ D/F级 - 较差", value: "D-F" },
            { label: "📋 未评估", value: "未评估" },
          ]}
        />
        <FilterSelect
          label="全部学历"
          width="w-24"
          value={eduFilter}
          onChange={onEduFilterChange}
          options={[
            { label: "学历不限", value: "学历不限" },
            { label: "本科", value: "本科" },
            { label: "硕士", value: "硕士" },
            { label: "博士", value: "博士" },
          ]}
        />
        <FilterSelect
          label="全部经验"
          width="w-24"
          value={expFilter}
          onChange={onExpFilterChange}
          options={[
            { label: "经验不限", value: "经验不限" },
            { label: "1-3年", value: "1-3年" },
            { label: "3-5年", value: "3-5年" },
            { label: "5-10年", value: "5-10年" },
            { label: "8-10年", value: "8-10年" },
          ]}
        />
        <FilterSelect
          label="全部规模"
          width="w-28"
          value={scaleFilter}
          onChange={onScaleFilterChange}
          options={[
            { label: "0-50人", value: "0-50人" },
            { label: "50-99人", value: "50-99人" },
            { label: "100-499人", value: "100-499人" },
            { label: "500-999人", value: "500-999人" },
            { label: "1000-9999人", value: "1000-9999人" },
          ]}
        />
        <FilterSelect
          label="全部平台"
          width="w-28"
          value={platformFilter}
          onChange={onPlatformFilterChange}
          options={[
            { label: "猎聘", value: "猎聘" },
            { label: "51job", value: "51job" },
            { label: "智联招聘", value: "智联招聘" },
            { label: "BOSS直聘", value: "BOSS直聘" },
            { label: "小红书", value: "小红书" },
            { label: "其他平台", value: "其他" },
          ]}
        />

        {/* 右侧：刷新 + 极速录入 */}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {refreshed && (
            <span className="text-xs text-green-600 font-medium animate-in fade-in slide-in-from-right-2">
              ✅ 数据已同步
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5 h-8 px-3 text-xs"
            onClick={onRefresh}
            disabled={isRefreshing}
          >
            <RefreshCw className={cn("size-3.5", isRefreshing && "animate-spin")} />
            {isRefreshing ? "刷新中..." : "刷新列表"}
          </Button>
          <Button
            size="sm"
            onClick={onOpenImport}
            className="gap-1.5 h-8 px-3 text-xs bg-slate-900 hover:bg-slate-700 text-white rounded-lg"
          >
            <Plus className="size-3.5" />
            极速录入
          </Button>
        </div>
      </div>

      {/* 第二行：计数 + 全局任务状态 */}
      <div className="px-6 pb-3 flex items-center gap-4">
        <div className="text-xs font-medium text-slate-400">
          共 <span className="font-semibold text-slate-700">{filteredCount}</span> 个职位
        </div>
        {globalTaskStatus === "running" && (
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-gradient-to-r from-blue-50/90 to-indigo-50/90 border border-blue-200/80 rounded-lg text-xs shadow-2xs animate-in fade-in">
            <Loader2 className="size-3.5 text-blue-600 animate-spin shrink-0" />
            <span className="font-semibold text-blue-700 shrink-0">
              {macroProgress?.totalJobs ? `批量任务 (共 ${macroProgress.totalJobs} 岗)` : "批量任务处理中"}
            </span>
            <span className="text-blue-300">|</span>
            <span className="text-slate-700 font-medium truncate max-w-[450px]">
              {macroProgress?.statusText || "正在分配波次流水线..."}
            </span>
          </div>
        )}
        {globalTaskStatus === "completed" && (
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-emerald-50 border border-emerald-200 rounded-lg text-xs font-semibold text-emerald-700 shadow-2xs animate-in fade-in">
            <CheckCircle2 className="size-3.5 text-emerald-600 shrink-0" />
            <span>{macroProgress?.totalJobs ? `✅ 批量任务完结 (共 ${macroProgress.totalJobs} 岗全部就绪)` : "✅ 批量任务完结"}</span>
          </div>
        )}
        {globalTaskStatus === "interrupted" && (
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-amber-50 border border-amber-200 rounded-lg text-xs font-semibold text-amber-800 shadow-2xs animate-in fade-in">
            <span>⚠️ 批量任务连接中断，可针对异常岗位点击重试</span>
          </div>
        )}
      </div>
    </div>
  )
}
