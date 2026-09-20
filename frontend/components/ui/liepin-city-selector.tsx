"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"
import {
  LIEPIN_DOMESTIC,
  LIEPIN_OVERSEAS,
  LIEPIN_HOT_CITIES,
  type LiepinCityGroup,
} from "@/lib/liepin-options"

/**
 * 猎聘城市选择器（照搬 c.liepin.com 城市弹窗布局）
 * - 顶部 Tab：国内 / 海外
 * - 左侧菜单：历史/热门 + 省市/大洲
 * - 右侧：城市标签网格（港澳台分 香港/澳门/台湾 三段）
 *
 * value 格式：「省份·城市」（如 广东·广州），热门城市直接为城市名
 */

interface LiepinCitySelectorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

export function LiepinCitySelector({ value, onChange, placeholder = "请选择城市" }: LiepinCitySelectorProps) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<"domestic" | "overseas">("domestic")
  const [activeGroup, setActiveGroup] = useState<string>("历史/热门")
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

  const domesticMenu = ["历史/热门", ...LIEPIN_DOMESTIC.map((g) => g.name)]
  const overseasMenu = LIEPIN_OVERSEAS.map((g) => g.name)
  const menu = tab === "domestic" ? domesticMenu : overseasMenu
  const groups: LiepinCityGroup[] = tab === "domestic" ? LIEPIN_DOMESTIC : LIEPIN_OVERSEAS

  const pick = (v: string) => {
    onChange(v)
    setOpen(false)
  }

  // 渲染右侧城市区
  const renderCityPanel = () => {
    // 热门
    if (tab === "domestic" && activeGroup === "历史/热门") {
      return (
        <div>
          <div className="text-sm text-gray-500 mb-3">热门城市</div>
          <div className="flex flex-wrap gap-2">
            {LIEPIN_HOT_CITIES.map((c) => (
              <CityTag key={c} name={c} selected={value === c} onClick={() => pick(c)} />
            ))}
          </div>
        </div>
      )
    }
    const group = groups.find((g) => g.name === activeGroup)
    if (!group) return null
    // 港澳台：多段子区域
    if (group.subregions) {
      return (
        <div className="space-y-5">
          {group.subregions.map((sub) => (
            <div key={sub.name}>
              <div className="text-sm text-gray-500 mb-3">{sub.name}</div>
              <div className="flex flex-wrap gap-2">
                {sub.cities.map((c) => {
                  const v = `${sub.name}·${c}`
                  return <CityTag key={c} name={c} selected={value === v} onClick={() => pick(v)} />
                })}
              </div>
            </div>
          ))}
        </div>
      )
    }
    // 普通省份/大洲
    return (
      <div>
        <div className="text-sm text-gray-500 mb-3">{group.name}</div>
        <div className="flex flex-wrap gap-2">
          {(group.cities || []).map((c) => {
            const v = `${group.name}·${c}`
            return <CityTag key={c} name={c} selected={value === v} onClick={() => pick(v)} />
          })}
        </div>
      </div>
    )
  }

  return (
    <div className="relative" ref={wrapRef}>
      {/* 触发器 */}
      <input
        readOnly
        value={value || ""}
        placeholder={placeholder}
        onClick={() => {
          setOpen(true)
          // 打开时根据当前值推断 tab
          const inDomestic =
            LIEPIN_HOT_CITIES.includes(value) ||
            LIEPIN_DOMESTIC.some((g) => value.startsWith(g.name + "·") || value.startsWith(g.name))
          setTab(inDomestic || !value ? "domestic" : "overseas")
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

            {/* Tab */}
            <div className="flex gap-6 px-5 pt-3">
              {(["domestic", "overseas"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => {
                    setTab(t)
                    setActiveGroup(t === "domestic" ? "历史/热门" : LIEPIN_OVERSEAS[0].name)
                  }}
                  className={cn(
                    "pb-2 text-sm border-b-2 transition-colors",
                    tab === t ? "text-[#FF6B00] border-[#FF6B00] font-medium" : "text-gray-500 border-transparent hover:text-gray-700"
                  )}
                >
                  {t === "domestic" ? "国内" : "海外"}
                </button>
              ))}
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

/**
 * 猎聘城市多选器（最多选 5 个城市）
 * - 布局与单选器一致：800×530 弹窗，左侧菜单 + 右侧城市网格
 * - 本地 draft 状态，点"确定"才提交
 * - 选满 5 个后未选城市置灰不可点
 */

interface LiepinCityMultiSelectorProps {
  value: string[] // array of selected city names, max 5
  onChange: (value: string[]) => void
  placeholder?: string
}

export function LiepinCityMultiSelector({
  value,
  onChange,
  placeholder = "请选择城市",
}: LiepinCityMultiSelectorProps) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<"domestic" | "overseas">("domestic")
  const [activeGroup, setActiveGroup] = useState<string>("历史/热门")
  // draft is local working copy; only committed on confirm
  const [draft, setDraft] = useState<string[]>(value)
  const wrapRef = useRef<HTMLDivElement>(null)

  // Sync draft when modal opens
  useEffect(() => {
    if (open) setDraft([...value])
  }, [open, value])

  // 点击外部关闭（不提交）
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  const domesticMenu = ["历史/热门", ...LIEPIN_DOMESTIC.map((g) => g.name)]
  const overseasMenu = LIEPIN_OVERSEAS.map((g) => g.name)
  const menu = tab === "domestic" ? domesticMenu : overseasMenu
  const groups: LiepinCityGroup[] = tab === "domestic" ? LIEPIN_DOMESTIC : LIEPIN_OVERSEAS

  const MAX = 5

  const toggleCity = (city: string) => {
    setDraft((prev) => {
      if (prev.includes(city)) return prev.filter((c) => c !== city)
      if (prev.length >= MAX) return prev
      return [...prev, city]
    })
  }

  const confirm = () => {
    onChange(draft)
    setOpen(false)
  }

  const removeCity = (city: string) => {
    onChange(value.filter((c) => c !== city))
  }

  // 渲染右侧城市区（多选版）
  const renderMultiCityPanel = () => {
    // 热门
    if (tab === "domestic" && activeGroup === "历史/热门") {
      return (
        <div>
          <div className="text-sm text-gray-500 mb-3">热门城市</div>
          <div className="flex flex-wrap gap-2">
            {LIEPIN_HOT_CITIES.map((c) => (
              <MultiCityTag
                key={c}
                name={c}
                selected={draft.includes(c)}
                disabled={!draft.includes(c) && draft.length >= MAX}
                onClick={() => toggleCity(c)}
              />
            ))}
          </div>
        </div>
      )
    }
    const group = groups.find((g) => g.name === activeGroup)
    if (!group) return null
    // 港澳台：多段子区域
    if (group.subregions) {
      return (
        <div className="space-y-5">
          {group.subregions.map((sub) => (
            <div key={sub.name}>
              <div className="text-sm text-gray-500 mb-3">{sub.name}</div>
              <div className="flex flex-wrap gap-2">
                {sub.cities.map((c) => {
                  const v = `${sub.name}·${c}`
                  return (
                    <MultiCityTag
                      key={c}
                      name={c}
                      selected={draft.includes(v)}
                      disabled={!draft.includes(v) && draft.length >= MAX}
                      onClick={() => toggleCity(v)}
                    />
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )
    }
    // 普通省份/大洲
    return (
      <div>
        <div className="text-sm text-gray-500 mb-3">{group.name}</div>
        <div className="flex flex-wrap gap-2">
          {(group.cities || []).map((c) => {
            const v = `${group.name}·${c}`
            return (
              <MultiCityTag
                key={c}
                name={c}
                selected={draft.includes(v)}
                disabled={!draft.includes(v) && draft.length >= MAX}
                onClick={() => toggleCity(v)}
              />
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div className="relative" ref={wrapRef}>
      {/* 触发器 */}
      <input
        readOnly
        value={value.length > 0 ? value.join(", ") : ""}
        placeholder={placeholder}
        onClick={() => {
          setOpen(true)
          // 打开时根据当前值推断 tab（取第一个选中城市）
          const first = value[0] || ""
          const inDomestic =
            LIEPIN_HOT_CITIES.includes(first) ||
            LIEPIN_DOMESTIC.some((g) => first.startsWith(g.name + "·") || first.startsWith(g.name))
          setTab(inDomestic || !first ? "domestic" : "overseas")
        }}
        className={cn(
          "w-full h-[40px] rounded-md border bg-background px-3 text-sm cursor-pointer transition-colors",
          "hover:border-[#FF6B00] focus:outline-none",
          open ? "border-[#FF6B00]" : "border-input"
        )}
      />

      {/* 已选城市标签行 */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-2">
          {value.map((city) => (
            <span
              key={city}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-[#FFF5ED] text-[#FF6B00] border border-[#FFD6B0]"
            >
              {city}
              <button
                type="button"
                onClick={() => removeCity(city)}
                className="text-[#FF6B00] hover:text-[#e05e00] leading-none text-sm font-bold"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {/* 城市弹窗 */}
      {open && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl w-[800px] max-w-[92vw] h-[530px] max-h-[86vh] flex flex-col overflow-hidden">
            {/* 标题栏 */}
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <div className="flex items-center gap-3">
                <span className="text-base font-medium text-gray-800">请选择城市</span>
                <span className="text-sm text-[#FF6B00]">已选 {draft.length}/{MAX}</span>
              </div>
              <button className="text-gray-400 hover:text-gray-600 text-xl leading-none" onClick={() => setOpen(false)}>
                ×
              </button>
            </div>

            {/* Tab */}
            <div className="flex gap-6 px-5 pt-3">
              {(["domestic", "overseas"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => {
                    setTab(t)
                    setActiveGroup(t === "domestic" ? "历史/热门" : LIEPIN_OVERSEAS[0].name)
                  }}
                  className={cn(
                    "pb-2 text-sm border-b-2 transition-colors",
                    tab === t ? "text-[#FF6B00] border-[#FF6B00] font-medium" : "text-gray-500 border-transparent hover:text-gray-700"
                  )}
                >
                  {t === "domestic" ? "国内" : "海外"}
                </button>
              ))}
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
              <div className="flex-1 overflow-y-auto p-5">{renderMultiCityPanel()}</div>
            </div>

            {/* 底部确定按钮 */}
            <div className="flex items-center justify-end px-5 py-3 border-t">
              <button
                onClick={confirm}
                className="px-6 py-2 rounded-md bg-[#FF6B00] text-white text-sm font-medium hover:bg-[#e05e00] transition-colors"
              >
                确定
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function MultiCityTag({
  name,
  selected,
  disabled,
  onClick,
}: {
  name: string
  selected: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "px-3 py-1 rounded text-sm border transition-colors",
        selected
          ? "bg-[#FF6B00] text-white border-[#FF6B00]"
          : disabled
            ? "bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed"
            : "bg-white text-gray-700 border-gray-200 hover:border-[#FF6B00] hover:text-[#FF6B00]"
      )}
    >
      {name}
    </button>
  )
}
