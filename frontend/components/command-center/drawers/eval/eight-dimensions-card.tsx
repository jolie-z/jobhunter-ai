"use client"

import { Scale,  Info, HelpCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface EightDimensionsCardProps {
  weights: Record<string, number>
  onWeightChange: (key: string, val: number) => void
  onApplyPreset: (presetWeights: Record<string, number>) => void
}

const DIMENSION_CONFIGS = [
  {
    key: "role_match",
    label: "角色匹配",
    desc: "核心维度：岗位核心定位与候选人职能对口程度，行业背景对口加分",
    tag: "核心",
    tagColor: "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20",
  },
  {
    key: "skills_align",
    label: "技能重合",
    desc: "核心维度：对比硬技能与技术栈要求（如大模型、架构、前端、后端）",
    tag: "核心",
    tagColor: "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20",
  },
  {
    key: "seniority",
    label: "职级资历",
    desc: "高权维度：项目复杂度与独立带盘操盘能力（严禁无大厂经验盲目打低分）",
    tag: "高权",
    tagColor: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
  },
  {
    key: "compensation",
    label: "薪资契合",
    desc: "高权维度：岗位薪资范围与候选人期望重合度（强制优先读取基本信息）",
    tag: "高权",
    tagColor: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
  },
  {
    key: "interview_prob",
    label: "面试概率",
    desc: "高权维度：综合评估简历通过筛选并最终拿到 Offer 的综合概率",
    tag: "高权",
    tagColor: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
  },
  {
    key: "market_fit",
    label: "赛道前景",
    desc: "中权维度：结合网络实时搜索情报，评估公司所处赛道景气度与市场空间",
    tag: "中权",
    tagColor: "bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/20",
  },
  {
    key: "growth",
    label: "成长空间",
    desc: "中权维度：候选人技术广度拓展、业务操盘体量与职业发展空间",
    tag: "中权",
    tagColor: "bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/20",
  },
  {
    key: "company_stage",
    label: "公司阶段",
    desc: "中权保底：融资轮次与规模（采用中性保底逻辑，缺失时默认 3 分不倒扣分）",
    tag: "保底",
    tagColor: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
  },
]

const PRESET_MODES = [
  {
    name: "🎯 综合平衡",
    weights: {
      role_match: 1.0,
      skills_align: 1.0,
      seniority: 0.8,
      compensation: 0.8,
      interview_prob: 0.8,
      market_fit: 0.5,
      growth: 0.5,
      company_stage: 0.2,
    },
  },
  {
    name: "💰 薪资优先",
    weights: {
      role_match: 1.0,
      skills_align: 0.7,
      seniority: 0.9,
      compensation: 1.0,
      interview_prob: 0.8,
      market_fit: 0.4,
      growth: 0.4,
      company_stage: 0.2,
    },
  },
  {
    name: "🛠️ 技能对口",
    weights: {
      role_match: 1.0,
      skills_align: 1.0,
      seniority: 0.8,
      compensation: 0.6,
      interview_prob: 0.7,
      market_fit: 0.6,
      growth: 0.9,
      company_stage: 0.2,
    },
  },
  {
    name: "🚀 赛道成长",
    weights: {
      role_match: 0.9,
      skills_align: 0.8,
      seniority: 0.6,
      compensation: 0.6,
      interview_prob: 0.7,
      market_fit: 1.0,
      growth: 1.0,
      company_stage: 0.8,
    },
  },
]

// 与 eval-config-panel.tsx 顶部的 DEFAULT_WEIGHTS 保持完全一致（该常量未导出，此处为同步副本，修改时两处需同步）
const DEFAULT_WEIGHTS: Record<string, number> = {
  role_match: 1.0,
  skills_align: 1.0,
  seniority: 0.8,
  compensation: 0.8,
  interview_prob: 0.8,
  market_fit: 0.5,
  growth: 0.5,
  company_stage: 0.2,
}

export function EightDimensionsCard({
  weights,
  onWeightChange,
  onApplyPreset,
}: EightDimensionsCardProps) {
  return (
    <div className="rounded-2xl border border-border/70 bg-card p-4.5 space-y-4 shadow-xs">
      {/* 顶栏：标题 + 快捷预设 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 border-b border-border/50 pb-3">
        <div className="flex items-center gap-2">
          <Scale className="h-4 w-4 text-violet-500" />
          <span className="font-semibold text-foreground text-xs">
            八维智能评估加权矩阵
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors">
                <HelpCircle className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs space-y-2 p-3 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl">
              <p className="font-semibold text-zinc-100 flex items-center gap-1.5">
                <span>📐</span> 匹配度计算公式：
              </p>
              <div className="font-mono text-[11px] bg-zinc-950/80 text-emerald-400 border border-zinc-800 p-2 rounded-lg leading-relaxed shadow-inner">
                综合得分 = ∑(维度得分 × 权重) ÷ (5 × ∑权重) × 100%
              </div>
              <p className="text-zinc-300 text-[11px] leading-relaxed">
                <span className="text-amber-300 font-medium">≥90%</span> 为 A 级，
                <span className="text-sky-300 font-medium">75%~89%</span> 为 B 级，
                <span className="text-purple-300 font-medium">60%~74%</span> 为 C 级。<br />
                <span className="text-zinc-400">💡 中性维度（如公司阶段）采用 3 分保底，不产生倒扣分。</span>
              </p>
            </TooltipContent>
          </Tooltip>
        </div>

        {/* 预设模式按钮组 */}
        <div className="flex items-center gap-1 flex-wrap">
          {PRESET_MODES.map((preset) => (
            <button
              key={preset.name}
              type="button"
              onClick={() => onApplyPreset(preset.weights)}
              className="rounded-lg border border-border/70 bg-muted/20 px-2 py-1 text-[10px] font-medium text-foreground hover:bg-violet-500/10 hover:border-violet-500/30 hover:text-violet-600 dark:hover:text-violet-300 active:scale-95 transition-all"
            >
              {preset.name}
            </button>
          ))}
        </div>
      </div>

      {/* 8 维度滑块网格 (2 列排版) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3.5">
        {DIMENSION_CONFIGS.map((dim) => {
          const val = weights[dim.key] !== undefined ? weights[dim.key] : (DEFAULT_WEIGHTS[dim.key] ?? 0.8)
          return (
            <div key={dim.key} className="space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="font-medium text-foreground text-xs">{dim.label}</span>
                  <span
                    className={cn(
                      "rounded px-1.2 py-0.2 text-[9px] font-semibold border",
                      dim.tagColor
                    )}
                  >
                    {dim.tag}
                  </span>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button type="button" className="text-muted-foreground/50 hover:text-foreground">
                        <Info className="h-3 w-3" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                      {dim.desc}
                    </TooltipContent>
                  </Tooltip>
                </div>

                <span className="font-mono text-violet-600 dark:text-violet-400 text-xs font-bold bg-violet-500/10 px-1.5 py-0.2 rounded">
                  {val.toFixed(1)}
                </span>
              </div>

              <input
                type="range"
                min="0.1"
                max="1.0"
                step="0.1"
                value={val}
                onChange={(e) => onWeightChange(dim.key, parseFloat(e.target.value))}
                className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-violet-600 focus:outline-none"
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}
