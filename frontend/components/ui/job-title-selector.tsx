"use client"

import { useState, useMemo } from "react"
import { cn } from "@/lib/utils"
import { jobCategories } from "@/lib/job-categories"
import { fulltimeCategories } from "@/lib/job-categories-fulltime"

interface JobTitleSelectorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  /** 求职类型：全职用3级左右面板，兼职用2级行内展开 */
  jobType?: "fulltime" | "parttime"
}

export function JobTitleSelector({
  value,
  onChange,
  placeholder = "选择期望职位",
  jobType = "fulltime",
}: JobTitleSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)

  const handleSelect = (name: string) => {
    onChange(name)
    setIsOpen(false)
  }

  const handleClose = () => {
    setIsOpen(false)
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
          {jobType === "fulltime" ? (
            <FulltimePanel value={value} onSelect={handleSelect} onClose={handleClose} />
          ) : (
            <ParttimePanel value={value} onSelect={handleSelect} onClose={handleClose} />
          )}
        </div>
      )}
    </div>
  )
}

/* ========== 全职：左右面板，3级 ========== */
function FulltimePanel({
  value,
  onSelect,
  onClose,
}: {
  value: string
  onSelect: (v: string) => void
  onClose: () => void
}) {
  // 打开时自动定位到当前值所在分类（如 agent 映射到的合法职位，点开即可看到高亮项）
  const [activeCategory, setActiveCategory] = useState<string>(() => {
    const cat = fulltimeCategories.find((c) => c.children.some((s) => s.children.includes(value)))
    return cat?.name || fulltimeCategories[0]?.name || ""
  })
  const [expandedSub, setExpandedSub] = useState<string | null>(() => {
    const sub = fulltimeCategories.flatMap((c) => c.children).find((s) => s.children.includes(value))
    return sub?.name || null
  })
  const [search, setSearch] = useState("")

  // 搜索模式
  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const kw = search.trim().toLowerCase()
    const results: { category: string; sub: string; position: string }[] = []
    for (const cat of fulltimeCategories) {
      for (const sub of cat.children) {
        for (const pos of sub.children) {
          if (pos.toLowerCase().includes(kw) || sub.name.toLowerCase().includes(kw)) {
            results.push({ category: cat.name, sub: sub.name, position: pos })
          }
        }
      }
    }
    return results.slice(0, 50)
  }, [search])

  const activeCat = fulltimeCategories.find((c) => c.name === activeCategory)

  return (
    <div className="relative z-10 w-[960px] max-h-[600px] rounded-lg bg-white shadow-xl flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between border-b px-5 py-3">
        <h3 className="text-base font-medium text-gray-900">请选择期望职位</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
      </div>

      {/* 搜索框 */}
      <div className="px-5 pt-3 pb-2">
        <div className="flex items-center rounded-md border border-gray-200 px-3 py-2 focus-within:border-[#00beab]">
          <svg className="mr-2 h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="搜索职位关键词"
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
            <div className="py-8 text-center text-sm text-gray-400">未找到匹配的职位</div>
          ) : (
            <div className="space-y-1">
              {searchResults.map((r, i) => (
                <button
                  key={i}
                  onClick={() => onSelect(r.position)}
                  className={cn(
                    "block w-full rounded px-3 py-2 text-left text-[13px] transition-colors",
                    value === r.position
                      ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                      : "text-gray-700 hover:bg-gray-50"
                  )}
                >
                  <span className="text-gray-400 text-xs mr-2">{r.category} / {r.sub}</span>
                  {r.position}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        /* 左右面板 */
        <div className="flex flex-1 overflow-hidden">
          {/* 左侧：一级分类 */}
          <div className="w-[200px] border-r overflow-y-auto bg-gray-50/50">
            {fulltimeCategories.map((cat) => (
              <button
                key={cat.name}
                onClick={() => {
                  setActiveCategory(cat.name)
                  setExpandedSub(null)
                }}
                className={cn(
                  "block w-full px-4 py-[9px] text-left text-[13px] transition-colors border-l-2",
                  activeCategory === cat.name
                    ? "border-l-[#00beab] bg-white text-[#00beab] font-medium"
                    : "border-l-transparent text-gray-700 hover:bg-gray-100"
                )}
              >
                {cat.name}
              </button>
            ))}
          </div>

          {/* 右侧：二级 + 三级展开 */}
          <div className="flex-1 overflow-y-auto px-4 py-3">
            {activeCat?.children.map((sub) => (
              <div key={sub.name} className="mb-1">
                {/* 二级分类行 */}
                <button
                  onClick={() => setExpandedSub(expandedSub === sub.name ? null : sub.name)}
                  className={cn(
                    "flex w-full items-center gap-1.5 rounded px-2 py-[7px] text-left text-[13px] transition-colors",
                    expandedSub === sub.name
                      ? "text-[#00beab] font-medium"
                      : "text-gray-700 hover:bg-gray-50"
                  )}
                >
                  <span
                    className={cn(
                      "inline-flex h-[16px] w-[16px] flex-shrink-0 items-center justify-center rounded-full border text-[10px]",
                      expandedSub === sub.name
                        ? "border-[#00beab] text-[#00beab]"
                        : "border-gray-300 text-gray-400"
                    )}
                  >
                    {expandedSub === sub.name ? "−" : "+"}
                  </span>
                  <span>{sub.name}</span>
                  <span className="ml-auto text-xs text-gray-300">{sub.children.length}</span>
                </button>

                {/* 三级职位：内联展开 */}
                {expandedSub === sub.name && (
                  <div className="ml-[26px] mt-1 mb-2 grid grid-cols-4 gap-x-2 gap-y-0.5">
                    {sub.children.map((pos) => (
                      <button
                        key={pos}
                        onClick={() => onSelect(pos)}
                        className={cn(
                          "rounded px-2 py-[6px] text-left text-[13px] leading-tight transition-colors",
                          value === pos
                            ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                            : "text-gray-600 hover:bg-[#00beab]/5 hover:text-[#00beab]"
                        )}
                      >
                        {pos}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ========== 兼职：行内展开，2级 ========== */
function ParttimePanel({
  value,
  onSelect,
  onClose,
}: {
  value: string
  onSelect: (v: string) => void
  onClose: () => void
}) {
  // 打开时自动定位到当前值所在一级分类（兼职两级结构）
  const [activeCategory, setActiveCategory] = useState<string | null>(() => {
    const cat = jobCategories.find((c) => c.children.includes(value))
    return cat?.name || null
  })
  const [search, setSearch] = useState("")

  const filteredCategories = useMemo(() => {
    if (!search.trim()) return jobCategories
    const keyword = search.trim().toLowerCase()
    return jobCategories
      .map((cat) => {
        const nameMatch = cat.name.toLowerCase().includes(keyword)
        const childMatches = cat.children.filter((c) => c.toLowerCase().includes(keyword))
        if (nameMatch) return cat
        if (childMatches.length > 0) return { ...cat, children: childMatches }
        return null
      })
      .filter(Boolean) as typeof jobCategories
  }, [search])

  const activeChildren = useMemo(() => {
    if (!activeCategory) return []
    const cat = jobCategories.find((c) => c.name === activeCategory)
    return cat?.children || []
  }, [activeCategory])

  // 按每行4个分组
  const rows = useMemo(() => {
    const result: (typeof jobCategories)[] = []
    for (let i = 0; i < filteredCategories.length; i += 4) {
      result.push(filteredCategories.slice(i, i + 4))
    }
    return result
  }, [filteredCategories])

  return (
    <div className="relative z-10 w-[960px] max-h-[580px] rounded-lg bg-white shadow-xl flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between border-b px-5 py-3">
        <h3 className="text-base font-medium text-gray-900">请选择期望职位（兼职）</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
      </div>

      {/* 搜索框 */}
      <div className="px-5 pt-3 pb-2">
        <div className="flex items-center rounded-md border border-gray-200 px-3 py-2 focus-within:border-[#00beab]">
          <svg className="mr-2 h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="请输入职位关键词"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 text-sm outline-none placeholder:text-gray-400"
            autoFocus
          />
        </div>
      </div>

      {/* 内容区：按行渲染，点击后在下方展开二级 */}
      <div className="flex-1 overflow-y-auto px-5 py-3">
        {rows.map((row, rowIdx) => {
          const activeInRow = row.find((cat) => cat.name === activeCategory)
          return (
            <div key={rowIdx}>
              {/* 一级分类行 */}
              <div className="grid grid-cols-4 gap-x-3 gap-y-0.5">
                {row.map((cat) => (
                  <button
                    key={cat.name}
                    onClick={() => setActiveCategory(cat.name === activeCategory ? null : cat.name)}
                    className={cn(
                      "flex items-center gap-1 rounded px-2 py-[7px] text-left text-[13px] leading-tight transition-colors",
                      activeCategory === cat.name
                        ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                        : "text-gray-700 hover:bg-gray-50"
                    )}
                  >
                    <span
                      className={cn(
                        "inline-block h-[14px] w-[14px] flex-shrink-0 rounded-full border text-center text-[10px] leading-[13px]",
                        activeCategory === cat.name
                          ? "border-[#00beab] text-[#00beab]"
                          : "border-gray-300 text-gray-400"
                      )}
                    >
                      {activeCategory === cat.name ? "−" : "+"}
                    </span>
                    <span className="truncate">{cat.name}</span>
                  </button>
                ))}
              </div>

              {/* 二级展开（在被点击行的正下方） */}
              {activeInRow && activeChildren.length > 0 && (
                <div className="my-2 rounded-md border border-gray-100 bg-gray-50/60 p-4">
                  <div className="mb-2 text-xs font-medium text-gray-500">{activeCategory}</div>
                  <div className="grid grid-cols-4 gap-x-3 gap-y-0.5">
                    {activeChildren.map((child) => (
                      <button
                        key={child}
                        onClick={() => onSelect(child)}
                        className={cn(
                          "rounded px-2 py-[7px] text-left text-[13px] leading-tight transition-colors",
                          value === child
                            ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                            : "text-gray-700 hover:bg-white hover:text-[#00beab]"
                        )}
                      >
                        {child}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })}

        {filteredCategories.length === 0 && (
          <div className="py-8 text-center text-sm text-gray-400">未找到匹配的职位</div>
        )}
      </div>
    </div>
  )
}
