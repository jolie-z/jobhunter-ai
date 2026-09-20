/**
 * 环形 AI 匹配度评分组件（移植自 v0 设计）。
 *
 * 中央显示 A-F 等级，外圈是按分数百分比的环形进度，颜色随等级变化。
 * 未评级岗位显示灰色占位态。
 */

import { cn } from "@/lib/utils"
import type { ScoreGrade } from "@/lib/job-data"

interface AiScoreProps {
  /** 实际得分 */
  score: number
  /** 满分（恒为 50） */
  maxScore: number
  /** A-F 等级；为 null 表示未评估 */
  grade: ScoreGrade | null
}

const GRADE_CONFIG: Record<
  ScoreGrade,
  { color: string; bg: string; ring: string; label: string }
> = {
  A: { color: "text-orange-600", bg: "bg-orange-50", ring: "ring-orange-200", label: "优秀" },
  B: { color: "text-blue-600", bg: "bg-blue-50", ring: "ring-blue-200", label: "良好" },
  C: { color: "text-teal-600", bg: "bg-teal-50", ring: "ring-teal-200", label: "一般" },
  D: { color: "text-purple-600", bg: "bg-purple-50", ring: "ring-purple-200", label: "偏低" },
  F: { color: "text-slate-400", bg: "bg-slate-50", ring: "ring-slate-200", label: "较低" },
}

const UNEVALUATED = {
  color: "text-slate-400",
  bg: "bg-slate-50",
  ring: "ring-slate-200",
  label: "未评估",
}

export function AiScore({ score, maxScore, grade }: AiScoreProps) {
  const config = grade ? GRADE_CONFIG[grade] : UNEVALUATED
  const percent = maxScore > 0 ? Math.min(100, Math.round((score / maxScore) * 100)) : 0

  // SVG 环形进度
  const radius = 20
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference - (percent / 100) * circumference

  return (
    <div className="flex flex-col items-center gap-1 shrink-0">
      <div
        className={cn(
          "relative size-14 rounded-full ring-2 flex items-center justify-center",
          config.bg,
          config.ring
        )}
        title={`AI 匹配度：${score}/${maxScore}分`}
      >
        {/* 环形 SVG */}
        <svg className="absolute inset-0 size-14 -rotate-90" viewBox="0 0 48 48">
          <circle
            cx="24"
            cy="24"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            className="text-border opacity-40"
          />
          <circle
            cx="24"
            cy="24"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            className={config.color}
          />
        </svg>
        {/* 中间内容 */}
        <div className="relative flex flex-col items-center leading-none">
          <span className={cn("text-xs font-bold", config.color)}>{grade ?? "—"}</span>
          <span className={cn("text-[9px] tabular-nums", config.color, "opacity-70")}>
            {score}/{maxScore}
          </span>
        </div>
      </div>
      <span className={cn("text-[10px] font-medium", config.color)}>{config.label}</span>
    </div>
  )
}
