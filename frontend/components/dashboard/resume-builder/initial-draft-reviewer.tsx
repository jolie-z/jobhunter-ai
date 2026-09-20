import React, { useState, useEffect } from "react"
import { Check, X, FileText, Loader2, ArrowRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { API_BASE } from "@/lib/api"
import { createPanelResultCache } from "@/lib/resume-panel-cache"
import type { ResumeSection } from "@/types/resume"

interface InitialDraftReviewerProps {
  sections: ResumeSection[]
  parentCategory: string  // "工作经历" | "项目经历"，传递给后端让 LLM 区分 STAR/CRD
  customJdContext: string
  customDiagnosisContext: string
  fullResumeContext?: string  // 🌟 全量简历视野，注入后端后触发加强版全量视野约束指令
  jobId?: string
  onAccept: (drafts: { id: string, newContent: string }[]) => void
  onCancel: () => void
  /** 错误态关闭时通知外层"本次不会有产出"（如模块经历为空），供向导队列把该项置为已完成 */
  onResolveWithoutDraft?: () => void
}

interface DraftResult {
  id: string
  initial_draft_content: string
}


export function InitialDraftReviewer({
  sections,
  parentCategory,
  customJdContext,
  customDiagnosisContext,
  fullResumeContext,
  jobId,
  onAccept,
  onCancel,
  onResolveWithoutDraft,
}: InitialDraftReviewerProps) {
  const [isGenerating, setIsGenerating] = useState(true)
  const [results, setResults] = useState<DraftResult[]>([])
  const [error, setError] = useState<string | null>(null)

  const [selectedIdsToApply, setSelectedIdsToApply] = useState<Set<string>>(new Set())

  const panelCache = createPanelResultCache<DraftResult>({
    storageKey: "resume_initial_draft_cache",
    sessionScope: "session_draft_last_results",
    jobId,
    scope: parentCategory,
  })

  const sectionsIds = sections.map(s => `${s.id}-${s.title}`).join('|')

  // 归属校验：缓存结果必须与当前条目列表一一对应，防止索引错位串内容
  const isResultSetValid = (res: DraftResult[]) =>
    sections.length > 0 &&
    res.length === sections.length &&
    res.every(r => sections.some(s => s.id === r.id))

  const fetchResults = async (force: boolean = false) => {
    setIsGenerating(true)
    setError(null)
    try {
      const cacheKey = panelCache.localKey(sectionsIds, `${customJdContext.length}-${customDiagnosisContext.length}`)

      const localCache = panelCache.getLocalMap()
      if (!force && localCache.has(cacheKey)) {
        const cachedRes = localCache.get(cacheKey)!
        if (!isResultSetValid(cachedRes)) {
          localCache.delete(cacheKey)
          panelCache.saveLocalMap(localCache)
        } else {
          setResults(cachedRes)
          const preSelected = cachedRes.filter(r => {
            const s = sections.find(sec => sec.id === r.id)
            return s && !s.isDrafted
          }).map(r => r.id)
          setSelectedIdsToApply(new Set(preSelected))
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
          const preSelected = sessionRes.filter(r => {
            const s = sections.find(sec => sec.id === r.id)
            return s && !s.isDrafted
          }).map(r => r.id)
          setSelectedIdsToApply(new Set(preSelected))
          setIsGenerating(false)
          return
        }
      }

      const response = await fetch(`${API_BASE}/api/strategy/initial_draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jd_text: customJdContext,
          diagnosis_report: customDiagnosisContext,
          experiences: sections.map(s => ({
            id: s.id,
            title: s.title,
            content: s.content,
            category: parentCategory  // 传递父模块类别："工作经历" 或 "项目经历"
          })),
          full_resume_context: fullResumeContext || null
        }),
      })

      if (!response.ok) {
        throw new Error("网络响应异常")
      }

      const data = await response.json()
      if (data.status !== "success") {
        throw new Error(data.message || "接口返回错误")
      }

      const res: DraftResult[] = data.data || []
      localCache.set(cacheKey, res)
      panelCache.saveLocalMap(localCache)
      panelCache.saveSession(res)
      setResults(res)
      const preSelected = res.filter(r => {
        const s = sections.find(sec => sec.id === r.id)
        return s && !s.isDrafted
      }).map(r => r.id)
      setSelectedIdsToApply(new Set(preSelected))
      setIsGenerating(false)
    } catch (err: any) {
      setError(err.message || "请求失败，请重试")
      setIsGenerating(false)
    }
  }

  useEffect(() => {
    if (sections.length === 0) {
      setError("未找到任何有效经历")
      setIsGenerating(false)
      return
    }
    fetchResults()
  }, [sectionsIds, customJdContext, customDiagnosisContext])

  const toggleApply = (id: string, checked: boolean) => {
    const next = new Set(selectedIdsToApply)
    if (checked) {
      next.add(id)
    } else {
      next.delete(id)
    }
    setSelectedIdsToApply(next)
  }

  const handleApply = () => {
    const drafts: { id: string, newContent: string }[] = []
    selectedIdsToApply.forEach(id => {
      const res = results.find(r => r.id === id)
      if (res && res.initial_draft_content) {
        drafts.push({ id, newContent: res.initial_draft_content })
      }
    })
    onAccept(drafts)
  }

  const handleContentChange = (id: string, newContent: string) => {
    setResults(prev => prev.map(r => r.id === id ? { ...r, initial_draft_content: newContent } : r))
  }

  return (
    <div className="mt-2 w-full border border-blue-200 bg-blue-50/40 rounded-lg p-3 shadow-sm text-sm animate-in fade-in slide-in-from-top-2">
      <div className="flex items-center justify-between mb-3 border-b border-blue-200/60 pb-2">
        <h4 className="font-semibold flex items-center text-blue-700">
          <FileText className="mr-1.5 h-4 w-4" /> AI 初步改写 (Align the bones)
        </h4>
        <div className="flex items-center gap-2">
          {!isGenerating && !error && (
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs text-blue-500 hover:text-blue-700 hover:bg-blue-100/50" onClick={() => fetchResults(true)}>
              重新生成
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-6 w-6 text-blue-400 hover:text-blue-700 hover:bg-blue-100/50" onClick={onCancel}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {isGenerating ? (
        <div className="flex flex-col items-center justify-center py-8 text-blue-600/70">
          <Loader2 className="h-6 w-6 animate-spin mb-3" />
          <p className="text-xs font-medium">正在结合 JD 偏好调整结构与侧重点...</p>
        </div>
      ) : error ? (
        <div className="py-4 text-center">
          <p className="text-red-500 mb-2">出错了：{error}</p>
          <Button variant="outline" size="sm" onClick={() => { onResolveWithoutDraft?.(); onCancel() }}>关闭</Button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-blue-600/80 leading-relaxed mb-3">
            以下是 AI 根据 JD 偏好为您生成的<b>初版改写</b>。它仅重组了结构并突出了重点，未生硬植入任何术语。
            <br />如果您觉得部分内容需要微调，可以直接在右侧的输入框中编辑，确认无误后勾选采纳。
          </p>
          <div className="max-h-[450px] overflow-y-auto space-y-4 pr-1 custom-scrollbar">
            {sections.map(s => {
              const res = results.find(r => r.id === s.id)
              const willApply = selectedIdsToApply.has(s.id)
              const isAlreadyDrafted = !!s.isDrafted
              const hasResult = !!res?.initial_draft_content

              return (
                <div
                  key={s.id}
                  className={`flex flex-col gap-2 p-3 rounded-lg border transition-colors ${
                    isAlreadyDrafted
                      ? "bg-slate-50 border-slate-200 opacity-60"
                      : willApply
                        ? "bg-blue-50/80 border-blue-300"
                        : "bg-white border-slate-200 hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    {isAlreadyDrafted ? (
                      <div className="w-4 h-4 rounded border border-transparent flex items-center justify-center">
                        <Check className="h-3 w-3 text-blue-500" />
                      </div>
                    ) : (
                      <Checkbox 
                        checked={willApply} 
                        onCheckedChange={(c) => toggleApply(s.id, !!c)} 
                        className={willApply ? "border-blue-500 data-[state=checked]:bg-blue-500" : ""}
                      />
                    )}
                    <span className={`font-semibold text-[13px] truncate ${willApply ? "text-blue-800" : "text-slate-800"}`}>
                      {s.title || "未命名经历"}
                    </span>
                    {isAlreadyDrafted && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 bg-blue-100 text-blue-600 border border-blue-200 ml-auto">
                        已采纳初改
                      </span>
                    )}
                  </div>
                  {isAlreadyDrafted ? (
                    <div className="mt-2 text-[11px] text-slate-500 italic pl-6">
                      该经历已完成初改采纳，您可以继续下一步流程。
                    </div>
                  ) : !hasResult ? (
                    <div className="mt-2 text-[11px] text-amber-600 italic pl-6">
                      ⚠️ AI 未能为该经历生成改写（内容可能为空）。您可以点击「重新生成」重试，或直接跳过此段。
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-3 pl-6">
                      {/* 左侧原文 */}
                      <div className="flex flex-col gap-1.5">
                        <span className="text-[10px] font-bold text-slate-400 uppercase">Original 原文</span>
                        <div className="p-2.5 bg-slate-50/80 rounded border border-slate-200 text-[11.5px] text-slate-500 whitespace-pre-wrap opacity-80 h-full leading-relaxed">
                          {s.content}
                        </div>
                      </div>

                      {/* 右侧编辑框 */}
                      <div className="flex flex-col gap-1.5">
                        <span className="text-[10px] font-bold text-blue-500 uppercase flex items-center gap-1">
                          <ArrowRight className="h-3 w-3" /> Initial Draft 初稿
                        </span>
                        <textarea
                          className="w-full h-full min-h-[120px] p-2.5 bg-white rounded border border-blue-300 text-[11.5px] text-blue-900 whitespace-pre-wrap font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/50 resize-none custom-scrollbar leading-relaxed"
                          value={res.initial_draft_content}
                          onChange={(e) => handleContentChange(s.id, e.target.value)}
                        />
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          <div className="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-blue-200/60">
            <Button variant="ghost" size="sm" className="h-8 text-xs text-blue-600 hover:bg-blue-100" onClick={onCancel}>
              跳过此步
            </Button>
            <Button 
              size="sm" 
              className="h-8 text-xs bg-blue-600 hover:bg-blue-700 text-white gap-1.5 shadow-sm px-4"
              onClick={handleApply}
              disabled={selectedIdsToApply.size === 0 && sections.some(s => !s.isDrafted)}
            >
              <Check className="h-4 w-4" />
              {sections.every(s => s.isDrafted) ? "已全部采纳，关闭面板" : `采纳并替换选中内容 (${selectedIdsToApply.size})`}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
