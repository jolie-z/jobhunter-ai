"use client"

import { useState, useEffect, useRef, useCallback } from "react"

interface CascaderNode {
  code: string
  value: string
  items?: CascaderNode[]
}

interface Job51CascaderProps {
  /** 当前选中值 {id, label} */
  value?: { id: string; label: string } | null
  /** 选中回调 */
  onChange: (id: string, label: string) => void
  /** 级联层数: 2=省→市, 3=省→市→区 */
  level: 2 | 3
  /** 数据文件 URL */
  dataUrl: string
  placeholder?: string
}

export function Job51Cascader({ value, onChange, level, dataUrl, placeholder = "请选择" }: Job51CascaderProps) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<CascaderNode[]>([])
  const [loading, setLoading] = useState(false)
  // 每列当前激活的索引
  const [activeCol0, setActiveCol0] = useState(0)
  const [activeCol1, setActiveCol1] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)

  // 加载数据
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(dataUrl)
      .then((r) => r.json())
      .then((json) => {
        if (!cancelled) {
          setData(json)
          setLoading(false)
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [dataUrl])

  // 点击外部关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  // 当前列数据
  const col0 = data // 省/热门城市
  const col1 = col0[activeCol0]?.items || [] // 市
  const col2 = level === 3 ? (col1[activeCol1]?.items || []) : [] // 区

  // 构建选中路径的 label
  const buildLabel = useCallback((c0: number, c1: number, c2: number) => {
    const parts: string[] = []
    const n0 = col0[c0]
    if (!n0) return ""
    // 如果是热门城市，直接取城市名
    if (n0.code === "000000") {
      const city = n0.items?.[c1]
      if (!city) return ""
      if (level === 3) {
        const district = city.items?.[c2]
        return district ? district.value : city.value
      }
      return city.value
    }
    // 普通省份：跳过省级 item（第一个子项是省本身）
    const city = n0.items?.[c1]
    if (!city) return n0.value
    if (level === 3) {
      const district = city.items?.[c2]
      return district ? district.value : city.value
    }
    return city.value
  }, [col0, level])

  // 获取最终选中的 code
  const buildCode = useCallback((c0: number, c1: number, c2: number) => {
    const n0 = col0[c0]
    if (!n0) return ""
    if (n0.code === "000000") {
      const city = n0.items?.[c1]
      if (!city) return ""
      if (level === 3) {
        const district = city.items?.[c2]
        return district ? district.code : city.code
      }
      return city.code
    }
    const city = n0.items?.[c1]
    if (!city) return n0.code
    if (level === 3) {
      const district = city.items?.[c2]
      return district ? district.code : city.code
    }
    return city.code
  }, [col0, level])

  // 点击最终列选项
  const handleSelect = (c0: number, c1: number, c2: number) => {
    const code = buildCode(c0, c1, c2)
    const label = buildLabel(c0, c1, c2)
    if (code) {
      onChange(code, label)
      setOpen(false)
    }
  }

  // 判断某列某项是否被选中
  const isSelected = (node: CascaderNode) => {
    return value?.id === node.code
  }

  const displayText = value?.label || ""

  return (
    <div ref={containerRef} className="relative">
      {/* 输入框 */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`w-full h-[40px] rounded-md border px-3 text-sm text-left flex items-center justify-between transition-colors ${
          open ? "border-[#FF6B00]" : "border-gray-300 hover:border-[#FF6B00]"
        }`}
      >
        <span className={displayText ? "text-gray-900" : "text-gray-400"}>
          {displayText || placeholder}
        </span>
        <svg
          className={`w-4 h-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* 下拉面板 */}
      {open && (
        <div className="absolute z-50 mt-1 bg-white border border-gray-200 rounded-md shadow-lg flex">
          {loading ? (
            <div className="px-4 py-3 text-sm text-gray-400">加载中...</div>
          ) : (
            <>
              {/* 第一列：省/热门城市 */}
              <div className="w-[130px] max-h-[280px] overflow-y-auto border-r border-gray-100">
                {col0.map((node, i) => (
                  <div
                    key={node.code}
                    onMouseEnter={() => { setActiveCol0(i); setActiveCol1(0) }}
                    className={`px-3 py-2 text-[13px] cursor-pointer transition-colors ${
                      i === activeCol0
                        ? "text-[#FF6B00] bg-[#FFF7F0] font-medium"
                        : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    {node.value}
                  </div>
                ))}
              </div>

              {/* 第二列：市 */}
              {col1.length > 0 && (
                <div className="w-[130px] max-h-[280px] overflow-y-auto border-r border-gray-100">
                  {col1.map((node, i) => {
                    const isLeaf = level === 2 || !node.items || node.items.length === 0
                    return (
                      <div
                        key={node.code}
                        onMouseEnter={() => { if (!isLeaf) setActiveCol1(i) }}
                        onClick={() => { if (isLeaf) handleSelect(activeCol0, i, 0) }}
                        className={`px-3 py-2 text-[13px] cursor-pointer transition-colors flex items-center justify-between ${
                          isSelected(node)
                            ? "text-[#FF6B00] font-medium"
                            : i === activeCol1 && level === 3 && !isLeaf
                              ? "text-[#FF6B00] bg-[#FFF7F0]"
                              : "text-gray-700 hover:bg-gray-50"
                        }`}
                      >
                        <span>{node.value}</span>
                        {!isLeaf && <span className="text-gray-300 text-xs">›</span>}
                      </div>
                    )
                  })}
                </div>
              )}

              {/* 第三列：区/县（仅3级） */}
              {level === 3 && col2.length > 0 && (
                <div className="w-[130px] max-h-[280px] overflow-y-auto">
                  {col2.map((node, i) => (
                    <div
                      key={node.code}
                      onClick={() => handleSelect(activeCol0, activeCol1, i)}
                      className={`px-3 py-2 text-[13px] cursor-pointer transition-colors ${
                        isSelected(node)
                          ? "text-[#FF6B00] font-medium"
                          : "text-gray-700 hover:bg-gray-50"
                      }`}
                    >
                      {node.value}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
