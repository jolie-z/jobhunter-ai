"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { cn } from "@/lib/utils"
import {
  LIEPIN_JOB_CATEGORIES,
  type LiepinJobCategory,
} from "@/lib/liepin-options"

interface LiepinJobSelectorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

const PRIMARY = "#FF6B00"

export function LiepinJobSelector({
  value,
  onChange,
  placeholder = "请选择职位类别",
}: LiepinJobSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const modalRef = useRef<HTMLDivElement>(null)

  // Default to first category when modal opens
  useEffect(() => {
    if (isOpen && !activeCategory) {
      setActiveCategory(LIEPIN_JOB_CATEGORIES[0]?.name ?? null)
    }
  }, [isOpen, activeCategory])

  // Search: filter ALL jobs across ALL categories, grouped by subcategory name
  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const kw = search.trim().toLowerCase()
    const grouped: Record<string, { jobName: string; categoryName: string }[]> = {}

    for (const cat of LIEPIN_JOB_CATEGORIES) {
      for (const sub of cat.subcategories) {
        for (const job of sub.jobs) {
          if (job.name.toLowerCase().includes(kw)) {
            const key = sub.name
            if (!grouped[key]) grouped[key] = []
            grouped[key].push({ jobName: job.name, categoryName: cat.name })
          }
        }
      }
    }

    return grouped
  }, [search])

  // Active category data
  const activeCategoryData = useMemo(() => {
    if (!activeCategory) return null
    return LIEPIN_JOB_CATEGORIES.find((c) => c.name === activeCategory) ?? null
  }, [activeCategory])

  const handleSelect = (jobName: string) => {
    onChange(jobName)
    handleClose()
  }

  const handleClose = () => {
    setIsOpen(false)
    setActiveCategory(null)
    setSearch("")
  }

  // Click outside modal to close
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
      handleClose()
    }
  }

  return (
    <div className="relative">
      {/* Trigger input */}
      <div
        className={cn(
          "flex h-10 w-full cursor-pointer items-center rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background",
          "hover:border-[#FF6B00] focus-within:border-[#FF6B00]",
          !value && "text-muted-foreground",
        )}
        onClick={() => setIsOpen(true)}
      >
        {value || placeholder}
      </div>

      {/* Modal overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center"
          onClick={handleBackdropClick}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/50" />

          {/* Modal panel */}
          <div
            ref={modalRef}
            className="relative z-10 flex w-[800px] flex-col rounded-lg bg-white shadow-xl"
            style={{ height: 530 }}
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="text-base font-medium text-gray-900">
                请选择职位类别
              </h3>
              <button
                onClick={handleClose}
                className="text-lg leading-none text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>

            {/* Search bar */}
            <div className="px-5 pt-3 pb-2">
              <div className="flex items-center rounded-md border border-gray-200 px-3 py-2 focus-within:border-[#FF6B00]">
                <svg
                  className="mr-2 h-4 w-4 text-gray-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                  />
                </svg>
                <input
                  type="text"
                  placeholder="搜索职位"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="flex-1 text-sm outline-none placeholder:text-gray-400"
                  autoFocus
                />
              </div>
            </div>

            {/* Body */}
            {searchResults ? (
              /* Search results view */
              <div className="flex-1 overflow-y-auto px-5 py-3">
                {Object.keys(searchResults).length === 0 ? (
                  <div className="py-8 text-center text-sm text-gray-400">
                    未找到匹配的职位
                  </div>
                ) : (
                  Object.entries(searchResults).map(([subName, jobs]) => (
                    <div key={subName} className="mb-4">
                      <div className="mb-2 text-sm font-medium text-gray-500">
                        {subName}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {jobs.map((item, idx) => (
                          <button
                            key={`${subName}__${item.jobName}__${idx}`}
                            onClick={() => handleSelect(item.jobName)}
                            className={cn(
                              "rounded border px-3 py-1 text-sm transition-colors",
                              value === item.jobName
                                ? "border-[#FF6B00] bg-[#FF6B00] text-white font-medium"
                                : "border-gray-200 text-gray-700 hover:border-[#FF6B00] hover:text-[#FF6B00]",
                            )}
                          >
                            {item.jobName}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            ) : (
              /* Two-column browse view */
              <div className="flex flex-1 overflow-hidden">
                {/* Left column: root categories */}
                <div className="w-[200px] overflow-y-auto border-r bg-gray-50/50">
                  {LIEPIN_JOB_CATEGORIES.map((cat) => (
                    <button
                      key={cat.code}
                      onClick={() => setActiveCategory(cat.name)}
                      className={cn(
                        "block w-full border-l-2 px-4 py-[9px] text-left text-[13px] transition-colors",
                        activeCategory === cat.name
                          ? "border-l-[#FF6B00] bg-white text-[#FF6B00] font-medium"
                          : "border-l-transparent text-gray-700 hover:bg-gray-100",
                      )}
                    >
                      {cat.name}
                    </button>
                  ))}
                </div>

                {/* Right column: subcategories + job tags */}
                <div className="flex-1 overflow-y-auto px-4 py-3">
                  {activeCategoryData ? (
                    activeCategoryData.subcategories.map((sub) => (
                      <div key={sub.code} className="mb-4">
                        <div className="mb-2 text-sm font-medium text-gray-500">
                          {sub.name}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {sub.jobs.map((job) => (
                            <button
                              key={job.code}
                              onClick={() => handleSelect(job.name)}
                              className={cn(
                                "rounded border px-3 py-1 text-sm transition-colors",
                                value === job.name
                                  ? "border-[#FF6B00] bg-[#FF6B00] text-white font-medium"
                                  : "border-gray-200 text-gray-700 hover:border-[#FF6B00] hover:text-[#FF6B00]",
                              )}
                            >
                              {job.name}
                            </button>
                          ))}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="py-8 text-center text-sm text-gray-400">
                      请选择职位类别
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
