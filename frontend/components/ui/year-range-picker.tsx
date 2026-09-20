"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"

interface YearRangePickerProps {
  startYear: string
  endYear: string
  onChange: (startYear: string, endYear: string) => void
}

const YEAR_START = 2000
const YEAR_END = 2030

// 单个年份选择面板
function YearPanel({
  year,
  onSelect,
  onClose,
}: {
  year: string
  onSelect: (year: string) => void
  onClose: () => void
}) {
  const selectedYear = year ? parseInt(year) : null
  const [pageStart, setPageStart] = useState(() => {
    if (selectedYear) {
      return Math.floor((selectedYear - YEAR_START) / 12) * 12 + YEAR_START
    }
    return YEAR_END - 11
  })

  const pageEnd = Math.min(pageStart + 11, YEAR_END)
  const canPrev = pageStart > YEAR_START
  const canNext = pageEnd < YEAR_END

  const years: number[] = []
  for (let y = pageStart; y <= pageEnd; y++) years.push(y)

  return (
    <div className="w-[220px]">
      {/* 翻页头 */}
      <div className="flex items-center justify-between mb-2 px-1">
        <button
          onClick={() => canPrev && setPageStart(pageStart - 12)}
          className={cn("text-sm px-1.5 py-0.5 rounded", canPrev ? "text-gray-600 hover:text-[#00beab] hover:bg-gray-50" : "text-gray-300 cursor-not-allowed")}
        >
          ‹
        </button>
        <span className="text-xs text-gray-500">{pageStart}-{pageEnd}</span>
        <button
          onClick={() => canNext && setPageStart(pageStart + 12)}
          className={cn("text-sm px-1.5 py-0.5 rounded", canNext ? "text-gray-600 hover:text-[#00beab] hover:bg-gray-50" : "text-gray-300 cursor-not-allowed")}
        >
          ›
        </button>
      </div>
      {/* 年份网格 3列 */}
      <div className="grid grid-cols-3 gap-1">
        {years.map((y) => (
          <button
            key={y}
            onClick={() => {
              onSelect(String(y))
              onClose()
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
    </div>
  )
}

export function YearRangePicker({ startYear, endYear, onChange }: YearRangePickerProps) {
  const [activePanel, setActivePanel] = useState<"start" | "end" | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

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

  return (
    <div className="relative" ref={containerRef}>
      {/* 触发区域 */}
      <div className="flex items-center gap-2">
        <div
          className={cn(
            "flex-1 h-[40px] flex items-center rounded-md border px-3 text-sm transition-colors cursor-pointer",
            startYear ? "border-input text-gray-900" : "border-input text-muted-foreground",
            activePanel === "start" && "border-[#00beab] ring-1 ring-[#00beab]/20"
          )}
          onClick={() => setActivePanel(activePanel === "start" ? null : "start")}
        >
          {startYear || "选择年份"}
        </div>
        <span className="text-gray-400 text-sm shrink-0">至</span>
        <div
          className={cn(
            "flex-1 h-[40px] flex items-center rounded-md border px-3 text-sm transition-colors cursor-pointer",
            endYear ? "border-input text-gray-900" : "border-input text-muted-foreground",
            activePanel === "end" && "border-[#00beab] ring-1 ring-[#00beab]/20"
          )}
          onClick={() => setActivePanel(activePanel === "end" ? null : "end")}
        >
          {endYear || "选择年份"}
        </div>
      </div>

      {/* 开始年份面板 */}
      {activePanel === "start" && (
        <div className="absolute top-full left-0 mt-1 z-50 rounded-lg border bg-white p-4 shadow-lg">
          <YearPanel
            year={startYear}
            onSelect={(y) => onChange(y, endYear)}
            onClose={() => setActivePanel(null)}
          />
        </div>
      )}

      {/* 结束年份面板 */}
      {activePanel === "end" && (
        <div className="absolute top-full right-0 mt-1 z-50 rounded-lg border bg-white p-4 shadow-lg">
          <YearPanel
            year={endYear}
            onSelect={(y) => onChange(startYear, y)}
            onClose={() => setActivePanel(null)}
          />
        </div>
      )}
    </div>
  )
}
