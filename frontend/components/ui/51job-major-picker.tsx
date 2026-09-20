"use client"

import { useState, useEffect, useMemo } from "react"
import { X, Search } from "lucide-react"

interface MajorNode { code: string; name: string; children?: MajorNode[] }

interface Job51MajorPickerProps {
  open: boolean
  onClose: () => void
  /** 已选专业 code */
  selectedCode: string
  onConfirm: (code: string, name: string, categoryName: string) => void
}

export function Job51MajorPicker({ open, onClose, selectedCode, onConfirm }: Job51MajorPickerProps) {
  const [tree, setTree] = useState<MajorNode[]>([])
  const [activeCol0, setActiveCol0] = useState(0)
  const [activeCol1, setActiveCol1] = useState(0)
  const [search, setSearch] = useState("")
  const [localSelected, setLocalSelected] = useState<{ code: string; name: string; categoryName: string } | null>(null)

  useEffect(() => {
    fetch("/51job_majors.json")
      .then((r) => r.json())
      .then(setTree)
      .catch(() => {})
  }, [])

  // 打开时重置搜索
  useEffect(() => {
    if (open) {
      setSearch("")
      setLocalSelected(null)
    }
  }, [open])

  // 搜索：在所有三级专业中匹配
  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const kw = search.trim().toLowerCase()
    const results: { code: string; name: string; categoryName: string; subName: string }[] = []
    for (const cat of tree) {
      for (const sub of cat.children || []) {
        for (const leaf of sub.children || []) {
          if (leaf.name.toLowerCase().includes(kw)) {
            results.push({ code: leaf.code, name: leaf.name, categoryName: cat.name, subName: sub.name })
          }
        }
      }
    }
    return results
  }, [search, tree])

  if (!open) return null

  const col0 = tree
  const col1 = col0[activeCol0]?.children || []
  const col2 = col1[activeCol1]?.children || []

  const handleConfirm = () => {
    if (localSelected) {
      onConfirm(localSelected.code, localSelected.name, localSelected.categoryName)
      onClose()
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-[780px] max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <span className="text-base font-bold text-gray-900">选择专业</span>
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
        <div className="flex flex-1 overflow-hidden min-h-[360px]">
          {searchResults ? (
            /* 搜索结果 */
            <div className="flex-1 overflow-y-auto py-3 px-4">
              {searchResults.length === 0 ? (
                <div className="text-sm text-gray-400 text-center py-8">无匹配结果</div>
              ) : (
                <div className="grid grid-cols-3 gap-x-4">
                  {searchResults.slice(0, 60).map((item) => (
                    <button
                      key={item.code}
                      onClick={() => setLocalSelected({ code: item.code, name: item.name, categoryName: item.categoryName })}
                      className={`text-left px-3 py-2 text-[13px] rounded transition-colors ${
                        localSelected?.code === item.code ? "text-[#FF6B00] bg-[#FFF7F0] font-medium" : "text-gray-700 hover:bg-gray-50"
                      }`}
                    >
                      {item.name}
                      <span className="text-xs text-gray-400 ml-1">({item.categoryName})</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            /* 三级浏览：左=一级大类，中=二级专业类，右=三级具体专业 */
            <>
              {/* 一级大类 */}
              <div className="w-[160px] overflow-y-auto border-r border-gray-100 py-2 flex-shrink-0">
                {col0.map((item, i) => (
                  <div
                    key={item.code}
                    onClick={() => { setActiveCol0(i); setActiveCol1(0) }}
                    className={`px-4 py-2.5 text-[13px] cursor-pointer transition-colors ${
                      i === activeCol0 ? "text-[#FF6B00] bg-[#FFF7F0] font-medium" : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    {item.name}
                  </div>
                ))}
              </div>

              {/* 二级专业类 */}
              <div className="w-[180px] overflow-y-auto border-r border-gray-100 py-2 flex-shrink-0">
                {col1.map((item, i) => (
                  <div
                    key={item.code}
                    onClick={() => setActiveCol1(i)}
                    className={`px-4 py-2.5 text-[13px] cursor-pointer transition-colors ${
                      i === activeCol1 ? "text-[#FF6B00] font-medium" : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    {item.name}
                  </div>
                ))}
              </div>

              {/* 三级具体专业 */}
              <div className="flex-1 overflow-y-auto py-3 px-4">
                <div className="grid grid-cols-2 gap-x-4">
                  {col2.map((item) => (
                    <button
                      key={item.code}
                      onClick={() => setLocalSelected({ code: item.code, name: item.name, categoryName: col0[activeCol0]?.name || "" })}
                      className={`text-left px-3 py-2 text-[13px] rounded transition-colors ${
                        localSelected?.code === item.code || item.code === selectedCode
                          ? "text-[#FF6B00] bg-[#FFF7F0] font-medium"
                          : "text-gray-700 hover:bg-gray-50"
                      }`}
                    >
                      {item.name}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-5 py-3 border-t border-gray-100">
          <button onClick={onClose} className="px-5 py-2 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50">
            取消
          </button>
          <button
            onClick={handleConfirm}
            disabled={!localSelected}
            className={`px-5 py-2 text-sm rounded-md ${
              localSelected ? "text-white bg-[#FF6B00] hover:bg-[#e55f00]" : "text-gray-400 bg-gray-200 cursor-not-allowed"
            }`}
          >
            完成
          </button>
        </div>
      </div>
    </div>
  )
}
