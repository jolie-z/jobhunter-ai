import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { BookOpen, Activity, Sparkles, Filter, ChevronDown, ChevronUp, Flame, Trash2, Briefcase, Link as LinkIcon, AlertCircle, Target } from "lucide-react"
import ReactMarkdown from "react-markdown"
import type { QuestionItem } from "@/hooks/use-question-bank"

interface CampQuestionBankTabProps {
  sourceFilter: "全部" | "⚔️ 真实复盘" | "🌐 简历专项预测"
  setSourceFilter: (val: "全部" | "⚔️ 真实复盘" | "🌐 简历专项预测") => void
  fetchQuestions: () => void
  isLoadingQs: boolean
  questions: QuestionItem[]
  groupedQuestions: [string, QuestionItem[]][]
  expandedDemo: Record<string, boolean>
  setExpandedDemo: React.Dispatch<React.SetStateAction<Record<string, boolean>>>
  expandedOriginal: Record<string, boolean>
  setExpandedOriginal: React.Dispatch<React.SetStateAction<Record<string, boolean>>>
  savingMap: Record<string, boolean>
  cycleMastery: (q: QuestionItem) => void
  setActiveDrillQuestion: (q: QuestionItem) => void
  setActiveTab: (val: string) => void
  deleteQuestion: (recordId: string) => void
  masteryColor: (status: string) => string
  updateQuestionField: (recordId: string, fields: Partial<QuestionItem>) => void
}

export function CampQuestionBankTab({
  sourceFilter, setSourceFilter, fetchQuestions, isLoadingQs, questions, groupedQuestions,
  expandedDemo, setExpandedDemo, expandedOriginal, setExpandedOriginal,
  savingMap, cycleMastery, setActiveDrillQuestion, setActiveTab, deleteQuestion,
  masteryColor, updateQuestionField
}: CampQuestionBankTabProps) {
  const weaknesses = questions.filter(q => q.mastery_status?.includes("🔴"))
  const topFreq = [...questions].sort((a, b) => (b.frequency || 0) - (a.frequency || 0)).slice(0, 20)

  return (
    <div className="flex-1 overflow-y-auto px-6 pb-6 m-0 custom-scrollbar">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div>
          <h2 className="text-base font-bold text-blue-900 flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-blue-600"/> 专属面经库 · 私有题库
          </h2>
          <p className="text-xs text-blue-700/70 mt-0.5">
            历次「面经粉碎机」沉淀的真题，会随机注入到下次模拟面试中进行<span className="font-bold text-red-500">暗杀考察</span>。
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1 bg-white border border-blue-200 rounded-lg p-0.5">
            {(["全部", "⚔️ 真实复盘", "🌐 简历专项预测"] as const).map(opt => (
              <button
                key={opt}
                onClick={() => setSourceFilter(opt)}
                className={`text-[11px] px-2.5 py-1 rounded-md font-medium transition-all ${sourceFilter === opt ? "bg-blue-600 text-white shadow-sm" : "text-gray-600 hover:bg-blue-50"}`}
              >
                {opt}
              </button>
            ))}
          </div>
          <Button variant="outline" size="sm" onClick={fetchQuestions} disabled={isLoadingQs} className="h-8 text-xs bg-white text-blue-600 border-blue-200 hover:bg-blue-50 shadow-sm">
            {isLoadingQs ? <Spinner className="w-3.5 h-3.5 mr-1" /> : <Activity className="w-3.5 h-3.5 mr-1" />}
            刷新
          </Button>
        </div>
      </div>

      {isLoadingQs ? (
        <div className="h-64 flex flex-col items-center justify-center text-muted-foreground gap-3">
          <Spinner className="h-8 w-8 text-blue-500" />
          <p className="text-sm">正在拉取专属面经库...</p>
        </div>
      ) : questions.length === 0 ? (
        <div className="flex flex-col items-center justify-center text-gray-400 py-20">
          <BookOpen size={48} className="opacity-20 mb-4" />
          <p className="text-sm">题库还是空的，去【现场面经】Tab 把流水账丢进粉碎机吧！</p>
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-4">
          {/* 左侧展厅 */}
          <div className="col-span-12 lg:col-span-8 flex flex-col gap-4">
            {groupedQuestions.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-gray-400 py-16 bg-gray-50/50 rounded-xl border border-dashed border-gray-200">
                <Filter className="w-8 h-8 opacity-20 mb-3" />
                <p className="text-sm">当前筛选条件下暂无题目</p>
              </div>
            ) : groupedQuestions.map(([questionText, records], groupIndex) => (
              <Card key={`group-${groupIndex}`} className="border-purple-100 bg-gradient-to-br from-purple-50/30 via-white to-indigo-50/20 shadow-sm hover:shadow-md transition-shadow rounded-xl overflow-hidden">
                <CardHeader className="py-3 px-4 bg-gradient-to-r from-purple-100/60 to-indigo-100/40 border-b border-purple-100">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2 flex-1">
                      <Sparkles className="w-5 h-5 text-purple-600 shrink-0 mt-0.5"/>
                      <CardTitle className="text-sm font-bold text-gray-900 leading-relaxed">{questionText}</CardTitle>
                    </div>
                    <Badge variant="outline" className="shrink-0 text-[11px] bg-white border-purple-300 text-purple-700 font-bold">共 {records.length} 个视角的记录</Badge>
                  </div>
                </CardHeader>
                <CardContent className="p-4 flex flex-col gap-3">
                  {records.map((q, idx) => {
                    const isExp = !!expandedDemo[q.record_id]
                    const isOrigExp = !!expandedOriginal[q.record_id]
                    const isSaving = !!savingMap[q.record_id]
                    return (
                      <div key={q.record_id} className="rounded-lg border border-dashed border-gray-300 bg-white/70 p-3 flex flex-col gap-2.5 hover:border-purple-300 hover:bg-white transition-colors">
                        <div className="flex items-center justify-between gap-2">
                          <Badge variant="outline" className="text-[10px] bg-purple-50 border-purple-200 text-purple-700 font-bold">视角 {idx + 1}</Badge>
                          <div className="flex items-center gap-1">
                            <button onClick={() => cycleMastery(q)} disabled={isSaving} className={`text-[11px] font-bold px-2.5 py-1 rounded-full border transition-all ${masteryColor(q.mastery_status)} ${isSaving ? "opacity-60" : ""}`} title="点击循环切换：⚪已收录 → 🔴未掌握 → 🟡练习中 → 🟢已掌握">
                              {q.mastery_status || "⚪ 已收录"}
                            </button>
                            <button onClick={() => { setActiveDrillQuestion(q); setActiveTab("practice"); }} className="shrink-0 text-orange-400 hover:text-orange-600 hover:bg-orange-50 p-1.5 rounded-md transition-colors" title="开启单点爆破"><Flame className="w-4 h-4" /></button>
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <button disabled={isSaving} className="shrink-0 text-gray-300 hover:text-red-500 hover:bg-red-50 p-1.5 rounded-md transition-colors" title="从飞书中永久删除此卡片"><Trash2 className="w-4 h-4" /></button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>确认永久删除这道面经题？</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    该题卡将从云端飞书题库中永久移除，无法恢复。若它是重复题，建议先合并答案再删除。
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>取消</AlertDialogCancel>
                                  <AlertDialogAction onClick={() => deleteQuestion(q.record_id)}>确认删除</AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          </div>
                        </div>

                        <div className="flex flex-wrap items-center gap-1.5">
                          {q.source && <Badge variant="outline" className="text-[10px] bg-amber-50 border-amber-200 text-amber-700">{q.source}</Badge>}
                          {q.question_type && <Badge variant="outline" className="text-[10px] bg-indigo-50 border-indigo-200 text-indigo-700">{q.question_type}</Badge>}
                          {q.job_group && <Badge variant="outline" className="text-[10px] bg-cyan-50 border-cyan-200 text-cyan-700"><Briefcase className="w-2.5 h-2.5 mr-0.5"/> {Array.isArray(q.job_group) ? q.job_group.join(", ") : q.job_group}</Badge>}
                          {q.company_and_job && <Badge variant="outline" className="text-[10px] bg-violet-50 border-violet-200 text-violet-700"><LinkIcon className="w-2.5 h-2.5 mr-0.5"/> {q.company_and_job}</Badge>}
                          {q.interview_stage && <Badge variant="outline" className="text-[10px] bg-orange-50 border-orange-200 text-orange-700">{q.interview_stage}</Badge>}
                          {q.frequency > 0 && <Badge variant="outline" className="text-[10px] bg-red-50 border-red-200 text-red-600">🔥 ×{q.frequency}</Badge>}
                          {q.tags && <Badge variant="outline" className="text-[10px] bg-slate-50 border-slate-200 text-slate-600">{q.tags}</Badge>}
                        </div>

                        {q.original_text && (
                          <div className="border-t border-dashed border-gray-100 pt-2">
                            <button onClick={() => setExpandedOriginal(s => ({ ...s, [q.record_id]: !s[q.record_id] }))} className="flex items-center gap-1 text-[11px] text-indigo-500 hover:text-indigo-700 transition-colors">
                              {isOrigExp ? <ChevronUp className="w-3 h-3"/> : <ChevronDown className="w-3 h-3"/>} 📎 关联原文溯源
                            </button>
                            {isOrigExp && <div className="mt-1.5 p-2.5 bg-indigo-50/50 border border-indigo-100 rounded-lg text-[11px] text-indigo-800 leading-relaxed italic">&ldquo;{q.original_text}&rdquo;</div>}
                          </div>
                        )}

                        <div>
                          <Label className="text-[11px] font-bold text-amber-700 flex items-center gap-1 mb-1">💰 答案 {idx + 1} (失焦自动同步)</Label>
                          <Textarea
                            defaultValue={q.golden_answer}
                            onBlur={(e) => {
                              const val = e.target.value
                              if (val !== q.golden_answer) updateQuestionField(q.record_id, { golden_answer: val })
                            }}
                            placeholder="把你最稳的标准答案写在这里，下次模拟暗杀时 AI 会拿它来对标比分..."
                            className="h-[100px] shrink-0 resize-none text-xs leading-relaxed bg-amber-50/30 border-amber-200 focus-visible:ring-amber-400 rounded-lg custom-scrollbar"
                          />
                        </div>

                        {q.ai_demo && (
                          <div className="border-t border-gray-100 pt-2">
                            <button onClick={() => setExpandedDemo(s => ({ ...s, [q.record_id]: !s[q.record_id] }))} className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-700 transition-colors">
                              {isExp ? <ChevronUp className="w-3 h-3"/> : <ChevronDown className="w-3 h-3"/>} AI 原始示范参考
                            </button>
                            {isExp && <div className="mt-2 p-2 bg-gray-50 border border-gray-100 rounded-lg text-[11px] text-gray-600 leading-relaxed prose prose-xs max-w-none"><ReactMarkdown>{q.ai_demo}</ReactMarkdown></div>}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </CardContent>
              </Card>
            ))}
          </div>

          {/* 右侧特训中枢 */}
          <div className="col-span-12 lg:col-span-4 flex flex-col gap-4">
            <Card className="border-red-100 bg-gradient-to-br from-red-50/40 via-white to-orange-50/20 shadow-sm">
              <CardHeader className="py-2.5 px-4 border-b border-red-100">
                <CardTitle className="text-sm text-red-800 flex items-center gap-1.5">
                  <AlertCircle className="w-3.5 h-3.5 text-red-500"/> 🩹 弱点账本
                  <Badge variant="outline" className="text-[10px] ml-auto bg-red-50 border-red-200 text-red-600">{weaknesses.length}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                {weaknesses.length === 0 ? (
                  <div className="py-8 text-center text-gray-400 text-xs">暂无未掌握题目，太棒了！🎉</div>
                ) : (
                  <div className="max-h-64 overflow-y-auto custom-scrollbar divide-y divide-red-50">
                    {weaknesses.map(q => (
                      <div key={q.record_id} className="flex items-center gap-2 px-4 py-2.5 hover:bg-red-50/50 transition-colors group">
                        <p className="text-xs text-gray-800 flex-1 leading-relaxed line-clamp-2">{q.question}</p>
                        <Button size="sm" variant="ghost" onClick={() => { setActiveDrillQuestion(q); setActiveTab("practice") }} className="h-7 w-7 p-0 shrink-0 text-red-400 hover:text-red-600 hover:bg-red-100 opacity-60 group-hover:opacity-100 transition-opacity" title="单点爆破此弱项"><Target className="w-3.5 h-3.5"/></Button>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-orange-100 bg-gradient-to-br from-orange-50/30 via-white to-amber-50/20 shadow-sm flex flex-col">
              <CardHeader className="py-2.5 px-4 border-b border-orange-100 shrink-0">
                <CardTitle className="text-sm text-orange-800 flex items-center gap-1.5"><Flame className="w-3.5 h-3.5 text-orange-500"/> 🔥 高频靶场 Top 20</CardTitle>
              </CardHeader>
              <CardContent className="p-0 flex-1 overflow-y-auto custom-scrollbar min-h-[300px] max-h-[500px]">
                {topFreq.length === 0 ? (
                  <div className="py-8 text-center text-gray-400 text-xs">暂无高频题目数据</div>
                ) : (
                  <div className="divide-y divide-orange-50">
                    {topFreq.map((q, i) => (
                      <div key={q.record_id} className="flex items-center gap-2 px-4 py-2.5 hover:bg-orange-50/50 transition-colors group">
                        <span className={`text-[10px] font-bold w-5 text-center shrink-0 ${i < 3 ? "text-orange-600" : "text-gray-400"}`}>{i + 1}</span>
                        <p className="text-xs text-gray-800 flex-1 leading-relaxed line-clamp-2">{q.question}</p>
                        {q.frequency > 0 && <span className="text-[10px] text-orange-500 font-medium shrink-0">×{q.frequency}</span>}
                        <button onClick={() => { setActiveDrillQuestion(q); setActiveTab("practice") }} className="shrink-0 text-orange-400 hover:text-orange-600 opacity-60 group-hover:opacity-100 transition-opacity" title="🔥 开启单点爆破"><Flame className="w-3.5 h-3.5"/></button>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
