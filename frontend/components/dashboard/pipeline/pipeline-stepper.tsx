"use client"

import { Check, Loader2 } from "lucide-react"
import { PIPELINE_STAGES, usePipelineStore } from "@/store/pipeline-store"

/**
 * 全链路横向阶段步进器。
 * - 已完成阶段：绿色打勾
 * - 当前阶段：靛蓝呼吸高亮
 * - 未到达阶段：灰色
 * 与后端 PIPELINE_STAGES 一一对应。
 */
export function PipelineStepper() {
  const stageStatus = usePipelineStore(s => s.stageStatus)
  const status = usePipelineStore(s => s.status)

  // 链路尚未启动时的空态
  const notStarted = status === "idle"

  return (
    <div className="w-full overflow-x-auto custom-scrollbar">
      <div className="flex items-start min-w-max px-1 py-2">
        {PIPELINE_STAGES.map((stage, idx) => {
          const st = notStarted ? "pending" : (stageStatus[stage.key] ?? "pending")
          const isLast = idx === PIPELINE_STAGES.length - 1

          return (
            <div key={stage.key} className="flex items-start">
              {/* 节点 + 标签 */}
              <div className="flex flex-col items-center gap-1.5 w-[68px] shrink-0">
                <div
                  className={[
                    "relative flex items-center justify-center size-7 rounded-full border-2 transition-all duration-300",
                    st === "done"
                      ? "bg-emerald-500 border-emerald-500 text-white"
                      : st === "running"
                        ? "bg-indigo-600 border-indigo-600 text-white shadow-md"
                        : "bg-white border-slate-200 text-slate-300",
                  ].join(" ")}
                >
                  {/* 当前节点呼吸光圈 */}
                  {st === "running" && (
                    <span className="absolute inset-0 rounded-full bg-indigo-400 animate-ping opacity-40" />
                  )}

                  {st === "done" ? (
                    <Check className="size-3.5 relative z-10" strokeWidth={3} />
                  ) : st === "running" ? (
                    <Loader2 className="size-3.5 relative z-10 animate-spin" />
                  ) : (
                    <span className="text-[10px] font-bold relative z-10">{idx + 1}</span>
                  )}
                </div>
                <span
                  className={[
                    "text-[10px] font-medium text-center leading-tight transition-colors",
                    st === "done"
                      ? "text-emerald-600"
                      : st === "running"
                        ? "text-indigo-600 font-semibold"
                        : "text-slate-400",
                  ].join(" ")}
                >
                  {stage.label}
                </span>
              </div>

              {/* 连接线 */}
              {!isLast && (
                <div className="flex items-center h-7 shrink-0">
                  <div
                    className={[
                      "h-0.5 w-6 rounded-full transition-colors duration-300",
                      st === "done" ? "bg-emerald-400" : "bg-slate-200",
                    ].join(" ")}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
