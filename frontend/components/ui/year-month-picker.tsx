"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"

/**
 * 年月选择器（照搬 BOSS 官网两步选择逻辑）
 * 第一步：选年份（每页显示12年，可前后翻页）
 * 第二步：选月份（12个月，可返回上一步改年）
 *
 * value 格式: "YYYY-MM"（如 "1996-11"）
 */

const YEARS_PER_PAGE = 12
const MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]

interface YearMonthPickerProps {
  value: string                        // "YYYY-MM" 或 ""
  onChange: (value: string) => void
  label?: string                       // 占位文字
  yearRange?: [number, number]         // 可选年份范围，默认 [1960, 当前年]
}

export function YearMonthPicker({ value, onChange, label = "请选择", yearRange }: YearMonthPickerProps) {
  const currentYear = new Date().getFullYear()
  const YEAR_START = yearRange?.[0] ?? 1960
  const YEAR_END = yearRange?.[1] ?? currentYear

  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<"year" | "month">("year")
  const [tempYear, setTempYear] = useState("")

  // 计算初始页：让已选年份落在当前页内
  const selectedYear = value ? parseInt(value.split("-")[0]) : NaN
  const [pageStart, setPageStart] = useState(() => {
    if (!isNaN(selectedYear)) {
      const base = Math.floor((selectedYear - YEAR_START) / YEARS_PER_PAGE) * YEARS_PER_PAGE + YEAR_START
      return Math.max(YEAR_START, Math.min(base, YEAR_END - YEARS_PER_PAGE + 1))
    }
    return Math.max(YEAR_START, YEAR_END - YEARS_PER_PAGE + 1)
  })

  const containerRef = useRef<HTMLDivElement>(null)

  // 点击外部关闭
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setStep("year")
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  // 打开时重置步骤
  const handleOpen = () => {
    setStep("year")
    setTempYear(value ? value.split("-")[0] : "")
    setOpen(true)
  }

  // 选中某年 → 进入月份步骤
  const handleYearClick = (y: number) => {
    setTempYear(String(y))
    setStep("month")
  }

  // 选中某月 → 完成
  const handleMonthClick = (m: number) => {
    const monthStr = String(m).padStart(2, "0")
    onChange(`${tempYear}-${monthStr}`)
    setOpen(false)
    setStep("year")
  }

  // 翻页
  const canPrev = pageStart - YEARS_PER_PAGE >= YEAR_START
  const canNext = pageStart + YEARS_PER_PAGE <= YEAR_END
  const pageYears: number[] = []
  for (let i = 0; i < YEARS_PER_PAGE && pageStart + i <= YEAR_END; i++) {
    pageYears.push(pageStart + i)
  }

  const pageEnd = pageYears[pageYears.length - 1]
  const displayValue = value || ""

  return (
    <div className="relative" ref={containerRef}>
      {/* 触发器 */}
      <input
        readOnly
        value={displayValue}
        placeholder={label}
        className={cn(
          "w-full h-[40px] rounded-md border bg-background px-3 text-sm cursor-pointer transition-colors",
          "hover:border-[#00beab] focus:outline-none",
          open ? "border-[#00beab]" : "border-input"
        )}
        onClick={handleOpen}
      />

      {/* 下拉面板 */}
      {open && (
        <div className="absolute z-50 top-full mt-1 left-0 bg-white border rounded-lg shadow-lg p-4 w-[240px]">

          {/* === 第一步：选年 === */}
          {step === "year" && (
            <>
              {/* 翻页导航 */}
              <div className="flex items-center justify-between mb-3">
                <button
                  disabled={!canPrev}
                  className={cn("px-2 py-1 text-sm", canPrev ? "text-gray-500 hover:text-gray-900" : "text-gray-300 cursor-not-allowed")}
                  onClick={() => setPageStart(Math.max(YEAR_START, pageStart - YEARS_PER_PAGE))}
                >
                  ‹
                </button>
                <span className="text-sm font-medium text-gray-700">
                  {pageStart}-{pageEnd}
                </span>
                <button
                  disabled={!canNext}
                  className={cn("px-2 py-1 text-sm", canNext ? "text-gray-500 hover:text-gray-900" : "text-gray-300 cursor-not-allowed")}
                  onClick={() => setPageStart(Math.min(YEAR_END - YEARS_PER_PAGE + 1, pageStart + YEARS_PER_PAGE))}
                >
                  ›
                </button>
              </div>

              {/* 年份网格（2列） */}
              <div className="grid grid-cols-2 gap-1">
                {pageYears.map(y => (
                  <button
                    key={y}
                    className={cn(
                      "py-[7px] text-[13px] rounded transition-colors",
                      String(y) === String(selectedYear)
                        ? "bg-[#00beab] text-white"
                        : "text-gray-700 hover:bg-[#00beab]/10"
                    )}
                    onClick={() => handleYearClick(y)}
                  >
                    {y}
                  </button>
                ))}
              </div>
            </>
          )}

          {/* === 第二步：选月 === */}
          {step === "month" && (
            <>
              {/* 返回按钮 */}
              <div className="mb-3">
                <button
                  className="text-sm text-gray-500 hover:text-[#00beab]"
                  onClick={() => setStep("year")}
                >
                  ‹ {tempYear}年
                </button>
              </div>

              {/* 月份网格（3列） */}
              <div className="grid grid-cols-3 gap-1">
                {MONTHS.map((m, i) => {
                  const monthNum = String(i + 1).padStart(2, "0")
                  const isSelected = value === `${tempYear}-${monthNum}`
                  return (
                    <button
                      key={m}
                      className={cn(
                        "py-[7px] text-[13px] rounded transition-colors",
                        isSelected
                          ? "bg-[#00beab] text-white"
                          : "text-gray-700 hover:bg-[#00beab]/10"
                      )}
                      onClick={() => handleMonthClick(i + 1)}
                    >
                      {m}
                    </button>
                  )
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
