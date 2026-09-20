"use client"

import { useState, useMemo, useEffect } from "react"
import { cn } from "@/lib/utils"
import {
  countryRegions,
  COUNTRY_MAX_SELECT,
  type CountryRegion,
  type CountryItem,
} from "@/lib/overseas-options"
import { X, Check } from "lucide-react"

interface CountrySelectorProps {
  value: string[]  // 已选国家名称列表
  onChange: (value: string[]) => void
  externalOpen?: boolean
  onExternalClose?: () => void
}

export function CountrySelector({ value = [], onChange, externalOpen, onExternalClose }: CountrySelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeRegion, setActiveRegion] = useState<string>(countryRegions[0]?.name || "")
  const [search, setSearch] = useState("")

  // 同步外部 open 状态
  useEffect(() => {
    if (externalOpen) {
      setIsOpen(true)
    }
  }, [externalOpen])

  // 当前大洲的子国家列表
  const activeItems = useMemo(() => {
    const region = countryRegions.find((r) => r.name === activeRegion)
    return region?.subLevelModelList || []
  }, [activeRegion])

  // 搜索结果（跨大洲搜索）
  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const keyword = search.trim().toLowerCase()
    const results: { name: string; region: string }[] = []
    for (const region of countryRegions) {
      if (region.name === "不限") continue
      for (const item of region.subLevelModelList || []) {
        if (item.name.toLowerCase().includes(keyword)) {
          results.push({ name: item.name, region: region.name })
        }
      }
    }
    return results
  }, [search])

  const handleToggle = (name: string) => {
    if (value.includes(name)) {
      onChange(value.filter((v) => v !== name))
    } else if (value.length < COUNTRY_MAX_SELECT) {
      onChange([...value, name])
    }
  }

  const handleClose = () => {
    setIsOpen(false)
    setSearch("")
    if (onExternalClose) onExternalClose()
  }

  const handleConfirm = () => {
    handleClose()
  }

  return (
    <div className="relative">
      {/* 触发区域：显示已选标签 */}
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
          <span>选择可接受的境外国家/地区</span>
        )}
      </div>

      {/* 弹窗 */}
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={handleClose} />

          <div className="relative z-10 w-[800px] max-h-[560px] rounded-lg bg-white shadow-xl flex flex-col">
            {/* 头部 */}
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="text-base font-medium text-gray-900">
                选择可接受的境外国家/地区
                <span className="ml-2 text-xs text-gray-400">（{value.length}/{COUNTRY_MAX_SELECT}）</span>
              </h3>
              <button onClick={handleClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>

            {/* 搜索框 */}
            <div className="px-5 py-2">
              <div className="flex items-center rounded-md border border-gray-200 px-3 py-2 focus-within:border-[#00beab]">
                <input
                  type="text"
                  placeholder="搜索国家或地区"
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

            {/* 左右面板 */}
            <div className="flex flex-1 overflow-hidden border-t">
              {searchResults ? (
                /* 搜索结果模式 */
                <div className="flex-1 overflow-y-auto px-4 py-3">
                  {searchResults.length > 0 ? (
                    <div className="grid grid-cols-3 gap-x-3 gap-y-1">
                      {searchResults.map((item) => (
                        <button
                          key={item.name}
                          onClick={() => handleToggle(item.name)}
                          className={cn(
                            "rounded px-2 py-[7px] text-left text-[13px] transition-colors flex items-center gap-1",
                            value.includes(item.name)
                              ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                              : value.length >= COUNTRY_MAX_SELECT
                                ? "text-gray-300 cursor-not-allowed"
                                : "text-gray-700 hover:bg-[#00beab]/5 hover:text-[#00beab]"
                          )}
                          disabled={!value.includes(item.name) && value.length >= COUNTRY_MAX_SELECT}
                          title={item.name}
                        >
                          {value.includes(item.name) && <Check className="h-3 w-3 shrink-0" />}
                          <span className="truncate">{item.name}</span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center text-sm text-gray-400 py-8">未找到匹配的国家/地区</div>
                  )}
                </div>
              ) : (
                <>
                  {/* 左侧大洲分类 */}
                  <div className="w-[120px] border-r overflow-y-auto bg-gray-50/50">
                    {countryRegions.map((region) => (
                      <button
                        key={region.name}
                        onClick={() => setActiveRegion(region.name)}
                        className={cn(
                          "block w-full px-3 py-[9px] text-left text-[13px] transition-colors border-l-2",
                          activeRegion === region.name
                            ? "border-l-[#00beab] bg-white text-[#00beab] font-medium"
                            : "border-l-transparent text-gray-700 hover:bg-gray-100"
                        )}
                      >
                        {region.name}
                      </button>
                    ))}
                  </div>

                  {/* 右侧国家列表 */}
                  <div className="flex-1 overflow-y-auto px-4 py-3">
                    <div className="grid grid-cols-3 gap-x-3 gap-y-1">
                      {activeItems.map((item) => (
                        <button
                          key={item.name}
                          onClick={() => handleToggle(item.name)}
                          className={cn(
                            "rounded px-2 py-[7px] text-left text-[13px] transition-colors flex items-center gap-1",
                            value.includes(item.name)
                              ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                              : item.flag === 1
                                ? "text-gray-900 font-medium hover:bg-[#00beab]/5 hover:text-[#00beab]"
                                : value.length >= COUNTRY_MAX_SELECT
                                  ? "text-gray-300 cursor-not-allowed"
                                  : "text-gray-700 hover:bg-[#00beab]/5 hover:text-[#00beab]"
                          )}
                          disabled={!value.includes(item.name) && value.length >= COUNTRY_MAX_SELECT}
                          title={item.name}
                        >
                          {value.includes(item.name) && <Check className="h-3 w-3 shrink-0" />}
                          <span className="truncate">{item.name}</span>
                        </button>
                      ))}
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
                onClick={handleConfirm}
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
