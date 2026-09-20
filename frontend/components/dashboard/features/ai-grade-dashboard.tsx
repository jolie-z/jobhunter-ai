import React from "react"
import type { JobData } from "@/types/job"

// ── 10维度评估大盘 ──────────────────────────────────────
const GRADE_STYLE: Record<string, { bg: string; ring: string; label: string; desc: string }> = {
  A: { bg: "from-yellow-400 to-orange-500", ring: "ring-yellow-400", label: "A", desc: "顶级匹配" },
  B: { bg: "from-emerald-400 to-teal-500", ring: "ring-emerald-400", label: "B", desc: "良好匹配" },
  C: { bg: "from-blue-400 to-indigo-500", ring: "ring-blue-400", label: "C", desc: "一般匹配" },
  D: { bg: "from-orange-400 to-red-400", ring: "ring-orange-400", label: "D", desc: "较差匹配" },
  F: { bg: "from-gray-300 to-gray-400", ring: "ring-gray-300", label: "F", desc: "不匹配" },
}

const DIM_CONFIG = [
  { key: "roleMatch" as const, label: "角色匹配", tag: "核心", dot: "bg-purple-500" },
  { key: "skillsAlign" as const, label: "技能重合", tag: "核心", dot: "bg-purple-500" },
  { key: "seniority" as const, label: "职级资历", tag: "高权", dot: "bg-amber-500" },
  { key: "compensation" as const, label: "薪资契合", tag: "高权", dot: "bg-amber-500" },
  { key: "interviewProb" as const, label: "面试概率", tag: "高权", dot: "bg-amber-500" },
  { key: "companyStage" as const, label: "公司阶段", tag: "中权", dot: "bg-blue-500" },
  { key: "marketFit" as const, label: "赛道前景", tag: "中权", dot: "bg-blue-500" },
  { key: "growth" as const, label: "成长空间", tag: "中权", dot: "bg-blue-500" },
]

export function AiGradeDashboard({ job }: { job: JobData }) {
  const grade = job.grade ?? ""
  const gs = GRADE_STYLE[grade]
  const rawTotal = DIM_CONFIG.reduce((s, d) => s + (Number(job[d.key]) || 0), 0)

  return (
    <div className="space-y-2.5">
      {/* Grade Hero */}
      <div className={`flex items-center gap-3 p-3 rounded-xl bg-gradient-to-r ${gs ? gs.bg : "from-gray-100 to-gray-200"}`}>
        <div className={`h-12 w-12 rounded-xl bg-white/20 flex items-center justify-center font-black text-2xl text-white shadow-inner ring-2 ${gs ? gs.ring : "ring-gray-300"}`}>
          {gs ? gs.label : "?"}
        </div>
        <div>
          <p className="text-white font-bold text-sm">{gs ? gs.desc : "暂未评估"}</p>
          <p className="text-white/80 text-xs">{rawTotal > 0 ? `综合 ${rawTotal}/40 分` : "等待 AI 评估"}</p>
        </div>
      </div>

      {/* 10-dim grid */}
      {rawTotal > 0 && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
          {DIM_CONFIG.map((d) => {
            const score = Number(job[d.key]) || 0
            return (
              <div key={d.key} className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-muted-foreground">{d.label}</span>
                  <span className={`text-[9px] px-1 rounded-full font-medium ${d.tag === "核心" ? "bg-purple-100 text-purple-700" :
                    d.tag === "高权" ? "bg-amber-100 text-amber-700" :
                      d.tag === "中权" ? "bg-blue-100 text-blue-700" :
                        "bg-gray-100 text-gray-500"
                    }`}>{d.tag}</span>
                </div>
                <div className="flex gap-0.5">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <div
                      key={i}
                      className={`h-1.5 flex-1 rounded-full ${i <= score ? d.dot : "bg-gray-200"}`}
                    />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
// ─────────────────────────────────────────────────────────