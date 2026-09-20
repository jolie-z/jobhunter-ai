"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { cn } from "@/lib/utils"
import {
  LIEPIN_CERT_CATEGORIES,
  type LiepinCertCategory,
} from "@/lib/liepin-options"

const MAX_SELECT = 20
const PRIMARY = "#FF6B00"

interface LiepinCertSelectorProps {
  value: string[]
  onChange: (value: string[]) => void
  placeholder?: string
  /** Externally control modal open state */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Hide the built-in trigger input (when parent provides its own trigger) */
  hideTrigger?: boolean
}

export function LiepinCertSelector({
  value,
  onChange,
  placeholder = "请选择资格证书",
  open: externalOpen,
  onOpenChange,
  hideTrigger = false,
}: LiepinCertSelectorProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const isOpen = externalOpen !== undefined ? externalOpen : internalOpen
  const setIsOpen = (v: boolean) => {
    if (onOpenChange) onOpenChange(v)
    else setInternalOpen(v)
  }
  const [activeCategory, setActiveCategory] = useState<string>(
    LIEPIN_CERT_CATEGORIES[0].name,
  )
  const [draft, setDraft] = useState<string[]>(value)
  const [search, setSearch] = useState("")
  const [isFocused, setIsFocused] = useState(false)

  const modalRef = useRef<HTMLDivElement>(null)

  // Sync draft when modal opens
  useEffect(() => {
    if (isOpen) {
      setDraft([...value])
      setSearch("")
      setActiveCategory(LIEPIN_CERT_CATEGORIES[0].name)
    }
  }, [isOpen, value])

  // Click outside to close
  useEffect(() => {
    if (!isOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
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

  // Search results across ALL categories (deduplicated)
  const searchResults = useMemo(() => {
    const kw = search.trim().toLowerCase()
    if (!kw) return null
    const seen = new Set<string>()
    const results: { category: string; items: string[] }[] = []
    for (const cat of LIEPIN_CERT_CATEGORIES) {
      if (cat.name === "推荐") continue // skip 推荐 in search to avoid duplicates
      const matched = cat.certs.filter(
        (c) => c.toLowerCase().includes(kw) && !seen.has(c),
      )
      if (matched.length > 0) {
        matched.forEach((m) => seen.add(m))
        results.push({ category: cat.name, items: matched })
      }
    }
    return results
  }, [search])

  // Current category
  const currentCategory = useMemo<LiepinCertCategory | undefined>(
    () => LIEPIN_CERT_CATEGORIES.find((c) => c.name === activeCategory),
    [activeCategory],
  )

  const isAtMax = draft.length >= MAX_SELECT

  const toggleItem = (name: string) => {
    setDraft((prev) => {
      if (prev.includes(name)) {
        return prev.filter((n) => n !== name)
      }
      if (prev.length >= MAX_SELECT) return prev
      return [...prev, name]
    })
  }

  const removeItem = (name: string) => {
    setDraft((prev) => prev.filter((n) => n !== name))
  }

  const handleConfirm = () => {
    onChange(draft)
    setIsOpen(false)
  }

  const displayText = value.length > 0 ? value.join("、") : ""

  // Cert tag button renderer
  const renderCertTag = (name: string) => {
    const selected = draft.includes(name)
    const disabled = isAtMax && !selected
    return (
      <button
        key={name}
        disabled={disabled}
        onClick={() => toggleItem(name)}
        className={cn(
          "rounded border px-3 py-1.5 text-[13px] leading-5 transition-colors",
          selected
            ? "border-[#FF6B00] bg-[#FFF7F0] text-[#FF6B00]"
            : disabled
              ? "cursor-not-allowed border-gray-200 bg-gray-50 text-gray-300"
              : "border-gray-200 bg-white text-gray-700 hover:border-[#FF6B00] hover:text-[#FF6B00]",
        )}
      >
        {name}
      </button>
    )
  }

  return (
    <>
      {/* Trigger input (hidden when parent provides its own trigger) */}
      {!hideTrigger && (
        <div className="relative">
          <input
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
          />
        </div>
      )}

      {/* Modal overlay */}
      {isOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40">
          <div
            ref={modalRef}
            className="flex flex-col rounded-lg bg-white shadow-2xl"
            style={{ width: 800, maxHeight: 560 }}
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div className="flex items-center gap-4">
                <h3 className="text-base font-semibold text-gray-900">
                  请选择资格证书
                </h3>
                <span className="text-sm text-gray-500">
                  已选（
                  <span className="font-medium" style={{ color: PRIMARY }}>
                    {draft.length}
                  </span>
                  /{MAX_SELECT}）
                </span>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="flex h-7 w-7 items-center justify-center rounded text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
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

            {/* Search bar */}
            <div className="border-b border-gray-100 px-6 py-3">
              <div className="relative">
                <svg
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
                  width="14"
                  height="14"
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
                  placeholder="请输入证书名称搜索"
                  className="w-full rounded border border-gray-200 py-1.5 pl-9 pr-3 text-sm outline-none transition-colors focus:border-[#FF6B00]"
                />
              </div>
            </div>

            {/* Selected chips bar */}
            {draft.length > 0 && (
              <div className="flex flex-wrap gap-1.5 border-b border-gray-100 px-6 py-2.5">
                {draft.map((name) => (
                  <span
                    key={name}
                    className="inline-flex items-center gap-1 rounded bg-[#FFF7F0] px-2 py-0.5 text-xs text-[#FF6B00]"
                  >
                    {name}
                    <button
                      onClick={() => removeItem(name)}
                      className="ml-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full text-[#FF6B00]/60 transition-colors hover:bg-[#FF6B00]/10 hover:text-[#FF6B00]"
                    >
                      <svg
                        width="8"
                        height="8"
                        viewBox="0 0 8 8"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                      >
                        <line x1="1" y1="1" x2="7" y2="7" />
                        <line x1="7" y1="1" x2="1" y2="7" />
                      </svg>
                    </button>
                  </span>
                ))}
              </div>
            )}

            {/* Body */}
            <div className="flex min-h-0 flex-1">
              {/* Left: category list */}
              <div className="w-[160px] flex-shrink-0 overflow-y-auto border-r border-gray-100 bg-gray-50/80 py-1">
                {LIEPIN_CERT_CATEGORIES.map((cat) => {
                  const isActive = activeCategory === cat.name
                  return (
                    <button
                      key={cat.name}
                      onClick={() => {
                        setActiveCategory(cat.name)
                        setSearch("")
                      }}
                      className={cn(
                        "block w-full px-4 py-2 text-left text-[13px] transition-colors",
                        isActive
                          ? "border-l-2 bg-white font-medium"
                          : "border-l-2 border-l-transparent text-gray-600 hover:bg-gray-100",
                      )}
                      style={
                        isActive
                          ? { color: PRIMARY, borderLeftColor: PRIMARY }
                          : undefined
                      }
                    >
                      {cat.name}
                    </button>
                  )
                })}
              </div>

              {/* Right: cert items or search results */}
              <div className="flex-1 overflow-y-auto p-5">
                {searchResults !== null ? (
                  searchResults.length === 0 ? (
                    <div className="flex h-full items-center justify-center text-sm text-gray-400">
                      无匹配证书
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {searchResults.map((group) => (
                        <div key={group.category}>
                          <div className="mb-2 text-xs font-medium text-gray-400">
                            {group.category}
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {group.items.map((name) => renderCertTag(name))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )
                ) : currentCategory ? (
                  <div className="flex flex-wrap gap-2">
                    {currentCategory.certs.map((name) => renderCertTag(name))}
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-gray-400">
                    暂无证书
                  </div>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end border-t border-gray-200 px-6 py-3">
              <button
                onClick={handleConfirm}
                className="rounded px-6 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
                style={{ backgroundColor: PRIMARY }}
              >
                确定
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
