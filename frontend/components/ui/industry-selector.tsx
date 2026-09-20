"use client"

import { useState, useMemo } from "react"
import { cn } from "@/lib/utils"
import { industryOptions, industryCategories } from "@/lib/industry-options"
import { X } from "lucide-react"

interface IndustrySelectorProps {
  value: string[]
  onChange: (value: string[]) => void
  placeholder?: string
  max?: number
}

export function IndustrySelector({ value = [], onChange, placeholder = "请选择期望行业（最多3个）", max = 3 }: IndustrySelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeGroup, setActiveGroup] = useState<string>(industryCategories[0]?.name || "")
  const [search, setSearch] = useState("")

  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const kw = search.trim().toLowerCase()
    return industryOptions.filter((i) => i.toLowerCase().includes(kw)).slice(0, 30)
  }, [search])

  const activeItems = useMemo(() => {
    const group = industryCategories.find((g) => g.name === activeGroup)
    return group?.subs || []
  }, [activeGroup])

  const handleToggle = (industry: string) => {
    if (value.includes(industry)) {
      onChange(value.filter((v) => v !== industry))
      // 单选模式下取消选择也直接关闭
      if (max === 1) handleClose()
    } else if (max === 1) {
      // 单选模式：选择新值直接替换旧值（避免被 value.length < max 卡住）
      onChange([industry])
      handleClose()
    } else if (value.length < max) {
      onChange([...value, industry])
    }
  }

  // 单选模式（max=1）不禁止点击：点击即替换旧值；多选模式已达上限时禁止添加
  const isDisabled = (item: string) => max === 1 ? false : !value.includes(item) && value.length >= max

  const handleClose = () => {
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
            {value.map((industry) => (
              <span
                key={industry}
                className="inline-flex items-center gap-1 rounded bg-[#00beab]/10 px-2 py-0.5 text-xs text-[#00beab]"
              >
                {industry}
                <X
                  className="h-3 w-3 cursor-pointer hover:text-[#009e8e]"
                  onClick={(e) => {
                    e.stopPropagation()
                    onChange(value.filter((v) => v !== industry))
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

          <div className="relative z-10 w-[720px] max-h-[520px] rounded-lg bg-white shadow-xl flex flex-col">
            {/* 头部 */}
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="text-base font-medium text-gray-900">
                {max === 1 ? "请选择所属行业" : "请选择期望行业"}
                {max > 1 && <span className="ml-2 text-xs text-gray-400">最多选{max}个（已选{value.length}）</span>}
              </h3>
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
                  placeholder="搜索行业"
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
                  <div className="py-8 text-center text-sm text-gray-400">未找到匹配的行业</div>
                ) : (
                  <div className="grid grid-cols-3 gap-x-3 gap-y-1">
                    {searchResults.map((item) => (
                      <button
                        key={item}
                        onClick={() => handleToggle(item)}
                        className={cn(
                          "rounded px-2 py-[7px] text-left text-[13px] transition-colors",
                          value.includes(item)
                            ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                            : isDisabled(item)
                              ? "text-gray-300 cursor-not-allowed"
                              : "text-gray-700 hover:bg-gray-50"
                        )}
                        disabled={isDisabled(item)}
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              /* 左右面板 */
              <div className="flex flex-1 overflow-hidden">
                {/* 左侧分组 */}
                <div className="w-[160px] border-r overflow-y-auto bg-gray-50/50">
                  {industryCategories.map((g) => (
                    <button
                      key={g.name}
                      onClick={() => setActiveGroup(g.name)}
                      className={cn(
                        "block w-full px-3 py-[9px] text-left text-[13px] transition-colors border-l-2",
                        activeGroup === g.name
                          ? "border-l-[#00beab] bg-white text-[#00beab] font-medium"
                          : "border-l-transparent text-gray-700 hover:bg-gray-100"
                      )}
                    >
                      {g.name}
                    </button>
                  ))}
                </div>

                {/* 右侧行业列表 */}
                <div className="flex-1 overflow-y-auto px-4 py-3">
                  <div className="grid grid-cols-3 gap-x-3 gap-y-1">
                    {activeItems.map((item) => (
                      <button
                        key={item}
                        onClick={() => handleToggle(item)}
                        className={cn(
                          "rounded px-2 py-[7px] text-left text-[13px] transition-colors",
                          value.includes(item)
                            ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                            : isDisabled(item)
                              ? "text-gray-300 cursor-not-allowed"
                              : "text-gray-700 hover:bg-[#00beab]/5 hover:text-[#00beab]"
                        )}
                        disabled={isDisabled(item)}
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* 底部确认（多选模式才显示） */}
            {max > 1 && (
              <div className="border-t px-5 py-3 flex items-center justify-between">
                <span className="text-xs text-gray-400">
                  {value.length > 0 ? `已选：${value.join("、")}` : "未选择"}
                </span>
                <button
                  onClick={handleClose}
                  className="rounded-md bg-[#00beab] px-4 py-1.5 text-sm text-white hover:bg-[#00a99a] transition-colors"
                >
                  确定
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
