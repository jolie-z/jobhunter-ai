"use client"

import { useState, useEffect } from "react"
import {
  Terminal, BookOpen, Copy, Check, Sparkles, MessageSquareCode,
  ExternalLink, ChevronRight
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  FEISHU_CHATOPS_TUTORIAL,
  CHATOPS_COMMANDS,
  type ChatOpsCommandGroup,
  type Tutorial,
} from "../strategy-lab/system-config-meta"

interface ChatOpsGuideCardProps {
  apiBase: string
}

export function ChatOpsGuideCard({ apiBase }: ChatOpsGuideCardProps) {
  const [commandGroups, setCommandGroups] = useState<ChatOpsCommandGroup[]>(CHATOPS_COMMANDS)
  const [copiedPhrase, setCopiedPhrase] = useState<string | null>(null)
  const [showTutorial, setShowTutorial] = useState(false)
  const [activeCategory, setActiveCategory] = useState<string>(CHATOPS_COMMANDS[0]?.category || "岗位与简历")

  // 动态从后端拉取 TOOL_META，保证话术与后端注册工具绝对一致
  useEffect(() => {
    const icons: Record<string, string> = {
      "岗位与简历": "📋",
      "评估与进度": "🚀",
      "表格维护": "🧹",
      "数据与战报": "📊",
    }
    fetch(`${apiBase}/api/chatops/tools`)
      .then((r) => r.json())
      .then((data) => {
        if (data?.code === 0 && Array.isArray(data.data?.categories) && data.data.categories.length > 0) {
          setCommandGroups(
            data.data.categories.map((c: { category: string; commands: ChatOpsCommandGroup["commands"] }) => ({
              category: c.category,
              icon: icons[c.category] || "•",
              commands: c.commands || [],
            }))
          )
        }
      })
      .catch(() => {
        // 后端不可用时保留静态兜底
      })
  }, [apiBase])

  const handleCopy = (phrase: string) => {
    navigator.clipboard.writeText(phrase)
    setCopiedPhrase(phrase)
    setTimeout(() => setCopiedPhrase(null), 1800)
  }

  const currentGroup = commandGroups.find((g) => g.category === activeCategory) || commandGroups[0]

  return (
    <div className="rounded-2xl border border-border/70 bg-card p-6 shadow-sm">
      {/* 头部 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-violet-500/10 text-violet-600">
            <MessageSquareCode className="size-5" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-foreground">飞书 ChatOps 指令集</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              在飞书群 @机器人 下达自然语言指令，AI Agent 自动分析意图并调用自动化工具完成操作。
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => setShowTutorial(true)}
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-medium text-slate-700 shadow-xs transition-all hover:bg-slate-50 hover:border-slate-300 active:scale-[0.98]"
        >
          <BookOpen className="size-3.5 text-violet-600" />
          教程说明
        </button>
      </div>

      {/* 分类标签切换 */}
      <div className="mt-5 flex flex-wrap items-center gap-1.5 border-b border-border/60 pb-3">
        {commandGroups.map((g) => {
          const isActive = g.category === activeCategory
          return (
            <button
              key={g.category}
              type="button"
              onClick={() => setActiveCategory(g.category)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                isActive
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              <span>{g.icon}</span>
              <span>{g.category}</span>
              <span className={`text-[10px] ${isActive ? "opacity-90" : "opacity-60"}`}>
                ({g.commands.length})
              </span>
            </button>
          )
        })}
      </div>

      {/* 指令与话术展示区 */}
      {currentGroup && (
        <div className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            {currentGroup.commands.map((cmd) => (
              <div
                key={cmd.tool}
                className="group relative flex flex-col justify-between rounded-xl border border-border/60 bg-background/60 p-3.5 transition-all hover:border-primary/40 hover:bg-card hover:shadow-sm"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] font-medium text-primary bg-primary/10 px-2 py-0.5 rounded-md">
                      {cmd.tool}
                    </span>
                  </div>
                  <p className="mt-1.5 text-xs font-medium text-foreground">{cmd.desc}</p>
                </div>

                <div className="mt-3 space-y-1.5 border-t border-border/40 pt-2.5">
                  <p className="text-[10px] uppercase font-semibold text-muted-foreground/70 tracking-wider">
                    推荐群聊话术示例：
                  </p>
                  <div className="flex flex-col gap-1">
                    {cmd.phrases.map((phrase) => {
                      const isCopied = copiedPhrase === phrase
                      return (
                        <button
                          key={phrase}
                          type="button"
                          onClick={() => handleCopy(phrase)}
                          className="flex items-center justify-between rounded-lg bg-muted/40 px-2.5 py-1.5 text-left text-xs text-foreground/90 transition-colors hover:bg-muted hover:text-foreground"
                        >
                          <span className="truncate pr-2 font-mono text-[11px]">{phrase}</span>
                          <span className="shrink-0 text-muted-foreground">
                            {isCopied ? (
                              <Check className="size-3 text-emerald-500" />
                            ) : (
                              <Copy className="size-3 opacity-40 group-hover:opacity-100" />
                            )}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 启用教程弹窗 */}
      <Dialog open={showTutorial} onOpenChange={setShowTutorial}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base font-semibold">
              <Sparkles className="size-4 text-violet-600" />
              {FEISHU_CHATOPS_TUTORIAL.title}
            </DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              {FEISHU_CHATOPS_TUTORIAL.intro}
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4 space-y-3">
            {FEISHU_CHATOPS_TUTORIAL.steps.map((step, idx) => (
              <div key={step.title} className="flex gap-3 rounded-xl border border-border/60 bg-muted/20 p-3.5">
                <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                  {idx + 1}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-foreground">{step.title}</p>
                  <p className="mt-1 whitespace-pre-line text-xs leading-relaxed text-muted-foreground">
                    {step.desc}
                  </p>
                </div>
              </div>
            ))}

            {FEISHU_CHATOPS_TUTORIAL.tip && (
              <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-3 text-xs leading-relaxed text-blue-700 dark:text-blue-400">
                <span className="font-semibold">💡 架构提示：</span>
                {FEISHU_CHATOPS_TUTORIAL.tip}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
