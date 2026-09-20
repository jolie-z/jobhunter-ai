import React, { useState, useEffect } from "react"
import { Check, X, Scale, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { API_BASE } from "@/lib/api"
import { createPanelResultCache } from "@/lib/resume-panel-cache"
import type { ResumeSection } from "@/types/resume"

interface WorkCompressorProps {
  works: ResumeSection[]
  customJdContext: string
  customDiagnosisContext: string
  jobId?: string
  onAccept: (compressions: { id: string, newContent: string }[]) => void
  onCancel: () => void
}

interface CompressResult {
  id: string
  score: number
  decision: "focus" | "compress"
  reason: string
  compressed_content: string
}


export function WorkCompressor({
  works,
  customJdContext,
  customDiagnosisContext,
  jobId,
  onAccept,
  onCancel,
}: WorkCompressorProps) {
  const [isGenerating, setIsGenerating] = useState(true)
  const [results, setResults] = useState<CompressResult[]>([])
  const [error, setError] = useState<string | null>(null)

  // IDs of work experiences that the user wants to compress
  const [selectedIdsToCompress, setSelectedIdsToCompress] = useState<Set<string>>(new Set())

  const panelCache = createPanelResultCache<CompressResult>({
    storageKey: "resume_compress_cache",
    sessionScope: "session_compress_last_results",
    jobId,
  })

  // Memoize dependency
  const worksIds = works.map(w => `${w.id}-${w.title}`).join('|')

  // 归属校验：缓存结果必须与当前条目列表一一对应，防止索引错位串内容
  const isResultSetValid = (res: CompressResult[]) =>
    works.length > 0 &&
    res.length === works.length &&
    res.every(r => works.some(w => w.id === r.id))

  const fetchResults = async (force: boolean = false) => {
    setIsGenerating(true)
    setError(null)
    try {
      const cacheKey = panelCache.localKey(worksIds, `${customJdContext.length}-${customDiagnosisContext.length}`)

      const localCache = panelCache.getLocalMap()
      if (!force && localCache.has(cacheKey)) {
        const cachedRes = localCache.get(cacheKey)!
        if (!isResultSetValid(cachedRes)) {
          localCache.delete(cacheKey)
          panelCache.saveLocalMap(localCache)
        } else {
          setResults(cachedRes)
          const toCompress = new Set<string>()
          cachedRes.forEach(item => {
            if (item.decision === "compress") {
              const work = works.find(w => w.id === item.id)
              if (work && !work.originalContent) {
                toCompress.add(item.id)
              }
            }
          })
          setSelectedIdsToCompress(toCompress)
          setIsGenerating(false)
          return
        }
      }

      // Session-level restore: show previous results immediately without re-fetching
      if (!force) {
        const sessionRes = panelCache.loadSession()
        if (sessionRes && !isResultSetValid(sessionRes)) {
          panelCache.clearSession()
        }
        if (sessionRes && isResultSetValid(sessionRes)) {
          setResults(sessionRes)
          const toCompress = new Set<string>()
          sessionRes.forEach(item => {
            if (item.decision === "compress") {
              const work = works.find(w => w.id === item.id)
              if (work && !work.originalContent) {
                toCompress.add(item.id)
              }
            }
          })
          setSelectedIdsToCompress(toCompress)
          setIsGenerating(false)
          return
        }
      }

      const response = await fetch(`${API_BASE}/api/strategy/compress_work_experience`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jd_text: customJdContext,
          diagnosis_report: customDiagnosisContext,
          work_experiences: works.map(w => ({
            id: w.id,
            title: w.title,
            content: w.content
          }))
        }),
      })

      if (!response.ok) {
        throw new Error("网络响应异常")
      }

      const data = await response.json()
      if (data.status !== "success") {
        throw new Error(data.message || "接口返回错误")
      }

      const res: CompressResult[] = data.data || []
      localCache.set(cacheKey, res)
      panelCache.saveLocalMap(localCache)
      panelCache.saveSession(res)
      setResults(res)
      
      const toCompress = new Set<string>()
      res.forEach(item => {
        if (item.decision === "compress") {
          const work = works.find(w => w.id === item.id)
          if (work && !work.originalContent) {
            toCompress.add(item.id)
          }
        }
      })
      setSelectedIdsToCompress(toCompress)
      setIsGenerating(false)
    } catch (err: any) {
      setError(err.message || "请求失败，请重试")
      setIsGenerating(false)
    }
  }

  useEffect(() => {
    if (works.length === 0) {
      setError("未找到任何工作经历")
      setIsGenerating(false)
      return
    }
    fetchResults()
  }, [worksIds, customJdContext, customDiagnosisContext])

  const toggleCompress = (id: string, checked: boolean) => {
    const next = new Set(selectedIdsToCompress)
    if (checked) {
      next.add(id)
    } else {
      next.delete(id)
    }
    setSelectedIdsToCompress(next)
  }

  const handleApply = () => {
    const compressions: { id: string, newContent: string }[] = []
    selectedIdsToCompress.forEach(id => {
      const res = results.find(r => r.id === id)
      if (res && res.compressed_content) {
        compressions.push({ id, newContent: res.compressed_content })
      }
    })
    onAccept(compressions)
  }

  const handleContentChange = (id: string, newContent: string) => {
    setResults(prev => prev.map(r => r.id === id ? { ...r, compressed_content: newContent } : r))
  }

  return (
    <div className="mt-2 w-full border border-purple-200 bg-purple-50/40 rounded-lg p-3 shadow-sm text-sm">
      <div className="flex items-center justify-between mb-3 border-b border-purple-200/60 pb-2">
        <h4 className="font-semibold flex items-center text-purple-700">
          <Scale className="mr-1.5 h-4 w-4" /> AI 工作经历战略折叠
        </h4>
        <div className="flex items-center gap-2">
          {!isGenerating && !error && (
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs text-purple-500 hover:text-purple-700 hover:bg-purple-100/50" onClick={() => fetchResults(true)}>
              重新生成
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-6 w-6 text-purple-400 hover:text-purple-700 hover:bg-purple-100/50" onClick={onCancel}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {isGenerating ? (
        <div className="flex flex-col items-center justify-center py-6 text-purple-600/70">
          <Loader2 className="h-6 w-6 animate-spin mb-2" />
          <p className="text-xs">正在基于 JD 与诊断报告，为您权衡每段经历的战略价值...</p>
        </div>
      ) : error ? (
        <div className="py-4 text-center">
          <p className="text-red-500 mb-2">出错了：{error}</p>
          <Button variant="outline" size="sm" onClick={onCancel}>关闭</Button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-purple-600/80 leading-relaxed mb-2">
            以下是 AI 为您权衡的“核心拿分项（建议着重写）”与“边缘项（建议一笔带过）”。
            <br />打勾的项目表示 <b>将要被折叠为两句话</b>，释放版面空间。未勾选的项目保持原样。
          </p>
          <div className="max-h-[300px] overflow-y-auto space-y-2 pr-1 custom-scrollbar">
            {works.map(w => {
              const res = results.find(r => r.id === w.id)
              const score = res?.score ?? 0
              const isCompress = res?.decision === "compress"
              const reason = res?.reason || "暂无理由"
              const willCompress = selectedIdsToCompress.has(w.id)

              return (
                <div 
                  key={w.id} 
                  className={`flex gap-3 items-start p-2.5 rounded-md border transition-colors ${
                    willCompress 
                      ? "bg-purple-100/60 border-purple-300" 
                      : "bg-white border-slate-200 hover:border-slate-300"
                  }`}
                >
                  <div className="mt-0.5">
                    {w.originalContent ? (
                       <div className="w-4 h-4 rounded border border-transparent flex items-center justify-center">
                         <Check className="h-3 w-3 text-purple-500" />
                       </div>
                    ) : isCompress ? (
                      <Checkbox 
                        checked={willCompress} 
                        onCheckedChange={(c) => toggleCompress(w.id, !!c)} 
                        className={willCompress ? "border-purple-500 data-[state=checked]:bg-purple-500" : ""}
                      />
                    ) : (
                      <div className="w-4 h-4 rounded border border-transparent flex items-center justify-center">
                        <Check className="h-3 w-3 text-green-600" />
                      </div>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`font-semibold text-[13px] truncate ${willCompress ? "text-purple-800 opacity-80" : "text-slate-800"}`}>
                        {w.title || "未命名经历"}
                      </span>
                      {res && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${
                          score >= 80 ? "bg-green-100 text-green-700" :
                          score >= 60 ? "bg-yellow-100 text-yellow-700" :
                          "bg-purple-100 text-purple-700"
                        }`}>
                          {score} 分
                        </span>
                      )}
                      {w.originalContent ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 bg-purple-100 text-purple-600 border border-purple-200">
                          已折叠
                        </span>
                      ) : isCompress ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 bg-purple-500 text-white">
                          建议略写
                        </span>
                      ) : (
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 bg-green-600 text-white">
                          核心拿分项 (着重写)
                        </span>
                      )}
                    </div>
                    <div className={`text-[11px] leading-relaxed mb-1 ${isCompress ? "text-slate-500" : "text-green-700/90 font-medium"}`}>
                      <b>指导建议：</b>{reason}
                    </div>
                    {isCompress && willCompress && res?.compressed_content && (
                      <div className="mt-2 flex flex-col gap-1.5">
                        <div className="p-2 bg-slate-50 rounded border border-slate-200 text-[11px] text-slate-500 whitespace-pre-wrap opacity-80">
                          {w.content}
                        </div>
                        <textarea
                          className="w-full min-h-[70px] p-2 bg-white rounded border border-purple-300 text-[11px] text-purple-900 whitespace-pre-wrap font-mono focus:outline-none focus:ring-1 focus:ring-purple-500 resize-none custom-scrollbar"
                          value={res.compressed_content}
                          onChange={(e) => handleContentChange(w.id, e.target.value)}
                        />
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          <div className="flex items-center justify-end gap-2 mt-4 pt-2 border-t border-purple-200/60">
            <Button variant="ghost" size="sm" className="h-7 text-xs text-purple-600 hover:bg-purple-100" onClick={onCancel}>
              取消
            </Button>
            <Button 
              size="sm" 
              className="h-7 text-xs bg-purple-600 hover:bg-purple-700 text-white gap-1 shadow-sm"
              onClick={handleApply}
            >
              <Check className="h-3.5 w-3.5" />
              {selectedIdsToCompress.size === 0 ? "跳过折叠 (完美保留)" : `一键应用折叠 (${selectedIdsToCompress.size})`}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
