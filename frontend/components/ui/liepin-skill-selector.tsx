"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { cn } from "@/lib/utils"
import { LIEPIN_SKILL_SUGGESTIONS } from "@/lib/liepin-options"

const MAX_SELECT = 10
const PRIMARY = "#FF6B00"

interface LiepinSkillSelectorProps {
  value: string[]
  onChange: (value: string[]) => void
  open?: boolean
  onOpenChange?: (open: boolean) => void
  hideTrigger?: boolean
}

export function LiepinSkillSelector({
  value,
  onChange,
  open: externalOpen,
  onOpenChange,
  hideTrigger = false,
}: LiepinSkillSelectorProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const isOpen = externalOpen !== undefined ? externalOpen : internalOpen
  const setIsOpen = (v: boolean) => {
    if (onOpenChange) onOpenChange(v)
    else setInternalOpen(v)
  }

  const [draft, setDraft] = useState<string[]>(value)
  const [inputValue, setInputValue] = useState("")
  const [isFocused, setIsFocused] = useState(false)
  const modalRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Sync draft when modal opens
  useEffect(() => {
    if (isOpen) {
      setDraft([...value])
      setInputValue("")
      // Focus the input after render
      setTimeout(() => inputRef.current?.focus(), 100)
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

  const isAtMax = draft.length >= MAX_SELECT

  // Filter suggestions: exclude already selected, filter by input
  const filteredSuggestions = useMemo(() => {
    const kw = inputValue.trim().toLowerCase()
    return LIEPIN_SKILL_SUGGESTIONS.filter((s) => {
      if (draft.includes(s)) return false
      if (kw && !s.toLowerCase().includes(kw)) return false
      return true
    })
  }, [draft, inputValue])

  const addTag = (tag: string) => {
    const t = tag.trim().slice(0, 15)
    if (!t || draft.includes(t) || draft.length >= MAX_SELECT) return
    setDraft((prev) => [...prev, t])
    setInputValue("")
  }

  const removeTag = (tag: string) => {
    setDraft((prev) => prev.filter((t) => t !== tag))
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault()
      addTag(inputValue)
    } else if (e.key === "Backspace" && !inputValue && draft.length > 0) {
      // Remove last tag on backspace when input is empty
      setDraft((prev) => prev.slice(0, -1))
    }
  }

  const handleConfirm = () => {
    const cleanDraft = draft.map((t) => t.trim().slice(0, 15)).filter(Boolean)
    onChange(cleanDraft)
    setIsOpen(false)
  }

  const displayText = value.length > 0 ? value.join("、") : ""

  return (
    <>
      {/* Trigger input */}
      {!hideTrigger && (
        <div className="relative">
          <input
            type="text"
            readOnly
            value={displayText}
            placeholder="请选择技能"
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
            style={{ width: 840, maxHeight: 520 }}
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div className="flex items-center gap-3">
                <h3 className="text-base font-semibold text-gray-900">
                  请选择技能
                </h3>
                <span className="text-sm text-gray-400">
                  最多可选{MAX_SELECT}项
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

            {/* Input + selected tags area */}
            <div className="border-b border-gray-100 px-6 py-3">
              <div
                className={cn(
                  "flex flex-wrap items-center gap-1.5 rounded border px-3 py-2 transition-colors",
                  isFocused
                    ? "border-[#FF6B00] ring-1 ring-[#FF6B00]/20"
                    : "border-gray-200",
                )}
              >
                {/* Selected tags */}
                {draft.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 rounded bg-[#E8F4FF] px-2.5 py-1 text-[13px] text-[#1677FF]"
                  >
                    {tag}
                    <button
                      onClick={() => removeTag(tag)}
                      className="ml-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full text-[#1677FF]/50 transition-colors hover:bg-[#1677FF]/10 hover:text-[#1677FF]"
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
                {/* Input field */}
                <input
                  ref={inputRef}
                  type="text"
                  maxLength={15}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onFocus={() => setIsFocused(true)}
                  onBlur={() => setIsFocused(false)}
                  placeholder={
                    draft.length === 0
                      ? "请输入技能关键词（限15字）"
                      : isAtMax
                        ? `最多可选${MAX_SELECT}项`
                        : "输入后回车添加（限15字）"
                  }
                  disabled={isAtMax}
                  className="min-w-[120px] flex-1 border-none bg-transparent text-sm outline-none placeholder:text-gray-400 disabled:cursor-not-allowed"
                />
              </div>
              <div className="mt-1 flex items-center justify-between text-xs text-gray-400">
                <span>{isAtMax ? `已达上限，最多可选${MAX_SELECT}项` : "每个标签限 15 字符，最多可选 10 项"}</span>
                {inputValue.length > 0 && (
                  <span className={inputValue.length >= 15 ? "text-amber-500 font-medium" : ""}>
                    {inputValue.length} / 15
                  </span>
                )}
              </div>
            </div>

            {/* Suggestion tags */}
            <div className="flex-1 overflow-y-auto px-6 py-4">
              {filteredSuggestions.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {filteredSuggestions.map((tag) => {
                    const disabled = isAtMax
                    return (
                      <button
                        key={tag}
                        disabled={disabled}
                        onClick={() => addTag(tag)}
                        className={cn(
                          "rounded border px-3 py-1.5 text-[13px] leading-5 transition-colors",
                          disabled
                            ? "cursor-not-allowed border-gray-200 bg-gray-50 text-gray-300"
                            : "border-gray-200 bg-white text-gray-700 hover:border-[#FF6B00] hover:text-[#FF6B00]",
                        )}
                      >
                        {tag}
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="flex h-20 items-center justify-center text-sm text-gray-400">
                  {inputValue.trim()
                    ? "无匹配技能，回车直接添加"
                    : "暂无推荐技能"}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-6 py-3">
              <button
                onClick={() => setIsOpen(false)}
                className="rounded border border-gray-300 px-6 py-1.5 text-sm text-gray-600 transition-colors hover:bg-gray-50"
              >
                取消
              </button>
              <button
                onClick={handleConfirm}
                className="rounded px-6 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
                style={{ backgroundColor: "#1677FF" }}
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
