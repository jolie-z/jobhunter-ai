"use client"

import { useState, useEffect } from "react"
import { X } from "lucide-react"

interface CityItem { code: string; value: string }
interface CityGroup { title: string; type: string; items: CityItem[] }

interface Job51CityPickerProps {
  open: boolean
  onClose: () => void
  /** 已选城市 code 列表 */
  selected: string[]
  onConfirm: (cities: CityItem[]) => void
  maxSelect?: number
}

export function Job51CityPicker({ open, onClose, selected, onConfirm, maxSelect = 3 }: Job51CityPickerProps) {
  const [groups, setGroups] = useState<CityGroup[]>([])
  const [localSelected, setLocalSelected] = useState<CityItem[]>([])

  useEffect(() => {
    fetch("/51job_intention_cities.json")
      .then((r) => r.json())
      .then(setGroups)
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (open) {
      // 从 groups 中还原已选城市
      const items: CityItem[] = []
      for (const code of selected) {
        for (const g of groups) {
          const found = g.items?.find((c) => c.code === code)
          if (found) { items.push(found); break }
        }
      }
      setLocalSelected(items)
    }
  }, [open, selected, groups])

  const toggleCity = (city: CityItem) => {
    const exists = localSelected.find((c) => c.code === city.code)
    if (exists) {
      setLocalSelected(localSelected.filter((c) => c.code !== city.code))
    } else if (localSelected.length < maxSelect) {
      setLocalSelected([...localSelected, city])
    }
  }

  const isSelected = (code: string) => localSelected.some((c) => c.code === code)

  if (!open) return null

  const hotGroup = groups.find((g) => g.type === "1")
  const letterGroups = groups.filter((g) => g.type !== "1")

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-[600px] max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <span className="text-base font-bold text-gray-900">
            选择城市 · {localSelected.length}/{maxSelect}
          </span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {/* 热门城市 */}
          {hotGroup && (
            <div className="mb-5">
              <div className="text-sm font-bold text-gray-900 mb-3">热门城市</div>
              <div className="flex flex-wrap gap-2">
                {hotGroup.items.map((city) => (
                  <button
                    key={city.code}
                    onClick={() => toggleCity(city)}
                    className={`px-3 py-1.5 rounded text-[13px] transition-colors ${
                      isSelected(city.code)
                        ? "bg-[#FF6B00] text-white"
                        : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                    }`}
                  >
                    {city.value}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 按字母选择 */}
          <div className="text-sm font-bold text-gray-900 mb-3">按字母选择：</div>
          {letterGroups.map((group) => (
            <div key={group.title} className="mb-3">
              <div className="text-sm font-bold text-gray-900 mb-1.5">{group.title}</div>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {group.items.map((city) => (
                  <button
                    key={city.code}
                    onClick={() => toggleCity(city)}
                    className={`text-[13px] py-0.5 transition-colors ${
                      isSelected(city.code)
                        ? "text-[#FF6B00] font-medium"
                        : "text-gray-600 hover:text-[#FF6B00]"
                    }`}
                  >
                    {city.value}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-5 py-3 border-t border-gray-100">
          <button onClick={onClose} className="px-5 py-2 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50">
            取消
          </button>
          <button
            onClick={() => { onConfirm(localSelected); onClose() }}
            className="px-5 py-2 text-sm text-white bg-[#FF6B00] rounded-md hover:bg-[#e55f00]"
          >
            确定
          </button>
        </div>
      </div>
    </div>
  )
}
