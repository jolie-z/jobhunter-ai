"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"

/**
 * 51job 年月选择器
 * 第一步：选年份（每页12年，可翻页）
 * 第二步：选月份（12个月）
 *
 * value 格式: "YYYY-MM"（如 "2024-04"），与51job存储格式一致
 * 显示格式: "YYYY年MM月"（如 "2024年04月"），方便用户阅读
 */

const YEARS_PER_PAGE = 12
const MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]

interface Job51YearMonthPickerProps {
  value: string // "YYYY-MM" 或 "" 或 "至今"
  onChange: (value: string) => void
  placeholder?: string
  yearRange?: [number, number]
  /** 是否显示"至今"选项（用于结束时间） */
  allowPresent?: boolean
}

function parseValue(value: string): { year: string; month: string } {
  if (!value) return { year: "", month: "" }
  const m = value.match(/^(\d{4})-(\d{1,2})$/)
  if (!m) return { year: "", month: "" }
  return { year: m[1], month: m[2].padStart(2, "0") }
}

function formatDisplay(value: string): string {
  if (value === "至今") return "至今"
  const parsed = parseValue(value)
  if (!parsed.year) return ""
  return `${parsed.year}年${parsed.month}月`
}

export function Job51YearMonthPicker({ value, onChange, placeholder = "请选择", yearRange, allowPresent = false }: Job51YearMonthPickerProps) {
  const currentYear = new Date().getFullYear()
  const YEAR_START = yearRange?.[0] ?? 1960
  const YEAR_END = yearRange?.[1] ?? Math.max(currentYear + 5, 2029)

  const parsed = parseValue(value)
  const selectedYear = parsed.year ? parseInt(parsed.year) : NaN

  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<"year" | "month">("year")
  const [tempYear, setTempYear] = useState("")
  const [pageStart, setPageStart] = useState(() => {
    if (!isNaN(selectedYear)) {
      const base = Math.floor((selectedYear - YEAR_START) / YEARS_PER_PAGE) * YEARS_PER_PAGE + YEAR_START
      return Math.max(YEAR_START, Math.min(base, YEAR_END - YEARS_PER_PAGE + 1))
    }
    return Math.max(YEAR_START, YEAR_END - YEARS_PER_PAGE + 1)
  })

  const containerRef = useRef<HTMLDivElement>(null)

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

  const handleOpen = () => {
    setStep("year")
    setTempYear(parsed.year)
    setOpen(true)
  }

  const handleYearClick = (y: number) => {
    setTempYear(String(y))
    setStep("month")
  }

  const handleMonthClick = (m: number) => {
    const monthStr = String(m).padStart(2, "0")
    onChange(`${tempYear}-${monthStr}`)
    setOpen(false)
    setStep("year")
  }

  const canPrev = pageStart - YEARS_PER_PAGE >= YEAR_START
  const canNext = pageStart + YEARS_PER_PAGE <= YEAR_END
  const pageYears: number[] = []
  for (let i = 0; i < YEARS_PER_PAGE && pageStart + i <= YEAR_END; i++) {
    pageYears.push(pageStart + i)
  }
  const pageEnd = pageYears[pageYears.length - 1]

  return (
    <div className="relative" ref={containerRef}>
      <input
        readOnly
        value={formatDisplay(value)}
        placeholder={placeholder}
        onClick={handleOpen}
        className={cn(
          "w-full h-[40px] rounded-md border bg-background px-3 text-sm cursor-pointer transition-colors",
          "hover:border-[#FF6B00] focus:outline-none",
          open ? "border-[#FF6B00]" : "border-input"
        )}
      />

      {open && (
        <div className="absolute z-[60] top-full mt-1 left-0 bg-white border rounded-lg shadow-lg p-4 w-[240px]">
          {step === "year" && (
            <>
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
              <div className="grid grid-cols-2 gap-1">
                {pageYears.map((y) => (
                  <button
                    key={y}
                    className={cn(
                      "py-[7px] text-[13px] rounded transition-colors",
                      String(y) === String(selectedYear) ? "bg-[#FF6B00] text-white" : "text-gray-700 hover:bg-[#FF6B00]/10"
                    )}
                    onClick={() => handleYearClick(y)}
                  >
                    {y}
                  </button>
                ))}
              </div>
            </>
          )}

          {step === "month" && (
            <>
              <div className="mb-3">
                <button className="text-sm text-gray-500 hover:text-[#FF6B00]" onClick={() => setStep("year")}>
                  ‹ {tempYear}年
                </button>
              </div>
              <div className="grid grid-cols-3 gap-1">
                {MONTHS.map((m, i) => {
                  const monthNum = String(i + 1).padStart(2, "0")
                  const isSelected = parsed.year === tempYear && parsed.month === monthNum
                  return (
                    <button
                      key={m}
                      className={cn(
                        "py-[7px] text-[13px] rounded transition-colors",
                        isSelected ? "bg-[#FF6B00] text-white" : "text-gray-700 hover:bg-[#FF6B00]/10"
                      )}
                      onClick={() => handleMonthClick(i + 1)}
                    >
                      {m}
                    </button>
                  )
                })}
              </div>
              {allowPresent && (
                <button
                  className={cn(
                    "w-full mt-2 py-[7px] text-[13px] rounded border transition-colors",
                    value === "至今" ? "bg-[#FF6B00] text-white border-[#FF6B00]" : "text-gray-600 border-gray-200 hover:border-[#FF6B00] hover:text-[#FF6B00]"
                  )}
                  onClick={() => { onChange("至今"); setOpen(false); setStep("year") }}
                >
                  至今
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
