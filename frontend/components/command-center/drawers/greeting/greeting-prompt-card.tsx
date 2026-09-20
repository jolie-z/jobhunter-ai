"use client"

import { useState, useEffect, useRef } from "react"
import { ShieldCheck, Info, ChevronDown, ChevronUp, FileCode, Sparkles, Edit3, RotateCcw, Trash2, Copy, Check } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface RuleItem {
  icon: string
  title: string
  ruleText: string
  tooltipNote: string
  highlight?: string
}

const CORE_RULES: RuleItem[] = [
  {
    icon: "🎯",
    title: "固定开场白（一字不差）",
    ruleText:
      "您好，认真看了贵公司岗位JD，核心胜任力我是全覆盖的，简单做个自我介绍方便您快速匹配:",
    tooltipNote:
      "固定首句直击 HR 筛选痛点，表明已认真阅读 JD 并确信全覆盖，迅速建立专业信任，大幅提升前 3 秒停留率。",
    highlight: "强制固定开场",
  },
  {
    icon: "🚫",
    title: "严禁 AI 腥味虚词套话",
    ruleText:
      "禁用「可能匹配、了解、协助、参与过、较高、大量、持续探索、习惯使用」等虚词或弱势套话，百分之百使用实打实的客观事实和硬核成果支撑。",
    tooltipNote:
      "HR 极度反感空洞的 AI 套话与弱势表达。剔除模糊词，展现笃定、自信的资深人选特质。",
    highlight: "零AI味与虚词",
  },
  {
    icon: "⚡",
    title: "2~3 条硬核量化子弹点",
    ruleText:
      "用数字列表（1. 2. 3.）输出 2 到 3 个最核心的匹配理由，只罗列独立主导项目、核心技术栈与可量化商业战果。",
    tooltipNote:
      "引擎将自动消费「深度评估」提取的高杠杆匹配点与王牌战果，条理清晰、极易扫读。",
    highlight: "量化事实支撑",
  },
  {
    icon: "📌",
    title: "固定结尾与字数红线 (150-250字)",
    ruleText:
      "总字数严格控制在 150-250 字之间（绝对不超过 300 字），结尾一字不差：这是我的简历，期待和您有关于岗位的深度沟通。",
    tooltipNote:
      "移动端与微聊窗口过长会导致阅读疲劳甚至被直接折叠忽略；短小精悍的陈述回复转化率最高。",
    highlight: "150-250字红线",
  },
]

interface GreetingPromptCardProps {
  promptMode: "official" | "custom"
  onPromptModeChange: (mode: "official" | "custom") => void
  customPrompt: string
  onCustomPromptChange: (text: string) => void
  officialPrompt?: string
  modelName?: string
}

export function GreetingPromptCard({
  promptMode,
  onPromptModeChange,
  customPrompt,
  onCustomPromptChange,
  officialPrompt = "",
  modelName = "mimo-v2.5-pro",
}: GreetingPromptCardProps) {
  const [showPromptDetails, setShowPromptDetails] = useState(false)
  const [copied, setCopied] = useState(false)
  // 「已复制」状态回退定时器（组件卸载时清理，防止 setState 泄漏）
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
    }
  }, [])

  const handleLoadOfficialTemplate = () => {
    if (officialPrompt) {
      onCustomPromptChange(officialPrompt)
      toast.success("已载入官方标准 Prompt 模版，您可以直接进行二次编辑修改")
    } else {
      toast.error("未能读取到官方模版内容")
    }
  }

  const handleCopy = async () => {
    const textToCopy = promptMode === "custom" ? customPrompt : officialPrompt
    if (!textToCopy) return
    if (!navigator.clipboard?.writeText) return
    try {
      await navigator.clipboard.writeText(textToCopy)
      setCopied(true)
      toast.success("Prompt 已复制到剪贴板")
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
      copiedTimer.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      // 剪贴板写入失败时不弹「已复制」提示
    }
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3.5">
      {/* 头部标题与双模式切换 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
        <div className="flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <ShieldCheck className="h-3.5 w-3.5" />
          </div>
          <span className="text-xs font-semibold text-foreground tracking-tight">
            Prompt 规则与提示词设置
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
              【官方标准】采用经过实战验证的 4 大黄金破冰 SOP；【自定义 Prompt】允许您自由替换全部 System Prompt 文本，按您独有的求职风格生成沟通开场白。
            </TooltipContent>
          </Tooltip>
        </div>

        {/* 模式选择胶囊与模型标识 */}
        <div className="flex items-center gap-2">
          <div className="inline-flex items-center rounded-xl bg-muted/60 p-0.5 border border-border/50 text-[11px]">
            <button
              type="button"
              onClick={() => onPromptModeChange("official")}
              className={cn(
                "inline-flex items-center gap-1 rounded-lg px-2.5 py-1 font-medium transition-all cursor-pointer",
                promptMode === "official"
                  ? "bg-background text-foreground shadow-xs font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Sparkles className="h-3 w-3 text-emerald-500" />
              <span>官方标准 SOP</span>
            </button>

            <button
              type="button"
              onClick={() => onPromptModeChange("custom")}
              className={cn(
                "inline-flex items-center gap-1 rounded-lg px-2.5 py-1 font-medium transition-all cursor-pointer",
                promptMode === "custom"
                  ? "bg-background text-violet-600 dark:text-violet-400 shadow-xs font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Edit3 className="h-3 w-3" />
              <span>自定义 Prompt</span>
            </button>
          </div>

          <span className="text-[10px] font-mono text-muted-foreground bg-muted/60 px-2 py-1 rounded-lg hidden md:inline-block">
            {modelName}
          </span>
        </div>
      </div>

      {/* 官方标准模式展示 */}
      {promptMode === "official" && (
        <div className="space-y-2 animate-in fade-in-50 duration-200">
          {CORE_RULES.map((rule, idx) => (
            <div
              key={idx}
              className="group flex items-start gap-2.5 rounded-xl border border-border/50 bg-background/50 p-2.5 transition-all hover:border-border hover:bg-muted/30"
            >
              <span className="text-sm shrink-0 mt-0.5 select-none">{rule.icon}</span>
              <div className="flex-1 min-w-0 space-y-0.5">
                <div className="flex items-center justify-between gap-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-semibold text-foreground">
                      {rule.title}
                    </span>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          className="inline-flex items-center justify-center text-muted-foreground/70 hover:text-foreground transition-colors cursor-help p-0.5 rounded-full"
                        >
                          <Info className="h-3 w-3 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                        {rule.tooltipNote}
                      </TooltipContent>
                    </Tooltip>
                  </div>

                  {rule.highlight && (
                    <span className="shrink-0 text-[10px] font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 px-1.5 py-0.2 rounded-full">
                      {rule.highlight}
                    </span>
                  )}
                </div>

                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  {rule.ruleText}
                </p>
              </div>
            </div>
          ))}

          {/* 展开查看官方完整 Prompt 源码 */}
          <div className="pt-1 flex items-center justify-between">
            <button
              type="button"
              onClick={() => setShowPromptDetails(!showPromptDetails)}
              className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            >
              <FileCode className="h-3 w-3" />
              <span>{showPromptDetails ? "收起官方 Prompt 源码" : "查看官方 Prompt 源码"}</span>
              {showPromptDetails ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </button>

            <button
              type="button"
              onClick={() => {
                onPromptModeChange("custom")
                if (!customPrompt && officialPrompt) {
                  onCustomPromptChange(officialPrompt)
                }
              }}
              className="inline-flex items-center gap-1 text-[11px] text-violet-600 dark:text-violet-400 hover:underline"
            >
              <Edit3 className="h-3 w-3" />
              <span>基于官方模版自定义编辑 &rarr;</span>
            </button>
          </div>

          {showPromptDetails && (
            <div className="mt-2 rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-zinc-950/90 p-3 text-[11px] text-zinc-300 font-mono space-y-2 animate-in fade-in-50 duration-200">
              <div className="flex items-center justify-between border-b border-zinc-800 pb-1.5">
                <span className="text-[10px] font-semibold text-zinc-400">
                  greeting_writer.md · 官方完整 System Prompt
                </span>
                <button
                  type="button"
                  onClick={handleCopy}
                  className="inline-flex items-center gap-1 text-[10px] text-zinc-400 hover:text-zinc-200"
                >
                  {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                  <span>{copied ? "已复制" : "复制"}</span>
                </button>
              </div>
              <pre className="overflow-x-auto whitespace-pre-wrap leading-relaxed text-[11px] text-zinc-300 max-h-60 overflow-y-auto">
                {officialPrompt || "加载中..."}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* 自定义 System Prompt 编辑模式 */}
      {promptMode === "custom" && (
        <div className="space-y-2.5 animate-in fade-in-50 duration-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] font-medium text-foreground">
                自定义 System Prompt 全文
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex items-center justify-center text-muted-foreground/70 hover:text-foreground transition-colors cursor-help p-0.5 rounded-full"
                  >
                    <Info className="h-3 w-3 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                  您可以在此处自由定义任何提示词、角色设定与禁忌约束。引擎在执行时会自动向大模型注入【目标岗位 JD】、【深度诊断报告】和【候选人简历】，无需手动硬编码。
                </TooltipContent>
              </Tooltip>
            </div>

            {/* 快捷操作栏 */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleLoadOfficialTemplate}
                className="inline-flex h-6 items-center gap-1 rounded-md border border-violet-500/30 bg-violet-500/10 px-2 text-[11px] font-medium text-violet-600 dark:text-violet-400 hover:bg-violet-500/20 active:scale-95 transition-all cursor-pointer"
              >
                <RotateCcw className="h-3 w-3" />
                <span>载入官方模版</span>
              </button>

              {customPrompt && (
                <>
                  <button
                    type="button"
                    onClick={handleCopy}
                    className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  >
                    {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                    <span>{copied ? "已复制" : "复制"}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onCustomPromptChange("")}
                    title="清空自定义 Prompt"
                    className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[11px] text-muted-foreground hover:bg-rose-500/10 hover:text-rose-500 transition-colors"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="relative">
            <textarea
              rows={8}
              value={customPrompt}
              onChange={(e) => onCustomPromptChange(e.target.value)}
              placeholder="在此粘贴或输入您的专属 System Prompt（例如设定您的特殊口吻、行业关键词、格式要求等）..."
              className="w-full resize-y min-h-[160px] rounded-xl border border-border/80 bg-zinc-950/90 dark:bg-zinc-950 text-zinc-100 dark:text-zinc-200 px-3.5 py-2.5 text-[11px] font-mono placeholder:text-zinc-600 focus:border-violet-500 focus:ring-1 focus:ring-violet-500 focus:outline-none transition-all leading-relaxed"
            />
            <div className="absolute right-2.5 bottom-2.5 flex items-center gap-2 pointer-events-none">
              <span className="font-mono text-[10px] text-zinc-400 bg-zinc-900/90 px-1.5 py-0.5 rounded-md">
                {customPrompt.length} 字符
              </span>
            </div>
          </div>

          <div className="rounded-xl bg-violet-500/5 border border-violet-500/15 p-2.5 flex items-start gap-2 text-[11px] text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5 text-violet-500 shrink-0 mt-0.5" />
            <span>
              <strong>底层安全防线保护</strong>：无论您自定义什么 Prompt，系统在生成时均会自动在末尾附带纯净打招呼语提取防护，确保发给招聘官的内容 100% 稳定无多余 AI 废话。
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
