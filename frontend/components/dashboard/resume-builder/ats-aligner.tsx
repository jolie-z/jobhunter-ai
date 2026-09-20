"use client"

import React, { useState, useRef, useEffect } from "react"
import { API_BASE } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Loader2, Target, CheckCircle2, XCircle, Sparkles, AlertCircle } from "lucide-react"
import ReactMarkdown from 'react-markdown'

export interface Block {
  id: number
  original_content: string
  new_content: string
  is_modified: boolean
}

export interface AtsAlignerProps {
  originalExperience: string
  onAccept: (newContent: string) => void
  onCancel: () => void
  customJdContext?: string
  fullResumeContext?: string
}


export function AtsAligner({ originalExperience, onAccept, onCancel, customJdContext, fullResumeContext }: AtsAlignerProps) {
  const [isLoading, setIsLoading] = useState(false)
  const [result, setResult] = useState<{
    blocks: Block[]
    injected_keywords: string[]
    surgeon_rationale: string
    is_modified: boolean
  } | null>(null)
  const [acceptedBlockIds, setAcceptedBlockIds] = useState<Set<number>>(new Set())
  const [error, setError] = useState("")
  // 组件卸载（收起面板/取消）时中断在飞的 LLM 请求
  const abortRef = useRef<AbortController | null>(null)
  useEffect(() => () => abortRef.current?.abort(), [])

  // 🌟 组件挂载时自动开始诊断。此处不能加 ref 守卫拦"重复挂载"：StrictMode（dev 默认开）
  // 会模拟一次卸载-重挂，模拟卸载会触发上方 abort cleanup 中止首次请求，ref 守卫又拦掉
  // 重挂后的唯一一次启动，面板将永久卡在加载态（与 ai-module-sync-inline 保持同一模式）。
  useEffect(() => {
    handleStartAlign()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleStartAlign = async () => {
    setIsLoading(true)
    setError("")
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    try {
      let jdContext = customJdContext
      if (jdContext === undefined) {
        const jdRes = await fetch(`${API_BASE}/api/strategy/get_jd_report`, { signal: controller.signal })
        const jdData = await jdRes.json()
        // Q-M4-5：与 griller/dialog 口径对齐——后端异常（status!=="success"）时响亮报错，
        // 不再静默拿空串继续跑 ATS，让"没有画像"的错因可见
        if (jdData?.status !== "success" || !jdData?.data) {
          setError("尚未生成全局 A 级岗位画像，请先点击「A级岗位画像」生成后再对齐。")
          return
        }
        jdContext = jdData.data
      }

      const res = await fetch(`${API_BASE}/api/strategy/ats_align`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          original_experience: originalExperience,
          jd_report_context: jdContext,
          full_resume_context: fullResumeContext
        })
      })

      const data = await res.json()
      if (controller.signal.aborted) return
      if (res.ok && data.status === "success" && data.data) {
        setResult(data.data)
        if (data.data.blocks) {
          setAcceptedBlockIds(new Set(data.data.blocks.filter((b: Block) => b.is_modified).map((b: Block) => b.id)))
        }
      } else {
        setError(data.message || "未知错误")
      }
    } catch (err) {
      if (controller.signal.aborted) return
      setError("网络请求异常，请检查后端服务。")
    } finally {
      if (!controller.signal.aborted) setIsLoading(false)
    }
  }

  // Pre-process text to bold keywords and fix inline bullets
  const getHighlightedMarkdown = (text: string, keywords: string[]) => {
    let processedText = text;
    
    // 0. Remove the title row if LLM still hallucinated it (e.g. [Company · Role · Date])
    processedText = processedText.replace(/^\[.*?\]\n+/, '');
    
    // 1. Convert inline dots to proper Markdown lists
    processedText = processedText.replace(/(?:\s+|^)[·•]\s+/g, '\n\n- ');

    // 2. Highlight keywords
    if (keywords && keywords.length > 0) {
      keywords.forEach(kw => {
        if (!kw.trim()) return;
        const cleanKw = kw.replace(/[-[\]{}()*+?.,\\^$|#\s]/g, '\\$&');
        // First, remove existing exact bolding of this keyword to avoid double bolding
        processedText = processedText.replace(new RegExp(`\\*\\*${cleanKw}\\*\\*`, 'gi'), kw);
        // Then bold it
        processedText = processedText.replace(new RegExp(`(${cleanKw})`, 'gi'), `**$1**`);
      });
    }
    return processedText;
  }

  // State 1: Loading / Error（🌟 已去掉二次点击，组件挂载自动开始诊断）
  if (!result) {
    return (
      <div className="mt-5 rounded-lg border border-border bg-zinc-50/50 p-5 shadow-sm transition-all">
        <div className="flex items-center gap-2.5 mb-3 text-foreground">
          <Target className="h-5 w-5 text-indigo-500" />
          <h4 className="font-semibold text-sm">ATS 靶向诊断预检</h4>
        </div>
        {isLoading ? (
          <div className="flex items-center gap-3 py-4">
            <Loader2 className="h-5 w-5 animate-spin text-indigo-500" />
            <span className="text-sm text-muted-foreground">正在扫描与微调...</span>
          </div>
        ) : error ? (
          <div className="space-y-3">
            <div className="flex items-center gap-1.5 text-red-600 text-xs font-medium">
              <AlertCircle className="h-3.5 w-3.5" />
              {error}
            </div>
            <div className="flex items-center gap-3">
              <Button onClick={handleStartAlign} size="sm" className="bg-indigo-600 hover:bg-indigo-700 text-white">
                <Sparkles className="mr-2 h-4 w-4" />重试
              </Button>
              <Button variant="ghost" size="sm" onClick={onCancel} className="text-muted-foreground hover:text-foreground">
                取消
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 py-4">
            <Loader2 className="h-5 w-5 animate-spin text-indigo-500" />
            <span className="text-sm text-muted-foreground">正在准备诊断...</span>
          </div>
        )}
      </div>
    )
  }

  // State 2: Result view
  return (
    <div className="mt-5 rounded-lg border border-indigo-100 bg-white p-6 shadow-sm ring-1 ring-black/5">
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-border/60">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-indigo-50">
            <Target className="h-4 w-4 text-indigo-600" />
          </div>
          <h3 className="font-semibold text-base text-foreground tracking-tight">诊断与改写报告</h3>
        </div>
      </div>
      
      {!result.is_modified ? (
        <div className="py-8 text-center">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 mb-3">
            <CheckCircle2 className="h-6 w-6 text-emerald-500" />
          </div>
          <p className="text-sm font-medium text-foreground">完美匹配！</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-sm mx-auto">
            您的原始经历已经非常专业，完美包含了 A 级画像的核心要素，无需进行额外微调。
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          
          {/* Section: Rationale */}
          <section>
            <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-amber-500" />
              诊断理由与手术切入点
            </h4>
            <div className="prose prose-sm prose-zinc max-w-none text-muted-foreground bg-zinc-50/80 p-4 rounded-md border border-zinc-100/80">
              <ReactMarkdown>{result.surgeon_rationale}</ReactMarkdown>
            </div>
          </section>

          {/* Section: Keywords */}
          {result.injected_keywords && result.injected_keywords.length > 0 && (
            <section>
              <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-3">
                成功注入 ATS 核心词汇
              </h4>
              <div className="flex flex-wrap gap-2">
                {result.injected_keywords.map((kw, idx) => (
                  <span key={idx} className="inline-flex items-center rounded-md border border-indigo-200/60 bg-indigo-50/80 px-2.5 py-1 text-xs font-medium text-indigo-700 shadow-sm">
                    {kw}
                  </span>
                ))}
              </div>
            </section>
          )}
          
          {/* Section: Preview (Block-based Diff) */}
          <section>
            <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-3">
              重构后文本预览（请按区块挑选采纳）
            </h4>
            <div className="space-y-4">
              {result.blocks?.map((block) => (
                <div 
                  key={block.id} 
                  className={`relative rounded-lg border p-4 transition-all ${
                    !block.is_modified 
                      ? 'bg-zinc-50 border-zinc-200 opacity-80' 
                      : acceptedBlockIds.has(block.id)
                        ? 'bg-indigo-50/40 border-indigo-300 shadow-sm ring-1 ring-indigo-200'
                        : 'bg-white border-zinc-200 hover:border-indigo-200'
                  }`}
                >
                  {!block.is_modified && (
                    <div className="absolute top-2 right-3 text-xs text-zinc-400 font-medium bg-zinc-100 px-2 py-0.5 rounded-full">
                      无需修改
                    </div>
                  )}
                  {block.is_modified && (
                    <div className="absolute top-3 right-3">
                      <label className="flex items-center gap-2 cursor-pointer text-sm font-medium">
                        <input 
                          type="checkbox" 
                          checked={acceptedBlockIds.has(block.id)}
                          onChange={() => {
                            const newSet = new Set(acceptedBlockIds)
                            if (newSet.has(block.id)) newSet.delete(block.id)
                            else newSet.add(block.id)
                            setAcceptedBlockIds(newSet)
                          }}
                          className="w-4 h-4 text-indigo-600 rounded border-zinc-300 focus:ring-indigo-500 cursor-pointer"
                        />
                        <span className={acceptedBlockIds.has(block.id) ? "text-indigo-700" : "text-zinc-500"}>
                          {acceptedBlockIds.has(block.id) ? '已采纳此修改' : '采纳此修改'}
                        </span>
                      </label>
                    </div>
                  )}
                  
                  <div className="space-y-3 mt-1">
                    {block.is_modified && (
                      <div className="text-[13px] text-zinc-500 line-through pr-24 whitespace-pre-wrap">
                        {block.original_content}
                      </div>
                    )}
                    <div className={`text-[13px] leading-[1.8] ${block.is_modified && acceptedBlockIds.has(block.id) ? 'text-indigo-900 font-medium' : 'text-zinc-700'} space-y-3 [&_p]:mb-2 [&_ul]:pl-5 [&_ul]:list-disc [&_ul]:space-y-1.5 [&_li]:pl-1 [&_li]:mb-1`}>
                      {block.is_modified ? (
                        <ReactMarkdown
                          components={{
                            strong: ({ node, ...props }) => (
                              <strong className="bg-indigo-100/80 text-indigo-800 font-bold px-1 py-0.5 rounded-sm mx-0.5" {...props} />
                            )
                          }}
                        >
                          {getHighlightedMarkdown(block.new_content, result.injected_keywords || [])}
                        </ReactMarkdown>
                      ) : (
                        <div className="whitespace-pre-wrap">{block.original_content}</div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {/* Footer Actions */}
      <div className="mt-8 flex items-center justify-between pt-4 border-t border-border">
        {result.is_modified ? (
          <div className="text-sm text-zinc-500">
            已选中 <span className="font-semibold text-indigo-600">{acceptedBlockIds.size}</span> 个优化区块
          </div>
        ) : <div />}
        <div className="flex items-center gap-3">
          <Button 
            onClick={() => {
              if (!result.is_modified) {
                onAccept(originalExperience)
                return
              }
              const finalContent = (result.blocks || [])
                .map(b => acceptedBlockIds.has(b.id) ? b.new_content : b.original_content)
                .join("\n\n")
              onAccept(finalContent.trim() || originalExperience)
            }}
            className="bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition-all active:scale-[0.98]"
          >
            <CheckCircle2 className="mr-2 h-4 w-4" />
            应用选中的修改
          </Button>
          <Button variant="outline" onClick={onCancel} className="bg-white text-muted-foreground hover:text-foreground shadow-sm">
            <XCircle className="mr-2 h-4 w-4" />
            丢弃修改
          </Button>
        </div>
      </div>
    </div>
  )
}
