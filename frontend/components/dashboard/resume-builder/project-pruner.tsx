import React, { useState, useEffect } from "react"
import { Check, X, Target, Scissors, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { API_BASE } from "@/lib/api"
import { createPanelResultCache } from "@/lib/resume-panel-cache"
import type { ResumeSection } from "@/types/resume"

interface ProjectPrunerProps {
  projects: ResumeSection[]
  archivedProjects?: ResumeSection[]
  customJdContext: string
  customDiagnosisContext: string
  jobId?: string
  onAccept: (idsToDelete: string[]) => void
  onCancel: () => void
}

interface FilterResult {
  id: string
  score: number
  decision: "keep" | "kill"
  reason: string
}


export function ProjectPruner({
  projects,
  archivedProjects = [],
  customJdContext,
  customDiagnosisContext,
  jobId,
  onAccept,
  onCancel,
}: ProjectPrunerProps) {
  const allProjects = React.useMemo(() => [...projects, ...archivedProjects], [projects, archivedProjects])
  const [isGenerating, setIsGenerating] = useState(true)
  const [results, setResults] = useState<FilterResult[]>([])
  const [error, setError] = useState<string | null>(null)

  // By default, we select the ones marked as "kill" to be deleted.
  const [selectedIdsToDelete, setSelectedIdsToDelete] = useState<Set<string>>(new Set())
  const [purgeConfirmOpen, setPurgeConfirmOpen] = useState(false)

  const panelCache = createPanelResultCache<FilterResult>({
    storageKey: "resume_pruner_cache",
    sessionScope: "session_pruner_last_results",
    jobId,
  })

  // Memoize dependency to prevent infinite loops caused by parent re-renders creating new arrays
  const projectsIds = allProjects.map(p => `${p.id}-${p.title}`).join('|')

  // 归属校验：缓存结果必须与当前条目列表一一对应，防止索引错位串内容
  const isResultSetValid = (res: FilterResult[]) =>
    allProjects.length > 0 &&
    res.length === allProjects.length &&
    res.every(r => allProjects.some(p => p.id === r.id))

  const fetchResults = async (force: boolean = false) => {
    setIsGenerating(true)
    setError(null)
    try {
      const cacheKey = panelCache.localKey(projectsIds, `${customJdContext.length}-${customDiagnosisContext.length}`)

      const localCache = panelCache.getLocalMap()
      if (!force && localCache.has(cacheKey)) {
        const cachedRes = localCache.get(cacheKey)!
        if (!isResultSetValid(cachedRes)) {
          localCache.delete(cacheKey)
          panelCache.saveLocalMap(localCache)
        } else {
          setResults(cachedRes)
          const toDelete = new Set<string>()
          cachedRes.forEach(item => {
            if (item.decision === "kill" && !archivedProjects?.some(a => a.id === item.id)) {
              toDelete.add(item.id)
            }
          })
          setSelectedIdsToDelete(toDelete)
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
          const toDelete = new Set<string>()
          sessionRes.forEach(item => {
            if (item.decision === "kill" && !archivedProjects?.some(a => a.id === item.id)) {
              toDelete.add(item.id)
            }
          })
          setSelectedIdsToDelete(toDelete)
          setIsGenerating(false)
          return
        }
      }

      const response = await fetch(`${API_BASE}/api/strategy/filter_projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jd_text: customJdContext,
          diagnosis_report: customDiagnosisContext,
          projects: allProjects.map(p => ({
            id: p.id,
            title: p.title,
            content: p.content
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

      const res: FilterResult[] = data.data || []
      localCache.set(cacheKey, res)
      panelCache.saveLocalMap(localCache)
      panelCache.saveSession(res)
      setResults(res)
      
      // Auto-select those with decision === "kill"
      const toDelete = new Set<string>()
      res.forEach(item => {
        if (item.decision === "kill" && !archivedProjects?.some(a => a.id === item.id)) {
          toDelete.add(item.id)
        }
      })
      setSelectedIdsToDelete(toDelete)
      setIsGenerating(false)
    } catch (err: any) {
      setError(err.message || "请求失败，请重试")
      setIsGenerating(false)
    }
  }

  useEffect(() => {
    if (allProjects.length === 0) {
      setError("未找到任何项目经历")
      setIsGenerating(false)
      return
    }
    fetchResults()
  }, [projectsIds, customJdContext, customDiagnosisContext])

  const toggleDelete = (id: string, checked: boolean) => {
    const next = new Set(selectedIdsToDelete)
    if (checked) {
      next.add(id)
    } else {
      next.delete(id)
    }
    setSelectedIdsToDelete(next)
  }

  // 全切护栏判据按活跃项目口径：归档项复选框禁用、永不进入 selectedIdsToDelete，
  // 若用 allProjects.length 作分母，存在归档项目时护栏将永远无法触发
  const isPurgeAll = projects.length > 0 && selectedIdsToDelete.size >= projects.length

  const handleApply = () => {
    if (isPurgeAll) {
      setPurgeConfirmOpen(true)
      return
    }
    onAccept(Array.from(selectedIdsToDelete))
  }

  const confirmPurge = () => {
    setPurgeConfirmOpen(false)
    onAccept(Array.from(selectedIdsToDelete))
  }

  return (
    <div className="mt-2 w-full border border-red-200 bg-red-50/40 rounded-lg p-3 shadow-sm text-sm">
      <div className="flex items-center justify-between mb-3 border-b border-red-200/60 pb-2">
        <h4 className="font-semibold flex items-center text-red-700">
          <Scissors className="mr-1.5 h-4 w-4" /> AI 项目经历智能删减
        </h4>
        <div className="flex items-center gap-2">
          {!isGenerating && !error && (
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs text-red-500 hover:text-red-700 hover:bg-red-100/50" onClick={() => fetchResults(true)}>
              重新生成
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-6 w-6 text-red-400 hover:text-red-700 hover:bg-red-100/50" onClick={onCancel}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {isGenerating ? (
        <div className="flex flex-col items-center justify-center py-6 text-red-600/70">
          <Loader2 className="h-6 w-6 animate-spin mb-2" />
          <p className="text-xs">正在根据 JD 和诊断报告严苛筛选项目...</p>
        </div>
      ) : error ? (
        <div className="py-4 text-center">
          <p className="text-red-500 mb-2">出错了：{error}</p>
          <Button variant="outline" size="sm" onClick={onCancel}>关闭</Button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-red-600/80 leading-relaxed mb-2">
            以下是 AI 基于当前岗位的“核心能力要求”为您打出的匹配得分。
            <br />打勾的项目表示 <b>将要被删除（切除）</b>，您可以人工调整复核。
          </p>
          <div className="max-h-[300px] overflow-y-auto space-y-2 pr-1 custom-scrollbar">
            {allProjects.map(p => {
              const res = results.find(r => r.id === p.id)
              const score = res?.score ?? 0
              const isKill = res?.decision === "kill"
              const reason = res?.reason || "暂无理由"
              const isAlreadyArchived = archivedProjects?.some(a => a.id === p.id)
              const willDelete = selectedIdsToDelete.has(p.id)
              const displayChecked = willDelete || isAlreadyArchived

              return (
                <div 
                  key={p.id} 
                  className={`flex gap-3 items-start p-2.5 rounded-md border transition-colors ${
                    isAlreadyArchived
                      ? "bg-slate-100 border-slate-200 opacity-60 grayscale"
                      : willDelete 
                        ? "bg-red-100/60 border-red-300" 
                        : "bg-white border-slate-200 hover:border-slate-300"
                  }`}
                >
                  <div className="mt-0.5">
                    <Checkbox 
                      checked={displayChecked} 
                      disabled={isAlreadyArchived}
                      onCheckedChange={(c) => toggleDelete(p.id, !!c)} 
                      className={displayChecked && !isAlreadyArchived ? "border-red-500 data-[state=checked]:bg-red-500" : ""}
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`font-semibold text-[13px] truncate ${displayChecked ? "text-red-800 line-through opacity-70" : "text-slate-800"}`}>
                        {p.title || "未命名项目"}
                      </span>
                      {res && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${
                          score >= 80 ? "bg-green-100 text-green-700" :
                          score >= 60 ? "bg-yellow-100 text-yellow-700" :
                          "bg-red-100 text-red-700"
                        }`}>
                          {score} 分
                        </span>
                      )}
                      {isKill && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 bg-red-600 text-white">
                          建议切除
                        </span>
                      )}
                      {!isKill && res && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 bg-green-600 text-white">
                          建议保留
                        </span>
                      )}
                    </div>
                    <div className={`text-[11px] leading-relaxed ${willDelete ? "text-red-700/80" : "text-slate-500"}`}>
                      <b>理由：</b>{reason}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          <div className="flex items-center justify-end gap-2 mt-4 pt-2 border-t border-red-200/60">
            <Button variant="ghost" size="sm" className="h-7 text-xs text-red-600 hover:bg-red-100" onClick={onCancel}>
              取消
            </Button>
            <Button
              size="sm"
              className="h-7 text-xs bg-red-600 hover:bg-red-700 text-white gap-1 shadow-sm"
              onClick={handleApply}
            >
              <Check className="h-3.5 w-3.5" />
              {selectedIdsToDelete.size === 0 ? "跳过删减 (完美保留)" : `一键确认切除 (${selectedIdsToDelete.size})`}
            </Button>
          </div>
        </div>
      )}

      <AlertDialog open={purgeConfirmOpen} onOpenChange={setPurgeConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认清空整个项目经历板块？</AlertDialogTitle>
            <AlertDialogDescription>
              你勾选了全部 {projects.length} 段项目经历，确认后它们将全部进入回收站，「项目经历」板块变为空，
              后续初改、深挖与 ATS 对齐将跳过该板块。若想保留至少一段，请取消并调整勾选。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={confirmPurge}>仍要清空</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
