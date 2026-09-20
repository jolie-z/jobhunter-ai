"use client"

import { Globe, Info, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface DeliveryPlatformCardProps {
  platforms: string[]
  onChangePlatforms: (platforms: string[]) => void
}

interface PlatformOption {
  id: string
  name: string
  desc: string
  tag: string
  color: string
}

const PLATFORM_OPTIONS: PlatformOption[] = [
  {
    id: "boss",
    name: "BOSS 直聘",
    desc: "微聊窗口即时沟通",
    tag: "图片长图 + 打招呼语",
    color: "text-cyan-600 dark:text-cyan-400 border-cyan-500/20 bg-cyan-500/[0.04]",
  },
  {
    id: "liepin",
    name: "猎聘",
    desc: "标准投递通道",
    tag: "PDF 附件 + 打招呼语",
    color: "text-amber-600 dark:text-amber-400 border-amber-500/20 bg-amber-500/[0.04]",
  },
  {
    id: "51job",
    name: "前程无忧 (51job)",
    desc: "职位直通投递",
    tag: "PDF 附件简历",
    color: "text-blue-600 dark:text-blue-400 border-blue-500/20 bg-blue-500/[0.04]",
  },
  {
    id: "zhilian",
    name: "智联招聘",
    desc: "即时微聊 / 职位投递",
    tag: "PDF 附件 + 打招呼语",
    color: "text-indigo-600 dark:text-indigo-400 border-indigo-500/20 bg-indigo-500/[0.04]",
  },
]

export function DeliveryPlatformCard({
  platforms,
  onChangePlatforms,
}: DeliveryPlatformCardProps) {
  const togglePlatform = (id: string) => {
    if (platforms.includes(id)) {
      if (platforms.length === 1) return // 至少保留 1 个平台
      onChangePlatforms(platforms.filter((p) => p !== id))
    } else {
      onChangePlatforms([...platforms, id])
    }
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3">
      {/* 顶栏标题与感叹号说明 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <Globe className="h-3.5 w-3.5" />
          </div>
          <span className="text-xs font-semibold text-foreground tracking-tight">
            目标投递平台与多平台串行规则
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors cursor-help p-0.5 rounded-full hover:bg-muted"
              >
                <Info className="h-3.5 w-3.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
              【防封 · 串行互斥执行】：为了杜绝多平台并发请求被封号并防止浏览器崩溃，投递引擎严格按顺序逐个平台完成投递，并安全关闭对应浏览器实例后再流转至下一个平台。
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[11px] text-muted-foreground">
          串行流转 · 零并发冲突防封
        </span>
      </div>

      {/* 2 列宽敞卡片网格，所有文字完整显示 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {PLATFORM_OPTIONS.map((item) => {
          const isSelected = platforms.includes(item.id)
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => togglePlatform(item.id)}
              className={cn(
                "flex items-center justify-between rounded-xl border p-3 text-left transition-all cursor-pointer",
                isSelected
                  ? cn(item.color, "border-current/40 shadow-xs")
                  : "border-border/50 bg-background/40 text-muted-foreground opacity-60 hover:opacity-100 hover:border-border"
              )}
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-foreground">
                    {item.name}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    ({item.desc})
                  </span>
                </div>
                <div className="text-[10px] font-mono opacity-80">
                  {item.tag}
                </div>
              </div>
              <CheckCircle2
                className={cn(
                  "h-4 w-4 shrink-0 transition-opacity ml-2",
                  isSelected ? "opacity-100" : "opacity-0"
                )}
              />
            </button>
          )
        })}
      </div>
    </div>
  )
}
