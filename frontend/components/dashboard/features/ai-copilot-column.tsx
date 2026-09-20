import React, { useState, useEffect, useMemo } from "react"
import type { JobData } from "@/types/job"
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip"
import { Sparkles, Save, Copy, Brain, Loader2, Zap, Hand, RefreshCw, Check } from "lucide-react"
import { parseAiRewriteAnnotations } from "@/lib/utils/resume-parser"
import { toast } from "@/hooks/use-toast"
import { mapApiItemToJob } from "@/lib/job-mapper"
import { AiGradeDashboard } from "./ai-grade-dashboard"
import { EvaluationDimensionsCard } from "./evaluation-dimensions-card"
import { ResumeAuditCard } from "./resume-audit-card"
import { API_BASE } from "@/lib/api"

export function AICopilotColumn({
  job,
  onUpdateJob,
  selectedText,
  onPolish,
  qaReport,
}: {
  job: JobData
  onUpdateJob: (job: JobData) => void
  selectedText: string
  onPolish: (instruction: string) => Promise<void>
  qaReport?: any
}) {
  const [instruction, setInstruction] = useState("")
  const [isPolishing, setIsPolishing] = useState(false)
  const [myReview, setMyReview] = useState(job?.myReview || "")
  const [isSavingReview, setIsSavingReview] = useState(false)
  const [greetingMsg, setGreetingMsg] = useState(job?.greetingMsg || "")
  const [isSavingGreeting, setIsSavingGreeting] = useState(false)
  const [isEvaluating, setIsEvaluating] = useState(false)
  const [isDeepEvaluating, setIsDeepEvaluating] = useState(false)
  const skillsText = useMemo(() => job?.skillReq || "暂无数据", [job?.skillReq])
  const rewriteAnnotations = useMemo(
    () => parseAiRewriteAnnotations(job?.aiRewriteJson || ""),
    [job?.aiRewriteJson],
  )

  // 🌟 从混合了 Markdown 和 JSON 的文本中强行提取改写说明和缺失数据
  const rewriteLogicData = useMemo(() => {
    if (!job?.aiRewriteJson) return { rationaleItems: [] as { label: string; rationale: string }[], missingItems: [] as { question: string }[], hasAny: false }

    const rationaleItems: { label: string; rationale: string }[] = []
    let missingItems: { question: string }[] = []

    try {
      const rawText = job.aiRewriteJson;
      // 🚀 核心：用正则直接匹配字符串中 { "rewrite_rationale" ... } 这一段 JSON，无视前面的简历正文
      const jsonMatch = rawText.match(/\{[\s\S]*"rewrite_rationale"[\s\S]*\}/);

      let parsedData = null;
      if (jsonMatch) {
        parsedData = JSON.parse(jsonMatch[0]); // 只解析提取出来的 JSON 块
      } else {
        // 仅当文本整体看起来像 JSON（以 { 或 [ 开头）时才尝试解析兜底
        // Markdown 混合文本（含 # 标题）不是 JSON，静默跳过，避免 console.warn 噪声
        const trimmed = rawText.trim();
        const jsonMatch = trimmed.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
        if (jsonMatch) {
          try {
            parsedData = JSON.parse(jsonMatch[0]);
          } catch (e) {
            console.warn("⚠️ AI 返回的 JSON 格式仍有损坏，解析失败:", e);
          }
        }
      }

      if (parsedData && typeof parsedData === 'object') {
        // 1. 提取改写理由
        if (parsedData.rewrite_rationale && typeof parsedData.rewrite_rationale === 'object') {
          Object.entries(parsedData.rewrite_rationale).forEach(([key, val]) => {
            rationaleItems.push({ label: key, rationale: String(val) });
          });
        }

        // 2. 提取数据补充
        if (Array.isArray(parsedData.missing_data_requests)) {
          missingItems = parsedData.missing_data_requests.map((r: any) => ({
            question: typeof r === 'string' ? r : (r?.question || String(r))
          }));
        }
      }
    } catch (e) {
      console.warn("⚠️ 从混合文本中提取 AI改写JSON 失败:", e);
    }

    return { rationaleItems, missingItems, hasAny: rationaleItems.length > 0 || missingItems.length > 0 };
  }, [job?.aiRewriteJson]);

  // 同步 job.myReview 到本地状态
  useEffect(() => {
    setMyReview(job?.myReview || "")
    setGreetingMsg(job?.greetingMsg || "")
  }, [job?.id, job?.myReview, job?.greetingMsg])

  const [isCopiedGreeting, setIsCopiedGreeting] = useState(false)

  const handlePolish = async () => {
    if (!selectedText || !instruction.trim()) return
    setIsPolishing(true)
    try {
      await onPolish(instruction.trim())
    } finally {
      setIsPolishing(false)
    }
  }

  const handleSaveReview = async () => {
    if (!job?.id) {
      toast({
        variant: "destructive",
        title: "保存失败",
        description: "无法获取当前岗位 ID",
      })
      return
    }

    setIsSavingReview(true)
    try {
      const response = await fetch(`${API_BASE}/api/update_review_comments`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.id,
          comments: myReview
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        toast({
          variant: "destructive",
          title: "❌ 保存失败",
          description: data.detail || data.msg || "未知错误",
        })
        return
      }

      if (data.status === "success") {
        // 更新全局状态
        if (onUpdateJob && job) {
          onUpdateJob({
            ...job,
            myReview: myReview
          })
        }
        toast({
          title: "✅ 复核意见已保存",
          description: "已成功同步至飞书多维表格「复核意见」字段。",
        })
      } else {
        toast({
          variant: "destructive",
          title: "❌ 保存失败",
          description: data.message || "未知错误",
        })
      }
    } catch (error) {
      toast({
        variant: "destructive",
        title: "❌ 网络错误",
        description: "请求失败，请检查后端服务是否正常运行",
      })
      console.error("保存复核意见错误:", error)
    } finally {
      setIsSavingReview(false)
    }
  }

  const handleSaveGreeting = async () => {
    if (!job?.id) {
      toast({
        variant: "destructive",
        title: "保存失败",
        description: "无法获取当前岗位 ID",
      })
      return
    }

    setIsSavingGreeting(true)
    try {
      const response = await fetch(`${API_BASE}/api/update_greeting`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.id,
          greeting: greetingMsg
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        toast({
          variant: "destructive",
          title: "❌ 保存失败",
          description: data.detail || data.msg || "未知错误，请检查网络或后端服务",
        })
        return
      }

      if (data.status === "success") {
        if (onUpdateJob && job) {
          onUpdateJob({
            ...job,
            greetingMsg: greetingMsg
          })
        }
        toast({
          title: "🎉 打招呼语已保存",
          description: "已成功同步并归档至飞书多维表格「打招呼语」字段。",
        })
      } else {
        toast({
          variant: "destructive",
          title: "❌ 保存失败",
          description: data.message || "未知错误",
        })
      }
    } catch (error) {
      toast({
        variant: "destructive",
        title: "❌ 网络错误",
        description: "请求失败，请检查后端服务是否正常运行",
      })
      console.error("保存打招呼语错误:", error)
    } finally {
      setIsSavingGreeting(false)
    }
  }

  const handleCopyGreeting = async () => {
    if (!greetingMsg?.trim()) {
      toast({
        title: "打招呼语为空",
        description: "当前没有可复制的打招呼语内容。",
      })
      return
    }
    try {
      await navigator.clipboard.writeText(greetingMsg)
      setIsCopiedGreeting(true)
      toast({
        title: "📋 已复制到剪贴板",
        description: "打招呼语已成功复制，可直接粘贴发送给 HR。",
      })
      setTimeout(() => setIsCopiedGreeting(false), 2000)
    } catch (err) {
      toast({
        variant: "destructive",
        title: "复制失败",
        description: "剪贴板权限受限，请手动选中文本复制。",
      })
    }
  }

  const handleTriggerEvaluation = async () => {
    try {
      setIsEvaluating(true)
      const response = await fetch(`${API_BASE}/api/tasks/batch-process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_type: "evaluate",
          job_ids: [job.id],
        }),
      })

      if (!response.ok) {
        throw new Error("Failed to start evaluation")
      }

      toast({
        title: "🚀 已推送至初步评估队列",
        description: "后台正在进行多维度分析，请稍后刷新查看。",
      })
    } catch (error) {
      toast({
        variant: "destructive",
        title: "❌ 触发评估失败",
        description: "网络错误，请检查后端连接状态",
      })
      console.error("Trigger evaluation error:", error)
    } finally {
      setIsEvaluating(false)
    }
  }

  const handleTriggerDeepEvaluation = async () => {
    try {
      setIsDeepEvaluating(true)
      const response = await fetch(`${API_BASE}/api/tasks/batch-process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_type: "deep_evaluate",
          job_ids: [job.id],
        }),
      })

      if (!response.ok) {
        throw new Error("Failed to start deep evaluation")
      }

      toast({
        title: "⚡ 已推送至深度评估队列",
        description: "后台正在进行深度画像与风险诊断，请稍后刷新查看。",
      })
    } catch (error) {
      toast({
        variant: "destructive",
        title: "❌ 触发深度评估失败",
        description: "网络错误，请检查后端连接状态",
      })
      console.error("Trigger deep evaluation error:", error)
    } finally {
      setIsDeepEvaluating(false)
    }
  }

  const [isGeneratingGreeting, setIsGeneratingGreeting] = useState(false)
  const handleGenerateGreeting = async () => {
    setIsGeneratingGreeting(true)
    try {
      const response = await fetch(`${API_BASE}/api/strategy/generate_greeting_and_save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.id,
          jd_text: job.jobDescription || "",
          job_name: job.jobTitle || "",
          resume_text: "", // 留空将由后端自动从飞书拉取已启用的母本简历
        }),
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        let errMsg = `生成失败 (HTTP ${response.status})`
        if (typeof errData.detail === "string") {
          errMsg = errData.detail
        } else if (Array.isArray(errData.detail)) {
          errMsg = errData.detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ")
        } else if (errData.detail) {
          errMsg = JSON.stringify(errData.detail)
        }
        throw new Error(errMsg)
      }

      const resData = await response.json()
      if (resData.data?.greeting) {
        setGreetingMsg(resData.data.greeting)
        onUpdateJob({ ...job, greetingMsg: resData.data.greeting })
        toast({
          title: "✨ 打招呼语已生成并保存",
          description: "已结合母本简历与当前 JD 亮点量身定制，并同步更新至飞书。",
        })
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "请求失败，请稍后重试"
      toast({
        variant: "destructive",
        title: "❌ 生成打招呼语失败",
        description: message,
      })
      console.error("Generate greeting error:", error)
    } finally {
      setIsGeneratingGreeting(false)
    }
  }

  const [isRefreshing, setIsRefreshing] = useState(false)
  const handleRefresh = async () => {
    if (!job.id || isRefreshing) return
    setIsRefreshing(true)
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${job.id}`)
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }
      const data = await res.json()
      if (data.code === 0 && data.data) {
        const mapped = mapApiItemToJob(data.data, 0)
        onUpdateJob({
          ...job,
          ...mapped,
          jobTitle: (mapped.jobTitle && mapped.jobTitle !== "未知职位") ? mapped.jobTitle : job.jobTitle,
          jobDescription: mapped.jobDescription || job.jobDescription,
          companyName: (mapped.companyName && mapped.companyName !== "未知公司") ? mapped.companyName : job.companyName,
          id: job.id,
        })
        setGreetingMsg(mapped.greetingMsg ?? "")
        setMyReview(mapped.myReview ?? "")
        toast({
          title: "🔄 面板数据已刷新",
          description: "已同步最新诊断指标与状态数据。",
        })
      } else {
        throw new Error(data.message || "刷新数据失败")
      }
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "请检查网络或后端服务状态"
      console.error("Refresh failed:", e)
      toast({
        variant: "destructive",
        title: "❌ 刷新面板失败",
        description: message,
      })
    } finally {
      setIsRefreshing(false)
    }
  }

  return (
    <div className="h-full bg-card flex flex-col relative">
      <div className="px-3 py-2 border-b border-border shrink-0 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-xs text-foreground flex items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5" />
            AI Copilot
          </h3>
          
          <div className="flex items-center gap-0.5">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-violet-500 hover:bg-violet-100/50 hover:text-violet-700 disabled:opacity-50"
                  onClick={handleTriggerEvaluation}
                  disabled={isEvaluating || !job.id}
                >
                  {isEvaluating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-[10px] px-2 py-1">
                AI初步评估
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-indigo-500 hover:bg-indigo-100/50 hover:text-indigo-700 disabled:opacity-50"
                  onClick={handleTriggerDeepEvaluation}
                  disabled={isDeepEvaluating || !job.id}
                >
                  {isDeepEvaluating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-[10px] px-2 py-1">
                AI深度评估
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-violet-500 hover:bg-violet-100/50 hover:text-violet-700 disabled:opacity-50"
                  onClick={handleGenerateGreeting}
                  disabled={isGeneratingGreeting}
                >
                  {isGeneratingGreeting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Hand className="h-3.5 w-3.5" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-[10px] px-2 py-1">
                写打招呼语
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50"
                  onClick={handleRefresh}
                  disabled={!job.id || isRefreshing}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin text-primary" : ""}`} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-[10px] px-2 py-1">
                刷新面板
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        <Accordion
          type="multiple"
          defaultValue={["ai_diagnosis", "rewrite_notes", "ai_rewrite_logic", "qa_report", "greeting", "my_review"]}
          className="w-full"
        >
          <AccordionItem value="ai_diagnosis" className="relative group">
            <AccordionTrigger className="text-xs py-2 hover:no-underline bg-violet-50 dark:bg-violet-950/20 px-2 rounded pr-10">
              🔬 AI 专家诊断
            </AccordionTrigger>

            <AccordionContent className="px-2 pt-2 space-y-3">
              <AiGradeDashboard job={job} />
              <div className="space-y-1">
                <h4 className="text-[10px] font-semibold text-violet-700 uppercase tracking-wide">各维度评分依据</h4>
                <EvaluationDimensionsCard detailText={job.aiEvaluationDetail} />
              </div>

              {job.atsAbilityAnalysis && (
                <div className="border border-teal-200 bg-teal-50/30 rounded-md p-2.5">
                  <h4 className="text-[10px] font-semibold text-teal-700 mb-2 uppercase tracking-wide">📚 01·JD分析</h4>
                  <div className="space-y-2 text-[11px] text-muted-foreground leading-relaxed max-h-[400px] overflow-y-auto">
                    {(() => {
                      const text = job.atsAbilityAnalysis
                      // 按编号分段
                      const segments = text.split(/\n(?=\d+\))/).filter(Boolean)
                      return segments.map((seg, i) => {
                        const trimmed = seg.trim()
                        // Must-Have 段
                        if (trimmed.includes('Must-Have') || trimmed.includes('硬性要求')) {
                          const keywords = trimmed.replace(/^.*?[：:]/, '').split(/[,，、]/).map(s => s.trim()).filter(Boolean)
                          return (
                            <div key={i}>
                              <p className="text-[10px] font-semibold text-red-600 mb-1">Must-Have 硬性要求</p>
                              <div className="flex flex-wrap gap-1">
                                {keywords.map((kw, ki) => (
                                  <span key={ki} className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-[9px] font-medium">{kw}</span>
                                ))}
                              </div>
                            </div>
                          )
                        }
                        // Nice-to-Have 段
                        if (trimmed.includes('Nice-to-Have') || trimmed.includes('加分项')) {
                          const keywords = trimmed.replace(/^.*?[：:]/, '').split(/[,，、]/).map(s => s.trim()).filter(Boolean)
                          return (
                            <div key={i}>
                              <p className="text-[10px] font-semibold text-blue-600 mb-1">Nice-to-Have 加分项</p>
                              <div className="flex flex-wrap gap-1">
                                {keywords.map((kw, ki) => (
                                  <span key={ki} className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-[9px] font-medium">{kw}</span>
                                ))}
                              </div>
                            </div>
                          )
                        }
                        // 缺失项硬约束
                        if (trimmed.includes('缺失项硬约束') || trimmed.includes('严禁')) {
                          return (
                            <div key={i} className="bg-red-50 border border-red-200 rounded-md p-2">
                              <p className="text-[10px] font-semibold text-red-700 mb-0.5">⚠️ 缺失项硬约束</p>
                              <p className="text-[10px] text-red-600 leading-snug">{trimmed.replace(/^.*?严禁/, '严禁')}</p>
                            </div>
                          )
                        }
                        // ATS关键词提取
                        if (trimmed.includes('ATS锚定') || trimmed.includes('JD关键词提取')) {
                          const keywords = trimmed.replace(/^.*?[：:]/, '').split(/[,，、]/).map(s => s.trim()).filter(Boolean)
                          return (
                            <div key={i}>
                              <p className="text-[10px] font-semibold text-teal-600 mb-1">ATS 锚定关键词</p>
                              <div className="flex flex-wrap gap-1">
                                {keywords.map((kw, ki) => (
                                  <span key={ki} className="px-1.5 py-0.5 bg-teal-100 text-teal-700 rounded text-[9px] font-medium">{kw}</span>
                                ))}
                              </div>
                            </div>
                          )
                        }
                        // 岗位类型识别
                        if (trimmed.includes('岗位类型识别')) {
                          return (
                            <div key={i} className="bg-gray-50 border border-gray-200 rounded-md p-2">
                              <p className="text-[10px] text-gray-700 leading-snug">{trimmed.replace(/^\d+\)\s*/, '')}</p>
                            </div>
                          )
                        }
                        // 软技能/综合素质
                        if (trimmed.includes('软技能') || trimmed.includes('综合素质')) {
                          const content = trimmed.replace(/^.*?[：:]/, '').trim()
                          const items = content.split(/[,，、]/).map(s => s.trim()).filter(Boolean)
                          return (
                            <div key={i}>
                              <p className="text-[10px] font-semibold text-purple-600 mb-1">软技能 / 综合素质</p>
                              <div className="flex flex-wrap gap-1">
                                {items.map((kw, ki) => (
                                  <span key={ki} className="px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded text-[9px] font-medium">{kw}</span>
                                ))}
                              </div>
                            </div>
                          )
                        }
                        // 行业/业务高频术语
                        if (trimmed.includes('行业') || trimmed.includes('高频术语')) {
                          const content = trimmed.replace(/^.*?[：:]/, '').trim()
                          const items = content.split(/[,，、]/).map(s => s.trim()).filter(Boolean)
                          return (
                            <div key={i}>
                              <p className="text-[10px] font-semibold text-orange-600 mb-1">行业 / 业务高频术语</p>
                              <div className="flex flex-wrap gap-1">
                                {items.map((kw, ki) => (
                                  <span key={ki} className="px-1.5 py-0.5 bg-orange-100 text-orange-700 rounded text-[9px] font-medium">{kw}</span>
                                ))}
                              </div>
                            </div>
                          )
                        }
                        // 词汇重合度分析
                        if (trimmed.includes('词汇重合度') || trimmed.includes('重合')) {
                          return (
                            <div key={i} className="bg-indigo-50/50 border border-indigo-100 rounded-md p-2">
                              <p className="text-[10px] font-semibold text-indigo-600 mb-0.5">词汇重合度分析</p>
                              <p className="text-[10px] text-gray-600 leading-snug whitespace-pre-line">{trimmed.replace(/^.*?[：:]/, '').trim()}</p>
                            </div>
                          )
                        }
                        // 其他段落
                        return (
                          <div key={i} className="whitespace-pre-line text-[10px] text-gray-600 leading-snug">
                            {trimmed.replace(/^\d+\)\s*/, '')}
                          </div>
                        )
                      })
                    })()}
                  </div>
                </div>
              )}
              {job.resumeAudit && <ResumeAuditCard auditText={job.resumeAudit} />}
              {/* ─── 文本框渲染辅助：解析编号子段 → 带边框内容框 ─── */}
              {(() => {
                // 去除 markdown 加粗标记 **text** → text
                const stripBold = (s: string) => s.replace(/\*\*(.+?)\*\*/g, '$1')
                const renderBoxedSections = (text: string, accentBorder: string) => {
                  // 去掉开头与外层标题重复的行（如 "04·高杠杆匹配点："）
                  const cleaned = text.replace(/^\d{2}·.+?[：:]\s*\n?/, '').trim()
                  // 按 "1）" "2）" 或 "【xxx】" 分段
                  const segments = cleaned.split(/\n(?=\d+[）)])/).filter(Boolean)
                  if (segments.length <= 1) {
                    // 无编号结构，按【】分段
                    const bracketSegs = cleaned.split(/\n(?=【)/).filter(Boolean)
                    if (bracketSegs.length > 1) {
                      return (
                        <div className="space-y-2">
                          {bracketSegs.map((seg, i) => {
                            const titleMatch = seg.match(/^【(.+?)】/)
                            const body = titleMatch ? seg.replace(/^【.+?】\s*/, '').trim() : seg.trim()
                            return (
                              <div key={i} className={`border ${accentBorder} rounded-md px-3 py-2 bg-white/60`}>
                                {titleMatch && <p className="text-[11px] font-semibold text-gray-800 mb-1">{stripBold(titleMatch[1])}</p>}
                                <p className="text-[11px] text-gray-600 whitespace-pre-line leading-relaxed">{stripBold(body)}</p>
                              </div>
                            )
                          })}
                        </div>
                      )
                    }
                    // 按 **加粗标题** 分段
                    const boldSegs = cleaned.split(/\n(?=\*\*.+?\*\*)/).filter(Boolean)
                    if (boldSegs.length > 1) {
                      return (
                        <div className="space-y-2">
                          {boldSegs.map((seg, i) => {
                            const boldMatch = seg.match(/^\*\*(.+?)\*\*/)
                            const title = boldMatch ? boldMatch[1].trim() : ''
                            const body = boldMatch ? seg.replace(/^\*\*.+?\*\*\s*[：:]?\s*/, '').trim() : seg.trim()
                            return (
                              <div key={i} className={`border ${accentBorder} rounded-md px-3 py-2 bg-white/60`}>
                                {title && <p className="text-[11px] font-semibold text-gray-800 mb-1">{title}</p>}
                                {body && <p className="text-[11px] text-gray-600 whitespace-pre-line leading-relaxed">{stripBold(body)}</p>}
                              </div>
                            )
                          })}
                        </div>
                      )
                    }
                    return <div className="text-[11px] text-gray-600 whitespace-pre-line leading-relaxed">{stripBold(cleaned)}</div>
                  }
                  return (
                    <div className="space-y-2">
                      {segments.map((seg, i) => {
                        const trimmed = seg.trim()
                        // 提取编号后的标题（到第一个冒号/换行为止）
                        const titleMatch = trimmed.match(/^\d+[）)]\s*(.+?)(?:[：:]|\n)/)
                        const title = titleMatch ? stripBold(titleMatch[1].trim()) : ''
                        const body = titleMatch
                          ? stripBold(trimmed.replace(/^\d+[）)]\s*.+?[：:]\s*/, '').trim())
                          : stripBold(trimmed.replace(/^\d+[）)]\s*/, '').trim())
                        return (
                          <div key={i} className={`border ${accentBorder} rounded-md px-3 py-2 bg-white/60`}>
                            {title && <p className="text-[11px] font-semibold text-gray-800 mb-1">{title}</p>}
                            <p className="text-[11px] text-gray-600 whitespace-pre-line leading-relaxed">{body}</p>
                          </div>
                        )
                      })}
                    </div>
                  )
                }
                return (
                  <>
                    {job.strongFitAssessment && (
                      <div className="border border-emerald-200 bg-emerald-50/30 rounded-md p-2.5">
                        <h4 className="text-[10px] font-semibold text-emerald-700 mb-2 uppercase tracking-wide">✅ 03·高杠杆匹配点</h4>
                        <div className="max-h-[300px] overflow-y-auto">
                          {renderBoxedSections(job.strongFitAssessment, 'border-emerald-100')}
                        </div>
                      </div>
                    )}
                    {job.dreamPicture && (
                      <div className="border border-indigo-200 bg-indigo-50/30 rounded-md p-2.5">
                        <h4 className="text-[10px] font-semibold text-indigo-700 mb-2 uppercase tracking-wide">🎯 04·理想画像与能力信号</h4>
                        <div className="max-h-[300px] overflow-y-auto">
                          {renderBoxedSections(job.dreamPicture, 'border-indigo-100')}
                        </div>
                      </div>
                    )}
                    {job.riskRedFlags && (
                      <div className="border border-red-200 bg-red-50/30 rounded-md p-2.5">
                        <h4 className="text-[10px] font-semibold text-red-700 mb-2 uppercase tracking-wide">⚠️ 05·致命硬伤与毒点</h4>
                        <div className="max-h-[300px] overflow-y-auto">
                          {renderBoxedSections(job.riskRedFlags, 'border-red-100')}
                        </div>
                      </div>
                    )}
                    {job.deepActionPlan && (
                      <div className="border border-blue-200 bg-blue-50/30 rounded-md p-2.5">
                        <h4 className="text-[10px] font-semibold text-blue-700 mb-2 uppercase tracking-wide">🚀 06·破局行动计划</h4>
                        <div className="max-h-[300px] overflow-y-auto">
                          {renderBoxedSections(job.deepActionPlan, 'border-blue-100')}
                        </div>
                      </div>
                    )}
                  </>
                )
              })()}
              {/* 🌟 专门的"简历改写理由及数据补充"模块 */}
              {rewriteLogicData.hasAny && (
                <div className="border border-indigo-200 bg-indigo-50/40 rounded-md p-2.5 mt-3 shadow-sm">
                  <h4 className="text-[10px] font-bold text-indigo-800 mb-2 uppercase tracking-wide flex items-center gap-1.5">
                    📝 简历改写理由及数据补充
                  </h4>
                  <div className="space-y-3">

                    {/* 1. 改写理由 */}
                    {rewriteLogicData.rationaleItems.length > 0 && (
                      <div className="space-y-1.5">
                        <div className="text-[11px] font-semibold text-indigo-900/90 bg-indigo-100/50 inline-block px-1.5 py-0.5 rounded">改写依据与逻辑：</div>
                        <ul className="list-disc pl-4 space-y-2 text-[11px] text-muted-foreground leading-relaxed">
                          {rewriteLogicData.rationaleItems.map((item, idx) => (
                            <li key={idx}>
                              <span className="font-semibold text-indigo-700 mr-1">[{item.label}]</span>
                              {item.rationale}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* 2. 数据补充 */}
                    {rewriteLogicData.missingItems.length > 0 && (
                      <div className="space-y-1.5 pt-2 border-t border-indigo-100/60">
                        <div className="text-[11px] font-semibold text-orange-700 bg-orange-100/50 inline-block px-1.5 py-0.5 rounded flex items-center gap-1 w-max">
                          💡 简历待补充信息：
                        </div>
                        <ul className="list-disc pl-4 space-y-1.5 text-[11px] text-orange-800/80 leading-relaxed">
                          {rewriteLogicData.missingItems.map((item, idx) => (
                            <li key={idx} className="font-medium">{item.question}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                  </div>
                </div>
              )}

            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="qa_report">
            <AccordionTrigger className="text-xs py-2 hover:no-underline bg-purple-50 dark:bg-purple-950/20 px-2 rounded">
              🔍 二次质检报告 (QA)
            </AccordionTrigger>
            <AccordionContent className="pt-2">
              {!qaReport ? (
                <p className="text-[11px] text-muted-foreground leading-relaxed py-2">
                  暂无质检数据，请点击中间栏的&quot;再次AI评估简历&quot;按钮
                </p>
              ) : (
                <div className="space-y-3">
                  {qaReport.match_verification && (
                    <div className="border border-border rounded-md p-2.5">
                      <h4 className="text-xs font-semibold text-green-700 dark:text-green-400 mb-1.5">✅ 已达成匹配点</h4>
                      <ul className="text-[11px] text-muted-foreground space-y-1 leading-relaxed">
                        {qaReport.match_verification.achieved_points?.map((point: string, idx: number) => (
                          <li key={idx} className="whitespace-pre-line">{point}</li>
                        ))}
                      </ul>
                      <h4 className="text-xs font-semibold text-orange-700 dark:text-orange-400 mt-3 mb-1.5">⚠️ 缺失匹配点</h4>
                      <ul className="text-[11px] text-muted-foreground space-y-1 leading-relaxed">
                        {qaReport.match_verification.missing_points?.map((point: string, idx: number) => (
                          <li key={idx} className="whitespace-pre-line">{point}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {qaReport.hallucination_check && (
                    <div className="border border-border rounded-md p-2.5">
                      <h4 className="text-xs font-semibold text-red-700 dark:text-red-400 mb-1.5">🚨 过度包装检查</h4>
                      <ul className="text-[11px] text-muted-foreground space-y-1 leading-relaxed">
                        {qaReport.hallucination_check.map((item: string, idx: number) => (
                          <li key={idx} className="whitespace-pre-line">{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {qaReport.human_action_items && qaReport.human_action_items.length > 0 && (
                    <div className="border border-purple-200 dark:border-purple-800 bg-purple-50/50 dark:bg-purple-950/30 rounded-md p-2.5">
                      <h4 className="text-xs font-semibold text-purple-700 dark:text-purple-400 mb-1.5">📋 人工待办清单</h4>
                      <ul className="text-[11px] text-muted-foreground space-y-1.5 leading-relaxed">
                        {qaReport.human_action_items.map((item: string, idx: number) => (
                          <li key={idx} className="whitespace-pre-line font-mono">{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="greeting">
            <AccordionTrigger className="text-xs py-2 hover:no-underline">
              打招呼语
            </AccordionTrigger>
            <AccordionContent>
              <div className="space-y-2">
                {/* 🌟 相对定位容器，用于字数统计的绝对定位 */}
                <div className="relative w-full">
                  <Textarea
                    className="min-h-[200px] text-[11px] leading-relaxed pb-8"
                    value={greetingMsg}
                    onChange={(e) => setGreetingMsg(e.target.value)}
                    placeholder="暂无数据"
                  />
                  {/* 🌟 字数统计标签 - 右下角绝对定位 */}
                  <div className="absolute bottom-2 right-2 text-xs text-gray-400 pointer-events-none select-none">
                    {greetingMsg.length} 字
                  </div>
                </div>
                {/* 🌟 两个等宽按钮布局 */}
                <div className="flex w-full gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1 h-7 text-xs gap-1.5 bg-gray-50 hover:bg-gray-100 transition-all active:scale-[0.98]"
                    onClick={handleSaveGreeting}
                    disabled={isSavingGreeting}
                  >
                    {isSavingGreeting ? (
                      <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                    ) : (
                      <Save className="h-3 w-3" />
                    )}
                    {isSavingGreeting ? "保存中..." : "保存"}
                  </Button>
                  <Button
                    variant="default"
                    size="sm"
                    className="flex-1 h-7 text-xs gap-1.5 transition-all active:scale-[0.98]"
                    onClick={handleCopyGreeting}
                  >
                    {isCopiedGreeting ? (
                      <>
                        <Check className="h-3 w-3 text-emerald-400" />
                        已复制
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3" />
                        复制
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="my_review">
            <AccordionTrigger className="text-xs py-2 hover:no-underline">
              我的复核
            </AccordionTrigger>
            <AccordionContent>
              <div className="space-y-2">
                <Textarea
                  className="min-h-[150px] text-[11px] leading-relaxed"
                  value={myReview}
                  onChange={(e) => setMyReview(e.target.value)}
                  placeholder="在这里记录你对这个岗位的复核意见..."
                />
                <Button
                  variant="default"
                  size="sm"
                  className="w-full h-7 text-xs gap-1.5"
                  onClick={handleSaveReview}
                  disabled={isSavingReview}
                >
                  <Save className="h-3 w-3" />
                  {isSavingReview ? "保存中..." : "保存到飞书"}
                </Button>
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    </div>
  )
}
