"use client"

import { useState, useMemo } from "react"
import { cn } from "@/lib/utils"
import { cityData } from "@/lib/city-options"

interface CitySelectorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

export function CitySelector({ value, onChange, placeholder = "请选择工作城市" }: CitySelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeProvince, setActiveProvince] = useState<string | null>(null)
  const [search, setSearch] = useState("")

  // 搜索过滤
  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const kw = search.trim().toLowerCase()
    const results: { province: string; city: string }[] = []
    // 热门城市
    for (const c of cityData.hotCities) {
      if (c.toLowerCase().includes(kw)) {
        results.push({ province: "热门城市", city: c })
      }
    }
    // 所有省份下的城市
    for (const p of cityData.provinces) {
      if (p.name.toLowerCase().includes(kw)) {
        results.push({ province: p.name, city: p.name })
      }
      for (const c of p.cities) {
        if (c.toLowerCase().includes(kw)) {
          results.push({ province: p.name, city: c })
        }
      }
    }
    return results.slice(0, 30)
  }, [search])

  const activeCities = useMemo(() => {
    if (!activeProvince) return []
    const p = cityData.provinces.find((p) => p.name === activeProvince)
    return p?.cities || []
  }, [activeProvince])

  const handleSelect = (city: string) => {
    onChange(city)
    setIsOpen(false)
    setActiveProvince(null)
    setSearch("")
  }

  const handleClose = () => {
    setIsOpen(false)
    setActiveProvince(null)
    setSearch("")
  }

  return (
    <div className="relative">
      {/* 触发按钮 */}
      <div
        className={cn(
          "flex h-10 w-full cursor-pointer items-center rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background",
          "hover:border-[#00beab] focus-within:border-[#00beab]",
          !value && "text-muted-foreground"
        )}
        onClick={() => setIsOpen(true)}
      >
        {value || placeholder}
      </div>

      {/* 弹窗 */}
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={handleClose} />

          <div className="relative z-10 w-[680px] max-h-[520px] rounded-lg bg-white shadow-xl flex flex-col">
            {/* 头部 */}
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="text-base font-medium text-gray-900">请选择工作城市</h3>
              <button onClick={handleClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>

            {/* 搜索框 */}
            <div className="px-5 pt-3 pb-2">
              <div className="flex items-center rounded-md border border-gray-200 px-3 py-2 focus-within:border-[#00beab]">
                <svg className="mr-2 h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                  type="text"
                  placeholder="搜索城市"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="flex-1 text-sm outline-none placeholder:text-gray-400"
                  autoFocus
                />
              </div>
            </div>

            {/* 搜索结果 */}
            {searchResults ? (
              <div className="flex-1 overflow-y-auto px-5 py-3">
                {searchResults.length === 0 ? (
                  <div className="py-8 text-center text-sm text-gray-400">未找到匹配的城市</div>
                ) : (
                  <div className="grid grid-cols-4 gap-x-3 gap-y-1">
                    {searchResults.map((r, i) => (
                      <button
                        key={i}
                        onClick={() => handleSelect(r.city)}
                        className={cn(
                          "rounded px-2 py-[7px] text-left text-[13px] transition-colors",
                          value === r.city
                            ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                            : "text-gray-700 hover:bg-gray-50"
                        )}
                      >
                        {r.city}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              /* 左右面板：省份 → 城市 */
              <div className="flex flex-1 overflow-hidden">
                {/* 左侧：热门城市 + 省份 */}
                <div className="w-[180px] border-r overflow-y-auto bg-gray-50/50">
                  {/* 热门城市 */}
                  <button
                    onClick={() => setActiveProvince("热门城市")}
                    className={cn(
                      "block w-full px-4 py-[9px] text-left text-[13px] transition-colors border-l-2",
                      activeProvince === "热门城市"
                        ? "border-l-[#00beab] bg-white text-[#00beab] font-medium"
                        : "border-l-transparent text-gray-700 hover:bg-gray-100"
                    )}
                  >
                    热门城市
                  </button>
                  {cityData.provinces.map((p) => (
                    <button
                      key={p.name}
                      onClick={() => setActiveProvince(p.name)}
                      className={cn(
                        "block w-full px-4 py-[9px] text-left text-[13px] transition-colors border-l-2",
                        activeProvince === p.name
                          ? "border-l-[#00beab] bg-white text-[#00beab] font-medium"
                          : "border-l-transparent text-gray-700 hover:bg-gray-100"
                      )}
                    >
                      {p.name}
                    </button>
                  ))}
                </div>

                {/* 右侧：城市列表 */}
                <div className="flex-1 overflow-y-auto px-4 py-3">
                  {activeProvince === "热门城市" ? (
                    <div className="grid grid-cols-4 gap-x-3 gap-y-1">
                      {cityData.hotCities.map((city) => (
                        <button
                          key={city}
                          onClick={() => handleSelect(city)}
                          className={cn(
                            "rounded px-2 py-[7px] text-left text-[13px] transition-colors",
                            value === city
                              ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                              : "text-gray-700 hover:bg-[#00beab]/5 hover:text-[#00beab]"
                          )}
                        >
                          {city}
                        </button>
                      ))}
                    </div>
                  ) : activeProvince ? (
                    <div className="grid grid-cols-4 gap-x-3 gap-y-1">
                      {activeCities.map((city) => (
                        <button
                          key={city}
                          onClick={() => handleSelect(city)}
                          className={cn(
                            "rounded px-2 py-[7px] text-left text-[13px] transition-colors",
                            value === city
                              ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                              : "text-gray-700 hover:bg-[#00beab]/5 hover:text-[#00beab]"
                          )}
                        >
                          {city}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="py-8 text-center text-sm text-gray-400">请选择省份</div>
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
