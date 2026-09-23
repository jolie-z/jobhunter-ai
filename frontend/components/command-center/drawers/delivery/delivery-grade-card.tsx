"use client"

import { useEffect, useRef } from "react"
import { Filter, Info, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface DeliveryGradeCardProps {
  grades: string[]
  onChangeGrades: (grades: string[]) => void
}

interface GradeOption {
  id: string
  name: string
  track: "custom" | "mass"
  desc: string
  color: string
}

const GRADE_OPTIONS: GradeOption[] = [
  {
    id: "A",
    name: "A 级",
    track: "custom",
    desc: "极高匹配",
    color: "text-emerald-600 dark:text-emerald-400 border-emerald-500/20 bg-emerald-500/[0.04]",
  },
  {
    id: "B",
    name: "B 级",
    track: "custom",
    desc: "高价值",
    color: "text-teal-600 dark:text-teal-400 border-teal-500/20 bg-teal-500/[0.04]",
  },
  {
    id: "C",
    name: "C 级",
    track: "mass",
    desc: "良好",
    color: "text-amber-600 dark:text-amber-400 border-amber-500/20 bg-amber-500/[0.04]",
  },
  {
    id: "D",
    name: "D 级",
    track: "mass",
    desc: "中等",
    color: "text-orange-600 dark:text-orange-400 border-orange-500/20 bg-orange-500/[0.04]",
  },
  {
    id: "F",
    name: "F 级",
    track: "mass",
    desc: "保底",
    color: "text-slate-600 dark:text-slate-400 border-slate-500/20 bg-slate-500/[0.04]",
  },
]

// 清洗后为空时的兜底默认集，与后端 automation_configs 默认 auto_deliver_grades 一致
const DEFAULT_MASS_GRADES = ["C", "D", "F"]

export function DeliveryGradeCard({ grades, onChangeGrades }: DeliveryGradeCardProps) {
  // 存量配置可能残留已下线的等级（如 E）：入口归一化，避免变成不可见又不可取消的幽灵勾选
  const validGrades = grades.filter((g) => GRADE_OPTIONS.some((o) => o.id === g))

  // 清洗回写：首次拿到非空 grades 时执行一次（父级配置多为异步灌入，挂载时可能是 []，
  // 只看挂载会漏洗）。清洗后为空（存量配置全非法，如只剩 E）绝不可回写空集合——
  // 全空=所有岗位挂人工审批，等于静默停摆海投；回退与后端默认一致的 ["C","D","F"]。
  const cleanedRef = useRef(false)
  useEffect(() => {
    if (cleanedRef.current || grades.length === 0) return
    cleanedRef.current = true
    if (validGrades.length !== grades.length) {
      onChangeGrades(validGrades.length > 0 ? validGrades : DEFAULT_MASS_GRADES)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅首次非空灌入时清洗一次，随依赖回写会与父级 setState 成环
  }, [grades])

  const toggleGrade = (id: string) => {
    if (validGrades.includes(id)) {
      if (validGrades.length === 1) return // 至少保留 1 个等级，全空会导致所有岗位挂人工审批
      onChangeGrades(validGrades.filter((g) => g !== id))
    } else {
      onChangeGrades([...validGrades, id])
    }
  }

  const toggleTrack = (track: "custom" | "mass") => {
    const trackIds = GRADE_OPTIONS.filter((g) => g.track === track).map((g) => g.id)
    const allOn = trackIds.every((id) => validGrades.includes(id))
    if (allOn) {
      // 整轨取消至少要留下别的等级
      const rest = validGrades.filter((id) => !trackIds.includes(id))
      if (rest.length > 0) onChangeGrades(rest)
    } else {
      onChangeGrades([...new Set([...validGrades, ...trackIds])])
    }
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3">
      {/* 顶栏标题与感叹号说明 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <Filter className="h-3.5 w-3.5" />
          </div>
          <span className="text-xs font-semibold text-foreground tracking-tight">
            海投自动投递等级
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
              勾选的等级在 AI 评估完成后直接自动投递，不再挂人工审批；未勾选的等级会停在「简历人工复核」等待放行。A/B
              走定制轨（精修简历后投递），C/D/F 走海投轨（通用简历 + 打招呼语）。海投轨仍受公司规模门槛约束。
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[11px] text-muted-foreground">
          选中即投 · 未选挂审
        </span>
      </div>

      {/* 5 级勾选网格 */}
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
        {GRADE_OPTIONS.map((item) => {
          const isSelected = validGrades.includes(item.id)
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => toggleGrade(item.id)}
              className={cn(
                "flex flex-col items-center gap-0.5 rounded-xl border p-2.5 text-center transition-all cursor-pointer",
                isSelected
                  ? cn(item.color, "border-current/40 shadow-xs")
                  : "border-border/50 bg-background/40 text-muted-foreground opacity-60 hover:opacity-100 hover:border-border"
              )}
            >
              <span className="text-xs font-bold text-foreground">{item.name}</span>
              <span className="text-[10px] opacity-80">{item.desc}</span>
              <CheckCircle2
                className={cn(
                  "h-3.5 w-3.5 transition-opacity",
                  isSelected ? "opacity-100" : "opacity-0"
                )}
              />
            </button>
          )
        })}
      </div>

      {/* 轨道快捷开关 */}
      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        <span>快捷：</span>
        <button
          type="button"
          onClick={() => toggleTrack("custom")}
          className="rounded-full border border-border/60 px-2.5 py-0.5 transition-colors hover:border-emerald-500/40 hover:text-emerald-600 dark:hover:text-emerald-400 cursor-pointer"
        >
          定制轨 A/B
        </button>
        <button
          type="button"
          onClick={() => toggleTrack("mass")}
          className="rounded-full border border-border/60 px-2.5 py-0.5 transition-colors hover:border-amber-500/40 hover:text-amber-600 dark:hover:text-amber-400 cursor-pointer"
        >
          海投轨 C/D/F
        </button>
      </div>
    </div>
  )
}
