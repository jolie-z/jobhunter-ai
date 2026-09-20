"use client"

import { Info, Check } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export interface PlatformItem {
  key: string
  name: string
  desc: string
  tooltipNote: string
  recommended: boolean
}

const PLATFORMS: PlatformItem[] = [
  {
    key: "boss",
    name: "BOSS直聘",
    desc: "即时微聊开场白沟通",
    tooltipNote: "BOSS直聘采用直聘沟通机制，打招呼语将在向招聘官发起沟通时自动填充发送，强烈建议开启。",
    recommended: true,
  },
  {
    key: "liepin",
    name: "猎聘",
    desc: "顾问/猎头首句破冰话术",
    tooltipNote: "猎聘支持直聊与应聘附言，生成的开场白可极大提高猎头与业务面试官的查看率。",
    recommended: true,
  },
  {
    key: "zhilian",
    name: "智联招聘",
    desc: "即时微聊 / 先聊聊沟通",
    tooltipNote: "智联招聘全新改版支持即时在线微聊（先聊聊），打招呼语将在发起沟通时自动发送，强烈建议开启。",
    recommended: true,
  },
  {
    key: "51job",
    name: "前程无忧 (51job)",
    desc: "标准职位附件申请",
    tooltipNote: "前程无忧 (51job) 采用直接投递简历附件机制，无需且无法在沟通前发送开场白，默认关闭以节省 Token 消耗；如需生成可在右侧手动开启。",
    recommended: false,
  },
]

interface GreetingPlatformCardProps {
  greetingPlatforms: Record<string, boolean>
  onTogglePlatform: (key: string) => void
}

export function GreetingPlatformCard({
  greetingPlatforms,
  onTogglePlatform,
}: GreetingPlatformCardProps) {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3">
      {/* 头部标题与感叹号说明 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold text-foreground tracking-tight">
            生成目标平台
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
              系统将根据此处的平台开关，决定是否在全链路中为该平台的岗位触发打招呼语生成。
              默认仅对支持即时微聊的平台（BOSS 直聘、猎聘）生成，避免在仅需附件投递的平台浪费 Token。
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[11px] text-muted-foreground">
          已启用{" "}
          <span className="font-mono font-semibold text-violet-600 dark:text-violet-400">
            {Object.values(greetingPlatforms).filter(Boolean).length}
          </span>
          /{PLATFORMS.length} 个平台
        </span>
      </div>

      {/* 平台卡片网格 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {PLATFORMS.map((plat) => {
          const isEnabled = Boolean(greetingPlatforms[plat.key])
          return (
            <div
              key={plat.key}
              onClick={() => onTogglePlatform(plat.key)}
              className={cn(
                "group relative flex items-center justify-between rounded-xl border p-3 transition-all duration-200 cursor-pointer select-none",
                isEnabled
                  ? "border-violet-500/30 bg-violet-50/40 dark:bg-violet-950/20 shadow-xs"
                  : "border-border/60 bg-background/50 hover:border-border hover:bg-muted/40 opacity-75 hover:opacity-100"
              )}
            >
              <div className="space-y-1 pr-2">
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "text-xs font-semibold tracking-tight transition-colors",
                      isEnabled
                        ? "text-foreground font-medium"
                        : "text-muted-foreground"
                    )}
                  >
                    {plat.name}
                  </span>

                  {plat.recommended && (
                    <span className="rounded-full bg-violet-500/10 dark:bg-violet-500/20 px-1.5 py-0.2 text-[10px] font-medium text-violet-600 dark:text-violet-400">
                      推荐
                    </span>
                  )}

                  {/* 平台专属感叹号说明 */}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center justify-center text-muted-foreground/70 hover:text-foreground transition-colors cursor-help p-0.5 rounded-full"
                      >
                        <Info className="h-3 w-3 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                      {plat.tooltipNote}
                    </TooltipContent>
                  </Tooltip>
                </div>

                <p className="text-[11px] text-muted-foreground line-clamp-1">
                  {plat.desc}
                </p>
              </div>

              {/* 勾选开关态 */}
              <div
                className={cn(
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-lg border transition-all duration-200",
                  isEnabled
                    ? "border-violet-600 bg-violet-600 text-white dark:border-violet-500 dark:bg-violet-500 shadow-xs scale-105"
                    : "border-border/80 bg-background group-hover:border-zinc-400 text-transparent"
                )}
              >
                <Check className="h-3 w-3 stroke-[3]" />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
