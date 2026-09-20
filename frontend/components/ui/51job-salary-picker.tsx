"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"
import { JOB51_SALARY_RANGES } from "@/lib/51job-options"

interface Job51SalaryPickerProps {
  minSalary: string
  maxSalary: string
  salaryMonth: number
  onMinChange: (id: string) => void
  onMaxChange: (id: string) => void
  onMonthChange: (month: number) => void
}

const BRAND_COLOR = "#FF6B00"

function getSalaryText(id: string): string {
  const item = JOB51_SALARY_RANGES.find((s) => s.id === id)
  return item ? item.text : ""
}

export function Job51SalaryPicker({
  minSalary,
  maxSalary,
  salaryMonth,
  onMinChange,
  onMaxChange,
  onMonthChange,
}: Job51SalaryPickerProps) {
  const [openMin, setOpenMin] = useState(false)
  const [openMax, setOpenMax] = useState(false)
  const minRef = useRef<HTMLDivElement>(null)
  const maxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (minRef.current && !minRef.current.contains(e.target as Node)) setOpenMin(false)
      if (maxRef.current && !maxRef.current.contains(e.target as Node)) setOpenMax(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  const minText = getSalaryText(minSalary)
  const maxText = getSalaryText(maxSalary)

  return (
    <div className="flex items-center gap-2">
      {/* 最低薪资 */}
      <div className="relative flex-1" ref={minRef}>
        <div
          className={cn(
            "flex h-10 w-full cursor-pointer items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm",
            "hover:border-[#FF6B00]",
            openMin && "border-[#FF6B00] ring-1 ring-[#FF6B00]/20",
            !minSalary && "text-muted-foreground"
          )}
          onClick={() => { setOpenMin(!openMin); setOpenMax(false) }}
        >
          <span>{minText || "最低"}</span>
          <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
        {openMin && (
          <div className="absolute z-50 mt-1 max-h-[240px] w-full overflow-y-auto rounded-md border bg-white shadow-lg">
            {JOB51_SALARY_RANGES.map((opt) => (
              <button
                key={opt.id}
                onClick={() => { onMinChange(opt.id); setOpenMin(false) }}
                className={cn(
                  "block w-full px-3 py-2 text-left text-sm transition-colors",
                  minSalary === opt.id
                    ? "bg-[#FF6B00]/10 text-[#FF6B00] font-medium"
                    : "text-gray-700 hover:bg-gray-50"
                )}
              >
                {opt.text}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 至 */}
      <span className="text-sm text-gray-400 flex-shrink-0">至</span>

      {/* 最高薪资 */}
      <div className="relative flex-1" ref={maxRef}>
        <div
          className={cn(
            "flex h-10 w-full cursor-pointer items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm",
            "hover:border-[#FF6B00]",
            openMax && "border-[#FF6B00] ring-1 ring-[#FF6B00]/20",
            !maxSalary && "text-muted-foreground"
          )}
          onClick={() => { setOpenMax(!openMax); setOpenMin(false) }}
        >
          <span>{maxText || "最高"}</span>
          <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
        {openMax && (
          <div className="absolute z-50 mt-1 max-h-[240px] w-full overflow-y-auto rounded-md border bg-white shadow-lg">
            {JOB51_SALARY_RANGES.map((opt) => (
              <button
                key={opt.id}
                onClick={() => { onMaxChange(opt.id); setOpenMax(false) }}
                className={cn(
                  "block w-full px-3 py-2 text-left text-sm transition-colors",
                  maxSalary === opt.id
                    ? "bg-[#FF6B00]/10 text-[#FF6B00] font-medium"
                    : "text-gray-700 hover:bg-gray-50"
                )}
              >
                {opt.text}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 薪月 */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <input
          type="number"
          min={12}
          max={24}
          value={salaryMonth}
          onChange={(e) => {
            const val = parseInt(e.target.value, 10)
            if (!isNaN(val)) onMonthChange(val)
          }}
          className={cn(
            "h-10 w-16 rounded-md border border-input bg-background px-2 text-center text-sm",
            "focus:outline-none focus:border-[#FF6B00] focus:ring-1 focus:ring-[#FF6B00]/20"
          )}
        />
        <span className="text-sm text-gray-500">薪</span>
      </div>
    </div>
  )
}
