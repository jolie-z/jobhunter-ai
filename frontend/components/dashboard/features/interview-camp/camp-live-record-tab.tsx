import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Spinner } from "@/components/ui/spinner"
import { Swords, Save, Zap, Mic, MicOff, FileText, FileSearch, Sparkles, BookOpen, AlertCircle, CheckCircle2 } from "lucide-react"
import { useState } from "react"
import type { JobData } from "@/types/job"
import type { QuestionItem } from "@/hooks/use-question-bank"
import { API_BASE } from "@/lib/api"
import { toast } from "@/hooks/use-toast"

interface CampLiveRecordTabProps {
  isSavingLive: boolean
  handleShredInterview: () => void
  isShredding: boolean
  liveRecord: string
  setLiveRecord: (val: string) => void
  toggleVoiceRecording: () => void
  isRecording: boolean
  debouncedSaveLiveFields: (val: string) => void
  activeJob: JobData | undefined
  fetchQuestions: () => void
  questions: QuestionItem[]
  shreddedQuestions: { question: string; answer: string }[]
  saveLiveError?: string | null
}

export function CampLiveRecordTab({
  isSavingLive,
  handleShredInterview,
  isShredding,
  liveRecord,
  setLiveRecord,
  toggleVoiceRecording,
  isRecording,
  debouncedSaveLiveFields,
  activeJob,
  fetchQuestions,
  questions,
  shreddedQuestions,
  saveLiveError
}: CampLiveRecordTabProps) {
  const [newQaTitle, setNewQaTitle] = useState("")
  const [newQaAnswer, setNewQaAnswer] = useState("")
  const [isAddingQa, setIsAddingQa] = useState(false)

  const handleAddQa = async () => {
    if (!newQaTitle.trim()) {
      toast({ title: "⚠️ 提示", description: "问题不能为空，请先输入预测问题。" })
      return
    }
    setIsAddingQa(true)
    try {
      const res = await fetch(`${API_BASE}/api/jobs/add_resume_qa_card`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: activeJob?.id, question: newQaTitle, answer: newQaAnswer })
      })
      if (res.ok) {
        setNewQaTitle("")
        setNewQaAnswer("")
        fetchQuestions()
        toast({ title: "✅ 卡片已入库", description: "预测 QA 卡片已同步至专属面经库。" })
      } else {
        toast({ title: "❌ 添加失败", description: "请检查网络或飞书配置后重试。", variant: "destructive" })
      }
    } catch (e) {
      toast({ title: "❌ 网络异常", description: "请求未能送达后端，请检查网络连接。", variant: "destructive" })
    } finally {
      setIsAddingQa(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 pb-6 m-0 custom-scrollbar">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div>
          <h2 className="text-base font-bold text-amber-900 flex items-center gap-2">
            <Swords className="w-4 h-4 text-amber-600"/> 真实战场复盘 · 双窗面经
          </h2>
          <p className="text-xs text-amber-700/70 mt-0.5">
            左侧记录面试原始流水账（支持语音录入），右侧记录简历准备阶段的 QA 预测题。内容会自动保存到飞书。
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isSavingLive && (
            <span className="flex items-center gap-1 text-[11px] text-blue-600 bg-blue-50 px-2 py-0.5 rounded border border-blue-200 animate-pulse">
              <Save className="w-3 h-3"/> 保存中...
            </span>
          )}
          {saveLiveError && !isSavingLive && (
            <span className="flex items-center gap-1 text-[11px] text-red-600 font-medium bg-red-50 px-2 py-0.5 rounded border border-red-200" title={saveLiveError}>
              <AlertCircle className="w-3 h-3 text-red-500"/> {saveLiveError}
            </span>
          )}
          {!isSavingLive && !saveLiveError && liveRecord && (
            <span className="flex items-center gap-1 text-[11px] text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
              <CheckCircle2 className="w-3 h-3"/> 已自动同步
            </span>
          )}
          <Button
            onClick={handleShredInterview}
            disabled={isShredding || !liveRecord.trim()}
            className="h-9 px-4 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white text-xs font-bold shadow-sm rounded-lg gap-1.5"
          >
            {isShredding ? <><Spinner className="w-3.5 h-3.5"/> 粉碎中...</> : <><Zap className="w-3.5 h-3.5"/> 提取真题并入库</>}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 左窗 */}
        <Card className="border-amber-200 bg-gradient-to-br from-amber-50/40 via-white to-orange-50/20 shadow-sm flex flex-col">
          <CardHeader className="py-2.5 px-4 border-b border-amber-100 bg-amber-50/30 flex flex-row justify-between items-center shrink-0">
            <CardTitle className="text-sm text-amber-900 flex items-center gap-1.5">
              <Swords className="w-3.5 h-3.5 text-amber-600"/> 真实面试复盘
            </CardTitle>
            <button
              onClick={toggleVoiceRecording}
              className={`relative p-2 rounded-full transition-all ${isRecording ? "bg-red-500 text-white shadow-lg shadow-red-200 animate-pulse" : "bg-amber-100 text-amber-700 hover:bg-amber-200"}`}
              title={isRecording ? "点击停止语音录入" : "点击开始语音录入"}
            >
              {isRecording ? <MicOff className="w-4 h-4"/> : <Mic className="w-4 h-4"/>}
              {isRecording && (
                <>
                  <span className="absolute inset-0 rounded-full bg-red-400 animate-ping opacity-30"></span>
                  <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-white"></span>
                </>
              )}
            </button>
          </CardHeader>
          <CardContent className="p-4 flex-1 flex flex-col gap-2">
            {isRecording && (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-red-50 border border-red-200 rounded-lg text-[11px] text-red-700">
                <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>
                语音录入中...说话内容将自动追加到下方文本框
              </div>
            )}
            <Label className="text-[11px] font-bold text-gray-500 flex items-center gap-1">
              <FileText className="w-3 h-3 text-amber-600"/> 面试流水账
            </Label>
            <Textarea
              value={liveRecord}
              onChange={(e) => {
                setLiveRecord(e.target.value)
                debouncedSaveLiveFields(e.target.value)
              }}
              placeholder={"示例：今天 HR 问了我..."}
              className="flex-1 min-h-[300px] text-sm leading-relaxed bg-white border-amber-200 focus-visible:ring-amber-400 rounded-xl shadow-sm"
            />
          </CardContent>
        </Card>

        {/* 右窗 */}
        <Card className="border-violet-200 bg-gradient-to-br from-violet-50/30 via-white to-blue-50/20 shadow-sm flex flex-col">
          <CardHeader className="py-2.5 px-4 border-b border-violet-100 bg-violet-50/30 shrink-0">
            <CardTitle className="text-sm text-violet-900 flex items-center gap-1.5">
              <FileSearch className="w-3.5 h-3.5 text-violet-600"/> 简历专项预测 QA
            </CardTitle>
            <CardDescription className="text-[11px] text-violet-600/70 mt-0.5">一题一卡录入，自动携带岗位基因标签直达专属面经库</CardDescription>
          </CardHeader>
          <CardContent className="p-4 flex-1 flex flex-col">
            <div className="flex flex-col gap-3 h-full">
              <div className="space-y-1.5 shrink-0">
                <Label className="text-[11px] font-bold text-violet-700 flex items-center gap-1">
                  <Sparkles className="w-3 h-3"/> 预测问题 (Q)
                </Label>
                <Textarea
                  value={newQaTitle} onChange={e => setNewQaTitle(e.target.value)}
                  placeholder="输入面试官可能会问的问题..."
                  className="min-h-[60px] text-xs resize-none bg-white border-violet-200 focus-visible:ring-violet-400"
                />
              </div>
              <div className="space-y-1.5 flex-1 flex flex-col min-h-[120px]">
                <Label className="text-[11px] font-bold text-violet-700 flex items-center gap-1">
                  <BookOpen className="w-3 h-3"/> 我的回答草稿 (A)
                </Label>
                <Textarea
                  value={newQaAnswer} onChange={e => setNewQaAnswer(e.target.value)}
                  placeholder="输入你准备好的金牌话术..."
                  className="flex-1 text-xs resize-none bg-white border-violet-200 focus-visible:ring-violet-400"
                />
              </div>
              <Button onClick={handleAddQa} disabled={isAddingQa || !newQaTitle.trim()} className="shrink-0 w-full bg-violet-600 hover:bg-violet-700 text-white text-xs font-bold h-8 rounded-lg shadow-sm">
                {isAddingQa ? <Spinner className="w-3.5 h-3.5 mr-1"/> : <Zap className="w-3.5 h-3.5 mr-1"/>}
                封装卡片并直达专属面经库
              </Button>
              <div className="pt-3 border-t border-violet-100 mt-1">
                <p className="text-[11px] text-violet-600 font-medium text-center">
                  已为本岗位准备了 {questions.filter(q => q.source?.includes("简历专项预测") && q.related_jobs?.includes(activeJob?.id || "")).length} 道预测卡片
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {shreddedQuestions.length > 0 && (
        <div className="mt-4 bg-white rounded-xl border border-purple-200 shadow-sm p-4">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="w-4 h-4 text-purple-600"/>
            <h4 className="text-sm font-bold text-purple-900">本次粉碎结果（共 {shreddedQuestions.length} 道真题）</h4>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[360px] overflow-y-auto custom-scrollbar pr-1">
            {shreddedQuestions.map((q, i) => (
              <div key={i} className="border border-gray-100 rounded-lg p-3 bg-gradient-to-r from-purple-50/30 to-blue-50/20 hover:shadow-sm transition-shadow">
                <div className="flex items-start gap-2 mb-1.5">
                  <Badge className="text-[10px] bg-purple-100 text-purple-700 hover:bg-purple-100 shrink-0">Q{i + 1}</Badge>
                  <p className="text-xs font-bold text-gray-900 leading-relaxed">{q.question}</p>
                </div>
                {q.answer && (
                  <p className="text-[11px] text-gray-600 leading-relaxed pl-1 border-l-2 border-amber-300 ml-1 mt-1.5">
                    <span className="font-bold text-amber-700 mr-1">我的回答:</span>{q.answer}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
