// 文件路径: frontend/components/strategy-lab/global-nav.tsx
"use client"

import { Settings2, FileText, Home, MessageSquare, Rocket } from "lucide-react"
import Link from "next/link"
import { cn } from "@/lib/utils"
import type { SectionId } from "@/hooks/use-strategy-store"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useSetupGuide } from "@/components/dashboard/setup-guide/setup-guide-provider"

// 注：原「AI 初步评估偏好规则设置」入口已撤——与全链路指挥中心 AI 初评抽屉重复，该处为唯一配置入口
const NAV_ITEMS: { id: SectionId; label: string; icon: typeof Settings2 }[] = [
    { id: "system", label: "系统底层配置", icon: Settings2 },
    { id: "feishu", label: "飞书集成中心", icon: MessageSquare },
    { id: "resume", label: "简历库", icon: FileText },
]

export function GlobalNav({ active, onSelect }: { active: SectionId; onSelect: (id: SectionId) => void }) {
    const { openGuide, incomplete: setupIncomplete } = useSetupGuide()

    return (
        <TooltipProvider delayDuration={150}>
            <nav className="flex h-full w-16 flex-col items-center gap-1 border-r border-border bg-card py-4">
                <Tooltip>
                    <TooltipTrigger asChild>
                        <Link
                            href="/"
                            aria-label="返回首页"
                            className="mb-3 flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-md transition-all hover:scale-105 hover:bg-primary/90"
                        >
                            <Home className="size-5" />
                        </Link>
                    </TooltipTrigger>
                    <TooltipContent side="right" className="font-medium">
                        返回首页
                    </TooltipContent>
                </Tooltip>
                <div className="flex flex-1 flex-col items-center gap-1">
                    {NAV_ITEMS.map((item) => {
                        const isActive = active === item.id
                        const Icon = item.icon
                        return (
                            <Tooltip key={item.id}>
                                <TooltipTrigger asChild>
                                    <button
                                        type="button"
                                        onClick={() => onSelect(item.id)}
                                        aria-label={item.label}
                                        aria-current={isActive ? "page" : undefined}
                                        className={cn(
                                            "group relative flex size-11 items-center justify-center rounded-xl transition-all duration-200",
                                            isActive
                                                ? "bg-secondary text-foreground"
                                                : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                                        )}
                                    >
                                        <span
                                            className={cn(
                                                "absolute left-0 h-5 w-0.5 rounded-r-full bg-primary transition-all duration-200",
                                                isActive ? "opacity-100" : "opacity-0",
                                            )}
                                        />
                                        <Icon className="size-5" />
                                    </button>
                                </TooltipTrigger>
                                <TooltipContent side="right" className="font-medium">
                                    {item.label}
                                </TooltipContent>
                            </Tooltip>
                        )
                    })}
                </div>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <button
                            type="button"
                            onClick={openGuide}
                            aria-label="新手引导"
                            className={cn(
                                "group relative mb-1 flex size-10 items-center justify-center rounded-xl transition-all",
                                setupIncomplete
                                    ? "bg-amber-50 text-amber-600 hover:bg-amber-100"
                                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                            )}
                        >
                            <Rocket className="size-5" />
                            {setupIncomplete && (
                                <span className="absolute top-1 right-1 flex size-2">
                                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
                                    <span className="relative inline-flex size-2 rounded-full bg-amber-500" />
                                </span>
                            )}
                        </button>
                    </TooltipTrigger>
                    <TooltipContent side="right" className="font-medium">
                        新手引导 · 配置体检
                    </TooltipContent>
                </Tooltip>
                <div className="size-9 rounded-full bg-gradient-to-br from-zinc-200 to-zinc-300 ring-1 ring-border" />
            </nav>
        </TooltipProvider>
    )
}