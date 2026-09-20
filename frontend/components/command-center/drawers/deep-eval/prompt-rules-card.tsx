"use client"

import { useState } from "react"
import { ShieldCheck, ChevronDown, ChevronUp, Code2, Info } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface PromptRulesCardProps {
  antiHallucinationRules: string[]
}

const SAMPLE_PROMPT_SNIPPET = `// 🌟 深度评估精炼系统提示词
你是一位严谨资深的技术面试官与简历合规审计专家，专注于真实性核验与技能差距诊断。

【输出格式要求（最高优先级）】
必须且仅输出纯净 JSON 对象，包含：
1. extracted_skills: 硬技能与工具清单
2. ats_ability_analysis: ATS词频重合度与缺失硬约束
3. resume_audit: 简历逐行审计 (✅安全 / ⚠️谨慎 / ❌高风险)
4. dream_picture: 目标岗位理想画像与3大核心能力信号
5. strong_fit_assessment: 高杠杆匹配点与王牌战果
6. risk_red_flags: 致命硬伤与被拒后果推演
7. deep_action_plan: 破局行动计划与[半天/1天/3天/1周]时间桶任务`

export function PromptRulesCard({ antiHallucinationRules }: PromptRulesCardProps) {
  const [showPrompt, setShowPrompt] = useState(false)

  return (
    <div className="rounded-2xl border border-border/70 bg-card p-4.5 space-y-3.5 shadow-xs">
      {/* 顶栏 */}
      <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-emerald-500" />
          <span className="font-semibold text-foreground text-xs">
            Prompt 架构与防编造审计铁律
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors">
                <Info className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
              <p className="font-semibold text-zinc-100 mb-0.5">🛡️ 防造假与真实性保障：</p>
              <p className="text-zinc-300 text-[11px]">
                深度评估严禁无中生有编造技能。对量化无证明、绝对化表述一律标为谨慎并提供安全降级措辞，确保后续改写简历 100% 经得起技术面试拷问。
              </p>
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[10px] text-muted-foreground font-mono">
          4 项硬性合规约束
        </span>
      </div>

      {/* 4 大防造假铁律 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {antiHallucinationRules.map((rule, idx) => (
          <div
            key={idx}
            className="flex items-start gap-2 p-2.5 rounded-xl bg-muted/20 border border-border/50 text-[11px]"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mt-1.5 shrink-0" />
            <span className="text-foreground/90 font-medium leading-relaxed">{rule}</span>
          </div>
        ))}
      </div>

      {/* 查看完整精炼 Prompt 折叠区 */}
      <div className="pt-1">
        <button
          type="button"
          onClick={() => setShowPrompt(!showPrompt)}
          className="inline-flex items-center gap-1.5 text-xs text-violet-600 dark:text-violet-400 hover:text-violet-700 font-medium transition-colors"
        >
          <Code2 className="h-3.5 w-3.5" />
          <span>{showPrompt ? "收起 Prompt 源码结构" : "查看精炼 Prompt 源码结构"}</span>
          {showPrompt ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>

        {showPrompt && (
          <div className="mt-2 p-3 rounded-xl bg-zinc-950 text-emerald-400 font-mono text-[11px] leading-relaxed border border-zinc-800 overflow-x-auto shadow-inner whitespace-pre-wrap">
            {SAMPLE_PROMPT_SNIPPET}
          </div>
        )}
      </div>
    </div>
  )
}
