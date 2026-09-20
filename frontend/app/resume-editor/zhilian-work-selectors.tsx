"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect, useRef, useCallback } from "react"
import { createPortal } from "react-dom"
import { Loader2, ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  ZHILIAN_JOB_CATEGORIES,
  ZHILIAN_WORK_JOB_TITLES,
  ZHILIAN_INDUSTRIES,
} from "@/lib/zhilian-options"
import type { ZhilianJobCategory, ZhilianIndustry, ZhilianWorkJobTitle } from "@/lib/zhilian-options"

const PRIMARY = "#2A7BFF"

// ========== 职位类别级联选择器 ==========
export function JobCategoryCascader({ value, onChange, data = ZHILIAN_JOB_CATEGORIES }: {
  value: string
  onChange: (code: string, name: string) => void
  data?: ZhilianJobCategory[] | ZhilianWorkJobTitle[]
}) {
  const [open, setOpen] = useState(false)
  const [selL1, setSelL1] = useState<ZhilianJobCategory | null>(null)
  const [selL2, setSelL2] = useState<ZhilianJobCategory | null>(null)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const btnRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const PANEL_W = 540
  const PANEL_H = 320

  const findPath = (code: string): { l1?: ZhilianJobCategory; l2?: ZhilianJobCategory } => {
    for (const l1 of data) {
      for (const l2 of l1.children || []) {
        for (const l3 of l2.children || []) {
          if (l3.code === code) return { l1, l2 }
        }
      }
    }
    return {}
  }

  const displayName = (() => {
    if (!value) return ""
    for (const l1 of data) {
      for (const l2 of l1.children || []) {
        for (const l3 of l2.children || []) {
          if (l3.code === value) return l3.name
        }
      }
    }
    return value
  })()

  const calcPos = useCallback(() => {
    if (!btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    let top = rect.bottom + 4
    if (top + PANEL_H > vh - 10) {
      top = Math.max(10, rect.top - PANEL_H - 4)
    }
    let left = rect.left
    if (left + PANEL_W > vw - 10) {
      left = Math.max(10, vw - PANEL_W - 10)
    }
    setPos({ top, left })
  }, [])

  const toggleOpen = () => {
    if (!open) {
      calcPos()
      const path = findPath(value)
      setSelL1(path.l1 || data[0] || null)
      setSelL2(path.l2 || data[0]?.children?.[0] || null)
    }
    setOpen(!open)
  }

  useEffect(() => {
    if (!open) return
    const handleScroll = (e: Event) => {
      const target = e.target as Node
      if (panelRef.current && panelRef.current.contains(target)) return
      if (btnRef.current && btnRef.current.contains(target)) return
      setOpen(false)
    }
    const handleResize = () => setOpen(false)
    window.addEventListener("scroll", handleScroll, true)
    window.addEventListener("resize", handleResize)
    return () => {
      window.removeEventListener("scroll", handleScroll, true)
      window.removeEventListener("resize", handleResize)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node
      if (btnRef.current?.contains(target)) return
      if (panelRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [open])

  return (
    <div className="relative">
      <button
        ref={btnRef}
        type="button"
        onClick={toggleOpen}
        className={cn(
          "w-full h-9 px-3 text-sm border rounded-md bg-white text-left flex items-center justify-between transition-colors",
          open ? "border-[#2A7BFF] ring-1 ring-[#2A7BFF]" : "border-gray-300 hover:border-gray-400"
        )}
      >
        <span className={displayName ? "text-gray-900" : "text-gray-400"}>{displayName || "请选择职位类别"}</span>
        <ChevronDown className={cn("w-3.5 h-3.5 text-gray-400 transition-transform", open && "rotate-180")} />
      </button>
      {open && typeof document !== "undefined" && createPortal(
        <div
          ref={panelRef}
          className="fixed z-[9999] bg-white border border-gray-200 rounded-lg shadow-xl flex select-none overflow-hidden animate-in fade-in-50 zoom-in-95 duration-100"
          style={{ width: PANEL_W, top: pos.top, left: pos.left, height: PANEL_H }}
        >
          <div className="w-[160px] border-r border-gray-100 h-full overflow-y-auto py-1 bg-gray-50/50">
            {data.map(l1 => (
              <button
                key={l1.code}
                type="button"
                onMouseEnter={() => { setSelL1(l1); setSelL2(l1.children?.[0] || null) }}
                onClick={() => { setSelL1(l1); setSelL2(l1.children?.[0] || null) }}
                className={cn(
                  "w-full px-3 py-1.5 text-xs text-left transition-colors flex items-center justify-between",
                  selL1?.code === l1.code ? "text-white font-medium shadow-sm" : "text-gray-700 hover:bg-gray-100/80"
                )}
                style={selL1?.code === l1.code ? { backgroundColor: PRIMARY } : {}}
              >
                <span className="truncate">{l1.name}</span>
                <span className="text-[10px] opacity-60 ml-1 shrink-0">{">"}</span>
              </button>
            ))}
          </div>
          {selL1 && (
            <div className="w-[160px] border-r border-gray-100 h-full overflow-y-auto py-1 bg-white">
              {(selL1.children || []).map(l2 => (
                <button
                  key={l2.code}
                  type="button"
                  onMouseEnter={() => setSelL2(l2)}
                  onClick={() => setSelL2(l2)}
                  className={cn(
                    "w-full px-3 py-1.5 text-xs text-left transition-colors flex items-center justify-between",
                    selL2?.code === l2.code ? "text-[#2A7BFF] bg-blue-50/80 font-medium" : "text-gray-700 hover:bg-gray-50"
                  )}
                >
                  <span className="truncate">{l2.name}</span>
                  <span className="text-[10px] text-gray-400 ml-1 shrink-0">{">"}</span>
                </button>
              ))}
            </div>
          )}
          {selL2 && (
            <div className="flex-1 h-full overflow-y-auto p-3 bg-white">
              <div className="flex flex-wrap gap-1.5">
                {(selL2.children || []).map(l3 => (
                  <button
                    key={l3.code}
                    type="button"
                    onClick={() => { onChange(l3.code, l3.name); setOpen(false) }}
                    className={cn(
                      "px-2.5 py-1 text-xs rounded border transition-all",
                      value === l3.code
                        ? "border-[#2A7BFF] bg-blue-50 text-[#2A7BFF] font-medium"
                        : "border-gray-200 text-gray-700 bg-white hover:border-[#2A7BFF] hover:text-[#2A7BFF]"
                    )}
                  >
                    {l3.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>,
        document.body
      )}
    </div>
  )
}

// ========== 行业类别选择器 ==========
export function IndustrySelect({ selected, onChange, showUnlimited = true, maxSelect = 3 }: {
  selected: { code: string; name: string }[]
  onChange: (items: { code: string; name: string }[]) => void
  showUnlimited?: boolean
  maxSelect?: number
}) {
  const [open, setOpen] = useState(false)
  const [selL1, setSelL1] = useState<ZhilianIndustry | null>(null)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const btnRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const PANEL_W = 540
  const PANEL_H = 320

  const toggleIndustry = (code: string, name: string) => {
    if (code === "-1") {
      if (selected.some(s => s.code === "-1")) {
        onChange([])
      } else {
        onChange([{ code: "-1", name: "不限" }])
      }
      if (maxSelect === 1) setOpen(false)
      return
    }
    const exists = selected.find(s => s.code === code)
    if (exists) {
      onChange(selected.filter(s => s.code !== code))
    } else if (maxSelect === 1) {
      onChange([{ code, name }])
      setOpen(false)
    } else if (selected.length < maxSelect) {
      const filtered = selected.filter(s => s.code !== "-1")
      onChange([...filtered, { code, name }])
    }
  }

  const industries = showUnlimited ? ZHILIAN_INDUSTRIES : ZHILIAN_INDUSTRIES.filter(i => i.name !== "不限")

  const calcPos = useCallback(() => {
    if (!btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    let top = rect.bottom + 4
    if (top + PANEL_H > vh - 10) {
      top = Math.max(10, rect.top - PANEL_H - 4)
    }
    let left = rect.left
    if (left + PANEL_W > vw - 10) {
      left = Math.max(10, vw - PANEL_W - 10)
    }
    setPos({ top, left })
  }, [])

  const toggleOpen = () => {
    if (!open) {
      calcPos()
      if (!selL1) {
        const first = industries.find(i => i.name !== "不限")
        if (first) setSelL1(first)
      }
    }
    setOpen(!open)
  }

  useEffect(() => {
    if (!open) return
    const handleScroll = (e: Event) => {
      const target = e.target as Node
      // 关键修复：如果滚动发生在选择器面板内部，绝不关闭弹窗！
      if (panelRef.current && panelRef.current.contains(target)) return
      if (btnRef.current && btnRef.current.contains(target)) return
      setOpen(false)
    }
    const handleResize = () => setOpen(false)
    window.addEventListener("scroll", handleScroll, true)
    window.addEventListener("resize", handleResize)
    return () => {
      window.removeEventListener("scroll", handleScroll, true)
      window.removeEventListener("resize", handleResize)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node
      if (btnRef.current?.contains(target)) return
      if (panelRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [open])

  return (
    <div className="relative">
      <button
        ref={btnRef}
        type="button"
        onClick={toggleOpen}
        className={cn(
          "w-full min-h-9 px-3 py-1.5 text-sm border rounded-md bg-white text-left flex items-center justify-between transition-colors",
          open ? "border-[#2A7BFF] ring-1 ring-[#2A7BFF]" : "border-gray-300 hover:border-gray-400"
        )}
      >
        <span className="flex flex-wrap gap-1 items-center">
          {selected.length > 0 ? selected.map(s => (
            <span key={s.code} className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-[#2A7BFF] text-xs rounded font-medium border border-blue-100">
              {s.name}
              <span
                className="cursor-pointer hover:text-red-500 font-bold ml-0.5"
                onClick={e => { e.stopPropagation(); toggleIndustry(s.code, s.name) }}
              >
                ×
              </span>
            </span>
          )) : (
            <span className="text-gray-400">{maxSelect === 1 ? "请选择所属行业" : "请选择行业（最多3个）"}</span>
          )}
        </span>
        <div className="flex items-center gap-1.5 ml-2 shrink-0">
          {maxSelect > 1 && (
            <span className="text-xs text-gray-400">{selected.length}/{maxSelect}</span>
          )}
          <ChevronDown className={cn("w-3.5 h-3.5 text-gray-400 transition-transform", open && "rotate-180")} />
        </div>
      </button>
      {open && typeof document !== "undefined" && createPortal(
        <div
          ref={panelRef}
          className="fixed z-[9999] bg-white border border-gray-200 rounded-lg shadow-xl flex select-none overflow-hidden animate-in fade-in-50 zoom-in-95 duration-100"
          style={{ width: PANEL_W, top: pos.top, left: pos.left, height: PANEL_H }}
        >
          {/* 左侧一级行业列表 */}
          <div className="w-[185px] border-r border-gray-100 h-full overflow-y-auto py-1 bg-gray-50/60">
            {industries.map(ind => (
              <button
                key={ind.code}
                type="button"
                onMouseEnter={() => {
                  if (ind.code !== "-1") setSelL1(ind)
                }}
                onClick={() => {
                  if (ind.code === "-1") {
                    toggleIndustry("-1", "不限")
                  } else {
                    setSelL1(ind)
                  }
                }}
                className={cn(
                  "w-full px-3 py-2 text-xs text-left transition-colors flex items-center justify-between",
                  ind.code === "-1"
                    ? (selected.some(s => s.code === "-1")
                        ? "text-[#2A7BFF] font-semibold bg-blue-50/70"
                        : "text-gray-700 hover:bg-gray-100/80")
                    : (selL1?.code === ind.code
                        ? "text-white font-medium shadow-sm"
                        : "text-gray-700 hover:bg-gray-100/80")
                )}
                style={ind.code !== "-1" && selL1?.code === ind.code ? { backgroundColor: PRIMARY } : {}}
              >
                <span className="truncate">{ind.name}</span>
                {ind.code === "-1" ? (
                  selected.some(s => s.code === "-1") ? <span className="text-[#2A7BFF] font-bold">✓</span> : null
                ) : (
                  <span className="text-[10px] opacity-60 ml-1 shrink-0">{">"}</span>
                )}
              </button>
            ))}
          </div>

          {/* 右侧二级细分行业列表 */}
          {selL1 && (
            <div className="flex-1 h-full overflow-y-auto p-3 bg-white">
              <div className="text-[11px] text-gray-400 mb-2 font-medium">
                {selL1.name}（最多选择 {maxSelect} 个）
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(selL1.children || []).map(sub => {
                  const isSelected = selected.some(s => s.code === sub.code)
                  return (
                    <button
                      key={sub.code}
                      type="button"
                      onClick={() => toggleIndustry(sub.code, sub.name)}
                      className={cn(
                        "px-2.5 py-1.5 text-xs rounded border transition-all text-left",
                        isSelected
                          ? "border-[#2A7BFF] bg-[#2A7BFF] text-white font-medium shadow-sm"
                          : "border-gray-200 bg-white text-gray-700 hover:border-[#2A7BFF] hover:text-[#2A7BFF]",
                        !isSelected && selected.length >= maxSelect && "opacity-40 cursor-not-allowed hover:border-gray-200 hover:text-gray-700"
                      )}
                      disabled={!isSelected && selected.length >= maxSelect}
                    >
                      {sub.name}
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>,
        document.body
      )}
    </div>
  )
}

// ========== 拥有技能选择器 ==========
export interface SkillItem { id: number; name: string; isCustom?: boolean; pathId?: number }
interface SkillGroup { id: number; name: string; children: { id: number; name: string }[]; maxCount: number }

export function SkillSelect({ jobTypeId, value, onChange }: {
  jobTypeId: string
  value: SkillItem[]
  onChange: (items: SkillItem[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [tempSelected, setTempSelected] = useState<SkillItem[]>([])
  const [customInputs, setCustomInputs] = useState<Record<string, string>>({})
  const [showCustomFor, setShowCustomFor] = useState<string | null>(null)
  const [groups, setGroups] = useState<SkillGroup[]>([])
  const [loading, setLoading] = useState(false)

  const openModal = async () => {
    // 防御性规范化：确保 tempSelected 每个元素具有合规 ID 和 name
    const sanitized = (value || []).map((s: any, idx: number) => {
      if (typeof s === "string") {
        return { id: 300000000 + Math.floor(Math.random() * 90000000) + idx, name: s.trim(), isCustom: true, pathId: -1 }
      }
      const rawId = Number(s?.id || s?.skillId)
      return {
        ...s,
        id: rawId && !isNaN(rawId) ? rawId : (300000000 + Math.floor(Math.random() * 90000000) + idx),
        name: s?.name || s?.tagValue || "",
        pathId: s?.pathId !== undefined ? Number(s.pathId) : -1,
      }
    }).filter((s: SkillItem) => s.name)
    setTempSelected(sanitized)
    setCustomInputs({})
    setShowCustomFor(null)
    setOpen(true)
    if (jobTypeId) {
      setLoading(true)
      try {
        const resp = await fetch(`${API_BASE}/api/resume-editor/zhilian/work-skills/${jobTypeId}`)
        const json = await resp.json()
        if (json.success && Array.isArray(json.data)) {
          const parsed: SkillGroup[] = json.data
            .filter((g: any) => !g.isIndustry && g.children && g.children.length > 0)
            .map((g: any) => ({ id: g.id, name: g.name, children: g.children, maxCount: g.maxCount || 3 }))
          setGroups(parsed)
        } else {
          setGroups([])
        }
      } catch {
        setGroups([])
      } finally {
        setLoading(false)
      }
    } else {
      setGroups([])
    }
  }

  const getGroupSelected = (groupId: number | string) => {
    return tempSelected.filter(s => s.pathId === groupId)
  }

  const toggleOption = (groupId: number | string, opt: SkillItem, maxCount: number) => {
    const groupSel = getGroupSelected(groupId)
    const exists = groupSel.find(s => s.id === opt.id)
    if (exists) {
      setTempSelected(tempSelected.filter(s => s.id !== opt.id))
    } else if (groupSel.length < maxCount) {
      setTempSelected([...tempSelected, { ...opt, pathId: Number(groupId) }])
    }
  }

  const addCustom = (groupId: number | string, maxCount: number) => {
    const key = String(groupId)
    const name = (customInputs[key] || customInputs[key === "-1" ? "general" : key] || "").trim()
    if (!name) return
    const groupSel = getGroupSelected(groupId)
    if (groupSel.length >= maxCount) return
    // 智联官方自定义技能 ID 均为 9 位整型（300000000~389999999），避免 13 位时间戳导致的 SQL 溢出
    const newId = 300000000 + Math.floor(Math.random() * 90000000)
    setTempSelected([...tempSelected, { id: newId, name, isCustom: true, pathId: key === "general" || key === "-1" ? -1 : Number(groupId) }])
    setCustomInputs({ ...customInputs, [key]: "", general: "", "-1": "" })
    setShowCustomFor(null)
  }

  const removeSelected = (id: number, idx?: number) => {
    if (id) {
      setTempSelected(tempSelected.filter(s => s.id !== id))
    } else if (idx !== undefined) {
      setTempSelected(tempSelected.filter((_, i) => i !== idx))
    }
  }

  const confirm = () => {
    onChange(tempSelected)
    setOpen(false)
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={openModal}
        className="w-full min-h-9 px-3 py-1.5 text-sm border border-gray-300 rounded-md bg-white text-left flex items-center justify-between hover:border-[#2A7BFF] transition-colors"
      >
        <span className="flex flex-wrap gap-1">
          {value.length > 0 ? value.map((s, idx) => (
            <span key={s.id ? `skill-${s.id}` : `skill-fallback-${s.name || idx}-${idx}`} className="inline-flex items-center px-1.5 py-0.5 bg-blue-50 text-[#2A7BFF] text-xs rounded">{s.name}</span>
          )) : <span className="text-gray-400">点击添加技能标签</span>}
        </span>
        <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0 ml-2" />
      </button>

      {open && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="relative bg-white rounded-xl shadow-2xl w-[520px] max-h-[80vh] flex flex-col">
            <div className="px-6 pt-5 pb-3 border-b border-gray-100">
              <h3 className="text-base font-medium text-gray-900">丰富专业技能，招聘方会更加了解你~~</h3>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
              {loading && (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 animate-spin text-[#2A7BFF]" />
                  <span className="ml-2 text-sm text-gray-400">加载技能数据...</span>
                </div>
              )}
              {!loading && groups.length === 0 && (
                <div className="text-sm text-gray-400 text-center py-4">该职位类型暂无预设技能选项，可自定义添加</div>
              )}
              {!loading && groups.map(group => {
                const groupSel = getGroupSelected(group.id)
                return (
                  <div key={group.id}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-sm font-medium text-gray-800">{group.name}</span>
                      <span className="text-xs text-gray-400">({groupSel.length}/{group.maxCount})</span>
                    </div>
                    <p className="text-xs text-gray-400 mb-2">最多选择{group.maxCount}个选项</p>
                    <div className="flex flex-wrap gap-2">
                      {group.children.map(opt => {
                        const isSelected = groupSel.some(s => s.id === opt.id)
                        const isDisabled = !isSelected && groupSel.length >= group.maxCount
                        return (
                          <button
                            key={opt.id}
                            type="button"
                            onClick={() => toggleOption(group.id, { id: opt.id, name: opt.name }, group.maxCount)}
                            disabled={isDisabled}
                            className={cn(
                              "px-3 py-1.5 text-xs rounded-full border transition-colors",
                              isSelected ? "bg-[#E8F1FF] border-[#2A7BFF] text-[#2A7BFF]" : "bg-gray-50 border-gray-200 text-gray-700 hover:border-gray-300",
                              isDisabled && "opacity-40 cursor-not-allowed"
                            )}
                          >
                            {opt.name}
                          </button>
                        )
                      })}
                      {showCustomFor === String(group.id) ? (
                        <span className="inline-flex items-center gap-1">
                          <input
                            className="w-24 h-7 px-2 text-xs border border-[#2A7BFF] rounded-full focus:outline-none"
                            value={customInputs[String(group.id)] || ""}
                            onChange={e => setCustomInputs({ ...customInputs, [String(group.id)]: e.target.value })}
                            onKeyDown={e => {
                              if (e.key === "Enter") {
                                e.preventDefault()
                                e.stopPropagation()
                                addCustom(group.id, group.maxCount)
                              }
                            }}
                            placeholder="输入后回车"
                            autoFocus
                          />
                          <button type="button" onClick={() => addCustom(group.id, group.maxCount)} className="text-xs text-[#2A7BFF]">添加</button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setShowCustomFor(String(group.id))}
                          disabled={groupSel.length >= group.maxCount}
                          className={cn("px-3 py-1.5 text-xs rounded-full border border-dashed border-gray-300 text-gray-500 hover:border-[#2A7BFF] hover:text-[#2A7BFF]", groupSel.length >= group.maxCount && "opacity-40 cursor-not-allowed")}
                        >
                          + 自定义
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
              {!loading && (() => {
                const gId = -1
                const maxCount = 3
                const groupSel = getGroupSelected(gId)
                return (
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-sm font-medium text-gray-800">其他技能</span>
                      <span className="text-xs text-gray-400">({groupSel.length}/{maxCount})</span>
                    </div>
                    <p className="text-xs text-gray-400 mb-2">最多选择{maxCount}个选项</p>
                    <div className="flex flex-wrap gap-2">
                      {showCustomFor === "general" || showCustomFor === "-1" ? (
                        <span className="inline-flex items-center gap-1">
                          <input
                            className="w-32 h-7 px-2 text-xs border border-[#2A7BFF] rounded-full focus:outline-none"
                            value={customInputs["general"] || customInputs["-1"] || ""}
                            onChange={e => setCustomInputs({ ...customInputs, general: e.target.value, "-1": e.target.value })}
                            onKeyDown={e => {
                              if (e.key === "Enter") {
                                e.preventDefault()
                                e.stopPropagation()
                                addCustom(gId, maxCount)
                              }
                            }}
                            placeholder="输入后回车"
                            autoFocus
                          />
                          <button type="button" onClick={() => addCustom(gId, maxCount)} className="text-xs text-[#2A7BFF]">添加</button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setShowCustomFor("general")}
                          disabled={groupSel.length >= maxCount}
                          className={cn("px-3 py-1.5 text-xs rounded-full border border-dashed border-gray-300 text-gray-500 hover:border-[#2A7BFF] hover:text-[#2A7BFF]", groupSel.length >= maxCount && "opacity-40 cursor-not-allowed")}
                        >
                          + 自定义
                        </button>
                      )}
                    </div>
                  </div>
                )
              })()}
            </div>
            {tempSelected.length > 0 && (
              <div className="px-6 py-2 border-t border-gray-100">
                <div className="flex flex-wrap gap-1.5">
                  {tempSelected.map((s, idx) => (
                    <span key={s.id ? `temp-skill-${s.id}` : `temp-skill-fallback-${s.name || idx}-${idx}`} className="inline-flex items-center gap-0.5 px-2 py-0.5 bg-blue-50 text-[#2A7BFF] text-xs rounded-full">
                      {s.name}
                      <span className="cursor-pointer hover:text-red-500 ml-0.5" onClick={() => removeSelected(s.id, idx)}>×</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
              <button type="button" onClick={() => setOpen(false)} className="px-4 py-1.5 text-sm border border-[#2A7BFF] text-[#2A7BFF] rounded-full hover:bg-blue-50">取消</button>
              <button type="button" onClick={confirm} className="px-4 py-1.5 text-sm text-white rounded-full" style={{ backgroundColor: PRIMARY }}>确定 · {tempSelected.length}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
