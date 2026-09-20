"use client"

import { useState, useEffect, useCallback } from "react"
import { RefreshCw, Cpu, CheckCircle2 } from "lucide-react"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { ActiveResumeMeta } from "./common/active-resume-banner"
import { DeepModulesGrid, DeepModuleItem } from "./deep-eval/deep-modules-grid"
import { PromptRulesCard } from "./deep-eval/prompt-rules-card"

interface DeepEvalConfigPanelProps {
  onSaved?: () => void
}

const DEFAULT_MODULES: DeepModuleItem[] = [
  {
    key: "ats_ability_analysis",
    name: "01·ATS 词频与硬技能提取",
    icon: "🎯",
    desc: "提取 JD 明确要求的 Must-Have 与 Nice-to-Have 技能列表，执行词汇重合度比对，并列出严禁在改写中凭空注入的缺失项硬约束。",
  },
  {
    key: "resume_audit",
    name: "02·简历逐行合规审计",
    icon: "🔍",
    desc: "按个人总结、技能、项目、工作分段审计主张与证据，标出 ✅安全 / ⚠️谨慎 / ❌高风险，并为绝对化表述提供安全措辞降噪建议。",
  },
  {
    key: "dream_picture",
    name: "03·理想画像与能力信号",
    icon: "🌟",
    desc: "提炼目标岗位业务面试官最关心的 3 个核心能力信号与理想人选特质。",
  },
  {
    key: "strong_fit_assessment",
    name: "04·高杠杆匹配点",
    icon: "🚀",
    desc: "挖掘候选人最硬核、最能溢价打动用人部门的王牌经验与商业战果。",
  },
  {
    key: "risk_red_flags",
    name: "05·致命硬伤与后果推演",
    icon: "⚠️",
    desc: "预判面试官会发难的核心质疑点与技术短板，推演初筛被刷风险。",
  },
  {
    key: "deep_action_plan",
    name: "06·破局行动计划与时间桶任务",
    icon: "📋",
    desc: "制定针对本岗位的定制改写策略、向候选人索取关键技术细节清单，并生成 [半天/1天/3天/1周] 具体可交付的技能补强任务与预期匹配度提升。",
  },
]

const DEFAULT_RULES = [
  "只审计简历中实际写明的内容，严禁凭空脑补",
  "量化数据若无评估方法说明一律标记 ⚠️谨慎",
  "绝对化表述 (100%/零失误/彻底/精通) 一律标记 ⚠️谨慎并给出降级措辞",
  "缺失技能严禁以任何形式在后续改写中造假编造",
]

export function DeepEvalConfigPanel({ onSaved }: DeepEvalConfigPanelProps) {
  const [modelName, setModelName] = useState("mimo-v2.5-pro")
  const [temperature, setTemperature] = useState(0.2)
  const [activeResume, setActiveResume] = useState<ActiveResumeMeta>({
    title: "默认基准简历",
    status: "启用",
    word_count: 0,
  })
  const [allResumes, setAllResumes] = useState<ActiveResumeMeta[]>([])
  const [modules, setModules] = useState<DeepModuleItem[]>(DEFAULT_MODULES)
  const [antiHallucinationRules, setAntiHallucinationRules] = useState<string[]>(DEFAULT_RULES)

  const [loading, setLoading] = useState(true)

  const fetchConfig = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/deep-eval-config`)
      const result = await res.json()
      if (result.code === 0 && result.data) {
        const d = result.data
        if (d.model_name) setModelName(d.model_name)
        if (d.temperature !== undefined) setTemperature(d.temperature)
        if (d.active_resume) setActiveResume(d.active_resume)
        if (d.all_resumes) setAllResumes(d.all_resumes)
        if (d.modules) setModules(d.modules)
        if (d.anti_hallucination_rules) setAntiHallucinationRules(d.anti_hallucination_rules)
      }
    } catch {
      toast.error("读取深度评估配置异常")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  if (loading) {
    return (
      <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin mr-2 text-violet-500" />
        正在加载深度评估诊断矩阵与 Prompt 架构...
      </div>
    )
  }

  return (
    <div className="space-y-4 text-xs select-none">
      {/* 1. 推理基座信息 */}
      <div className="rounded-2xl border border-border/70 bg-gradient-to-b from-card to-muted/10 p-4 space-y-2.5 shadow-xs">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-violet-500/10 text-violet-600 dark:text-violet-400 border border-violet-500/20 font-bold shadow-xs">
              <Cpu className="h-4 w-4" />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-foreground text-xs tracking-tight">
                深度诊断推理模型
              </span>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/25 px-2 py-0.5 text-[10px] font-medium font-mono">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                {modelName || "mimo-v2.5-pro"}
              </span>
              <span className="rounded-full bg-muted border border-border/60 px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                Temperature: {temperature} (严谨模式)
              </span>

              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                  <p className="font-semibold text-zinc-100 mb-0.5">🧠 严谨诊断推理模式：</p>
                  <p className="text-zinc-300 text-[11px]">
                    深度评估采用严格的 JSON Object 强约束模式与 0.2 低温采样，杜绝幻觉，确保逐行审计真实可信。
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
          </div>
        </div>
      </div>

      {/* 3. 深度体检 6 大核心诊断输出矩阵 */}
      <DeepModulesGrid modules={modules} />

      {/* 4. Prompt 架构与防编造审计铁律 */}
      <PromptRulesCard antiHallucinationRules={antiHallucinationRules} />
    </div>
  )
}
