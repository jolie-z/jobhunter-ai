"use client"
import { useState, useEffect, useMemo } from "react"
import { Dialog, DialogContent, DialogTrigger, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { API_BASE } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { FileBarChart, Loader2, RefreshCw, Sparkles, ArrowRight, AlertTriangle, Link2 } from "lucide-react"
import ReactMarkdown from 'react-markdown'
import remarkGfm from "remark-gfm"

// 模块级常量：避免每次渲染新建数组引用触发 ReactMarkdown 插件重解析（CR P2）
const REMARK_PLUGINS = [remarkGfm]

// 画像元数据（后端 system_reports.meta_json；迁移自飞书的旧值 generated_at 为空、样本数缺失）
type JdReportMeta = {
  generated_at?: string | null
  a_count?: number
  b_count?: number
  total_a_in_pool?: number
  stage?: string
  migrated_from_feishu?: boolean
  format?: string
  // 来源映射（detailed_v2 报告）：报告里的〔来源:N〕据此渲染成可点击岗位深链
  sample_jobs?: SampleJob[]
}

type SampleJob = { idx: number; grade: string; company: string; title: string; record_id: string }

const STALE_MS = 7 * 24 * 60 * 60 * 1000

// 空值友好兜底：迁移旧画像缺 generated_at/样本数，禁止渲染 undefined/Invalid Date
function buildMetaLine(meta: JdReportMeta | null): string {
  if (!meta) return ""
  const parts: string[] = []
  if (meta.generated_at) {
    parts.push(`生成于 ${meta.generated_at.replace("T", " ").slice(0, 16)}`)
  } else {
    parts.push("历史同步画像")
  }
  if (typeof meta.a_count === "number" || typeof meta.b_count === "number") {
    parts.push(`基于 ${meta.a_count ?? 0} 条 A 级 + ${meta.b_count ?? 0} 条 B 级岗位`)
  } else {
    parts.push("样本数未知")
  }
  if (meta.stage === "mature") {
    parts.push("纯 A 精选 Top20")
  } else if (meta.stage) {
    // mixed（及 0.2.0 三阶段旧值 cold/growing）；b_count=0 时实际未补 B，不虚标
    const total = (meta.a_count ?? 0) + (meta.b_count ?? 0)
    parts.push(meta.b_count ? `已补 B 级（共 ${total || "?"} 条样本）` : `纯 A 样本（共 ${total || "?"} 条）`)
  }
  return parts.join(" · ")
}

function isMetaStale(meta: JdReportMeta | null): boolean {
  if (!meta) return false
  if (!meta.generated_at) return true
  const t = new Date(meta.generated_at).getTime()
  return Number.isNaN(t) || Date.now() - t > STALE_MS
}

// 来源标记预处理（与后端 jd_report_prompts 两端闭合）：
// 〔来源:1,5,16〕 → 内联代码占位 `JDSRC:1,5,16`，由 components.code 渲染成 HoverCard。
// 全角冒号/逗号容错；编号去重、越界剔除；全部无效保留原文（DC R2 P2 / CR R1 P2）。
function annotateJdSources(md: string, jobs?: SampleJob[]): string {
  if (!jobs?.length) return md
  const valid = new Set(jobs.map((j) => j.idx))
  return md.replace(/〔\s*来\s*源\s*[:：]\s*([0-9,，\s]+)〕/g, (full, inner: string) => {
    const ids = Array.from(new Set((inner.match(/\d+/g) ?? []).map(Number).filter((n) => valid.has(n))))
    return ids.length ? "`JDSRC:" + ids.join(",") + "`" : full
  })
}

// 来源徽标：hover 弹出岗位卡片，每行 公司·岗位名 可点击 → 新标签页定制面板（/?job_id=record_id）
function JdSourceChip({ ids, jobs }: { ids: number[]; jobs?: SampleJob[] }) {
  const map = new Map((jobs ?? []).map((j) => [j.idx, j]))
  const resolved = ids.map((i) => map.get(i)).filter((j): j is SampleJob => Boolean(j))
  if (!resolved.length) return null
  return (
    <HoverCard openDelay={150} closeDelay={100}>
      <HoverCardTrigger asChild>
        <span
          className="inline-flex items-center gap-1 align-baseline cursor-help rounded-md bg-muted px-1.5 py-0.5 mx-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors select-none"
        >
          <Link2 className="h-3 w-3" />
          来源 ·{ids.length}
        </span>
      </HoverCardTrigger>
      <HoverCardContent className="w-72 p-2" align="start">
        <div className="px-2 pb-1.5 text-[11px] text-muted-foreground">点击岗位打开定制面板详情</div>
        {resolved.map((j) => (
          <a
            key={j.idx}
            href={`/?job_id=${encodeURIComponent(j.record_id)}`}
            target="_blank"
            rel="noreferrer"
            className="block rounded-md px-2 py-1.5 text-xs hover:bg-accent transition-colors"
          >
            <span className="font-medium">{j.company || "未知公司"}·{j.title}</span>
            <span className="ml-1.5 text-[10px] text-muted-foreground">{j.grade} 级</span>
          </a>
        ))}
        <div className="mt-1 border-t border-border px-2 pt-1.5 text-[10px] text-muted-foreground">
          仅列代表岗位，完整来源数见条目频次
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}

export function JdReportDialog() {
  const [open, setOpen] = useState(false)
  const [report, setReport] = useState("")
  const [meta, setMeta] = useState<JdReportMeta | null>(null)
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
        setMeta(data.meta || null)
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
        setMeta(data.meta || null)
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

  const sampleJobs = meta?.sample_jobs
  // components 引用稳定：避免重绘时 ReactMarkdown 重挂全部渲染器（CR R1 P2）
  const markdownComponents = useMemo(() => ({
    code({ className, children }: { className?: string; children?: React.ReactNode }) {
      const raw = String(children ?? "")
      if (!className && raw.startsWith("JDSRC:")) {
        return <JdSourceChip ids={raw.slice(6).split(",").map(Number)} jobs={sampleJobs} />
      }
      return <code className={className}>{children}</code>
    },
  }), [sampleJobs])

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
                基于飞书岗位表高评级 JD 自动聚合提炼 · 本地存储 · 超 7 天提示重新生成
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
          {report && (
            <div className="mt-2.5 flex items-center gap-2 flex-wrap">
              {isMetaStale(meta) && (
                <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-500">
                  <AlertTriangle className="h-3 w-3" />
                  画像已陈旧，建议重新生成
                </span>
              )}
              {meta && (
                <span className="text-[11px] text-muted-foreground">{buildMetaLine(meta)}</span>
              )}
            </div>
          )}
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
                        本地暂无画像数据。若此前生成过，系统会自动迁移历史数据，点击下方按钮重新读取。
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
                      重新读取
                    </Button>
                  </>
                ) : (
                  <>
                    <div className="space-y-1.5">
                      <p className="text-sm font-medium text-foreground">
                        尚未生成能力画像
                      </p>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        系统将从岗位表读取高评级岗位 JD（A 级为核心样本，不足时以 B 级补位），由大模型提炼出硬技能、软技能、业务经验和加分项四个维度的核心能力要求，结果保存在本地并每日自动检查更新。
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
              {/* remark-gfm：LLM 可能输出 GFM 表格/删除线等扩展语法（不开会糊成纯文本）
                  components.code：JDSRC 占位符渲染来源 HoverCard，其余原样 */}
              <article className="px-6 py-5 prose-report">
                <ReactMarkdown
                  remarkPlugins={REMARK_PLUGINS}
                  components={markdownComponents}
                >
                  {annotateJdSources(report, sampleJobs)}
                </ReactMarkdown>
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
        /* GFM 表格（样式对齐 interview-prep-column 先例，配色走主题变量） */
        .prose-report table {
          border-spacing: 0;
          border-collapse: collapse;
          margin: 12px 0 16px;
          width: 100%;
          display: block;
          overflow-x: auto;
          font-size: 12px;
        }
        .prose-report th, .prose-report td {
          padding: 5px 10px;
          border: 1px solid hsl(var(--border));
          text-align: left;
          vertical-align: top;
        }
        .prose-report th {
          font-weight: 600;
          background: hsl(var(--muted));
          white-space: nowrap;
        }
        .prose-report tr:nth-child(2n) {
          background: hsl(var(--muted) / 0.4);
        }
      `}</style>
    </Dialog>
  )
}
