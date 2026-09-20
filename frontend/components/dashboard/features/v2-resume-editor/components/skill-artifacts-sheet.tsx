"use client"

import React, { useState, useEffect } from "react"
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { API_BASE } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { 
  FileText, 
  Sparkles, 
  Copy, 
  Check, 
  Download, 
  Loader2, 
  Layers, 
  ShieldAlert, 
  FileCode2, 
  FolderArchive,
  RefreshCw,
  ArrowRight,
  Trash2,
  Eye,
  Code2
} from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"


export interface ArtifactItem {
  skill_id: string
  name: string
  size: number
  is_resume_candidate: boolean
  executed_at?: string
  preview?: string
  path?: string
}

export interface SkillArtifactsSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  jobId?: string
  jobTitle?: string
  onFillSuccess?: (parsedJson: any) => void
}

export function SkillArtifactsSheet({
  open,
  onOpenChange,
  jobId,
  jobTitle,
  onFillSuccess,
}: SkillArtifactsSheetProps) {
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([])
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactItem | null>(null)
  const [content, setContent] = useState<string>("")
  const [isLoadingList, setIsLoadingList] = useState(false)
  const [isLoadingContent, setIsLoadingContent] = useState(false)
  const [isFilling, setIsFilling] = useState(false)
  const [copied, setCopied] = useState(false)
  const [viewMode, setViewMode] = useState<"rendered" | "raw">("rendered")

  // 1. 打开时拉取产物清单
  const fetchArtifacts = async () => {
    if (!jobId) return
    setIsLoadingList(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/skill_artifacts/${jobId}`)
      const json = await res.json()
      if (res.ok && json.status === "success") {
        const list: ArtifactItem[] = json.data || []
        setArtifacts(list)
        if (list.length > 0) {
          // 优先保留当前选中的，否则选中推荐的简历主稿，或者第一个产物
          setSelectedArtifact((prev) => {
            if (prev && list.some((a) => a.name === prev.name && a.skill_id === prev.skill_id)) {
              return prev
            }
            return list.find((a) => a.is_resume_candidate) || list[0]
          })
        } else {
          setSelectedArtifact(null)
          setContent("")
        }
      } else {
        setArtifacts([])
        setSelectedArtifact(null)
      }
    } catch (e) {
      console.error("Failed to load skill artifacts:", e)
      setArtifacts([])
    } finally {
      setIsLoadingList(false)
    }
  }

  useEffect(() => {
    if (open && jobId) {
      fetchArtifacts()
    }
  }, [open, jobId])

  // 2. 选中文件后拉取 Markdown 内容
  useEffect(() => {
    if (!open || !jobId || !selectedArtifact) {
      setContent("")
      return
    }
    const fetchContent = async () => {
      setIsLoadingContent(true)
      try {
        const res = await fetch(
          `${API_BASE}/api/strategy/skill_artifacts/${jobId}/${selectedArtifact.skill_id}/${selectedArtifact.name}`
        )
        const json = await res.json()
        if (res.ok && json.status === "success") {
          setContent(json.data?.content || "")
        } else {
          setContent("⚠️ 无法加载该产物文件的内容，请稍后重试。")
        }
      } catch (e) {
        console.error("Failed to load artifact content:", e)
        setContent("❌ 加载产物内容异常。")
      } finally {
        setIsLoadingContent(false)
      }
    }
    fetchContent()
  }, [open, jobId, selectedArtifact])

  // 3. 一键复制 Markdown
  const handleCopy = () => {
    if (!content) return
    navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // 4. 单文件下载
  const handleDownload = () => {
    if (!content || !selectedArtifact) return
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = selectedArtifact.name
    a.click()
    URL.revokeObjectURL(url)
  }

  // 5. 删除单个产物文件
  const handleDeleteSingleArtifact = async () => {
    if (!selectedArtifact || !jobId) return
    if (!confirm(`确定要删除产物文件「${selectedArtifact.name}」吗？此操作不可恢复。`)) return
    try {
      const res = await fetch(
        `${API_BASE}/api/strategy/skill_artifacts/${jobId}/${selectedArtifact.skill_id}/${selectedArtifact.name}`,
        { method: "DELETE" }
      )
      if (res.ok) {
        setSelectedArtifact(null)
        setContent("")
        fetchArtifacts()
      } else {
        alert("删除失败，请稍后重试。")
      }
    } catch (e: any) {
      alert("删除异常: " + e.message)
    }
  }

  // 6. 清空当前技能的所有产物
  const handleClearSkillArtifacts = async () => {
    if (!selectedArtifact || !jobId) return
    if (!confirm(`确定要清空技能「${selectedArtifact.skill_id}」下的全部本地产物吗？`)) return
    try {
      const res = await fetch(
        `${API_BASE}/api/strategy/skill_artifacts/${jobId}/${selectedArtifact.skill_id}`,
        { method: "DELETE" }
      )
      if (res.ok) {
        setSelectedArtifact(null)
        setContent("")
        fetchArtifacts()
      } else {
        alert("清空失败，请稍后重试。")
      }
    } catch (e: any) {
      alert("清空异常: " + e.message)
    }
  }

  // 7. 核心动作：一键回填到标准简历画布
  const handleFillToResumeCanvas = async () => {
    if (!content.trim()) return
    setIsFilling(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/fill_resume_from_markdown`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          markdown_content: content,
          job_id: jobId || "",
        }),
      })
      const json = await res.json()
      if (!res.ok || json.status !== "success" || !json.data?.parsed_json) {
        throw new Error(json.detail || "智能回填解析失败")
      }

      const parsedData = json.data.parsed_json

      // 注入 Zustand Store
      useResumeV2Store.getState().setResumeData(parsedData)

      // 回调给父级组件同步到 job 状态
      onFillSuccess?.(parsedData)

      alert(
        `✅ 成功将「${selectedArtifact?.name}」智能结构化回填至简历画布！\n已根据 Markdown 动态自适应模块名称与排序，可立即进行微调、导出高清 PDF 或保存到飞书。`
      )
      onOpenChange(false)
    } catch (err: any) {
      console.error(err)
      alert("❌ 回填失败: " + err.message)
    } finally {
      setIsFilling(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!max-w-[1320px] w-[95vw] h-[88vh] flex flex-col p-0 gap-0 overflow-hidden rounded-2xl border-slate-200/90 shadow-2xl bg-white focus:outline-none sm:!max-w-[1320px]">
        {/* 顶部 Header：采用极简高质感水平排版 */}
        <div className="px-6 py-3.5 border-b border-slate-100 bg-slate-50/70 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3.5">
            <div className="size-9 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-600 shadow-2xs">
              <FolderArchive className="size-5" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <DialogTitle className="text-base font-bold text-slate-800 tracking-tight">
                  Skill 作战产物归档 (Artifacts Studio)
                </DialogTitle>
                {jobTitle && (
                  <Badge variant="outline" className="text-xs font-normal text-slate-600 bg-white border-slate-200">
                    {jobTitle}
                  </Badge>
                )}
              </div>
              <DialogDescription className="text-xs text-slate-500 mt-0.5 flex items-center gap-2">
                <span>浏览并管理该技能生成的全套 Markdown 深度研报、面试卡片与定制简历底稿</span>
                <span className="text-amber-600/80 font-medium">（💡 随时可在顶部工具栏点击「📂 作战产物库」重新打开）</span>
              </DialogDescription>
            </div>
          </div>

          <div className="flex items-center gap-2 pr-8">
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs text-slate-600 hover:text-slate-900 bg-white border-slate-200 shadow-2xs"
              onClick={fetchArtifacts}
              disabled={isLoadingList}
            >
              <RefreshCw className={`size-3.5 mr-1.5 ${isLoadingList ? "animate-spin text-amber-600" : ""}`} />
              刷新产物
            </Button>
          </div>
        </div>

        {/* 核心主体：宽屏左右分栏 */}
        <div className="flex-1 flex overflow-hidden min-h-0">
          {/* 左侧：产物文件树列表 (宽 320px) */}
          <div className="w-80 shrink-0 border-r border-slate-100 bg-slate-50/40 flex flex-col min-h-0">
            <div className="p-3 px-4 border-b border-slate-100 flex items-center justify-between text-xs text-slate-500 font-medium bg-slate-50/60 shrink-0">
              <span className="flex items-center gap-1.5 font-semibold text-slate-700">
                <Layers className="size-3.5 text-slate-500" />
                产物文件清单 ({artifacts.length})
              </span>
              {artifacts.length > 0 && selectedArtifact && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 text-[11px] text-rose-500 hover:text-rose-700 hover:bg-rose-50 p-1 px-1.5"
                  onClick={handleClearSkillArtifacts}
                  title="清空当前技能的所有产物"
                >
                  <Trash2 className="size-3 mr-1" />
                  清空此技能
                </Button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-2 space-y-1.5 min-h-0">
              {isLoadingList ? (
                <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-2">
                  <Loader2 className="size-5 animate-spin text-amber-500" />
                  <span className="text-xs">扫描本地归档产物...</span>
                </div>
              ) : artifacts.length === 0 ? (
                <div className="text-center py-16 px-4 text-slate-400">
                  <FileCode2 className="size-10 mx-auto mb-2.5 text-slate-300 opacity-60" />
                  <p className="text-xs font-semibold text-slate-600">暂无本地产物归档</p>
                  <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">
                    在顶部工具栏点击「✨ 执行当前 Skill 改写」，AI 生成的多阶段作战资料将自动在此归档
                  </p>
                </div>
              ) : (
                artifacts.map((file) => {
                  const isSelected = selectedArtifact?.name === file.name && selectedArtifact?.skill_id === file.skill_id
                  return (
                    <button
                      key={`${file.skill_id}-${file.name}`}
                      onClick={() => setSelectedArtifact(file)}
                      className={`w-full text-left p-2.5 px-3 rounded-xl transition-all flex flex-col gap-1 border ${
                        isSelected
                          ? "bg-white border-amber-400/90 shadow-xs ring-1 ring-amber-200"
                          : "bg-transparent border-transparent hover:bg-slate-100/80 text-slate-600"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1.5 w-full">
                        <span className="font-medium text-xs truncate flex items-center gap-1.5 text-slate-800">
                          <FileText className={`size-3.5 shrink-0 ${file.is_resume_candidate ? "text-amber-500" : "text-slate-400"}`} />
                          <span className="truncate">{file.name}</span>
                        </span>
                        {file.is_resume_candidate ? (
                          <Badge className="bg-amber-50 text-amber-700 border-amber-200 text-[10px] h-4 px-1 shrink-0 font-medium">
                            ⭐ 简历主稿
                          </Badge>
                        ) : (
                          <Badge variant="secondary" className="bg-slate-100 text-slate-500 text-[10px] h-4 px-1 shrink-0 font-normal">
                            📑 备战资料
                          </Badge>
                        )}
                      </div>
                      <div className="flex items-center justify-between text-[10px] text-slate-400 mt-0.5">
                        <span>{(file.size / 1024).toFixed(1)} KB</span>
                        <span className="truncate max-w-[130px] font-mono text-[10px] text-slate-400">{file.skill_id}</span>
                      </div>
                    </button>
                  )
                })
              )}
            </div>
          </div>

          {/* 右侧：Markdown 渲染与防错操作区 (自适应宽屏 + 丝滑纵向滚动) */}
          <div className="flex-1 flex flex-col bg-white overflow-hidden min-h-0">
            {selectedArtifact ? (
              <>
                {/* 文件头部与操作栏 */}
                <div className="p-3.5 px-6 border-b border-slate-100 flex items-center justify-between bg-white shrink-0">
                  <div className="flex items-center gap-2.5">
                    <span className="text-sm font-bold text-slate-800">{selectedArtifact.name}</span>
                    {selectedArtifact.is_resume_candidate ? (
                      <Badge className="bg-emerald-50 text-emerald-700 border-emerald-200 text-xs font-normal">
                        可一键回填至简历画布
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-xs text-slate-500 font-normal bg-slate-50">
                        求职备战参考 / 深度研报
                      </Badge>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    {/* 视图切换：排版阅读 / 源码 */}
                    <div className="flex items-center bg-slate-100/80 p-0.5 rounded-lg border border-slate-200/60 mr-1">
                      <button
                        onClick={() => setViewMode("rendered")}
                        className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded-md transition-all ${
                          viewMode === "rendered"
                            ? "bg-white text-slate-800 font-medium shadow-2xs"
                            : "text-slate-500 hover:text-slate-700"
                        }`}
                      >
                        <Eye className="size-3" />
                        排版阅读
                      </button>
                      <button
                        onClick={() => setViewMode("raw")}
                        className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded-md transition-all ${
                          viewMode === "raw"
                            ? "bg-white text-slate-800 font-medium shadow-2xs"
                            : "text-slate-500 hover:text-slate-700"
                        }`}
                      >
                        <Code2 className="size-3" />
                        源码
                      </button>
                    </div>

                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 text-xs text-slate-600 hover:text-slate-800 bg-white shadow-2xs"
                      onClick={handleCopy}
                    >
                      {copied ? <Check className="size-3.5 mr-1.5 text-emerald-600" /> : <Copy className="size-3.5 mr-1.5" />}
                      {copied ? "已复制" : "复制全文"}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 text-xs text-slate-600 hover:text-slate-800 bg-white shadow-2xs"
                      onClick={handleDownload}
                    >
                      <Download className="size-3.5 mr-1.5" />
                      下载 .md
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 text-xs text-rose-500 hover:text-rose-700 hover:bg-rose-50"
                      onClick={handleDeleteSingleArtifact}
                      title="删除当前文件"
                    >
                      <Trash2 className="size-3.5 mr-1" />
                      删除
                    </Button>

                    {/* ✨ 核心回填按钮：自适应提取并灌入标准简历画布 */}
                    <Button
                      size="sm"
                      className={`h-8 text-xs font-medium transition-all shadow-sm ${
                        selectedArtifact.is_resume_candidate
                          ? "bg-amber-600 hover:bg-amber-700 text-white"
                          : "bg-indigo-600 hover:bg-indigo-700 text-white"
                      }`}
                      onClick={handleFillToResumeCanvas}
                      disabled={isFilling || isLoadingContent || !content.trim()}
                    >
                      {isFilling ? (
                        <Loader2 className="size-3.5 animate-spin mr-1.5" />
                      ) : (
                        <Sparkles className="size-3.5 mr-1.5" />
                      )}
                      一键回填到简历画布
                      <ArrowRight className="size-3 ml-1" />
                    </Button>
                  </div>
                </div>

                {/* 防错提示条：对非简历产物进行清晰隔离提醒 */}
                {!selectedArtifact.is_resume_candidate && (
                  <div className="bg-amber-50/70 border-b border-amber-100/80 px-6 py-2 flex items-center gap-2 text-xs text-amber-800 shrink-0">
                    <ShieldAlert className="size-4 shrink-0 text-amber-600" />
                    <span>
                      当前文档为<b>求职备战/深度情报参考</b>（非标准简历）。如需导出高清 A4 简历或保存到飞书，请点击左侧「⭐ 简历主稿」回填至标准画布。
                    </span>
                  </div>
                )}

                {/* Markdown 渲染正文区 (彻底隐藏原始语法，支持顺畅滚动) */}
                <div className="flex-1 min-h-0 overflow-y-auto p-6 md:p-8 bg-slate-50/60">
                  {isLoadingContent ? (
                    <div className="flex flex-col items-center justify-center py-24 text-slate-400 gap-2">
                      <Loader2 className="size-6 animate-spin text-amber-500" />
                      <span className="text-xs">加载 Markdown 原文...</span>
                    </div>
                  ) : viewMode === "rendered" ? (
                    <div className="max-w-4xl mx-auto bg-white rounded-2xl p-8 md:p-10 shadow-xs border border-slate-200/80">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          h1: ({ children }) => (
                            <h1 className="text-xl font-bold text-slate-900 border-b border-slate-200 pb-2.5 mb-4 mt-2 tracking-tight">
                              {children}
                            </h1>
                          ),
                          h2: ({ children }) => (
                            <h2 className="text-base font-bold text-slate-800 border-b border-slate-100 pb-1.5 mb-3 mt-6 tracking-tight flex items-center gap-2">
                              <span className="inline-block w-1.5 h-4 bg-amber-500 rounded-full shrink-0" />
                              {children}
                            </h2>
                          ),
                          h3: ({ children }) => (
                            <h3 className="text-sm font-semibold text-slate-800 mb-2 mt-4">
                              {children}
                            </h3>
                          ),
                          p: ({ children }) => (
                            <p className="text-xs text-slate-700 leading-relaxed mb-3">
                              {children}
                            </p>
                          ),
                          ul: ({ children }) => (
                            <ul className="list-disc pl-5 text-xs text-slate-700 space-y-1 mb-3">
                              {children}
                            </ul>
                          ),
                          ol: ({ children }) => (
                            <ol className="list-decimal pl-5 text-xs text-slate-700 space-y-1 mb-3">
                              {children}
                            </ol>
                          ),
                          li: ({ children }) => (
                            <li className="text-xs text-slate-700 leading-relaxed">
                              {children}
                            </li>
                          ),
                          table: ({ children }) => (
                            <div className="overflow-x-auto my-4 rounded-xl border border-slate-200 shadow-2xs">
                              <table className="w-full text-xs text-left border-collapse bg-white">
                                {children}
                              </table>
                            </div>
                          ),
                          thead: ({ children }) => (
                            <thead className="bg-slate-50/90 text-slate-700 border-b border-slate-200 text-[11px] font-semibold">
                              {children}
                            </thead>
                          ),
                          th: ({ children }) => (
                            <th className="px-3 py-2 border-r border-slate-200/60 last:border-r-0 font-medium">
                              {children}
                            </th>
                          ),
                          td: ({ children }) => (
                            <td className="px-3 py-2 border-b border-r border-slate-100 last:border-r-0 text-slate-600 text-xs">
                              {children}
                            </td>
                          ),
                          blockquote: ({ children }) => (
                            <blockquote className="border-l-4 border-amber-400 bg-amber-50/50 px-3.5 py-2 my-3 rounded-r-lg text-xs text-amber-900 leading-relaxed italic">
                              {children}
                            </blockquote>
                          ),
                          pre: ({ children }) => (
                            <pre className="p-4 rounded-xl bg-slate-900 text-slate-100 font-mono text-xs overflow-x-auto my-3 leading-relaxed shadow-inner border border-slate-800">
                              {children}
                            </pre>
                          ),
                          code: ({ className, children, ...props }: any) => {
                            const isBlock = /language-/.test(className || "") || String(children).includes("\n")
                            return (
                              <code
                                className={
                                  isBlock
                                    ? "font-mono text-xs text-slate-100 leading-relaxed"
                                    : "px-1.5 py-0.5 rounded bg-slate-100 text-amber-700 font-mono text-[11px] border border-slate-200/60"
                                }
                                {...props}
                              >
                                {children}
                              </code>
                            )
                          },
                          hr: () => <hr className="my-6 border-slate-200" />
                        }}
                      >
                        {content}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <div className="max-w-4xl mx-auto">
                      <pre className="p-5 rounded-xl bg-slate-900 text-slate-100 font-mono text-xs overflow-x-auto whitespace-pre-wrap leading-relaxed shadow-inner border border-slate-800">
                        {content}
                      </pre>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-slate-400 p-8">
                <FileText className="size-12 text-slate-200 mb-3" />
                <p className="text-sm font-semibold text-slate-600">请选择左侧产物文件进行预览</p>
                <p className="text-xs text-slate-400 mt-1">支持实时渲染 Markdown，并可一键提取回填到简历画布</p>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

