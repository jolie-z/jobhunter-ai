"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"
import { salaryOptions } from "@/lib/salary-options"

interface SalarySelectorProps {
  valueMin: string
  valueMax: string
  onChangeMin: (value: string) => void
  onChangeMax: (value: string) => void
}

export function SalarySelector({ valueMin, valueMax, onChangeMin, onChangeMax }: SalarySelectorProps) {
  const [openMin, setOpenMin] = useState(false)
  const [openMax, setOpenMax] = useState(false)
  const minRef = useRef<HTMLDivElement>(null)
  const maxRef = useRef<HTMLDivElement>(null)

  // 点击外部关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (minRef.current && !minRef.current.contains(e.target as Node)) setOpenMin(false)
      if (maxRef.current && !maxRef.current.contains(e.target as Node)) setOpenMax(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  return (
    <div className="flex items-center gap-2">
      {/* 最低薪资 */}
      <div className="relative flex-1" ref={minRef}>
        <div
          className={cn(
            "flex h-10 w-full cursor-pointer items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm",
            "hover:border-[#00beab]",
            openMin && "border-[#00beab] ring-1 ring-[#00beab]/20",
            !valueMin && "text-muted-foreground"
          )}
          onClick={() => { setOpenMin(!openMin); setOpenMax(false) }}
        >
          <span>{valueMin || "最低"}</span>
          <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
        {openMin && (
          <div className="absolute z-50 mt-1 max-h-[240px] w-full overflow-y-auto rounded-md border bg-white shadow-lg">
            {salaryOptions.map((opt) => (
              <button
                key={opt}
                onClick={() => { onChangeMin(opt); setOpenMin(false) }}
                className={cn(
                  "block w-full px-3 py-2 text-left text-sm transition-colors",
                  valueMin === opt
                    ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                    : "text-gray-700 hover:bg-gray-50"
                )}
              >
                {opt}
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
            "hover:border-[#00beab]",
            openMax && "border-[#00beab] ring-1 ring-[#00beab]/20",
            !valueMax && "text-muted-foreground"
          )}
          onClick={() => { setOpenMax(!openMax); setOpenMin(false) }}
        >
          <span>{valueMax || "最高"}</span>
          <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
        {openMax && (
          <div className="absolute z-50 mt-1 max-h-[240px] w-full overflow-y-auto rounded-md border bg-white shadow-lg">
            {salaryOptions.map((opt) => (
              <button
                key={opt}
                onClick={() => { onChangeMax(opt); setOpenMax(false) }}
                className={cn(
                  "block w-full px-3 py-2 text-left text-sm transition-colors",
                  valueMax === opt
                    ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                    : "text-gray-700 hover:bg-gray-50"
                )}
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
