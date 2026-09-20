import { API_BASE } from "@/lib/api"
import React, { useState, useEffect, useRef } from "react"
import type { JobData } from "@/types/job"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Download, Sparkles } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"


// ── 模块 D：面试资料 ──────────────────────────────────────────────────────────────
export function InterviewPrepColumn({ job, resumeText = "" }: { job: JobData | null; resumeText?: string }) {
  const [interviewReport, setInterviewReport] = useState<string | null>(
    job?.interviewReport || null
  )
  const [isGeneratingPrep, setIsGeneratingPrep] = useState(false)
  const [prepError, setPrepError] = useState<string | null>(null)
  const [terminalLogs, setTerminalLogs] = useState<string[]>([])
  const [tokenCount, setTokenCount] = useState<number | null>(null)
  const terminalRef = useRef<HTMLDivElement>(null)
  const markdownRef = useRef<HTMLDivElement>(null)

  // job 切换或飞书缓存报告变化时，同步初始化本地状态
  // 依赖 job?.id + job?.interviewReport：
  //   · id 变化 → 新岗位，重置终端日志和错误
  //   · interviewReport 变化 → 飞书读到了报告（或清空），立即回显
  useEffect(() => {
    const cached = job?.interviewReport || null
    setInterviewReport(cached)
    // 仅在切换岗位时清空终端和 token（同岗位收到 Feishu 回报不清除）
    setTerminalLogs(prev => (prev.length > 0 && cached ? prev : []))
    setTokenCount(null)
    setPrepError(null)
  }, [job?.id, job?.interviewReport])

  // 终端自动滚到底部
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight
    }
  }, [terminalLogs])

  const handleGenerate = async () => {
    if (!job) return
    setIsGeneratingPrep(true)
    setTerminalLogs([])
    setInterviewReport(null)
    setTokenCount(null)
    setPrepError(null)

    try {
      const res = await fetch(`${API_BASE}/api/jobs/interview-prep`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.id,
          resume_text: resumeText,
          job_description: job.jobDescription || "",
          company_name: job.companyName || "",
        }),
      })

      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}))
        throw new Error((err as any).detail || "请求失败")
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""
        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const event = JSON.parse(line)
            if (event.type === "log") {
              setTerminalLogs(prev => [...prev, event.message as string])
            } else if (event.type === "result") {
              setInterviewReport(event.content as string)
              setTokenCount((event.tokens as any)?.total ?? null)
            } else if (event.type === "error") {
              throw new Error(event.message as string)
            }
          } catch {
            // 忽略非 JSON 行（边界截断保护）
          }
        }
      }
    } catch (err: unknown) {
      setPrepError((err as Error).message || "生成失败，请重试")
    } finally {
      setIsGeneratingPrep(false)
    }
  }

  const handleExportHTML = () => {
    if (!interviewReport || !markdownRef.current) return
    const html = markdownRef.current.innerHTML
    const title = `${job?.companyName ?? ""} ${job?.jobTitle ?? "面试辅导报告"}`.trim()
    const fullHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${title}</title>
  <style>
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:16px;line-height:1.6;color:#24292f;max-width:860px;margin:0 auto;padding:32px 24px}
    h1,h2,h3,h4,h5,h6{margin-top:24px;margin-bottom:16px;font-weight:600;line-height:1.25}
    h1{font-size:2em;padding-bottom:.3em;border-bottom:1px solid #d0d7de}
    h2{font-size:1.5em;padding-bottom:.3em;border-bottom:1px solid #d0d7de}
    h3{font-size:1.25em}h4{font-size:1em}
    p{margin-top:0;margin-bottom:16px}
    ul,ol{padding-left:2em;margin-bottom:16px}
    li+li{margin-top:.25em}
    table{border-spacing:0;border-collapse:collapse;margin-bottom:16px;width:100%;display:block;overflow:auto}
    table th,table td{padding:6px 13px;border:1px solid #d0d7de}
    table th{font-weight:600;background:#f6f8fa}
    table tr:nth-child(2n){background:#f6f8fa}
    blockquote{padding:0 1em;color:#57606a;border-left:.25em solid #d0d7de;margin:0 0 16px}
    code{background:rgba(175,184,193,.2);padding:.2em .4em;border-radius:6px;font-family:'SFMono-Regular',Consolas,monospace;font-size:85%}
    pre{background:#f6f8fa;border-radius:6px;padding:16px;overflow:auto}
    pre code{background:none;padding:0;font-size:100%}
    strong{font-weight:600}
    hr{height:.25em;background:#d0d7de;border:0;margin:24px 0}
    a{color:#0969da;text-decoration:none}a:hover{text-decoration:underline}
  </style>
</head>
<body>
${html}
</body>
</html>`
    const blob = new Blob([fullHtml], { type: "text/html;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${title}_面试辅导报告.html`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="h-full bg-card flex flex-col overflow-hidden">
      {/* ── 标题栏 ── */}
      <div className="px-3 py-2 border-b border-border shrink-0 flex items-center justify-between gap-2">
        <h3 className="font-medium text-xs text-foreground flex items-center gap-1.5 shrink-0">
          📚 面试资料
        </h3>
        <div className="flex items-center gap-1">
          {tokenCount !== null && (
            <Badge variant="secondary" className="text-[10px] h-5 px-1.5">
              ⚡ {tokenCount.toLocaleString()} tokens
            </Badge>
          )}
          {interviewReport && !isGeneratingPrep && (
            <>
              <Button
                variant="ghost" size="sm"
                className="h-6 text-xs px-2 text-muted-foreground gap-1"
                onClick={handleExportHTML}
              >
                <Download className="h-3 w-3" />
                导出 HTML
              </Button>
              <Button
                variant="ghost" size="sm"
                className="h-6 text-xs px-2 text-muted-foreground"
                onClick={() => { setInterviewReport(null); setTerminalLogs([]); setTokenCount(null); setPrepError(null) }}
              >
                重新生成
              </Button>
            </>
          )}
        </div>
      </div>

      {/* ── 内容区 ── */}
      {isGeneratingPrep ? (
        // 终端 UI
        <div className="flex-1 flex flex-col overflow-hidden bg-zinc-950">
          <div className="px-3 py-1.5 border-b border-zinc-800 flex items-center gap-1.5 shrink-0">
            <span className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
            <span className="h-2.5 w-2.5 rounded-full bg-yellow-500/80" />
            <span className="h-2.5 w-2.5 rounded-full bg-green-500/80" />
            <span className="text-[10px] text-zinc-500 ml-1 font-mono">interview-prep-agent</span>
          </div>
          <div
            ref={terminalRef}
            className="flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed space-y-1"
          >
            {terminalLogs.map((log, i) => (
              <div key={i} className="flex gap-2">
                <span className="text-green-400 shrink-0 select-none">❯</span>
                <span className="text-zinc-300 break-all">{log}</span>
              </div>
            ))}
            <div className="flex gap-2 items-center">
              <span className="text-green-400 shrink-0 select-none">❯</span>
              <span className="inline-block w-2 h-3.5 bg-green-400 animate-pulse rounded-sm" />
            </div>
          </div>
        </div>
      ) : prepError ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-muted-foreground">
          <p className="text-sm text-red-500 text-center">{prepError}</p>
          <Button variant="outline" size="sm" className="text-xs" onClick={handleGenerate}>重试</Button>
        </div>
      ) : interviewReport ? (
        // Markdown 报告（prose 排版）
        <div className="flex-1 overflow-y-auto p-4">
          <div
            ref={markdownRef}
            className="prose prose-sm dark:prose-invert max-w-none"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {interviewReport}
            </ReactMarkdown>
          </div>
        </div>
      ) : (
        // 空状态
        <div className="flex-1 flex flex-col items-center justify-center gap-4 p-6 text-muted-foreground">
          <div className="text-4xl select-none">🎯</div>
          <div className="text-center space-y-1">
            <p className="text-sm font-medium text-foreground">AI 面试辅导报告</p>
            <p className="text-xs leading-relaxed opacity-70">
              基于岗位 JD 和你的简历<br />
              自动搜索面经并生成完整 8 章备考手册
            </p>
          </div>
          {job?.jobTitle && (
            <div className="text-xs bg-muted/50 rounded-lg px-3 py-2 text-center">
              {job.jobTitle} · {job.companyName || "–"}
            </div>
          )}
          <Button
            variant="default" size="sm"
            className="mt-2 h-8 px-4 text-xs bg-blue-600 hover:bg-blue-700 gap-1.5"
            onClick={handleGenerate}
            disabled={!job}
          >
            <Sparkles className="h-3.5 w-3.5" />
            一键生成 AI 面试辅导报告
          </Button>
        </div>
      )}
    </div>
  )
}
