"use client"

// 通用「功能不可用 - 需前往配置」拦截弹窗
// 用于视觉模型/主 LLM 未配置时的功能前置闸门：说明缺失字段 + 一键直达 配置大盘-系统底层配置

import { AlertTriangle, ArrowRight, Settings2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

type ConfigGateDialogProps = {
  open: boolean
  onClose: () => void
  title: string
  description: string
  /** 缺失的配置字段 key 列表（展示用） */
  missing?: string[]
  /** 主 CTA：前往配置（由调用方决定页内切换还是跨页跳转） */
  onGoConfigure: () => void
  /** 次选动作（如「不用图片，仅文本解析」） */
  secondaryLabel?: string
  onSecondary?: () => void
}

export function ConfigGateDialog({
  open,
  onClose,
  title,
  description,
  missing = [],
  onGoConfigure,
  secondaryLabel,
  onSecondary,
}: ConfigGateDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md border-slate-200 bg-white">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base font-bold text-slate-900">
            <span className="flex size-8 items-center justify-center rounded-xl bg-amber-100">
              <AlertTriangle className="size-4 text-amber-600" />
            </span>
            {title}
          </DialogTitle>
          <DialogDescription className="pt-2 text-[13px] leading-relaxed text-slate-600">
            {description}
          </DialogDescription>
        </DialogHeader>

        {missing.length > 0 && (
          <div className="flex flex-wrap gap-1.5 rounded-xl bg-slate-50 px-3.5 py-2.5 ring-1 ring-inset ring-slate-200/70">
            <Settings2 className="size-3.5 shrink-0 text-slate-400 mt-0.5" />
            {missing.map((key) => (
              <span key={key} className="rounded-md bg-white px-1.5 py-0.5 font-mono text-[10px] text-slate-500 ring-1 ring-inset ring-slate-200">
                {key}
              </span>
            ))}
          </div>
        )}

        <div className="flex flex-col gap-2 pt-1">
          <Button
            onClick={() => { onClose(); onGoConfigure() }}
            className="w-full gap-1.5 bg-slate-900 text-white hover:bg-slate-800"
          >
            <Settings2 className="size-3.5" />
            前往配置
            <ArrowRight className="size-3.5" />
          </Button>
          {secondaryLabel && onSecondary && (
            <Button variant="ghost" onClick={() => { onClose(); onSecondary() }} className="w-full text-slate-500">
              {secondaryLabel}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
