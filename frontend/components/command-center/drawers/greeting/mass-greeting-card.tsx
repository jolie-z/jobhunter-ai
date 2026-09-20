"use client"

import { useState, useEffect, useRef } from "react"
import { Sparkles, Info, RefreshCw, Copy, Check, Trash2 } from "lucide-react"
import { toast } from "sonner"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { API_BASE } from "@/lib/api"

interface MassGreetingCardProps {
  massGreeting: string
  onChangeMassGreeting: (text: string) => void
}

export function MassGreetingCard({
  massGreeting,
  onChangeMassGreeting,
}: MassGreetingCardProps) {
  const [generating, setGenerating] = useState(false)
  const [copied, setCopied] = useState(false)
  // 「已复制」状态回退定时器（组件卸载时清理，防止 setState 泄漏）
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
    }
  }, [])

  const handleGenerateTemplate = async () => {
    setGenerating(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/generate-mass-greeting`, {
        method: "POST",
      })
      const result = await res.json()
      if (res.ok && result.status === "success" && result.greeting) {
        onChangeMassGreeting(result.greeting)
        toast.success("AI 通用打招呼语模版生成成功！")
      } else {
        toast.error(result.detail || "生成失败，请确认已上传启用简历与A级画像")
      }
    } catch {
      toast.error("网络异常，无法生成通用打招呼语")
    } finally {
      setGenerating(false)
    }
  }

  const handleCopy = async () => {
    if (!massGreeting) return
    if (!navigator.clipboard?.writeText) return
    try {
      await navigator.clipboard.writeText(massGreeting)
      setCopied(true)
      toast.success("已复制到剪贴板")
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
      copiedTimer.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      // 剪贴板写入失败时不弹「已复制」提示
    }
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3">
      {/* 头部标题与操作 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold text-foreground tracking-tight">
            海投/通用打招呼语（可选复用）
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
              在 C/B 级批量海投或快速流转阶段，若配置了通用话术，系统将直接复用，实现
              <strong className="text-violet-400"> 0 延迟与 0 Token 消耗</strong>；若留空，系统将根据岗位 JD 现场调用 LLM 实时生成。
            </TooltipContent>
          </Tooltip>
        </div>

        {/* 快捷操作区 */}
        <div className="flex items-center gap-1.5">
          {massGreeting && (
            <>
              <button
                type="button"
                onClick={handleCopy}
                title="复制话术"
                className="inline-flex h-6 items-center gap-1 rounded-md px-2 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                <span>{copied ? "已复制" : "复制"}</span>
              </button>
              <button
                type="button"
                onClick={() => onChangeMassGreeting("")}
                title="清空通用话术"
                className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[11px] text-muted-foreground hover:bg-rose-500/10 hover:text-rose-500 transition-colors"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </>
          )}

          {/* AI 一键生成按钮 */}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleGenerateTemplate}
              disabled={generating}
              className="inline-flex h-6.5 items-center gap-1 rounded-lg border border-violet-500/30 bg-violet-500/10 px-2.5 text-[11px] font-medium text-violet-600 dark:text-violet-400 hover:bg-violet-500/20 active:scale-95 transition-all disabled:opacity-50 cursor-pointer"
            >
              {generating ? (
                <RefreshCw className="h-3 w-3 animate-spin text-violet-500" />
              ) : (
                <Sparkles className="h-3 w-3 text-violet-500" />
              )}
              <span>{generating ? "正在生成..." : "AI 生成通用模版"}</span>
            </button>

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
                结合当前启用的基准简历与全局 A 级岗位画像，调用破冰打招呼引擎一键生成高匹配度的通用开场白。
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>

      {/* 文本输入框 */}
      <div className="relative">
        <textarea
          rows={4}
          value={massGreeting}
          onChange={(e) => onChangeMassGreeting(e.target.value)}
          placeholder="可在此粘贴或由 AI 生成一段通用的破冰开场白（留空则每个岗位现场实时调用大模型生成）..."
          className="w-full resize-none rounded-xl border border-border/80 bg-background/80 px-3.5 py-2.5 text-xs text-foreground placeholder:text-muted-foreground/60 focus:border-violet-500 focus:ring-1 focus:ring-violet-500 focus:outline-none transition-all leading-relaxed font-sans"
        />

        <div className="absolute right-2.5 bottom-2.5 flex items-center gap-2 pointer-events-none">
          <span
            className={`font-mono text-[10px] ${
              massGreeting.length > 250
                ? "text-amber-500 font-semibold"
                : "text-muted-foreground/70"
            }`}
          >
            {massGreeting.length} / 250 字
          </span>
        </div>
      </div>

      {/* 生效范围显式说明：避免「精投岗发出的是 AI 定制话术」被误判为通用语失效 */}
      <p className="text-[10px] leading-relaxed text-muted-foreground/70">
        生效范围：仅海投轨（C/B 级）岗位直接复用此通用话术；精投轨（A/S
        级）岗位由 AI 针对岗位 JD 实时生成专属开场白，不使用本配置。
      </p>
    </div>
  )
}
