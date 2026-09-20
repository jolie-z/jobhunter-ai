"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"

interface DateRangePickerProps {
  startYear: string
  startMonth: string
  endYear: string
  endMonth: string
  onChange: (startYear: string, startMonth: string, endYear: string, endMonth: string) => void
}

const YEAR_START = 2000
const YEAR_END = 2026
const YEARS_PER_PAGE = 12
const MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]

// 单个日期面板（年→月选择）
function DatePanel({
  year,
  month,
  showPresent,
  onSelect,
  onClose,
}: {
  year: string
  month: string
  showPresent?: boolean
  onSelect: (year: string, month: string) => void
  onClose: () => void
}) {
  const [step, setStep] = useState<"year" | "month">("year")
  const selectedYear = year ? parseInt(year) : null
  const [pageStart, setPageStart] = useState(() => {
    if (selectedYear) {
      return Math.floor((selectedYear - YEAR_START) / YEARS_PER_PAGE) * YEARS_PER_PAGE + YEAR_START
    }
    return YEAR_END - YEARS_PER_PAGE + 1
  })

  const pageEnd = Math.min(pageStart + YEARS_PER_PAGE - 1, YEAR_END)
  const canPrev = pageStart > YEAR_START
  const canNext = pageEnd < YEAR_END

  const years: number[] = []
  for (let y = pageStart; y <= pageEnd; y++) years.push(y)

  // "至今" 选项
  const isPresent = showPresent && !year && !month

  return (
    <div className="w-[240px]">
      {step === "year" ? (
        <div>
          {/* 年份翻页头 */}
          <div className="flex items-center justify-between mb-2 px-1">
            <button
              onClick={() => canPrev && setPageStart(pageStart - YEARS_PER_PAGE)}
              className={cn("text-sm px-1.5 py-0.5 rounded", canPrev ? "text-gray-600 hover:text-[#00beab] hover:bg-gray-50" : "text-gray-300 cursor-not-allowed")}
            >
              ‹
            </button>
            <span className="text-xs text-gray-500">{pageStart}-{pageEnd}</span>
            <button
              onClick={() => canNext && setPageStart(pageStart + YEARS_PER_PAGE)}
              className={cn("text-sm px-1.5 py-0.5 rounded", canNext ? "text-gray-600 hover:text-[#00beab] hover:bg-gray-50" : "text-gray-300 cursor-not-allowed")}
            >
              ›
            </button>
          </div>
          {/* 年份网格 2列 */}
          <div className="grid grid-cols-2 gap-1">
            {years.map((y) => (
              <button
                key={y}
                onClick={() => {
                  setStep("month")
                  // 暂存选中年份，等月份选完再回调
                  onSelect(String(y), "")
                }}
                className={cn(
                  "rounded py-[7px] text-[13px] transition-colors",
                  selectedYear === y
                    ? "bg-[#00beab] text-white font-medium"
                    : "text-gray-700 hover:bg-[#00beab]/10 hover:text-[#00beab]"
                )}
              >
                {y}
              </button>
            ))}
          </div>
          {/* 至今选项（仅结束时间） */}
          {showPresent && (
            <button
              onClick={() => {
                onSelect("", "")
                onClose()
              }}
              className={cn(
                "mt-2 w-full rounded py-[7px] text-[13px] transition-colors border",
                isPresent
                  ? "bg-[#00beab] text-white font-medium border-[#00beab]"
                  : "text-gray-700 border-gray-200 hover:border-[#00beab] hover:text-[#00beab]"
              )}
            >
              至今
            </button>
          )}
        </div>
      ) : (
        <div>
          {/* 月份选择头 */}
          <div className="flex items-center mb-2 px-1">
            <button
              onClick={() => setStep("year")}
              className="text-[13px] text-[#00beab] hover:text-[#00a99a] font-medium flex items-center gap-0.5"
            >
              ‹ {selectedYear || parseInt(year)}年
            </button>
          </div>
          {/* 月份网格 3列 */}
          <div className="grid grid-cols-3 gap-1">
            {MONTHS.map((m, idx) => {
              const monthVal = String(idx + 1)
              const isSelected = month === monthVal
              return (
                <button
                  key={m}
                  onClick={() => {
                    onSelect(String(selectedYear || parseInt(year)), monthVal)
                    onClose()
                  }}
                  className={cn(
                    "rounded py-[7px] text-[13px] transition-colors",
                    isSelected
                      ? "bg-[#00beab] text-white font-medium"
                      : "text-gray-700 hover:bg-[#00beab]/10 hover:text-[#00beab]"
                  )}
                >
                  {m}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export function DateRangePicker({ startYear, startMonth, endYear, endMonth, onChange }: DateRangePickerProps) {
  const [activePanel, setActivePanel] = useState<"start" | "end" | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // 点击外部关闭
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setActivePanel(null)
      }
    }
    if (activePanel) {
      document.addEventListener("mousedown", handleClickOutside)
    }
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [activePanel])

  const formatDisplay = (y: string, m: string) => {
    if (!y) return ""
    return m ? `${y}-${m.padStart(2, "0")}` : y
  }

  const startText = formatDisplay(startYear, startMonth)
  const endText = endYear === "" && endMonth === "" && activePanel !== "end"
    ? "至今"
    : formatDisplay(endYear, endMonth)

  // 判断结束时间是否为"至今"
  const isEndPresent = !endYear && !endMonth

  return (
    <div className="relative" ref={containerRef}>
      {/* 触发区域：两个独立可点击的字段 */}
      <div className="flex items-center gap-2">
        <div
          className={cn(
            "flex-1 h-[40px] flex items-center rounded-md border px-3 text-sm transition-colors cursor-pointer",
            startText ? "border-input text-gray-900" : "border-input text-muted-foreground",
            activePanel === "start" && "border-[#00beab] ring-1 ring-[#00beab]/20"
          )}
          onClick={() => setActivePanel(activePanel === "start" ? null : "start")}
        >
          {startText || "开始时间"}
        </div>
        <span className="text-gray-400 text-sm shrink-0">至</span>
        <div
          className={cn(
            "flex-1 h-[40px] flex items-center rounded-md border px-3 text-sm transition-colors cursor-pointer",
            (endText || isEndPresent) ? "border-input text-gray-900" : "border-input text-muted-foreground",
            activePanel === "end" && "border-[#00beab] ring-1 ring-[#00beab]/20"
          )}
          onClick={() => setActivePanel(activePanel === "end" ? null : "end")}
        >
          {isEndPresent ? "至今" : (endText || "结束时间")}
        </div>
      </div>

      {/* 开始时间下拉面板 */}
      {activePanel === "start" && (
        <div className="absolute top-full left-0 mt-1 z-50 rounded-lg border bg-white p-4 shadow-lg">
          <DatePanel
            year={startYear}
            month={startMonth}
            onSelect={(y, m) => onChange(y, m, endYear, endMonth)}
            onClose={() => setActivePanel(null)}
          />
        </div>
      )}

      {/* 结束时间下拉面板 */}
      {activePanel === "end" && (
        <div className="absolute top-full right-0 mt-1 z-50 rounded-lg border bg-white p-4 shadow-lg">
          <DatePanel
            year={endYear}
            month={endMonth}
            showPresent
            onSelect={(y, m) => onChange(startYear, startMonth, y, m)}
            onClose={() => setActivePanel(null)}
          />
        </div>
      )}
    </div>
  )
}
