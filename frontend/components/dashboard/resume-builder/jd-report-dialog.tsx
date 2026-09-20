"use client"
import { useState, useEffect } from "react"
import { Dialog, DialogContent, DialogTrigger, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { API_BASE } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { FileBarChart, Loader2, RefreshCw, Sparkles, ArrowRight } from "lucide-react"
import ReactMarkdown from 'react-markdown'


export function JdReportDialog() {
  const [open, setOpen] = useState(false)
  const [report, setReport] = useState("")
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [refreshAttempted, setRefreshAttempted] = useState(false)

  // 弹窗打开时自动从后端拉取最新数据
  useEffect(() => {
    if (open && !report && !loading) {
      fetchReport(false)
    }
  }, [open])

  const fetchReport = async (isManualRefresh: boolean) => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/get_jd_report`)
      const data = await res.json()
      if (data.status === "success" && data.data) {
        setReport(data.data)
      } else if (isManualRefresh) {
        setRefreshAttempted(true)
      }
    } catch (e) {
      console.error(e)
      if (isManualRefresh) setRefreshAttempted(true)
    } finally {
      setLoading(false)
    }
  }

  const generateReport = async () => {
    setGenerating(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/generate_jd_report`, { method: "POST" })
      const data = await res.json()
      if (data.status === "success") {
        setReport(data.data)
      } else {
        alert("生成失败: " + data.message)
      }
    } catch (e) {
      console.error(e)
      alert("生成失败，请检查网络")
    } finally {
      setGenerating(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="group h-8 px-2 hover:px-2.5 text-muted-foreground hover:bg-background hover:shadow-sm rounded-lg transition-all duration-300 ease-out flex items-center"
        >
          <FileBarChart className="h-4 w-4 shrink-0 text-purple-500 group-hover:text-purple-600 transition-colors" />
          <span className="max-w-0 overflow-hidden opacity-0 group-hover:max-w-[100px] group-hover:opacity-100 group-hover:ml-1.5 text-[13px] font-medium whitespace-nowrap text-foreground transition-all duration-300 ease-out">
            A级岗位画像
          </span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[680px] p-0 gap-0 overflow-hidden border-border bg-background" aria-describedby="jd-report-desc">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-border">
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <DialogTitle className="text-base font-semibold tracking-tight text-foreground">
                A级岗位核心能力画像
              </DialogTitle>
              <DialogDescription id="jd-report-desc" className="text-xs text-muted-foreground">
                基于飞书表格中综合评级为 A 的顶级岗位 JD 自动聚合提炼
              </DialogDescription>
            </div>
            {report && (
              <Button
                variant="outline"
                size="sm"
                onClick={generateReport}
                disabled={generating}
                className="h-7 text-xs shrink-0 transition-all duration-200 hover:bg-accent active:scale-[0.98]"
              >
                {generating
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5"/>
                  : <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                }
                重新生成
              </Button>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="min-h-[400px] max-h-[60vh]">
          {loading ? (
            <div className="flex h-[400px] items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                <span className="text-xs text-muted-foreground">正在读取能力画像…</span>
              </div>
            </div>
          ) : !report ? (
            <div className="flex flex-col h-[400px] items-center justify-center px-8">
              <div className="flex flex-col items-center gap-5 max-w-xs text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                  <Sparkles className="h-5 w-5 text-muted-foreground" />
                </div>
                {!refreshAttempted ? (
                  <>
                    <div className="space-y-1.5">
                      <p className="text-sm font-medium text-foreground">
                        未读取到能力画像
                      </p>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        飞书简历库中可能已有此数据，点击下方按钮从飞书同步最新内容。
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      onClick={() => fetchReport(true)}
                      disabled={loading}
                      size="sm"
                      className="h-8 text-xs font-medium transition-all duration-200 active:scale-[0.98]"
                    >
                      {loading
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5"/>
                        : <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                      }
                      从飞书刷新
                    </Button>
                  </>
                ) : (
                  <>
                    <div className="space-y-1.5">
                      <p className="text-sm font-medium text-foreground">
                        尚未生成能力画像
                      </p>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        飞书中暂无此数据。点击下方按钮，系统将自动读取飞书岗位表中评级为 A 的 JD，由大模型提炼出硬技能、软技能、业务经验和加分项四个维度的核心能力要求。
                      </p>
                    </div>
                    <Button
                      onClick={generateReport}
                      disabled={generating}
                      size="sm"
                      className="h-8 text-xs font-semibold transition-all duration-200 active:scale-[0.98]"
                    >
                      {generating
                        ? <>
                            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5"/>
                            大模型正在分析中…
                          </>
                        : <>
                            一键分析并生成
                            <ArrowRight className="h-3.5 w-3.5 ml-1.5" />
                          </>
                      }
                    </Button>
                  </>
                )}
              </div>
            </div>
          ) : (
            <ScrollArea className="h-[60vh]">
              <article className="px-6 py-5 prose-report">
                <ReactMarkdown>{report}</ReactMarkdown>
              </article>
            </ScrollArea>
          )}
        </div>
      </DialogContent>

      {/* Scoped styles for Markdown rendering — small, restrained typography */}
      <style jsx global>{`
        .prose-report {
          font-size: 13px;
          line-height: 1.7;
          color: hsl(var(--foreground));
        }
        .prose-report h1 {
          font-size: 16px;
          font-weight: 700;
          margin-top: 0;
          margin-bottom: 12px;
          letter-spacing: -0.01em;
          color: hsl(var(--foreground));
        }
        .prose-report h2 {
          font-size: 14px;
          font-weight: 600;
          margin-top: 20px;
          margin-bottom: 8px;
          color: hsl(var(--foreground));
        }
        .prose-report h3 {
          font-size: 13px;
          font-weight: 600;
          margin-top: 16px;
          margin-bottom: 6px;
          color: hsl(var(--foreground));
        }
        .prose-report p {
          margin-bottom: 8px;
          color: hsl(var(--muted-foreground));
        }
        .prose-report ul, .prose-report ol {
          padding-left: 18px;
          margin-bottom: 10px;
        }
        .prose-report li {
          margin-bottom: 3px;
          color: hsl(var(--muted-foreground));
        }
        .prose-report strong {
          font-weight: 600;
          color: hsl(var(--foreground));
        }
        .prose-report hr {
          border-color: hsl(var(--border));
          margin: 16px 0;
        }
        .prose-report code {
          font-size: 12px;
          background: hsl(var(--muted));
          padding: 1px 4px;
          border-radius: 4px;
        }
      `}</style>
    </Dialog>
  )
}
