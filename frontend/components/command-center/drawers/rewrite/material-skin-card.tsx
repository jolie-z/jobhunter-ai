"use client"

import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { Palette, Info, Check, ZoomIn, X } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

// 与后端 build_resume_html 支持的 skins 严格一致（update_autopilot_config 白名单同源）；
// preview 为真实渲染引擎生成的示例图（frontend/public/template-*.png，与投递 PDF 同一套代码渲染）
export const MATERIAL_SKINS: { value: string; label: string; desc: string; preview: string; swatch: string[] }[] = [
  {
    value: "classic",
    label: "黑白经典",
    desc: "纯黑白极简，通过 ATS 机器筛选最稳",
    preview: "/template-classic.png",
    swatch: ["#111827", "#4b5563", "#9ca3af"],
  },
  {
    value: "color_v1",
    label: "商务蓝",
    desc: "蓝色标题条 + 强调色分区，正式稳重",
    preview: "/template-color-v1.png",
    swatch: ["#1d4ed8", "#3b82f6", "#dbeafe"],
  },
  {
    value: "color_v2",
    label: "极客高密",
    desc: "深蓝标题强调，紧凑排版内容更多",
    preview: "/template-color-v2.png",
    swatch: ["#1e40af", "#6366f1", "#e0e7ff"],
  },
]

interface MaterialSkinCardProps {
  materialSkin: string
  onSkinChange: (val: string) => void
}

export function MaterialSkinCard({ materialSkin, onSkinChange }: MaterialSkinCardProps) {
  const [zoomed, setZoomed] = useState<string | null>(null)
  // Portal 挂载点：抽屉容器常带 transform/filter（创建层叠上下文），fixed 弹层
  // 会相对抽屉而非视口定位——挂 body 才能真正全屏（R1-P2）
  const [portalHost, setPortalHost] = useState<HTMLElement | null>(null)
  useEffect(() => {
    setPortalHost(document.body)
  }, [])

  // 弹层打开期间 Escape 关闭（R1-P2 键盘可达性）
  useEffect(() => {
    if (!zoomed) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setZoomed(null)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [zoomed])

  return (
    <div className="rounded-2xl border border-border/80 bg-card p-4 space-y-3 shadow-xs">
      {/* 标题栏 */}
      <div className="flex items-center gap-2 border-b border-border/50 pb-2.5">
        <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 font-bold shrink-0">
          <Palette className="h-3.5 w-3.5" />
        </div>
        <div className="flex items-center gap-1.5">
          <h3 className="font-semibold text-foreground text-xs tracking-tight">
            物料简历模板
          </h3>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors cursor-pointer">
                <Info className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
              <p className="font-semibold text-zinc-100 mb-0.5">🎨 物料模板说明：</p>
              <p className="text-zinc-300 text-[11px]">
                控制自动渲染的投递 PDF 与长图外观（精投定制物料与海投通用物料共用），示例图即真实渲染效果。保存后对后续每一轮渲染生效，已生成的物料不受影响。
              </p>
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* 三模板选择（真实渲染示例图）。
          预览图区域独立于选中按钮：点击整个卡片 = 选中模板，点击右上角放大钮 = 查看全图，
          避免 80% 面积误触预览而不选中（R1-P2 交互拆分） */}
      <div className="grid gap-2.5 sm:grid-cols-3">
        {MATERIAL_SKINS.map((skin) => {
          const selected = materialSkin === skin.value
          return (
            <div
              key={skin.value}
              role="button"
              tabIndex={0}
              onClick={() => onSkinChange(skin.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  onSkinChange(skin.value)
                }
              }}
              className={`group relative flex cursor-pointer flex-col gap-2 rounded-xl border p-2.5 text-left outline-none transition-all active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-amber-500/40 ${
                selected
                  ? "border-amber-500/60 bg-amber-500/[0.06] ring-1 ring-amber-500/30"
                  : "border-border/70 bg-muted/20 hover:bg-muted/40 hover:border-border"
              }`}
            >
              {/* 真实渲染示例图（顶端裁切展示版式气质；放大走右上角独立按钮） */}
              <div className="relative h-44 w-full overflow-hidden rounded-lg border border-border/50 bg-white">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={skin.preview}
                  alt={`${skin.label}模板示例`}
                  className="h-full w-full object-cover object-top"
                  loading="lazy"
                  draggable={false}
                />
                {/* 放大按钮：独立交互，stopPropagation 防触发选中 */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    setZoomed(skin.value)
                  }}
                  title="查看完整示例"
                  aria-label={`查看${skin.label}模板完整示例`}
                  className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-lg bg-black/50 text-white opacity-0 shadow-sm transition-opacity hover:bg-black/70 focus-visible:opacity-100 group-hover:opacity-100 cursor-pointer"
                >
                  <ZoomIn className="h-3.5 w-3.5" />
                </button>
              </div>

              <div className="flex items-center justify-between gap-1 px-0.5">
                <div className="min-w-0">
                  <div className="flex items-center gap-1">
                    <span className="text-xs font-semibold text-foreground">{skin.label}</span>
                    {/* 主色 swatch */}
                    <span className="flex items-center gap-0.5">
                      {skin.swatch.map((c, i) => (
                        <span
                          key={i}
                          className="h-1.5 w-1.5 rounded-full border border-black/5"
                          style={{ backgroundColor: c }}
                        />
                      ))}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[10px] leading-snug text-muted-foreground line-clamp-2">
                    {skin.desc}
                  </p>
                </div>
                {selected && (
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-amber-500 text-white">
                    <Check className="h-2.5 w-2.5" />
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* 全图放大弹层：Portal 挂 body 防抽屉层叠上下文劫持 fixed 定位（R1-P2） */}
      {zoomed && portalHost && (() => {
        const skin = MATERIAL_SKINS.find(s => s.value === zoomed)!
        return createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6 backdrop-blur-sm"
            onClick={() => setZoomed(null)}
            role="dialog"
            aria-modal="true"
            aria-label={`${skin.label}模板完整示例`}
          >
            <div
              className="relative max-h-full w-auto max-w-2xl overflow-hidden rounded-2xl border border-border bg-card shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between border-b border-border/60 px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-foreground">{skin.label} · 模板完整示例</span>
                  <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">示例数据渲染，非个人简历</span>
                </div>
                <button
                  type="button"
                  onClick={() => setZoomed(null)}
                  className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground cursor-pointer"
                  aria-label="关闭"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="max-h-[calc(100vh-10rem)] overflow-y-auto bg-white">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={skin.preview} alt={`${skin.label}模板完整示例`} className="w-full" draggable={false} />
              </div>
            </div>
          </div>,
          portalHost
        )
      })()}
    </div>
  )
}
