"use client"

import React, { useState, useEffect, useRef } from "react"
import {
  FileDown,
  ImageIcon,
  ChevronDown,
  Loader2,
  Check,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export interface ExportActionGroupProps {
  onExport?: (type: "pdf" | "image", template: "classic" | "color" | "color_v2") => void
  isExportingPdf?: boolean
  isExportingImage?: boolean
  exportingType?: "pdf" | "image" | null
  exportSuccess?: { type: "pdf" | "image"; time: number } | null
}

const isDiyEnabled = process.env.NEXT_PUBLIC_ENABLE_DIY_TEMPLATE === "true"

export function ExportActionGroup({
  onExport,
  isExportingPdf = false,
  isExportingImage = false,
  exportingType = null,
  exportSuccess = null,
}: ExportActionGroupProps) {
  // 综合外部兼容与分轨状态
  const isPdfBusy = isExportingPdf || exportingType === "pdf"
  const isImageBusy = isExportingImage || exportingType === "image"

  // 就地成功反馈胶囊状态（3.5 秒后自动淡出）。双轨各自只依赖本轨完成时间戳，
  // 严禁在共享 Effect 清理中互清对方定时器——否则一轨完成会取消另一轨倒计时，绿标永不隐退。
  const [showPdfSuccess, setShowPdfSuccess] = useState(false)
  const [showImageSuccess, setShowImageSuccess] = useState(false)
  const pdfTimerRef = useRef<NodeJS.Timeout | null>(null)
  const imageTimerRef = useRef<NodeJS.Timeout | null>(null)

  const pdfSuccessAt = exportSuccess?.type === "pdf" ? exportSuccess.time : null
  const imageSuccessAt = exportSuccess?.type === "image" ? exportSuccess.time : null

  useEffect(() => {
    if (pdfSuccessAt == null) return
    setShowPdfSuccess(true)
    if (pdfTimerRef.current) clearTimeout(pdfTimerRef.current)
    pdfTimerRef.current = setTimeout(() => {
      setShowPdfSuccess(false)
    }, 3500)
  }, [pdfSuccessAt])

  useEffect(() => {
    if (imageSuccessAt == null) return
    setShowImageSuccess(true)
    if (imageTimerRef.current) clearTimeout(imageTimerRef.current)
    imageTimerRef.current = setTimeout(() => {
      setShowImageSuccess(false)
    }, 3500)
  }, [imageSuccessAt])

  // 仅在组件卸载时统一回收双轨定时器
  useEffect(() => {
    return () => {
      if (pdfTimerRef.current) clearTimeout(pdfTimerRef.current)
      if (imageTimerRef.current) clearTimeout(imageTimerRef.current)
    }
  }, [])

  return (
    <div className="flex items-center gap-1.5 shrink-0">
      {/* 🌟 1. 独立并行动态胶囊区（左侧紧邻展示） */}
      {/* ① PDF 进行中状态 */}
      {isPdfBusy && (
        <div className="flex items-center gap-1.5 px-2 h-7 rounded-md bg-blue-50/90 border border-blue-200/80 text-blue-700 text-xs font-medium animate-in fade-in slide-in-from-right-1 duration-200 shrink-0 shadow-2xs">
          <Loader2 className="size-3 animate-spin text-blue-600 shrink-0" />
          <span className="leading-none text-[11px]">正在生成 PDF...</span>
        </div>
      )}

      {/* ② PDF 完成态（就地平滑演变为绿色微胶囊，3.5s后自然隐退） */}
      {!isPdfBusy && showPdfSuccess && (
        <div className="flex items-center gap-1.5 px-2 h-7 rounded-md bg-emerald-50/95 border border-emerald-200/90 text-emerald-700 text-xs font-medium animate-in fade-in duration-200 shrink-0 shadow-2xs">
          <Check className="size-3.5 text-emerald-600 shrink-0" />
          <span className="leading-none text-[11px]">PDF 已同步飞书</span>
        </div>
      )}

      {/* ③ 图片 进行中状态 */}
      {isImageBusy && (
        <div className="flex items-center gap-1.5 px-2 h-7 rounded-md bg-indigo-50/90 border border-indigo-200/80 text-indigo-700 text-xs font-medium animate-in fade-in slide-in-from-right-1 duration-200 shrink-0 shadow-2xs">
          <Loader2 className="size-3 animate-spin text-indigo-600 shrink-0" />
          <span className="leading-none text-[11px]">正在生成长图...</span>
        </div>
      )}

      {/* ④ 图片 完成态（就地平滑演变为绿色微胶囊，3.5s后自然隐退） */}
      {!isImageBusy && showImageSuccess && (
        <div className="flex items-center gap-1.5 px-2 h-7 rounded-md bg-emerald-50/95 border border-emerald-200/90 text-emerald-700 text-xs font-medium animate-in fade-in duration-200 shrink-0 shadow-2xs">
          <Check className="size-3.5 text-emerald-600 shrink-0" />
          <span className="leading-none text-[11px]">长图已同步飞书</span>
        </div>
      )}

      {/* 🌟 2. 📥 导出主按钮（外层永远开放可点，绝不锁死） */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-1.5 text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 border-slate-200 shadow-2xs rounded-md flex items-center gap-1 transition-all"
            title="导出 PDF 或 高清长图（支持并行多模版）"
          >
            <FileDown className="size-3.5 text-slate-500" />
            <span className="hidden sm:inline">导出</span>
            <ChevronDown className="size-3 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56 p-1 shadow-lg rounded-xl border-slate-200 text-xs">
          {/* PDF 分组 */}
          <div className="px-2 py-1 text-[10px] font-semibold text-slate-400 select-none flex items-center justify-between">
            <span>PDF 附件</span>
            {isPdfBusy && <span className="text-blue-500 font-normal">生成中...</span>}
          </div>

          <DropdownMenuItem
            disabled={isPdfBusy}
            className="flex items-center gap-2 py-1.5 px-2.5 cursor-pointer text-xs disabled:opacity-50"
            onClick={() => onExport?.("pdf", "classic")}
          >
            {isPdfBusy ? (
              <Loader2 className="size-3.5 animate-spin text-blue-500 shrink-0" />
            ) : (
              <FileDown className="size-3.5 text-slate-500 shrink-0" />
            )}
            <span>PDF · 普通模版(黑白)</span>
          </DropdownMenuItem>

          <DropdownMenuItem
            disabled={isPdfBusy}
            className="flex items-center gap-2 py-1.5 px-2.5 cursor-pointer text-xs disabled:opacity-50"
            onClick={() => onExport?.("pdf", "color")}
          >
            {isPdfBusy ? (
              <Loader2 className="size-3.5 animate-spin text-blue-500 shrink-0" />
            ) : (
              <FileDown className="size-3.5 text-blue-500 shrink-0" />
            )}
            <span>PDF · 彩色模版</span>
          </DropdownMenuItem>

          {isDiyEnabled && (
            <DropdownMenuItem
              disabled={isPdfBusy}
              className="flex items-center gap-2 py-1.5 px-2.5 cursor-pointer text-xs disabled:opacity-50"
              onClick={() => onExport?.("pdf", "color_v2")}
            >
              {isPdfBusy ? (
                <Loader2 className="size-3.5 animate-spin text-blue-500 shrink-0" />
              ) : (
                <FileDown className="size-3.5 text-blue-700 shrink-0" />
              )}
              <span className="font-medium text-slate-800">PDF · DIY模版</span>
            </DropdownMenuItem>
          )}

          <DropdownMenuSeparator className="my-1" />

          {/* 图片分组 */}
          <div className="px-2 py-1 text-[10px] font-semibold text-slate-400 select-none flex items-center justify-between">
            <span>高清长图</span>
            {isImageBusy && <span className="text-indigo-500 font-normal">生成中...</span>}
          </div>

          <DropdownMenuItem
            disabled={isImageBusy}
            className="flex items-center gap-2 py-1.5 px-2.5 cursor-pointer text-xs disabled:opacity-50"
            onClick={() => onExport?.("image", "classic")}
          >
            {isImageBusy ? (
              <Loader2 className="size-3.5 animate-spin text-indigo-500 shrink-0" />
            ) : (
              <ImageIcon className="size-3.5 text-sky-500 shrink-0" />
            )}
            <span>图片 · 普通模版(黑白)</span>
          </DropdownMenuItem>

          <DropdownMenuItem
            disabled={isImageBusy}
            className="flex items-center gap-2 py-1.5 px-2.5 cursor-pointer text-xs disabled:opacity-50"
            onClick={() => onExport?.("image", "color")}
          >
            {isImageBusy ? (
              <Loader2 className="size-3.5 animate-spin text-indigo-500 shrink-0" />
            ) : (
              <ImageIcon className="size-3.5 text-indigo-400 shrink-0" />
            )}
            <span>图片 · 彩色模版</span>
          </DropdownMenuItem>

          {isDiyEnabled && (
            <DropdownMenuItem
              disabled={isImageBusy}
              className="flex items-center gap-2 py-1.5 px-2.5 cursor-pointer text-xs disabled:opacity-50"
              onClick={() => onExport?.("image", "color_v2")}
            >
              {isImageBusy ? (
                <Loader2 className="size-3.5 animate-spin text-indigo-500 shrink-0" />
              ) : (
                <ImageIcon className="size-3.5 text-indigo-600 shrink-0" />
              )}
              <span className="font-medium text-slate-800">图片 · DIY模版</span>
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
