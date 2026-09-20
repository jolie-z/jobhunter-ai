import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Spinner } from "@/components/ui/spinner"
import { Activity, BookOpen, RefreshCw, Zap } from "lucide-react"
import ReactMarkdown from "react-markdown"
import type { JobData } from "@/types/job"

interface CampIntelTabProps {
  loadingStates: { all: boolean; company: boolean; summary: boolean; qa: boolean }
  intelData: any
  activeJob: JobData | undefined
  fetchFullIntel: (target: 'all' | 'company' | 'summary' | 'qa') => void
}

export function CampIntelTab({ loadingStates, intelData, activeJob, fetchFullIntel }: CampIntelTabProps) {
  const renderMarkdownSafe = (text: any) => {
    if (typeof text === 'string') return text
    if (Array.isArray(text)) return text.map((t: any) => t.text || "").join("")
    return ""
  }

  const markdownComponents = {
    h3: ({node, ...props}: any) => <h3 className="text-[13px] font-bold mt-4 mb-2 border-l-[3px] pl-2 py-1.5 rounded-r break-words bg-opacity-70" {...props} />,
    h2: ({node, ...props}: any) => <h2 className="text-[13px] font-bold mt-4 mb-2 border-l-[3px] pl-2 py-1.5 rounded-r break-words bg-opacity-70" {...props} />,
    strong: ({node, ...props}: any) => <strong className="font-bold bg-opacity-60 px-1 py-0.5 rounded mx-0.5 break-words" {...props} />,
    p: ({node, ...props}: any) => <p className="my-1.5 leading-relaxed break-words" {...props} />,
    ul: ({node, ...props}: any) => <ul className="list-disc pl-4 space-y-1.5 my-2 break-words" {...props} />,
    li: ({node, ...props}: any) => <li className="leading-relaxed break-words" {...props} />,
    pre: ({node, ...props}: any) => <pre className="whitespace-pre-wrap break-words p-2 rounded w-full overflow-x-auto mt-2" {...props} />,
    code: ({node, ...props}: any) => <code className="break-all whitespace-pre-wrap px-1 rounded bg-opacity-50" {...props} />
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 pb-6 m-0 custom-scrollbar">
      <div className="flex justify-end mb-4 pt-2">
        <Button
          size="sm"
          onClick={() => fetchFullIntel('all')}
          disabled={loadingStates.all}
          className="h-8 px-4 text-xs font-bold shadow-sm rounded-lg gap-1.5 bg-white text-gray-600 border border-gray-200 hover:bg-gray-50 transition-all duration-300"
        >
          {loadingStates.all ? (
            <><Spinner className="w-3.5 h-3.5"/> 正在全量刷新...</>
          ) : intelData ? (
            <><Activity className="w-3.5 h-3.5 text-amber-500"/> 强制全量刷新</>
          ) : (
            <><Zap className="w-3.5 h-3.5 text-blue-500"/> 获取面试情报</>
          )}
        </Button>
      </div>

      {loadingStates.all && !intelData ? (
        <div className="h-64 flex flex-col items-center justify-center text-muted-foreground gap-3">
          <Spinner className="h-8 w-8 text-blue-500" />
          <p className="font-medium animate-pulse">正在全网检索情报并调用 AI 生成预测考题...</p>
        </div>
      ) : intelData ? (
        <div className="space-y-4 max-w-4xl mx-auto">
          {/* 公司资料 */}
          <Card className={`border-blue-100 shadow-sm transition-all ${loadingStates.company ? 'bg-gray-50/50 opacity-60 grayscale' : 'bg-blue-50/20'}`}>
            <CardHeader className="py-3 px-4 border-b border-blue-50 flex flex-row justify-between items-center">
              <div>
                <CardTitle className="text-base text-blue-900 flex items-center gap-2">🏢 外部 API 情报：公司概况与业务洞察</CardTitle>
                <CardDescription className="text-xs mt-1">由 Serper（Google 搜索）实时抓取的全网最新商业动态，建议背诵一两条在面试中自然提及</CardDescription>
              </div>
              <Button variant="ghost" size="sm" onClick={() => fetchFullIntel('company')} disabled={loadingStates.company || loadingStates.all} className="h-8 w-8 p-0 text-blue-600 hover:bg-blue-100 shrink-0">
                <RefreshCw className={`h-4 w-4 ${loadingStates.company ? 'animate-spin' : ''}`} />
              </Button>
            </CardHeader>
            <CardContent className="p-4 text-[12px] text-gray-800 max-h-[600px] overflow-y-auto custom-scrollbar prose-blue">
              <ReactMarkdown components={markdownComponents}>{renderMarkdownSafe(intelData.company_intel)}</ReactMarkdown>
            </CardContent>
          </Card>

          {/* 岗位面经 */}
          <Card className={`border-amber-100 shadow-sm transition-all ${loadingStates.summary ? 'bg-gray-50/50 opacity-60 grayscale' : 'bg-amber-50/20'}`}>
            <CardHeader className="py-3 px-4 border-b border-amber-50 flex flex-row justify-between items-center">
              <div>
                <CardTitle className="text-base text-amber-900 flex items-center gap-2">🎯 领域面经库：【{activeJob?.industry || "通用"}】赛道 - {activeJob?.jobTitle}</CardTitle>
                <CardDescription className="text-xs mt-1">大模型已将全网零散面经去重，提炼出的高频核心考点</CardDescription>
              </div>
              <Button variant="ghost" size="sm" onClick={() => fetchFullIntel('summary')} disabled={loadingStates.summary || loadingStates.all} className="h-8 w-8 p-0 text-amber-600 hover:bg-amber-100 shrink-0">
                <RefreshCw className={`h-4 w-4 ${loadingStates.summary ? 'animate-spin' : ''}`} />
              </Button>
            </CardHeader>
            <CardContent className="p-4 text-[12px] text-gray-800 max-h-[600px] overflow-y-auto custom-scrollbar prose-amber">
              <ReactMarkdown components={markdownComponents}>{renderMarkdownSafe(intelData.summary_text)}</ReactMarkdown>
            </CardContent>
          </Card>

          {/* 结合 JD 预测 */}
          {intelData.predicted_qa && (
            <Card className={`border-emerald-200 shadow-sm transition-all ring-1 ring-emerald-100 ${loadingStates.qa ? 'bg-gray-50/50 opacity-60 grayscale' : 'bg-emerald-50/40'}`}>
              <CardHeader className="py-3 px-4 border-b border-emerald-100 flex flex-row justify-between items-center">
                <div>
                  <CardTitle className="text-base text-emerald-900 flex items-center gap-2">🔮 绝密押题：结合当前具体 JD 的 AI 考点预测</CardTitle>
                  <CardDescription className="text-xs text-emerald-700/70 mt-1">AI 深度分析了本公司的具体 JD 与通用面经库，为你独家预测的 10-20 个必考题及稳妥的回答策略</CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={() => fetchFullIntel('qa')} disabled={loadingStates.qa || loadingStates.all} className="h-8 w-8 p-0 text-emerald-600 hover:bg-emerald-100 shrink-0">
                  <RefreshCw className={`h-4 w-4 ${loadingStates.qa ? 'animate-spin' : ''}`} />
                </Button>
              </CardHeader>
              <CardContent className="p-4 text-[12px] text-gray-800 max-h-[800px] overflow-y-auto custom-scrollbar prose-emerald">
                <ReactMarkdown components={markdownComponents}>{renderMarkdownSafe(intelData.predicted_qa)}</ReactMarkdown>
              </CardContent>
            </Card>
          )}

          {/* 黄金反问环节 */}
          {intelData.reverse_questions && (
            <Card className={`border-violet-200 shadow-sm transition-all ring-1 ring-violet-100 ${loadingStates.qa ? 'bg-gray-50/50 opacity-60 grayscale' : 'bg-violet-50/40'}`}>
              <CardHeader className="py-3 px-4 border-b border-violet-100 flex flex-row justify-between items-center">
                <div>
                  <CardTitle className="text-base text-violet-900 flex items-center gap-2">💡 黄金反问环节：向面试官提问</CardTitle>
                  <CardDescription className="text-xs text-violet-700/70 mt-1">基于公司情报、JD 与你的简历生成的 5 个战略级高含金量问题，助你在面试结尾绝地反击</CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={() => fetchFullIntel('qa')} disabled={loadingStates.qa || loadingStates.all} className="h-8 w-8 p-0 text-violet-600 hover:bg-violet-100 shrink-0">
                  <RefreshCw className={`h-4 w-4 ${loadingStates.qa ? 'animate-spin' : ''}`} />
                </Button>
              </CardHeader>
              <CardContent className="p-4 text-[12px] text-gray-800 max-h-[800px] overflow-y-auto custom-scrollbar prose-violet">
                <ReactMarkdown components={markdownComponents}>{renderMarkdownSafe(intelData.reverse_questions)}</ReactMarkdown>
              </CardContent>
            </Card>
          )}
        </div>
      ) : (
        <div className="h-64 flex flex-col items-center justify-center text-gray-400 gap-3 bg-gray-50/50 rounded-xl border border-dashed border-gray-200 m-4">
          <BookOpen className="h-10 w-10 text-gray-300" />
          <p className="text-sm font-medium text-gray-600">尚未获取该岗位的面试情报</p>
          <p className="text-xs text-gray-400 mb-2">完全由你掌控：点击按钮，AI 才会去全网检索并押题</p>
          <Button onClick={() => fetchFullIntel('all')} className="bg-white text-blue-600 border border-blue-200 hover:bg-blue-50 shadow-sm h-8 text-xs font-bold px-4 rounded-lg transition-all">
            <Zap className="w-3.5 h-3.5 mr-1.5"/> 立即获取情报
          </Button>
        </div>
      )}
    </div>
  )
}
