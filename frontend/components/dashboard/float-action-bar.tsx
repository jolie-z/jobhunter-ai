/**
 * 浮动批量操作栏（移植自 v0 设计 + 绑定现有业务 handler）。
 *
 * v0 原型的 6 个按钮是装饰性的；这里把它们接到 `JobListView` 的真实批量任务、
 * 删除与取消逻辑上。按钮在选中岗位正在执行任务时整体禁用。
 */

"use client"

import { Brain, Zap, FileEdit, Rocket, Trash2, X, Loader2, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface ActionButton {
  icon: React.ReactNode
  label: string
  shortLabel: string
  className: string
  danger?: boolean
}

const ACTION_BUTTONS: ActionButton[] = [
  {
    icon: <Brain className="size-3.5 shrink-0" />,
    label: "批量 AI 初步评估",
    shortLabel: "初步评估",
    className:
      "bg-blue-50 text-blue-700 hover:bg-blue-100 border-blue-100",
  },
  {
    icon: <Zap className="size-3.5 shrink-0" />,
    label: "批量 AI 深度评估",
    shortLabel: "深度评估",
    className:
      "bg-violet-50 text-violet-700 hover:bg-violet-100 border-violet-100",
  },
  {
    icon: <FileEdit className="size-3.5 shrink-0" />,
    label: "批量简历改写",
    shortLabel: "简历改写",
    className:
      "bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border-emerald-100",
  },
  {
    icon: <Rocket className="size-3.5 shrink-0" />,
    label: "批量一键海投",
    shortLabel: "一键海投",
    className:
      "bg-fuchsia-50 text-fuchsia-700 hover:bg-fuchsia-100 border-fuchsia-100",
  },
  {
    icon: <CheckCircle2 className="size-3.5 shrink-0" />,
    label: "批量批准投递",
    shortLabel: "批准投递",
    className:
      "bg-orange-50 text-orange-700 hover:bg-orange-100 border-orange-100",
  },
  {
    icon: <Trash2 className="size-3.5 shrink-0" />,
    label: "批量删除",
    shortLabel: "批量删除",
    className:
      "bg-rose-50 text-rose-600 hover:bg-rose-100 border-rose-100",
    danger: true,
  },
]

interface FloatActionBarProps {
  selectedCount: number
  disabled?: boolean
  onAction: (index: number) => void
  onClear: () => void
}

export function FloatActionBar({ selectedCount, disabled, onAction, onClear }: FloatActionBarProps) {
  if (selectedCount === 0) return null

  return (
    <div
      className={cn(
        "fixed bottom-8 left-1/2 -translate-x-1/2 z-50",
        "animate-in slide-in-from-bottom-3 fade-in duration-200"
      )}
      role="toolbar"
      aria-label={`已选择 ${selectedCount} 个职位，批量操作工具栏`}
    >
      <div
        className={cn(
          "flex items-center gap-2.5 px-4 py-3 rounded-2xl",
          "bg-white/90 backdrop-blur-2xl",
          "border border-slate-200/80",
          "shadow-[0_8px_40px_-4px_rgba(0,0,0,0.16),0_2px_12px_-2px_rgba(0,0,0,0.06)]"
        )}
      >
        {/* 选中计数 */}
        <div className="flex items-center gap-2 pr-3 border-r border-slate-200 shrink-0">
          <div className="size-5 rounded-md bg-blue-600 flex items-center justify-center">
            <span className="text-[10px] font-bold text-white leading-none">{selectedCount}</span>
          </div>
          <span className="text-xs font-semibold text-slate-700 whitespace-nowrap">
            已选 <span className="text-blue-600">{selectedCount}</span> 个岗位
          </span>
        </div>

        {/* 操作按钮 */}
        <div className="flex items-center gap-1.5">
          {ACTION_BUTTONS.map((action, index) => (
            <button
              key={index}
              disabled={disabled}
              onClick={() => onAction(index)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border",
                "transition-all duration-150 active:scale-95",
                "disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100",
                action.className
              )}
              title={action.label}
              aria-label={action.label}
            >
              {disabled ? <Loader2 className="size-3.5 shrink-0 animate-spin" /> : action.icon}
              <span>{action.shortLabel}</span>
            </button>
          ))}
        </div>

        {/* 取消 */}
        <button
          onClick={onClear}
          disabled={disabled}
          className="flex items-center gap-1 pl-3 border-l border-slate-200 text-xs text-slate-400 hover:text-slate-700 transition-colors shrink-0 ml-1 disabled:opacity-50"
          aria-label="取消选择"
        >
          <X className="size-3.5" />
          <span>取消</span>
        </button>
      </div>
    </div>
  )
}
