"use client"

import { useState, useMemo } from "react"
import { cn } from "@/lib/utils"
import { otherCityData } from "@/lib/other-city-options"
import { X } from "lucide-react"

interface OtherCitySelectorProps {
  value: string[]
  onChange: (value: string[]) => void
  placeholder?: string
}

export function OtherCitySelector({ value = [], onChange, placeholder = "选择其他感兴趣城市" }: OtherCitySelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState("")

  const maxSelect = otherCityData.maxSelect

  // 搜索过滤
  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const kw = search.trim().toLowerCase()
    const results: string[] = []
    for (const group of otherCityData.alphaGroups) {
      for (const city of group.cities) {
        if (city.toLowerCase().includes(kw)) {
          results.push(city)
        }
      }
    }
    return results.slice(0, 40)
  }, [search])

  const handleToggle = (city: string) => {
    if (value.includes(city)) {
      onChange(value.filter((v) => v !== city))
    } else if (value.length < maxSelect) {
      onChange([...value, city])
    }
  }

  const handleClose = () => {
    setIsOpen(false)
    setSearch("")
  }

  const handleConfirm = () => {
    setIsOpen(false)
    setSearch("")
  }

  return (
    <div className="relative">
      {/* 触发按钮 */}
      <div
        className={cn(
          "flex min-h-[40px] w-full cursor-pointer items-center rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background",
          "hover:border-[#00beab]",
          !value.length && "text-muted-foreground"
        )}
        onClick={() => setIsOpen(true)}
      >
        {value.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {value.map((city) => (
              <span
                key={city}
                className="inline-flex items-center gap-1 rounded bg-[#00beab]/10 px-2 py-0.5 text-xs text-[#00beab]"
              >
                {city}
                <X
                  className="h-3 w-3 cursor-pointer hover:text-[#009e8e]"
                  onClick={(e) => {
                    e.stopPropagation()
                    onChange(value.filter((v) => v !== city))
                  }}
                />
              </span>
            ))}
          </div>
        ) : (
          <span>{placeholder}</span>
        )}
      </div>

      {/* 弹窗 */}
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={handleClose} />

          <div className="relative z-10 w-[680px] max-h-[560px] rounded-lg bg-white shadow-xl flex flex-col">
            {/* 头部：搜索 + 计数 + 确认 */}
            <div className="flex items-center gap-3 border-b px-5 py-3">
              <div className="flex flex-1 items-center rounded-md border border-gray-200 px-3 py-2 focus-within:border-[#00beab]">
                <svg className="mr-2 h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                  type="text"
                  placeholder="城市名称"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="flex-1 text-sm outline-none placeholder:text-gray-400"
                  autoFocus
                />
              </div>
              <span className="text-xs text-gray-400 whitespace-nowrap">{value.length}/{maxSelect}</span>
              <button
                onClick={handleConfirm}
                className="rounded-md bg-[#00beab] px-4 py-1.5 text-sm text-white hover:bg-[#00a99a] transition-colors whitespace-nowrap"
              >
                确认
              </button>
              <button onClick={handleClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>

            {/* 内容区 */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {searchResults ? (
                /* 搜索结果 */
                searchResults.length === 0 ? (
                  <div className="py-8 text-center text-sm text-gray-400">未找到匹配的城市</div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {searchResults.map((city) => (
                      <button
                        key={city}
                        onClick={() => handleToggle(city)}
                        disabled={!value.includes(city) && value.length >= maxSelect}
                        className={cn(
                          "rounded-md px-3 py-1.5 text-[13px] transition-colors border",
                          value.includes(city)
                            ? "border-[#00beab] bg-[#00beab]/10 text-[#00beab] font-medium"
                            : value.length >= maxSelect
                              ? "border-gray-100 text-gray-300 cursor-not-allowed"
                              : "border-gray-200 text-gray-700 hover:border-[#00beab] hover:text-[#00beab]"
                        )}
                      >
                        {city}
                      </button>
                    ))}
                  </div>
                )
              ) : (
                <>
                  {/* 热门城市 */}
                  <div className="mb-5">
                    <div className="mb-2 text-sm font-medium text-gray-900">热门城市</div>
                    <div className="flex flex-wrap gap-2">
                      {otherCityData.hotCities.map((city) => (
                        <button
                          key={city}
                          onClick={() => handleToggle(city)}
                          disabled={!value.includes(city) && value.length >= maxSelect}
                          className={cn(
                            "rounded-md px-3 py-1.5 text-[13px] transition-colors border",
                            value.includes(city)
                              ? "border-[#00beab] bg-[#00beab]/10 text-[#00beab] font-medium"
                              : value.length >= maxSelect
                                ? "border-gray-100 text-gray-300 cursor-not-allowed"
                                : "border-gray-200 text-gray-700 hover:border-[#00beab] hover:text-[#00beab]"
                          )}
                        >
                          {city}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 按字母选择 */}
                  <div className="mb-2 text-sm font-medium text-gray-900">按字母选择</div>
                  {otherCityData.alphaGroups.map((group) => (
                    <div key={group.letter} className="mb-3">
                      <div className="mb-1.5 flex items-center gap-2">
                        <span className="flex h-5 w-5 items-center justify-center rounded bg-gray-100 text-xs font-bold text-gray-500">
                          {group.letter}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1.5 pl-7">
                        {group.cities.map((city) => (
                          <button
                            key={city}
                            onClick={() => handleToggle(city)}
                            disabled={!value.includes(city) && value.length >= maxSelect}
                            className={cn(
                              "rounded px-2 py-1 text-[13px] transition-colors",
                              value.includes(city)
                                ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                                : value.length >= maxSelect
                                  ? "text-gray-300 cursor-not-allowed"
                                  : "text-gray-600 hover:bg-gray-50 hover:text-[#00beab]"
                            )}
                          >
                            {city}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
