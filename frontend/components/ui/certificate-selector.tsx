"use client"

import { useState, useMemo, useEffect } from "react"
import { cn } from "@/lib/utils"
import { certCategories, CERT_MAX_SELECT } from "@/lib/certificate-options"
import { X } from "lucide-react"

interface CertificateSelectorProps {
  value: string[]
  onChange: (value: string[]) => void
  externalOpen?: boolean
  onExternalClose?: () => void
}

export function CertificateSelector({ value = [], onChange, externalOpen, onExternalClose }: CertificateSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeCategory, setActiveCategory] = useState<string>(certCategories[0]?.name || "")
  const [customInput, setCustomInput] = useState("")

  // 同步外部 open 状态
  useEffect(() => {
    if (externalOpen) {
      setIsOpen(true)
    }
  }, [externalOpen])

  const activeItems = useMemo(() => {
    const cat = certCategories.find((c) => c.name === activeCategory)
    return cat?.items || []
  }, [activeCategory])

  const handleToggle = (cert: string) => {
    if (value.includes(cert)) {
      onChange(value.filter((v) => v !== cert))
    } else if (value.length < CERT_MAX_SELECT) {
      onChange([...value, cert])
    }
  }

  const handleCustomAdd = () => {
    const text = customInput.trim()
    if (text && !value.includes(text) && value.length < CERT_MAX_SELECT) {
      onChange([...value, text])
      setCustomInput("")
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault()
      handleCustomAdd()
    }
  }

  const handleClose = () => {
    setIsOpen(false)
    setCustomInput("")
    if (onExternalClose) onExternalClose()
  }

  return (
    <div className="relative">
      {/* 触发按钮：显示已选标签 */}
      <div
        className={cn(
          "flex min-h-[40px] w-full cursor-pointer flex-wrap items-center gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background",
          "hover:border-[#00beab]",
          !value.length && "text-muted-foreground"
        )}
        onClick={() => setIsOpen(true)}
      >
        {value.length > 0 ? (
          value.map((cert) => (
            <span
              key={cert}
              className="inline-flex items-center gap-1 rounded bg-[#00beab]/10 px-2 py-0.5 text-xs text-[#00beab]"
            >
              {cert}
              <X
                className="h-3 w-3 cursor-pointer hover:text-[#009e8e]"
                onClick={(e) => {
                  e.stopPropagation()
                  onChange(value.filter((v) => v !== cert))
                }}
              />
            </span>
          ))
        ) : (
          <span>请选择资格证书</span>
        )}
      </div>

      {/* 弹窗 */}
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={handleClose} />

          <div className="relative z-10 w-[720px] max-h-[560px] rounded-lg bg-white shadow-xl flex flex-col">
            {/* 头部 */}
            <div className="flex items-center justify-between border-b px-5 py-3">
              <h3 className="text-base font-medium text-gray-900">
                资格证书
                <span className="ml-2 text-xs text-gray-400">（{value.length}/{CERT_MAX_SELECT}）</span>
              </h3>
              <button onClick={handleClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>

            {/* 已选标签区 */}
            {value.length > 0 && (
              <div className="px-5 pt-3 pb-1 flex flex-wrap gap-1.5">
                {value.map((cert) => (
                  <span
                    key={cert}
                    className="inline-flex items-center gap-1 rounded-full bg-[#00beab]/10 px-2.5 py-1 text-xs text-[#00beab]"
                  >
                    {cert}
                    <X
                      className="h-3 w-3 cursor-pointer hover:text-[#009e8e]"
                      onClick={() => onChange(value.filter((v) => v !== cert))}
                    />
                  </span>
                ))}
              </div>
            )}

            {/* 自定义输入 */}
            <div className="px-5 py-2">
              <div className="flex items-center rounded-md border border-gray-200 px-3 py-2 focus-within:border-[#00beab]">
                <input
                  type="text"
                  placeholder="请输入，回车添加自定义"
                  value={customInput}
                  onChange={(e) => setCustomInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  className="flex-1 text-sm outline-none placeholder:text-gray-400"
                />
              </div>
            </div>

            {/* 左右面板 */}
            <div className="flex flex-1 overflow-hidden border-t">
              {/* 左侧分类 */}
              <div className="w-[130px] border-r overflow-y-auto bg-gray-50/50">
                {certCategories.map((cat) => (
                  <button
                    key={cat.name}
                    onClick={() => setActiveCategory(cat.name)}
                    className={cn(
                      "block w-full px-3 py-[9px] text-left text-[13px] transition-colors border-l-2",
                      activeCategory === cat.name
                        ? "border-l-[#00beab] bg-white text-[#00beab] font-medium"
                        : "border-l-transparent text-gray-700 hover:bg-gray-100"
                    )}
                  >
                    {cat.name}
                  </button>
                ))}
              </div>

              {/* 右侧证书列表 */}
              <div className="flex-1 overflow-y-auto px-4 py-3">
                <div className="grid grid-cols-3 gap-x-3 gap-y-1">
                  {activeItems.map((item) => (
                    <button
                      key={item}
                      onClick={() => handleToggle(item)}
                      className={cn(
                        "rounded px-2 py-[7px] text-left text-[13px] transition-colors truncate",
                        value.includes(item)
                          ? "bg-[#00beab]/10 text-[#00beab] font-medium"
                          : value.length >= CERT_MAX_SELECT
                            ? "text-gray-300 cursor-not-allowed"
                            : "text-gray-700 hover:bg-[#00beab]/5 hover:text-[#00beab]"
                      )}
                      disabled={!value.includes(item) && value.length >= CERT_MAX_SELECT}
                      title={item}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* 底部确认 */}
            <div className="border-t px-5 py-3 flex justify-end">
              <button
                onClick={handleClose}
                className="rounded-md bg-[#00beab] px-5 py-1.5 text-sm text-white hover:bg-[#00a99a] transition-colors"
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
