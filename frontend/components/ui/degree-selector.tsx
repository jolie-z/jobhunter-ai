"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"

interface DegreeSelectorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

// 学历选项（大专~博士），每个有全日制/非全日制二级
const DEGREE_OPTIONS = [
  { label: "大专", sub: ["全日制", "非全日制"] },
  { label: "本科", sub: ["全日制", "非全日制"] },
  { label: "硕士", sub: ["全日制", "非全日制"] },
  { label: "博士", sub: ["全日制", "非全日制"] },
]

export function DegreeSelector({ value, onChange, placeholder = "选择学历/学制类型" }: DegreeSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeDegree, setActiveDegree] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
        setActiveDegree(null)
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside)
    }
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [isOpen])

  const handleSelect = (degree: string, sub: string) => {
    onChange(`${degree}·${sub}`)
    setIsOpen(false)
    setActiveDegree(null)
  }

  return (
    <div className="relative" ref={containerRef}>
      {/* 触发按钮 */}
      <div
        className={cn(
          "flex h-[40px] w-full cursor-pointer items-center rounded-md border border-input bg-background px-3 text-sm ring-offset-background transition-colors",
          "hover:border-[#00beab]",
          isOpen && "border-[#00beab]",
          !value && "text-muted-foreground"
        )}
        onClick={() => setIsOpen(!isOpen)}
      >
        {value || placeholder}
      </div>

      {/* 下拉面板 */}
      {isOpen && (
        <div className="absolute top-full left-0 mt-1 z-50 w-full rounded-lg border bg-white p-2 shadow-lg">
          <div className="flex">
            {/* 左侧：学历列表 */}
            <div className="w-1/2 border-r pr-2">
              {DEGREE_OPTIONS.map((opt) => (
                <button
                  key={opt.label}
                  onClick={() => setActiveDegree(opt.label)}
                  className={cn(
                    "block w-full rounded px-3 py-2 text-left text-sm transition-colors",
                    activeDegree === opt.label
                      ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                      : value.startsWith(opt.label)
                        ? "text-[#00beab]"
                        : "text-gray-700 hover:bg-gray-50"
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {/* 右侧：全日制/非全日制 */}
            <div className="w-1/2 pl-2">
              {activeDegree ? (
                DEGREE_OPTIONS.find((o) => o.label === activeDegree)?.sub.map((sub) => (
                  <button
                    key={sub}
                    onClick={() => handleSelect(activeDegree, sub)}
                    className={cn(
                      "block w-full rounded px-3 py-2 text-left text-sm transition-colors",
                      value === `${activeDegree}·${sub}`
                        ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                        : "text-gray-700 hover:bg-gray-50 hover:text-[#00beab]"
                    )}
                  >
                    {sub}
                  </button>
                ))
              ) : (
                <div className="px-3 py-2 text-xs text-gray-400">请选择学历</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
