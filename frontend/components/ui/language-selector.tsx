"use client"

import { useState, useMemo, useEffect } from "react"
import { cn } from "@/lib/utils"
import {
  allLanguages,
  regionLanguageMap,
  LANGUAGE_MAX_SELECT,
  type LanguageItem,
} from "@/lib/overseas-options"
import { X, Check } from "lucide-react"

interface LanguageSelectorProps {
  value: string[]  // 已选语言名称列表
  onChange: (value: string[]) => void
  selectedCountries?: string[]  // 已选国家名称（用于推荐）
  selectedRegions?: number[]    // 已选大洲code（用于推荐）
  externalOpen?: boolean
  onExternalClose?: () => void
}

export function LanguageSelector({
  value = [],
  onChange,
  selectedCountries = [],
  selectedRegions = [],
  externalOpen,
  onExternalClose,
}: LanguageSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState("")

  // 同步外部 open 状态
  useEffect(() => {
    if (externalOpen) {
      setIsOpen(true)
    }
  }, [externalOpen])

  // 根据已选大洲推荐语言
  const recommendedLanguages = useMemo(() => {
    const codeSet = new Set<number>()
    for (const regionCode of selectedRegions) {
      const codes = regionLanguageMap[regionCode]
      if (codes) codes.forEach((c) => codeSet.add(c))
    }
    if (codeSet.size === 0) return []
    return allLanguages.filter((l) => codeSet.has(l.code))
  }, [selectedRegions])

  // 搜索结果
  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const keyword = search.trim().toLowerCase()
    return allLanguages.filter((l) => l.name.toLowerCase().includes(keyword))
  }, [search])

  const handleToggle = (name: string) => {
    if (value.includes(name)) {
      onChange(value.filter((v) => v !== name))
    } else if (value.length < LANGUAGE_MAX_SELECT) {
      onChange([...value, name])
    }
  }

  const handleClose = () => {
    setIsOpen(false)
    setSearch("")
    if (onExternalClose) onExternalClose()
  }

  const renderLangButton = (lang: LanguageItem, isRecommended = false) => (
    <button
      key={lang.name}
      onClick={() => handleToggle(lang.name)}
      className={cn(
        "rounded px-2 py-[7px] text-left text-[13px] transition-colors flex items-center gap-1",
        value.includes(lang.name)
          ? "bg-[#00beab]/10 text-[#00beab] font-medium"
          : value.length >= LANGUAGE_MAX_SELECT
            ? "text-gray-300 cursor-not-allowed"
            : "text-gray-700 hover:bg-[#00beab]/5 hover:text-[#00beab]"
      )}
      disabled={!value.includes(lang.name) && value.length >= LANGUAGE_MAX_SELECT}
      title={lang.name}
    >
      {value.includes(lang.name) && <Check className="h-3 w-3 shrink-0" />}
      {lang.emoji && <span className="text-sm">{lang.emoji}</span>}
      <span className="truncate">{lang.name}</span>
    </button>
  )

  return (
    <div className="relative">
      {/* 触发区域 */}
      <div
        className={cn(
          "flex min-h-[40px] w-full cursor-pointer flex-wrap items-center gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm",
          "hover:border-[#00beab]",
          !value.length && "text-muted-foreground"
        )}
        onClick={() => setIsOpen(true)}
      >
        {value.length > 0 ? (
          value.map((name) => (
            <span
              key={name}
              className="inline-flex items-center gap-1 rounded bg-[#00beab]/10 px-2 py-0.5 text-xs text-[#00beab]"
            >
              {name}
              <X
                className="h-3 w-3 cursor-pointer hover:text-[#009e8e]"
                onClick={(e) => {
                  e.stopPropagation()
                  onChange(value.filter((v) => v !== name))
                }}
              />
            </span>
          ))
        ) : (
          <span>选择可用于工作交流的语言</span>
        )}
      </div>

      {/* 弹窗 */}
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={handleClose} />

          <div className="relative z-10 w-[680px] max-h-[520px] rounded-lg bg-white shadow-xl flex flex-col">
            {/* 头部 */}
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="text-base font-medium text-gray-900">
                选择可用于工作交流的语言
                <span className="ml-2 text-xs text-gray-400">（{value.length}/{LANGUAGE_MAX_SELECT}）</span>
              </h3>
              <button onClick={handleClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>

            {/* 搜索框 */}
            <div className="px-5 py-2">
              <div className="flex items-center rounded-md border border-gray-200 px-3 py-2 focus-within:border-[#00beab]">
                <input
                  type="text"
                  placeholder="搜索语言"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="flex-1 text-sm outline-none placeholder:text-gray-400"
                />
              </div>
            </div>

            {/* 已选标签区 */}
            {value.length > 0 && (
              <div className="px-5 pb-2 flex flex-wrap gap-1.5">
                {value.map((name) => (
                  <span
                    key={name}
                    className="inline-flex items-center gap-1 rounded-full bg-[#00beab]/10 px-2.5 py-1 text-xs text-[#00beab]"
                  >
                    {name}
                    <X
                      className="h-3 w-3 cursor-pointer hover:text-[#009e8e]"
                      onClick={() => onChange(value.filter((v) => v !== name))}
                    />
                  </span>
                ))}
              </div>
            )}

            {/* 内容区 */}
            <div className="flex-1 overflow-y-auto px-5 py-3 border-t">
              {searchResults ? (
                /* 搜索结果 */
                searchResults.length > 0 ? (
                  <div className="grid grid-cols-4 gap-x-3 gap-y-1">
                    {searchResults.map((lang) => renderLangButton(lang))}
                  </div>
                ) : (
                  <div className="text-center text-sm text-gray-400 py-8">未找到匹配的语言</div>
                )
              ) : (
                <>
                  {/* 推荐语言 */}
                  {recommendedLanguages.length > 0 && (
                    <div className="mb-4">
                      <div className="text-xs text-gray-500 mb-2">根据选择的国家/地区推荐</div>
                      <div className="grid grid-cols-4 gap-x-3 gap-y-1">
                        {recommendedLanguages.map((lang) => renderLangButton(lang, true))}
                      </div>
                    </div>
                  )}

                  {/* 全部语言 */}
                  <div>
                    <div className="text-xs text-gray-500 mb-2">全部语言</div>
                    <div className="grid grid-cols-4 gap-x-3 gap-y-1">
                      {allLanguages.map((lang) => renderLangButton(lang))}
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* 底部操作 */}
            <div className="border-t px-5 py-3 flex justify-end gap-3">
              <button
                onClick={handleClose}
                className="rounded-md border border-gray-300 px-5 py-1.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleClose}
                className="rounded-md bg-[#00beab] px-5 py-1.5 text-sm text-white hover:bg-[#00a99a] transition-colors"
              >
                完成
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
