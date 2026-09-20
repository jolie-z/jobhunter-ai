"use client"

import { useState, useEffect } from "react"
import { X, Check } from "lucide-react"

interface IndustryNode { code: string; name: string; children?: IndustryNode[] }

interface Job51IndustryPickerProps {
  open: boolean
  onClose: () => void
  /** 已选行业 code 列表 */
  selected: string[]
  onConfirm: (items: IndustryNode[]) => void
  maxSelect?: number
}

export function Job51IndustryPicker({ open, onClose, selected, onConfirm, maxSelect = 3 }: Job51IndustryPickerProps) {
  const [tree, setTree] = useState<IndustryNode[]>([])
  const [localSelected, setLocalSelected] = useState<IndustryNode[]>([])
  const [activeCol0, setActiveCol0] = useState(0)

  useEffect(() => {
    fetch("/51job_industry.json")
      .then((r) => r.json())
      .then((data) => {
        if (data.tree) setTree(data.tree)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (open && tree.length > 0) {
      const items: IndustryNode[] = []
      let firstCatIndex = -1
      for (const code of selected) {
        for (let i = 0; i < tree.length; i++) {
          const cat = tree[i]
          const found = cat.children?.find((c) => c.code === code)
          if (found) {
            items.push(found)
            if (firstCatIndex === -1) firstCatIndex = i
            break
          }
        }
      }
      setLocalSelected(items)
      if (firstCatIndex !== -1) {
        setActiveCol0(firstCatIndex)
      }
    }
  }, [open, selected, tree])

  const toggleItem = (item: IndustryNode) => {
    const exists = localSelected.find((c) => c.code === item.code)
    if (exists) {
      setLocalSelected(localSelected.filter((c) => c.code !== item.code))
    } else if (localSelected.length < maxSelect) {
      setLocalSelected([...localSelected, item])
    }
  }

  const isSelected = (code: string) => localSelected.some((c) => c.code === code)

  const jumpToCategoryOfItem = (item: IndustryNode) => {
    for (let i = 0; i < tree.length; i++) {
      if (tree[i].children?.some((c) => c.code === item.code)) {
        setActiveCol0(i)
        break
      }
    }
  }

  if (!open) return null

  const col0 = tree
  const children = col0[activeCol0]?.children || []

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-[700px] max-h-[82vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <span className="text-base font-bold text-gray-900">选择行业</span>
            <span className="text-sm font-normal text-gray-500">
              已选 ( <span className={localSelected.length > 0 ? "text-[#FF6B00] font-semibold" : ""}>{localSelected.length}</span> / {maxSelect} )
            </span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors p-1 rounded-md hover:bg-gray-100">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 已选行业快捷预览与快速取消条 */}
        {localSelected.length > 0 && (
          <div className="flex flex-wrap gap-2 px-5 py-2.5 bg-[#FFF9F5]/70 border-b border-gray-100 items-center">
            <span className="text-xs text-gray-500 font-medium flex-shrink-0">已选行业：</span>
            <div className="flex flex-wrap gap-1.5 items-center">
              {localSelected.map((item) => (
                <span
                  key={item.code}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md bg-[#FFF7F0] text-[#FF6B00] border border-[#FF6B00]/30 font-medium shadow-sm transition-all"
                >
                  <span
                    onClick={() => jumpToCategoryOfItem(item)}
                    className="cursor-pointer hover:underline"
                    title="点击定位到所属大类"
                  >
                    {item.name}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      toggleItem(item)
                    }}
                    className="hover:bg-[#FF6B00]/20 rounded-full p-0.5 text-[#FF6B00] transition-colors"
                    title="取消选择"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Body - 2 levels: left=一级大类, right=二级网格 */}
        <div className="flex flex-1 overflow-hidden min-h-[380px] max-h-[480px]">
          {/* 一级分类（窄栏：支持已选大类高亮与已选数量徽章） */}
          <div className="w-[210px] overflow-y-auto border-r border-gray-100 py-2 flex-shrink-0 bg-gray-50/50">
            {col0.map((item, i) => {
              const selectedCount = item.children?.filter((c) => localSelected.some((s) => s.code === c.code)).length || 0
              const hasSelected = selectedCount > 0
              const isActive = i === activeCol0

              return (
                <div
                  key={item.code}
                  onClick={() => setActiveCol0(i)}
                  onMouseEnter={() => setActiveCol0(i)}
                  className={`px-3.5 py-2.5 text-[13px] cursor-pointer transition-all flex items-center justify-between group relative ${
                    isActive
                      ? "text-[#FF6B00] bg-[#FFF7F0] font-semibold border-r-2 border-[#FF6B00]"
                      : hasSelected
                      ? "text-[#FF6B00] bg-[#FFF9F5] font-medium hover:bg-[#FFF7F0]"
                      : "text-gray-700 hover:bg-gray-100/80 hover:text-gray-900"
                  }`}
                >
                  <span className="truncate pr-1.5">{item.name}</span>
                  {hasSelected && (
                    <span
                      className={`inline-flex items-center justify-center px-1.5 py-0.5 text-[11px] font-bold rounded-full flex-shrink-0 shadow-sm ${
                        isActive
                          ? "bg-[#FF6B00] text-white"
                          : "bg-[#FF6B00]/15 text-[#FF6B00] border border-[#FF6B00]/30"
                      }`}
                      title={`该大类下已选 ${selectedCount} 项`}
                    >
                      {selectedCount}
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          {/* 二级子项（宽区域，网格布局，带已选复选态） */}
          <div className="flex-1 overflow-y-auto py-3.5 px-5 bg-white">
            <div className="grid grid-cols-2 gap-2.5">
              {children.map((item) => {
                const selected = isSelected(item.code)
                return (
                  <button
                    key={item.code}
                    onClick={() => toggleItem(item)}
                    className={`text-left px-3.5 py-2.5 text-[13px] rounded-md transition-all flex items-center justify-between border ${
                      selected
                        ? "text-[#FF6B00] bg-[#FFF7F0] font-medium border-[#FF6B00]/40 shadow-sm"
                        : "text-gray-700 hover:bg-gray-50 border-transparent hover:border-gray-200"
                    }`}
                  >
                    <span className="truncate pr-2">{item.name}</span>
                    {selected && <Check className="w-4 h-4 text-[#FF6B00] flex-shrink-0" />}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-5 py-3 border-t border-gray-100 bg-gray-50/40">
          <button onClick={onClose} className="px-5 py-2 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50 transition-colors">
            取消
          </button>
          <button
            onClick={() => { onConfirm(localSelected); onClose() }}
            className="px-5 py-2 text-sm text-white bg-[#FF6B00] rounded-md hover:bg-[#e55f00] font-medium shadow-sm transition-colors"
          >
            确定
          </button>
        </div>
      </div>
    </div>
  )
}
