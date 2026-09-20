"use client"

import { useState } from "react"
import { ShieldCheck, ChevronDown, ChevronUp, Code2, AlertOctagon, CheckCircle2, Award, FileSpreadsheet, Info } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface RewritePromptCardProps {
  promptRules?: string[]
}

const CLEAN_RULES = [
  {
    icon: AlertOctagon,
    color: "text-rose-500 bg-rose-500/10 border-rose-500/20",
    title: "🚫 严禁 AI 腥味黑话",
    tooltipTitle: "🚫 反 AI 黑话红线：",
    tooltipDesc: "自动拦截赋能、闭环、抓手、对齐、拉通、助力、深度参与等 12+ 虚假空洞黑话，杜绝动词修饰名词的病句。",
  },
  {
    icon: FileSpreadsheet,
    color: "text-indigo-500 bg-indigo-500/10 border-indigo-500/20",
    title: "🏢 工作经历全量保留",
    tooltipTitle: "🏢 时间线基石铁律：",
    tooltipDesc: "原简历有多少段工作经历，最终 100% 完整保留对应段落，严禁裁减候选人时间线，仅分层详略描写。",
  },
  {
    icon: Award,
    color: "text-amber-500 bg-amber-500/10 border-amber-500/20",
    title: "💎 五要素子弹点公式",
    tooltipTitle: "💎 猎头 Bullet 公式：",
    tooltipDesc: "每个子弹点严格满足：强动词 + 技术对象 + 约束难点/bad case + 采用方案 + 机制或量化成果。",
  },
  {
    icon: CheckCircle2,
    color: "text-emerald-500 bg-emerald-500/10 border-emerald-500/20",
    title: "🏷️ 三档证据防拷问标注",
    tooltipTitle: "🏷️ 证据链强度分级：",
    tooltipDesc: "经历行末附加 [稳] / [需补证] / [补证后可用]，协助候选人在业务面试时防被深度发难。",
  },
]

const PROMPT_SOURCE_SAMPLE = `## 🚀 简历改写 Prompt 核心规则与执行约束

你是一位严谨资深的技术猎头与简历重构专家。
你的任务是将候选人的原始简历重构为一份可以直接提交给 HR 和业务负责人的顶级简历。

### 1. 核心红线约束
- ❌ 绝对禁用 AI 味黑话词库（赋能/闭环/抓手/拉通/对齐/助力/深度参与）
- ❌ 严禁动词修饰名词的病句
- ❌ 严禁跨实体的无中生有（无某项技能绝对不允许凭空脑补）
- ✅ 工作经历严格全保留（按五要素子弹点详写 4-5 条，略写 1-2 条）
- ✅ 关键词加粗扫描（加粗核心技术栈与关键商业战果）

### 2. 输出结构
<THINKING>
1. ATS 技能推导与注入分析
2. 工作经历详写/略写决策
3. 项目经历高匹配度筛选
4. Truth Boundary 虚夸词自检与安全降级
</THINKING>

<FINAL_RESUME>
## 💡 个人总结
## 🛠️ 核心技能
## 🏢 工作经历
## 🚀 项目经历
## 🎓 教育背景
</FINAL_RESUME>`

export function RewritePromptCard({ promptRules }: RewritePromptCardProps) {
  const [showPromptSource, setShowPromptSource] = useState(false)

  return (
    <div className="rounded-2xl border border-border/80 bg-card p-4 space-y-3 shadow-xs">
      {/* 标题栏 */}
      <div className="flex items-center justify-between gap-2 border-b border-border/50 pb-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/20 font-bold shrink-0">
            <ShieldCheck className="h-3.5 w-3.5" />
          </div>
          <div className="flex items-center gap-1.5">
            <h3 className="font-semibold text-foreground text-xs tracking-tight">
              改写 Prompt 核心红线与排版规范
            </h3>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors cursor-pointer">
                  <Info className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                <p className="font-semibold text-zinc-100 mb-0.5">📜 改写红线与排版规范：</p>
                <p className="text-zinc-300 text-[11px]">
                  通过 4 项核心铁律严格约束大模型输出，杜绝 AI 假大空黑话，保证经历真实性，并优化 HR 快速扫视体验。
                </p>
              </TooltipContent>
            </Tooltip>
          </div>
        </div>

        {/* 查看源码 */}
        <button
          type="button"
          onClick={() => setShowPromptSource(!showPromptSource)}
          className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          <Code2 className="h-3 w-3" />
          <span>{showPromptSource ? "收起源码" : "Prompt 源码"}</span>
          {showPromptSource ? (
            <ChevronUp className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          )}
        </button>
      </div>

      {/* 4 大精简规则胶囊/卡片 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {CLEAN_RULES.map((rule, idx) => {
          const Icon = rule.icon
          return (
            <div
              key={idx}
              className="flex items-center justify-between p-2.5 rounded-xl border border-border/70 bg-muted/20 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-center gap-2 min-w-0 pr-1">
                <div className={`flex h-6 w-6 items-center justify-center rounded-lg border font-bold shrink-0 ${rule.color}`}>
                  <Icon className="h-3 w-3" />
                </div>
                <span className="font-medium text-foreground text-xs truncate">
                  {rule.title}
                </span>
              </div>

              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors cursor-pointer shrink-0">
                    <Info className="h-3.5 w-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                  <p className="font-semibold text-zinc-100 mb-0.5">{rule.tooltipTitle}</p>
                  <p className="text-zinc-300 text-[11px]">{rule.tooltipDesc}</p>
                </TooltipContent>
              </Tooltip>
            </div>
          )
        })}
      </div>

      {/* 可折叠 Prompt 源码预览 */}
      {showPromptSource && (
        <div className="rounded-xl border border-border/80 bg-zinc-950 p-3 text-[11px] font-mono text-zinc-300 overflow-x-auto space-y-2 animate-in fade-in duration-200">
          <div className="flex items-center justify-between text-[10px] text-zinc-500 border-b border-zinc-800 pb-1.5">
            <span>PROMPT SCHEMA SOURCE (resume_rewrite.md)</span>
            <span>Markdown Template</span>
          </div>
          <pre className="whitespace-pre-wrap leading-relaxed">
            {PROMPT_SOURCE_SAMPLE}
          </pre>
        </div>
      )}
    </div>
  )
}
