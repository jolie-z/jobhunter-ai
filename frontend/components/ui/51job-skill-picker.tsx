"use client"

import { useState, useEffect, useMemo } from "react"
import { X, Search } from "lucide-react"

interface SkillNode { code: string; name: string; children?: SkillNode[] }

interface Job51SkillPickerProps {
  open: boolean
  onClose: () => void
  selectedCode: string
  onConfirm: (code: string, name: string, categoryName: string) => void
  disabledCodes?: string[]
  disabledNames?: string[]
}

export function Job51SkillPicker({
  open,
  onClose,
  selectedCode,
  onConfirm,
  disabledCodes = [],
  disabledNames = [],
}: Job51SkillPickerProps) {
  const [tree, setTree] = useState<SkillNode[]>([])
  const [activeCat, setActiveCat] = useState(0)
  const [search, setSearch] = useState("")

  useEffect(() => {
    fetch("/51job_skills.json")
      .then((r) => r.json())
      .then(setTree)
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (open) setSearch("")
  }, [open])

  const isSkillDisabled = (code: string, name: string) => {
    if (disabledCodes && disabledCodes.some((c) => String(c).trim() === String(code).trim())) return true
    if (disabledNames && disabledNames.some((n) => n.trim().toLowerCase() === name.trim().toLowerCase())) return true
    return false
  }

  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const kw = search.trim().toLowerCase()
    const results: { code: string; name: string; categoryName: string }[] = []
    for (const cat of tree) {
      for (const skill of cat.children || []) {
        if (skill.name.toLowerCase().includes(kw)) {
          results.push({ code: skill.code, name: skill.name, categoryName: cat.name })
        }
      }
    }
    return results
  }, [search, tree])

  if (!open) return null

  const categories = tree
  const skills = categories[activeCat]?.children || []

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-[680px] max-h-[70vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <span className="text-base font-bold text-gray-900">请选择技能</span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3 border-b border-gray-50">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="请输入"
              className="w-full h-[36px] pl-9 pr-3 rounded-full border border-gray-200 bg-gray-50 text-sm focus:outline-none focus:border-[#FF6B00] focus:bg-white"
            />
          </div>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden min-h-[300px]">
          {searchResults ? (
            <div className="flex-1 overflow-y-auto py-3 px-4">
              {searchResults.length === 0 ? (
                <div className="text-sm text-gray-400 text-center py-8">无匹配结果</div>
              ) : (
                <div className="grid grid-cols-3 gap-x-4 gap-y-1">
                  {searchResults.map((item) => {
                    const disabled = isSkillDisabled(item.code, item.name)
                    return (
                      <button
                        key={item.code}
                        disabled={disabled}
                        onClick={() => {
                          if (disabled) return
                          onConfirm(item.code, item.name, item.categoryName)
                          onClose()
                        }}
                        className={`text-left px-3 py-2.5 text-[13px] rounded transition-colors flex items-center justify-between ${
                          disabled
                            ? "text-gray-400 bg-gray-50/80 cursor-not-allowed opacity-60"
                            : item.code === selectedCode
                            ? "text-[#FF6B00] bg-[#FFF7F0] font-medium"
                            : "text-gray-700 hover:bg-gray-50 cursor-pointer"
                        }`}
                      >
                        <span className="truncate">{item.name}</span>
                        {disabled && <span className="text-[11px] text-gray-400 font-normal ml-1 flex-shrink-0">已添加</span>}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ) : (
            <>
              {/* 左侧分类 */}
              <div className="w-[160px] overflow-y-auto border-r border-gray-100 py-2 flex-shrink-0">
                {categories.map((cat, i) => (
                  <div
                    key={cat.code}
                    onClick={() => setActiveCat(i)}
                    className={`px-4 py-2.5 text-[13px] cursor-pointer transition-colors ${
                      i === activeCat ? "text-[#FF6B00] bg-[#FFF7F0] font-medium" : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    {cat.name}
                  </div>
                ))}
              </div>

              {/* 右侧技能网格 */}
              <div className="flex-1 overflow-y-auto py-3 px-4">
                <div className="grid grid-cols-3 gap-x-4 gap-y-1">
                  {skills.map((skill) => {
                    const disabled = isSkillDisabled(skill.code, skill.name)
                    return (
                      <button
                        key={skill.code}
                        disabled={disabled}
                        onClick={() => {
                          if (disabled) return
                          onConfirm(skill.code, skill.name, categories[activeCat]?.name || "")
                          onClose()
                        }}
                        className={`text-left px-3 py-2.5 text-[13px] rounded transition-colors flex items-center justify-between ${
                          disabled
                            ? "text-gray-400 bg-gray-50/80 cursor-not-allowed opacity-60"
                            : skill.code === selectedCode
                            ? "text-[#FF6B00] bg-[#FFF7F0] font-medium"
                            : "text-gray-700 hover:bg-gray-50 cursor-pointer"
                        }`}
                      >
                        <span className="truncate">{skill.name}</span>
                        {disabled && <span className="text-[11px] text-gray-400 font-normal ml-1 flex-shrink-0">已添加</span>}
                      </button>
                    )
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
