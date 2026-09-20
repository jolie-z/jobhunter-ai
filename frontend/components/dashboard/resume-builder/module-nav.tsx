"use client"

import { useState } from "react"
import { ChevronLeft, LayoutList } from "lucide-react"
import { cn } from "@/lib/utils"

export interface ModuleNavItem {
  /** 模块唯一 key，同时是对应 ModuleCard 的 DOM 锚点 id */
  key: string
  /** 模块显示标题（来自 moduleTitles，随用户改名实时变化） */
  title: string
}

interface ModuleNavProps {
  items: ModuleNavItem[]
  /** 当前正在查看的模块 key（可选，用于高亮） */
  activeKey?: string | null
}

/**
 * 简历模块导览条。
 * - 固定在主滚动区右侧，平时只露出一条窄把手，鼠标悬停时展开完整列表
 * - 数据完全由外部传入（moduleOrder + moduleTitles），模块增删 / 排序 / 改名均实时反映
 * - 点击某项平滑滚动到对应 ModuleCard 锚点
 */
export function ModuleNav({ items, activeKey }: ModuleNavProps) {
  const [expanded, setExpanded] = useState(false)

  const scrollTo = (key: string) => {
    const el = document.getElementById(`module-anchor-${key}`)
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }

  return (
    <div
      className={cn(
        "fixed right-0 top-1/2 z-40 -translate-y-1/2 transition-transform duration-300 ease-out",
        expanded ? "translate-x-0" : "translate-x-[calc(100%-14px)]"
      )}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
    >
      {/* 窄把手：收起时露出的提示条 */}
      <div
        className={cn(
          "absolute -left-0 top-1/2 -translate-y-1/2 flex h-20 w-[14px] cursor-pointer flex-col items-center justify-center rounded-l-md border border-r-0 border-slate-200/70 bg-white/90 shadow-sm backdrop-blur transition-colors",
          expanded ? "opacity-0" : "opacity-100 hover:bg-emerald-50"
        )}
        onClick={() => setExpanded(true)}
      >
        <ChevronLeft className="h-3.5 w-3.5 text-emerald-600" />
      </div>

      {/* 展开后的完整导览列表 */}
      <div
        className={cn(
          "w-44 rounded-l-xl border border-r-0 border-slate-200/70 bg-white/95 shadow-lg backdrop-blur transition-opacity duration-200",
          expanded ? "opacity-100" : "pointer-events-none opacity-0"
        )}
      >
        <div className="flex items-center gap-1.5 border-b border-slate-100 px-3 py-2">
          <LayoutList className="h-3.5 w-3.5 text-emerald-600" />
          <span className="text-xs font-semibold text-foreground">模块导览</span>
          <span className="ml-auto text-[10px] text-muted-foreground">{items.length}</span>
        </div>

        <nav className="max-h-[60vh] overflow-y-auto py-1">
          {items.length === 0 ? (
            <p className="px-3 py-4 text-center text-xs text-muted-foreground">暂无模块</p>
          ) : (
            items.map((item) => (
              <button
                key={item.key}
                onClick={() => scrollTo(item.key)}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors",
                  activeKey === item.key
                    ? "bg-emerald-50 font-medium text-emerald-700"
                    : "text-slate-600 hover:bg-slate-50 hover:text-foreground"
                )}
                title={item.title}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 shrink-0 rounded-full",
                    activeKey === item.key ? "bg-emerald-500" : "bg-slate-300"
                  )}
                />
                <span className="truncate">{item.title}</span>
              </button>
            ))
          )}
        </nav>
      </div>
    </div>
  )
}
