"use client"

import { useState, useMemo } from "react"
import { X, Search, Check } from "lucide-react"
import { JOB51_FUNTYPE_TREE, type Job51FuntypeItem } from "@/lib/51job-options"

interface Job51FuntypePickerProps {
  open: boolean
  onClose: () => void
  /** 已选职位 code */
  selectedCode: string
  onConfirm: (code: string, name: string, path: string[]) => void
}

export function Job51FuntypePicker({ open, onClose, selectedCode, onConfirm }: Job51FuntypePickerProps) {
  const [activeCol0, setActiveCol0] = useState(0)
  const [activeCol1, setActiveCol1] = useState(0)
  const [search, setSearch] = useState("")

  const col0 = JOB51_FUNTYPE_TREE
  const col1 = col0[activeCol0]?.items || []
  const col2 = col1[activeCol1]?.items || []

  // 搜索：在所有三级中匹配
  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const kw = search.trim().toLowerCase()
    const results: { item: Job51FuntypeItem; path: string[] }[] = []
    for (const c0 of JOB51_FUNTYPE_TREE) {
      for (const c1 of c0.items || []) {
        for (const c2 of c1.items || []) {
          if (c2.value.toLowerCase().includes(kw)) {
            results.push({ item: c2, path: [c0.value, c1.value, c2.value] })
          }
        }
        if (c1.value.toLowerCase().includes(kw)) {
          results.push({ item: c1, path: [c0.value, c1.value] })
        }
      }
    }
    return results.slice(0, 20)
  }, [search])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-[680px] max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <span className="text-base font-bold text-gray-900">请选择职位</span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3">
          <div className="flex items-center gap-2 h-9 px-3 border border-gray-300 rounded-full focus-within:border-[#FF6B00]">
            <Search className="w-4 h-4 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="请输入"
              className="flex-1 text-sm outline-none"
            />
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-hidden">
          {searchResults ? (
            /* 搜索结果 */
            <div className="px-5 pb-4 max-h-[400px] overflow-y-auto">
              {searchResults.length === 0 ? (
                <div className="text-sm text-gray-400 py-4 text-center">未搜索到结果</div>
              ) : (
                searchResults.map((r, i) => (
                  <button
                    key={i}
                    onClick={() => { onConfirm(r.item.code, r.item.value, r.path); onClose() }}
                    className={`w-full text-left px-3 py-2 text-[13px] rounded transition-colors flex items-center justify-between ${
                      r.item.code === selectedCode ? "text-[#FF6B00] bg-[#FFF7F0]" : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    <span>{r.path.join(" > ")}</span>
                    {r.item.code === selectedCode && <Check className="w-4 h-4 text-[#FF6B00]" />}
                  </button>
                ))
              )}
            </div>
          ) : (
            /* 三列选择 */
            <div className="flex max-h-[400px]">
              {/* 一级分类 */}
              <div className="w-[180px] overflow-y-auto border-r border-gray-100">
                {col0.map((item, i) => (
                  <div
                    key={item.code}
                    onMouseEnter={() => { setActiveCol0(i); setActiveCol1(0) }}
                    className={`px-4 py-2.5 text-[13px] cursor-pointer transition-colors ${
                      i === activeCol0 ? "text-[#FF6B00] bg-[#FFF7F0] font-medium" : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    {item.value}
                  </div>
                ))}
              </div>
              {/* 二级分类 */}
              <div className="w-[180px] overflow-y-auto border-r border-gray-100">
                {col1.map((item, i) => (
                  <div
                    key={item.code}
                    onMouseEnter={() => setActiveCol1(i)}
                    className={`px-4 py-2.5 text-[13px] cursor-pointer transition-colors ${
                      i === activeCol1 ? "text-[#FF6B00] bg-[#FFF7F0] font-medium" : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    {item.value}
                  </div>
                ))}
              </div>
              {/* 三级分类 */}
              <div className="flex-1 overflow-y-auto">
                {col2.map((item) => (
                  <button
                    key={item.code}
                    onClick={() => {
                      onConfirm(item.code, item.value, [col0[activeCol0]?.value || "", col1[activeCol1]?.value || "", item.value])
                      onClose()
                    }}
                    className={`w-full text-left px-4 py-2.5 text-[13px] cursor-pointer transition-colors flex items-center justify-between ${
                      item.code === selectedCode ? "text-[#FF6B00] font-medium" : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    <span>{item.value}</span>
                    {item.code === selectedCode && <Check className="w-4 h-4 text-[#FF6B00]" />}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
