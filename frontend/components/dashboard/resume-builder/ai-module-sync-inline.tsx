"use client"

import { useState, useEffect, useRef } from "react"
import { API_BASE } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Loader2, Sparkles, CheckCircle2, XCircle, AlertCircle } from "lucide-react"

export interface Block {
  id: number
  original_content: string
  new_content: string
  is_modified: boolean
}

export interface AiModuleSyncInlineProps {
  moduleTitle: string
  currentContent: string
  experiencesContext: string
  onAccept: (newContent: string) => void
  onCancel: () => void
}


export function AiModuleSyncInline({
  moduleTitle,
  currentContent,
  experiencesContext,
  onAccept,
  onCancel
}: AiModuleSyncInlineProps) {
  const [loading, setLoading] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [result, setResult] = useState<{
    blocks: Block[]
    reason: string
    is_modified: boolean
  } | null>(null)
  const [acceptedBlockIds, setAcceptedBlockIds] = useState<Set<number>>(new Set())
  const [error, setError] = useState("")
  // 组件卸载（收起面板/取消）时中断在飞的 LLM 请求，避免无效计费与迟到写入
  const abortRef = useRef<AbortController | null>(null)
  useEffect(() => () => abortRef.current?.abort(), [])

  // 已等待秒数：AI 联动是同步全量调用（实测约 1 分钟），明示耗时预期消除"卡死感"
  useEffect(() => {
    if (!loading) return
    setElapsedSeconds(0)
    const timer = setInterval(() => setElapsedSeconds(s => s + 1), 1000)
    return () => clearInterval(timer)
  }, [loading])

  const handleStartSync = async () => {
    if (!experiencesContext.trim()) {
      setError("当前没有经历数据可以作为更新依据。")
      return
    }

    setLoading(true)
    setError("")
    setResult(null)
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    // 120s 前端超时（实测单次全量调用约 60s，留一倍余量）；旧实现无超时最坏挂 12 分钟
    const timeoutId = setTimeout(() => controller.abort(), 120000)

    try {
      const res = await fetch(`${API_BASE}/api/strategy/sync_basic_module`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          module_title: moduleTitle,
          current_content: currentContent,
          experiences_context: experiencesContext
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
        setError(data.message || "请求失败")
      }
    } catch (err) {
      // 用户主动取消走 onCancel（组件卸载），setState 卸载后为 no-op；到达这里的
      // aborted = 120s 超时，给出可行动文案（R2 审查 H1：loading 复位收口到 finally）
      if (controller.signal.aborted) {
        setError("AI 联动超时（120 秒无响应），请检查网络或稍后重试")
      } else {
        setError("网络请求异常")
      }
    } finally {
      clearTimeout(timeoutId)
      setLoading(false)
    }
  }

  useEffect(() => {
    handleStartSync()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading) {
    return (
      <div className="mt-3 rounded-lg border border-indigo-100 bg-indigo-50/30 p-5 flex flex-col items-center justify-center text-indigo-500">
        <div className="w-full max-w-sm space-y-2.5 mb-4" aria-hidden>
          {/* 骨架屏：内容骨架行，替代单一 pulse 呼吸块 */}
          <div className="h-3 w-3/4 rounded bg-indigo-100 animate-pulse" />
          <div className="h-3 w-full rounded bg-indigo-100/80 animate-pulse" />
          <div className="h-3 w-5/6 rounded bg-indigo-100/60 animate-pulse" />
        </div>
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          <p className="text-sm font-medium">正在扫描全局经历，为您联动精修 {moduleTitle}...</p>
        </div>
        <div className="mt-1.5 flex items-center gap-3 text-xs text-indigo-400">
          <span>已等待 {elapsedSeconds}s（通常约 1 分钟）</span>
          <button onClick={onCancel} className="underline hover:text-indigo-600">取消</button>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-3 rounded-lg border border-red-100 bg-red-50 p-4 flex items-center justify-between">
        <div className="flex items-center gap-2 text-red-600 text-sm">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
        <Button variant="outline" size="sm" onClick={onCancel} className="h-8">取消</Button>
      </div>
    )
  }

  if (!result) return null

  return (
    <div className="mt-4 rounded-lg border border-indigo-100 bg-white p-5 shadow-sm ring-1 ring-black/5">
      <div className="flex items-center gap-2.5 mb-5 pb-3 border-b border-border/60">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-indigo-50">
          <Sparkles className="h-4 w-4 text-indigo-600" />
        </div>
        <h3 className="font-semibold text-sm text-foreground tracking-tight">联动更新报告</h3>
      </div>
      
      {!result.is_modified ? (
        <div className="py-6 text-center">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-emerald-50 mb-3">
            <CheckCircle2 className="h-5 w-5 text-emerald-500" />
          </div>
          <p className="text-sm font-medium text-foreground">当前模块已足够完善！</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-sm mx-auto">
            AI 扫描了您的全部经历，认为当前 {moduleTitle} 已经充分体现了所有亮点，无需补充。
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          <section>
            <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-amber-500" />
              更新理由
            </h4>
            <div className="text-sm text-zinc-600 bg-zinc-50/80 p-3 rounded-md border border-zinc-100/80">
              {result.reason}
            </div>
          </section>

          <section>
            <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-3">
              重构后文本预览（请按区块挑选采纳）
            </h4>
            <div className="space-y-3">
              {result.blocks?.map((block) => (
                <div 
                  key={block.id} 
                  className={`relative rounded-lg border p-3 transition-all ${
                    !block.is_modified 
                      ? 'bg-zinc-50 border-zinc-200 opacity-80' 
                      : acceptedBlockIds.has(block.id)
                        ? 'bg-indigo-50/40 border-indigo-300 shadow-sm ring-1 ring-indigo-200'
                        : 'bg-white border-zinc-200 hover:border-indigo-200'
                  }`}
                >
                  {!block.is_modified && (
                    <div className="absolute top-2 right-2 text-[10px] text-zinc-400 font-medium bg-zinc-100 px-1.5 py-0.5 rounded-full">
                      无需修改
                    </div>
                  )}
                  {block.is_modified && (
                    <div className="absolute top-2.5 right-2.5">
                      <label className="flex items-center gap-1.5 cursor-pointer text-xs font-medium">
                        <input 
                          type="checkbox" 
                          checked={acceptedBlockIds.has(block.id)}
                          onChange={() => {
                            const newSet = new Set(acceptedBlockIds)
                            if (newSet.has(block.id)) newSet.delete(block.id)
                            else newSet.add(block.id)
                            setAcceptedBlockIds(newSet)
                          }}
                          className="w-3.5 h-3.5 text-indigo-600 rounded border-zinc-300 focus:ring-indigo-500 cursor-pointer"
                        />
                        <span className={acceptedBlockIds.has(block.id) ? "text-indigo-700" : "text-zinc-500"}>
                          {acceptedBlockIds.has(block.id) ? '已采纳此修改' : '采纳此修改'}
                        </span>
                      </label>
                    </div>
                  )}
                  
                  <div className="space-y-2 mt-1">
                    {block.is_modified && block.original_content && (
                      <div className="text-xs text-zinc-400 line-through pr-20 whitespace-pre-wrap">
                        {block.original_content}
                      </div>
                    )}
                    <div className={`text-[13px] leading-[1.6] ${block.is_modified && acceptedBlockIds.has(block.id) ? 'text-indigo-900 font-medium' : 'text-zinc-700'} whitespace-pre-wrap`}>
                      {block.is_modified ? block.new_content : block.original_content}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between pt-4 border-t border-border">
        {result.is_modified ? (
          <div className="text-xs text-zinc-500">
            已选中 <span className="font-semibold text-indigo-600">{acceptedBlockIds.size}</span> 个优化区块
          </div>
        ) : <div />}
        <div className="flex items-center gap-2.5">
          <Button 
            onClick={() => {
              if (!result.is_modified) {
                onAccept(currentContent)
                return
              }
              const finalContent = (result.blocks || [])
                .map(b => acceptedBlockIds.has(b.id) ? b.new_content : b.original_content)
                .join("\n\n")
              onAccept(finalContent.trim() || currentContent)
            }}
            size="sm"
            className="bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition-all active:scale-[0.98]"
          >
            <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
            应用选中的修改
          </Button>
          <Button variant="outline" size="sm" onClick={onCancel} className="bg-white text-muted-foreground hover:text-foreground shadow-sm">
            <XCircle className="mr-1.5 h-3.5 w-3.5" />
            取消
          </Button>
        </div>
      </div>
    </div>
  )
}
