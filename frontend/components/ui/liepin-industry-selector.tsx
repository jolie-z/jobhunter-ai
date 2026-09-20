"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { cn } from "@/lib/utils"
import {
  LIEPIN_INDUSTRIES,
  type LiepinIndustryCategory,
} from "@/lib/liepin-options"

const DEFAULT_MAX_SELECT = 3
const PRIMARY_COLOR = "#FF6B00"

interface LiepinIndustrySelectorProps {
  value: string[]
  onChange: (value: string[]) => void
  placeholder?: string
  maxSelect?: number
}

export function LiepinIndustrySelector({
  value,
  onChange,
  placeholder = "请选择行业",
  maxSelect = DEFAULT_MAX_SELECT,
}: LiepinIndustrySelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeCategory, setActiveCategory] = useState<string>(
    LIEPIN_INDUSTRIES[0].name,
  )
  const [draft, setDraft] = useState<string[]>(value)
  const [search, setSearch] = useState("")
  const [isFocused, setIsFocused] = useState(false)

  const triggerRef = useRef<HTMLInputElement>(null)
  const modalRef = useRef<HTMLDivElement>(null)

  // Sync draft when modal opens
  useEffect(() => {
    if (isOpen) {
      setDraft(Array.isArray(value) ? [...value] : [])
      setSearch("")
      setActiveCategory(LIEPIN_INDUSTRIES[0].name)
    }
  }, [isOpen, value])

  // Click outside to close (without confirming)
  useEffect(() => {
    if (!isOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (
        modalRef.current &&
        !modalRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false)
      }
    }
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", handleClickOutside)
    }, 0)
    return () => {
      clearTimeout(timer)
      document.removeEventListener("mousedown", handleClickOutside)
    }
  }, [isOpen])

  // 计算每个大类下已选中的子项数量（供左侧红点角标渲染）
  const categorySelectedCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const cat of LIEPIN_INDUSTRIES) {
      if (cat.name === "全部行业") {
        counts[cat.name] = draft.includes("全部行业") ? 1 : 0
      } else {
        const subNames = new Set(cat.subcategories.map((s) => s.name))
        let c = 0
        if (draft.includes(cat.name)) c += 1
        for (const item of draft) {
          if (subNames.has(item)) {
            c += 1
          }
        }
        counts[cat.name] = c
      }
    }
    return counts
  }, [draft])

  // Search results: filter sub-industries across ALL categories
  const searchResults = useMemo(() => {
    const kw = search.trim().toLowerCase()
    if (!kw) return null
    const results: { category: string; items: string[] }[] = []
    for (const cat of LIEPIN_INDUSTRIES) {
      const matched = cat.subcategories.filter((sub) =>
        sub.name.toLowerCase().includes(kw),
      )
      if (matched.length > 0) {
        results.push({ category: cat.name, items: matched.map((m) => m.name) })
      }
    }
    return results
  }, [search])

  // Current category object
  const currentCategory = useMemo<LiepinIndustryCategory | undefined>(
    () => LIEPIN_INDUSTRIES.find((c) => c.name === activeCategory),
    [activeCategory],
  )

  const isAtMax = draft.length >= maxSelect

  const toggleItem = (name: string) => {
    setDraft((prev) => {
      if (prev.includes(name)) {
        return prev.filter((n) => n !== name)
      }
      if (prev.length >= maxSelect) return prev
      return [...prev, name]
    })
  }

  const handleConfirm = () => {
    onChange(draft)
    setIsOpen(false)
  }

  const handleClose = () => {
    setIsOpen(false)
  }

  const displayText = Array.isArray(value) && value.length > 0 ? value.join("，") : ""

  return (
    <>
      {/* Trigger input */}
      <div className="relative">
        <input
          ref={triggerRef}
          type="text"
          readOnly
          value={displayText}
          placeholder={placeholder}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          onClick={() => setIsOpen(true)}
          className={cn(
            "w-full cursor-pointer rounded border px-3 py-2 text-sm outline-none transition-colors",
            "placeholder:text-gray-400",
            isFocused || isOpen
              ? "border-[#FF6B00] ring-1 ring-[#FF6B00]/30"
              : "border-gray-300 hover:border-gray-400",
          )}
          style={
            isFocused || isOpen
              ? { borderColor: PRIMARY_COLOR }
              : undefined
          }
        />
      </div>

      {/* Modal overlay */}
      {isOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/45 backdrop-blur-[1px]">
          <div
            ref={modalRef}
            className="flex flex-col rounded-xl bg-white shadow-2xl overflow-hidden border border-gray-100"
            style={{ width: 840, height: 560 }}
          >
            {/* Header: 标题 + 居中搜索框 + 关闭按钮 */}
            <div className="flex items-center justify-between border-b border-gray-100 px-6 py-3.5 bg-white">
              <h3 className="text-base font-bold text-gray-900 shrink-0">
                请选择行业
              </h3>

              {/* 搜索框 */}
              <div className="relative w-80 max-w-sm">
                <svg
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="请输入行业关键词"
                  className="w-full rounded-lg bg-[#F4F5F7] py-1.5 pl-9 pr-3 text-sm outline-none transition-all border border-transparent focus:border-[#FF6B00] focus:bg-white text-gray-800 placeholder:text-gray-400"
                />
              </div>

              <button
                onClick={handleClose}
                className="flex h-8 w-8 items-center justify-center rounded-full text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
                title="关闭"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                >
                  <line x1="1" y1="1" x2="13" y2="13" />
                  <line x1="13" y1="1" x2="1" y2="13" />
                </svg>
              </button>
            </div>

            {/* Body */}
            <div className="flex min-h-0 flex-1">
              {/* Left column: category list with Red Counter Badges */}
              <div className="w-[190px] flex-shrink-0 overflow-y-auto border-r border-gray-100 bg-white py-2 px-2 space-y-1">
                {LIEPIN_INDUSTRIES.map((cat) => {
                  const isActive = activeCategory === cat.name && !search.trim()
                  const selectedCount = categorySelectedCounts[cat.name] || 0
                  return (
                    <button
                      key={cat.code}
                      onClick={() => {
                        setActiveCategory(cat.name)
                        setSearch("")
                      }}
                      className={cn(
                        "flex items-center justify-between w-full px-3.5 py-2.5 text-left text-sm rounded-lg transition-colors cursor-pointer",
                        isActive
                          ? "bg-[#F4F5F7] font-bold text-gray-900"
                          : "text-gray-700 hover:bg-gray-100/70 font-normal",
                      )}
                    >
                      <span className="truncate">{cat.name}</span>
                      {selectedCount > 0 && (
                        <span className="flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[11px] font-bold text-white bg-[#E02020] rounded-full shrink-0 shadow-xs ml-1.5">
                          {selectedCount}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>

              {/* Right column: sub-industries chips or search results */}
              <div className="flex-1 overflow-y-auto p-6 bg-white">
                {searchResults !== null ? (
                  /* Search results view */
                  searchResults.length === 0 ? (
                    <div className="flex h-full items-center justify-center text-sm text-gray-400">
                      未找到相关行业，请尝试其他关键词
                    </div>
                  ) : (
                    <div className="space-y-5">
                      {searchResults.map((group) => (
                        <div key={group.category}>
                          <div className="mb-2.5 text-xs font-semibold text-gray-400">
                            {group.category}
                          </div>
                          <div className="flex flex-wrap gap-2.5">
                            {group.items.map((name) => {
                              const selected = draft.includes(name)
                              const disabled = isAtMax && !selected
                              return (
                                <button
                                  key={name}
                                  disabled={disabled}
                                  onClick={() => toggleItem(name)}
                                  className={cn(
                                    "rounded-lg px-4 py-2 text-sm transition-all cursor-pointer",
                                    selected
                                      ? "border border-[#FF6B00] bg-white text-[#FF6B00] font-medium shadow-xs"
                                      : disabled
                                        ? "cursor-not-allowed bg-[#F4F5F7] text-gray-300"
                                        : "bg-[#F4F5F7] text-[#333333] hover:bg-gray-200/80 hover:text-gray-900 border border-transparent",
                                  )}
                                >
                                  {name}
                                </button>
                              )
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  )
                ) : currentCategory &&
                  currentCategory.name === "全部行业" ? (
                  /* "全部行业" standalone option */
                  <div className="flex flex-wrap gap-2.5">
                    {(() => {
                      const name = "全部行业"
                      const selected = draft.includes(name)
                      const disabled = isAtMax && !selected
                      return (
                        <button
                          key={name}
                          disabled={disabled}
                          onClick={() => toggleItem(name)}
                          className={cn(
                            "rounded-lg px-4 py-2 text-sm transition-all cursor-pointer",
                            selected
                              ? "border border-[#FF6B00] bg-white text-[#FF6B00] font-medium shadow-xs"
                              : disabled
                                ? "cursor-not-allowed bg-[#F4F5F7] text-gray-300"
                                : "bg-[#F4F5F7] text-[#333333] hover:bg-gray-200/80 hover:text-gray-900 border border-transparent",
                          )}
                        >
                          {name}
                        </button>
                      )
                    })()}
                  </div>
                ) : currentCategory &&
                  currentCategory.subcategories.length > 0 ? (
                  /* Normal category: show sub-industries chips */
                  <div className="flex flex-wrap gap-2.5">
                    {currentCategory.subcategories.map((sub) => {
                      const selected = draft.includes(sub.name)
                      const disabled = isAtMax && !selected
                      return (
                        <button
                          key={sub.code}
                          disabled={disabled}
                          onClick={() => toggleItem(sub.name)}
                          className={cn(
                            "rounded-lg px-4 py-2 text-sm transition-all cursor-pointer",
                            selected
                              ? "border border-[#FF6B00] bg-white text-[#FF6B00] font-medium shadow-xs"
                              : disabled
                                ? "cursor-not-allowed bg-[#F4F5F7] text-gray-300"
                                : "bg-[#F4F5F7] text-[#333333] hover:bg-gray-200/80 hover:text-gray-900 border border-transparent",
                          )}
                        >
                          {sub.name}
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-gray-400">
                    暂无子行业
                  </div>
                )}
              </div>
            </div>

            {/* Footer: 已选数量 + 已选标签胶囊 + 确认按钮 */}
            <div className="flex items-center justify-between border-t border-gray-100 px-6 py-3.5 bg-white shrink-0">
              <div className="flex items-center gap-3 min-w-0 flex-1 mr-4">
                <span className="text-sm text-gray-600 shrink-0 font-medium">
                  已选（{draft.length}/{maxSelect}）
                </span>
                {/* 选中的标签列表胶囊 */}
                <div className="flex items-center gap-2 overflow-x-auto py-0.5 max-w-[500px] scrollbar-none">
                  {draft.map((name) => (
                    <div
                      key={name}
                      className="inline-flex items-center gap-1.5 rounded-md bg-[#FFF4EC] px-3 py-1 text-sm font-medium text-[#FF6B00] shrink-0 border border-[#FF6B00]/20"
                    >
                      <span>{name}</span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          toggleItem(name)
                        }}
                        className="flex h-3.5 w-3.5 items-center justify-center rounded-full text-[#FF6B00]/80 hover:bg-[#FF6B00]/20 hover:text-[#FF6B00] transition-colors cursor-pointer"
                        title={`移除 ${name}`}
                      >
                        <svg
                          width="9"
                          height="9"
                          viewBox="0 0 10 10"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                        >
                          <line x1="1" y1="1" x2="9" y2="9" />
                          <line x1="9" y1="1" x2="1" y2="9" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              <button
                onClick={handleConfirm}
                className="rounded-full px-8 py-2 text-sm font-medium text-white shadow-sm transition-all hover:opacity-95 active:scale-95 bg-[#FF6B00] shrink-0 cursor-pointer"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

