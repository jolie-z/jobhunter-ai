"use client"

import { useState, useEffect, useMemo } from "react"
import { X, Search } from "lucide-react"

interface CertNode { code: string; name: string; children?: CertNode[] }

interface Job51CertPickerProps {
  open: boolean
  onClose: () => void
  /** 已选证书 code 列表 */
  selected: string[]
  onConfirm: (codes: string[]) => void
  maxSelect?: number
}

export function Job51CertPicker({ open, onClose, selected, onConfirm, maxSelect = 20 }: Job51CertPickerProps) {
  const [tree, setTree] = useState<CertNode[]>([])
  const [activeCat, setActiveCat] = useState(0)
  const [search, setSearch] = useState("")
  const [localSelected, setLocalSelected] = useState<string[]>([])

  useEffect(() => {
    fetch("/51job_certificates.json")
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setTree(data)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (open) {
      setSearch("")
      setLocalSelected([...selected])
    }
  }, [open, selected])

  // 构建 code→name 映射
  const codeNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    const safeTree = Array.isArray(tree) ? tree : []
    for (const cat of safeTree) {
      for (const cert of cat.children || []) {
        map[cert.code] = cert.name
      }
    }
    return map
  }, [tree])

  const searchResults = useMemo(() => {
    if (!search.trim()) return null
    const kw = search.trim().toLowerCase()
    const results: { code: string; name: string; categoryName: string }[] = []
    const safeTree = Array.isArray(tree) ? tree : []
    for (const cat of safeTree) {
      for (const cert of cat.children || []) {
        if (cert.name.toLowerCase().includes(kw)) {
          results.push({ code: cert.code, name: cert.name, categoryName: cat.name })
        }
      }
    }
    return results
  }, [search, tree])

  if (!open) return null

  const categories = tree
  const certs = categories[activeCat]?.children || []

  const toggleCert = (code: string) => {
    if (localSelected.includes(code)) {
      setLocalSelected(localSelected.filter((c) => c !== code))
    } else if (localSelected.length < maxSelect) {
      setLocalSelected([...localSelected, code])
    }
  }

  const removeSelected = (code: string) => {
    setLocalSelected(localSelected.filter((c) => c !== code))
  }

  const handleConfirm = () => {
    onConfirm(localSelected)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-[720px] max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <span className="text-base font-bold text-gray-900">选择证书</span>
            <span className="text-xs text-gray-400">已选 ({localSelected.length} / {maxSelect})</span>
          </div>
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

        {/* Selected tags */}
        {localSelected.length > 0 && (
          <div className="px-5 py-2 border-b border-gray-50 flex flex-wrap gap-2">
            {localSelected.map((code) => (
              <span key={code} className="inline-flex items-center gap-1 px-2.5 py-1 bg-[#FFF7F0] text-[#FF6B00] text-xs rounded-full">
                {codeNameMap[code] || code}
                <button onClick={() => removeSelected(code)} className="hover:text-[#e55f00]">×</button>
              </span>
            ))}
          </div>
        )}

        {/* Body */}
        <div className="flex flex-1 overflow-hidden min-h-[300px]">
          {searchResults ? (
            <div className="flex-1 overflow-y-auto py-3 px-4">
              {searchResults.length === 0 ? (
                <div className="text-sm text-gray-400 text-center py-8">无匹配结果</div>
              ) : (
                <div className="grid grid-cols-3 gap-x-4">
                  {searchResults.slice(0, 60).map((item) => {
                    const isSelected = localSelected.includes(item.code)
                    return (
                      <button
                        key={item.code}
                        onClick={() => toggleCert(item.code)}
                        className={`text-left px-3 py-2 text-[13px] rounded transition-colors ${
                          isSelected ? "text-[#FF6B00] bg-[#FFF7F0] font-medium" : "text-gray-700 hover:bg-gray-50"
                        }`}
                      >
                        {item.name}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ) : (
            <>
              {/* 左侧分类（支持已选高亮与计数徽章） */}
              <div className="w-[190px] overflow-y-auto border-r border-gray-100 py-2 flex-shrink-0 bg-gray-50/50">
                {categories.map((cat, i) => {
                  const selCount = cat.children?.filter((c) => localSelected.includes(c.code)).length || 0
                  const hasSelected = selCount > 0
                  const isActive = i === activeCat

                  return (
                    <div
                      key={cat.code}
                      onClick={() => setActiveCat(i)}
                      className={`px-3.5 py-2.5 text-[13px] cursor-pointer transition-all flex items-center justify-between group ${
                        isActive
                          ? "text-[#FF6B00] bg-[#FFF7F0] font-semibold border-r-2 border-[#FF6B00]"
                          : hasSelected
                          ? "text-[#FF6B00] bg-[#FFF9F5] font-medium hover:bg-[#FFF7F0]"
                          : "text-gray-700 hover:bg-gray-100/80 hover:text-gray-900"
                      }`}
                    >
                      <span className="truncate pr-1.5">{cat.name}</span>
                      {hasSelected && (
                        <span
                          className={`inline-flex items-center justify-center px-1.5 py-0.5 text-[11px] font-bold rounded-full flex-shrink-0 shadow-sm ${
                            isActive
                              ? "bg-[#FF6B00] text-white"
                              : "bg-[#FF6B00]/15 text-[#FF6B00] border border-[#FF6B00]/30"
                          }`}
                          title={`已选 ${selCount} 项`}
                        >
                          {selCount}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>

              {/* 右侧证书网格 */}
              <div className="flex-1 overflow-y-auto py-3 px-4">
                <div className="grid grid-cols-3 gap-x-4">
                  {certs.map((cert) => {
                    const isSelected = localSelected.includes(cert.code)
                    return (
                      <button
                        key={cert.code}
                        onClick={() => toggleCert(cert.code)}
                        className={`text-left px-3 py-2 text-[13px] rounded transition-colors ${
                          isSelected ? "text-[#FF6B00] bg-[#FFF7F0] font-medium" : "text-gray-700 hover:bg-gray-50"
                        }`}
                      >
                        {cert.name}
                      </button>
                    )
                  })}
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
          <button onClick={handleConfirm} className="px-5 py-2 text-sm text-white bg-[#FF6B00] rounded-md hover:bg-[#e55f00]">
            确定
          </button>
        </div>
      </div>
    </div>
  )
}
