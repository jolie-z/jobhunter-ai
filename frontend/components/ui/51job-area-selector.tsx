"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"
import { JOB51_HOT_CITIES, JOB51_CITY_GROUPS } from "@/lib/51job-options"

/**
 * 51job 城市/地区选择器（照搬 51job 城市弹窗布局）
 * - 左侧菜单：热门 + 字母分组 (A-Z)
 * - 右侧：城市标签网格
 *
 * value 格式：地区编码字符串（如 "030200" 代表广州）
 * onChange 回调返回 (code, name)
 */

interface Job51AreaSelectorProps {
  value: string
  onChange: (code: string, name: string) => void
  placeholder?: string
}

export function Job51AreaSelector({ value, onChange, placeholder = "请选择城市" }: Job51AreaSelectorProps) {
  const [open, setOpen] = useState(false)
  const [activeGroup, setActiveGroup] = useState<string>("热门")
  const wrapRef = useRef<HTMLDivElement>(null)

  // 点击外部关闭
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  // 左侧菜单：热门 + A-Z 字母分组
  const menu = ["热门", ...JOB51_CITY_GROUPS.filter((g) => /^[A-Z]$/.test(g.letter)).map((g) => g.letter)]

  // 根据 code 找到城市名称用于显示
  const displayName = (() => {
    if (!value) return ""
    const hot = JOB51_HOT_CITIES.find((c) => c.code === value)
    if (hot) return hot.value
    for (const group of JOB51_CITY_GROUPS) {
      const city = group.cities.find((c) => c.code === value)
      if (city) return city.value
    }
    return value
  })()

  const pick = (code: string, name: string) => {
    onChange(code, name)
    setOpen(false)
  }

  // 渲染右侧城市区
  const renderCityPanel = () => {
    if (activeGroup === "热门") {
      return (
        <div>
          <div className="text-sm text-gray-500 mb-3">热门城市</div>
          <div className="flex flex-wrap gap-2">
            {JOB51_HOT_CITIES.map((c) => (
              <CityTag key={c.code} name={c.value} selected={value === c.code} onClick={() => pick(c.code, c.value)} />
            ))}
          </div>
        </div>
      )
    }
    const group = JOB51_CITY_GROUPS.find((g) => g.letter === activeGroup)
    if (!group) return null
    return (
      <div>
        <div className="text-sm text-gray-500 mb-3">{group.letter}</div>
        <div className="flex flex-wrap gap-2">
          {group.cities.map((c) => (
            <CityTag key={c.code} name={c.value} selected={value === c.code} onClick={() => pick(c.code, c.value)} />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="relative" ref={wrapRef}>
      {/* 触发器 */}
      <input
        readOnly
        value={displayName}
        placeholder={placeholder}
        onClick={() => {
          setOpen(true)
          setActiveGroup("热门")
        }}
        className={cn(
          "w-full h-[40px] rounded-md border bg-background px-3 text-sm cursor-pointer transition-colors",
          "hover:border-[#FF6B00] focus:outline-none",
          open ? "border-[#FF6B00]" : "border-input"
        )}
      />

      {/* 城市弹窗 */}
      {open && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl w-[800px] max-w-[92vw] h-[530px] max-h-[86vh] flex flex-col overflow-hidden">
            {/* 标题栏 */}
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <span className="text-base font-medium text-gray-800">请选择城市</span>
              <button className="text-gray-400 hover:text-gray-600 text-xl leading-none" onClick={() => setOpen(false)}>
                ×
              </button>
            </div>

            {/* 主体：左菜单 + 右城市 */}
            <div className="flex flex-1 min-h-0">
              {/* 左侧菜单 */}
              <div className="w-[200px] flex-shrink-0 overflow-y-auto border-r bg-gray-50/60 py-2">
                {menu.map((name) => (
                  <button
                    key={name}
                    onClick={() => setActiveGroup(name)}
                    className={cn(
                      "block w-full text-left px-5 py-2 text-sm transition-colors",
                      activeGroup === name
                        ? "text-[#FF6B00] bg-white font-medium border-l-2 border-[#FF6B00]"
                        : "text-gray-600 hover:text-[#FF6B00]"
                    )}
                  >
                    {name}
                  </button>
                ))}
              </div>

              {/* 右侧城市 */}
              <div className="flex-1 overflow-y-auto p-5">{renderCityPanel()}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function CityTag({ name, selected, onClick }: { name: string; selected: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-3 py-1 rounded text-sm border transition-colors",
        selected
          ? "bg-[#FF6B00] text-white border-[#FF6B00]"
          : "bg-white text-gray-700 border-gray-200 hover:border-[#FF6B00] hover:text-[#FF6B00]"
      )}
    >
      {name}
    </button>
  )
}
