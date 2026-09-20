"use client"

import { cn } from "@/lib/utils"
import { LIEPIN_SALARY_MIN_K, LIEPIN_SALARY_MONTHS } from "@/lib/liepin-options"

/**
 * 猎聘期望薪资选择器
 * 三个下拉：min月薪 - max月薪 × 月数
 * 自动计算期望年薪 = min*k*月数/10000 万 ~ max*k*月数/10000 万
 */

interface LiepinSalarySelectorProps {
  salaryMin: string   // e.g. "15k"
  salaryMax: string   // e.g. "25k"
  salaryMonths: number // e.g. 14
  onMinChange: (v: string) => void
  onMaxChange: (v: string) => void
  onMonthsChange: (v: number) => void
}

export function LiepinSalarySelector({
  salaryMin, salaryMax, salaryMonths,
  onMinChange, onMaxChange, onMonthsChange,
}: LiepinSalarySelectorProps) {
  const minK = salaryMin ? parseInt(salaryMin.replace("k", "")) : 0
  const maxK = salaryMax ? parseInt(salaryMax.replace("k", "")) : 0
  const months = salaryMonths || 12

  // Max salary options: all values > current min
  const maxOptions = LIEPIN_SALARY_MIN_K.filter((k) => minK > 0 && k > minK)

  // Annual salary calculation: k values are in thousands of yuan
  // e.g. minK=15 means 15,000 yuan/month → 15000 * 14 / 10000 = 21.0万
  const annualMin = minK > 0 ? ((minK * 1000 * months) / 10000).toFixed(1) : "—"
  const annualMax = maxK > 0 ? ((maxK * 1000 * months) / 10000).toFixed(1) : "—"
  const hasAnnual = minK > 0 && maxK > 0

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {/* Min salary dropdown */}
        <select
          value={salaryMin || ""}
          onChange={(e) => {
            onMinChange(e.target.value)
            // If max < new min, reset max
            const newMin = parseInt(e.target.value.replace("k", ""))
            if (maxK > 0 && maxK <= newMin) onMaxChange("")
          }}
          className={cn(
            "flex-1 h-[40px] rounded-md border bg-background px-3 text-sm transition-colors",
            "hover:border-[#FF6B00] focus:outline-none focus:border-[#FF6B00]",
            salaryMin ? "text-gray-800" : "text-gray-400"
          )}
        >
          <option value="" className="text-gray-400">月薪</option>
          {LIEPIN_SALARY_MIN_K.map((k) => (
            <option key={k} value={`${k}k`}>{k}k</option>
          ))}
        </select>

        <span className="text-gray-400 text-lg">-</span>

        {/* Max salary dropdown */}
        <select
          value={salaryMax || ""}
          onChange={(e) => onMaxChange(e.target.value)}
          disabled={!salaryMin}
          className={cn(
            "flex-1 h-[40px] rounded-md border bg-background px-3 text-sm transition-colors",
            "hover:border-[#FF6B00] focus:outline-none focus:border-[#FF6B00]",
            salaryMax ? "text-gray-800" : "text-gray-400",
            !salaryMin && "opacity-50 cursor-not-allowed"
          )}
        >
          <option value="" className="text-gray-400">月薪</option>
          {maxOptions.map((k) => (
            <option key={k} value={`${k}k`}>{k}k</option>
          ))}
        </select>

        <span className="text-gray-400 text-lg">×</span>

        {/* Months dropdown */}
        <select
          value={salaryMonths ? `${salaryMonths}个月` : ""}
          onChange={(e) => {
            const v = e.target.value
            onMonthsChange(parseInt(v.replace("个月", "")))
          }}
          className={cn(
            "w-[120px] h-[40px] rounded-md border bg-background px-3 text-sm transition-colors",
            "hover:border-[#FF6B00] focus:outline-none focus:border-[#FF6B00]",
            salaryMonths ? "text-gray-800" : "text-gray-400"
          )}
        >
          <option value="" className="text-gray-400">月数</option>
          {LIEPIN_SALARY_MONTHS.map((m) => (
            <option key={m} value={`${m}个月`}>{m}个月</option>
          ))}
        </select>
      </div>

      {/* Annual salary display */}
      {hasAnnual && (
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <span>🧮</span>
          <span>期望年薪：<span className="text-[#FF6B00] font-medium">{annualMin}万 - {annualMax}万</span></span>
        </div>
      )}
    </div>
  )
}
