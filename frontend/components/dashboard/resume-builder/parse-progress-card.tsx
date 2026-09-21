"use client"

// 简历解析进度浮动卡：上传解析期间展示真实阶段进度（读取文档 → 隐私脱敏 → AI 结构化 → 生成排版）
// AI 结构化阶段透出流式字数与本地计时；失败态展示错误详情 + 重试 / 关闭

import { useEffect, useState } from "react"
import { CheckCircle2, Circle, FileText, Loader2, RotateCcw, X, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useStrategyStore } from "@/hooks/use-strategy-store"

// 阶段顺序与后端 STAGE_LABELS 对齐
const STAGE_ORDER = [
    { key: "reading", label: "读取并解析文档" },
    { key: "desensitizing", label: "隐私信息脱敏" },
    { key: "structuring", label: "AI 智能结构化" },
    { key: "finalizing", label: "生成智能排版" },
]

export function ParseProgressCard() {
    const { isParsing, parseProgress, parseError, handleRetry, dismissParseError } = useStrategyStore()
    const [elapsedSec, setElapsedSec] = useState(0)

    // 本地计时：从进入 structuring（即拿到首个进度）或 isParsing 起算
    useEffect(() => {
        if (!isParsing) { setElapsedSec(0); return }
        const startedAt = Date.now()
        const timer = setInterval(() => setElapsedSec(Math.floor((Date.now() - startedAt) / 1000)), 1000)
        return () => clearInterval(timer)
    }, [isParsing])

    if (!isParsing && !parseError) return null

    // 失败态
    if (parseError && !isParsing) {
        return (
            <div className="fixed bottom-6 right-6 z-50 w-80 rounded-2xl border border-rose-200 bg-white p-4 shadow-xl">
                <div className="flex items-start gap-2.5">
                    <XCircle className="mt-0.5 size-4 shrink-0 text-rose-500" />
                    <div className="min-w-0 flex-1">
                        <p className="text-xs font-semibold text-slate-900">简历解析失败</p>
                        <p className="mt-1 text-[11px] leading-relaxed text-slate-500 break-words">{parseError.msg}</p>
                    </div>
                    <button onClick={dismissParseError} className="shrink-0 rounded p-0.5 text-slate-300 hover:text-slate-500" aria-label="关闭">
                        <X className="size-3.5" />
                    </button>
                </div>
                <div className="mt-3 flex justify-end gap-1.5">
                    <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]" onClick={handleRetry}>
                        <RotateCcw className="size-3" />
                        重试解析
                    </Button>
                </div>
            </div>
        )
    }

    // 进度态
    const currentStage = parseProgress?.stage || "reading"
    const currentIdx = Math.max(0, STAGE_ORDER.findIndex((s) => s.key === currentStage))

    return (
        <div className="fixed bottom-6 right-6 z-50 w-80 rounded-2xl border border-slate-200 bg-white p-4 shadow-xl">
            <div className="flex items-center gap-2">
                <FileText className="size-4 shrink-0 text-blue-500" />
                <p className="text-xs font-semibold text-slate-900">正在解析简历</p>
                <span className="ml-auto font-mono text-[10px] text-slate-400">{elapsedSec}s</span>
            </div>
            <div className="mt-3 space-y-2">
                {STAGE_ORDER.map((s, i) => {
                    const done = i < currentIdx
                    const active = i === currentIdx
                    // 当前阶段优先用后端下发的 stage_label（单点文案源），其余阶段用本地骨架文案
                    const label = active && parseProgress?.stageLabel ? parseProgress.stageLabel : s.label
                    return (
                        <div key={s.key} className="flex items-center gap-2 text-[11px]">
                            {done ? (
                                <CheckCircle2 className="size-3.5 shrink-0 text-emerald-500" />
                            ) : active ? (
                                <Loader2 className="size-3.5 shrink-0 animate-spin text-blue-500" />
                            ) : (
                                <Circle className="size-3.5 shrink-0 text-slate-200" />
                            )}
                            <span className={done ? "text-slate-400" : active ? "font-medium text-slate-900" : "text-slate-300"}>
                                {label}
                                {active && s.key === "structuring" && (parseProgress?.chars ?? 0) > 0 && (
                                    <span className="ml-1.5 font-mono text-[10px] text-blue-500">
                                        已生成 {parseProgress!.chars.toLocaleString()} 字
                                    </span>
                                )}
                            </span>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
