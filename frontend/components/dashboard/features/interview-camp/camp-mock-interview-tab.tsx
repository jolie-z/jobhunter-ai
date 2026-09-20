import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Mic, Play, X, Flame } from "lucide-react"
import { useEffect, useRef } from "react"
import type { JobData } from "@/types/job"
import type { QuestionItem } from "@/hooks/use-question-bank"

interface CampMockInterviewTabProps {
  activeJob: JobData | undefined
  activeDrillQuestion: QuestionItem | null
  setActiveDrillQuestion: (q: QuestionItem | null) => void
  interviewMode: string
  setInterviewMode: (mode: "hr" | "business" | "boss") => void
  isCoachMode: boolean
  setIsCoachMode: (mode: boolean) => void
  isInterviewing: boolean
  isPaused: boolean
  chatLog: { role: 'ai' | 'user'; text: string }[]
  startInterview: () => void
  stopInterview: () => void
  togglePause: () => void
}

export function CampMockInterviewTab({
  activeJob,
  activeDrillQuestion,
  setActiveDrillQuestion,
  interviewMode,
  setInterviewMode,
  isCoachMode,
  setIsCoachMode,
  isInterviewing,
  isPaused,
  chatLog,
  startInterview,
  stopInterview,
  togglePause
}: CampMockInterviewTabProps) {
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [chatLog])

  return (
    <div className="flex-1 m-0 flex flex-col justify-center overflow-hidden min-h-0 relative bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-blue-50 via-white to-white">
      {activeDrillQuestion ? (
        <div className="absolute top-4 left-6 right-6 flex items-center justify-between gap-4 bg-gradient-to-r from-red-500 via-orange-500 to-red-600 text-white px-4 py-3 rounded-xl shadow-lg z-20 animate-in fade-in slide-in-from-top-2">
          <div className="flex items-center gap-3 min-w-0">
            <Flame className="w-5 h-5 shrink-0 animate-pulse"/>
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-wider opacity-90">🔥 地狱专项特训中</p>
              <p className="text-sm font-semibold truncate">{activeDrillQuestion.question}</p>
            </div>
          </div>
          <Button
            size="sm" variant="ghost"
            onClick={() => setActiveDrillQuestion(null)}
            disabled={isInterviewing}
            className="shrink-0 h-8 px-3 bg-white/15 hover:bg-white/25 text-white text-xs font-bold rounded-lg gap-1 backdrop-blur-sm"
          >
            <X className="w-3.5 h-3.5"/> 退出特训
          </Button>
        </div>
      ) : (
        <div className="absolute top-4 right-6 flex items-center space-x-4 bg-white p-2 rounded-xl border shadow-sm z-20">
          <div className="flex items-center gap-1 border-r border-gray-100 pr-4">
            <Button variant="ghost" size="sm" onClick={() => setInterviewMode("business")} className={`text-xs px-3 h-8 rounded-lg transition-all ${interviewMode === "business" ? "bg-blue-50 text-blue-700 font-bold shadow-sm" : "text-gray-500 hover:bg-gray-50"}`}>业务线高压面</Button>
            <Button variant="ghost" size="sm" onClick={() => setInterviewMode("boss")} className={`text-xs px-3 h-8 rounded-lg transition-all ${interviewMode === "boss" ? "bg-purple-50 text-purple-700 font-bold shadow-sm" : "text-gray-500 hover:bg-gray-50"}`}>大老板宏观面</Button>
            <Button variant="ghost" size="sm" onClick={() => setInterviewMode("hr")} className={`text-xs px-3 h-8 rounded-lg transition-all ${interviewMode === "hr" ? "bg-pink-50 text-pink-700 font-bold shadow-sm" : "text-gray-500 hover:bg-gray-50"}`}>HRBP 行为面</Button>
          </div>
          <div className="flex items-center gap-3 pl-2 pr-2">
            <div className="flex flex-col items-end">
              <Label htmlFor="mode-switch" className="text-sm font-bold text-gray-800">{isCoachMode ? "教练陪跑模式" : "全真模拟实战"}</Label>
              <span className="text-xs text-muted-foreground mt-0.5">{isCoachMode ? "逐题反馈与纠偏打分" : "极度压迫无反馈连问"}</span>
            </div>
            <Switch id="mode-switch" checked={isCoachMode} onCheckedChange={setIsCoachMode} className="data-[state=checked]:bg-blue-600" />
          </div>
        </div>
      )}

      {/* 实战控制台 */}
      <div className="flex flex-col mx-auto w-full max-w-2xl h-full py-4 relative">
        <div className="flex flex-col items-center shrink-0 mb-6 mt-4">
          <div className={`w-24 h-24 rounded-full flex items-center justify-center transition-all duration-500 border-4 shadow-xl ${isInterviewing ? "bg-red-100 border-red-50 animate-pulse ring-4 ring-red-200" : "bg-blue-100 border-blue-50"}`}>
            <Mic size={32} className={isInterviewing ? "text-red-600" : "text-blue-600"}/>
          </div>
          <h2 className="text-xl font-bold mt-4 mb-1 text-gray-800">
            {isInterviewing ? "面试进行中，面试官正在倾听..." : `即将对决：${activeJob?.companyName} 面试官`}
          </h2>
        </div>

        <div className="flex-1 min-h-0 bg-gray-50/50 rounded-2xl border border-gray-100 shadow-inner p-4 overflow-y-auto space-y-4 mb-6 custom-scrollbar">
          {chatLog.length === 0 ? (
            <div className="h-full flex items-center justify-center text-sm text-gray-400">字幕与复核区域...</div>
          ) : (
            chatLog.map((msg, idx) => (
              <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed shadow-sm ${msg.role === 'user' ? 'bg-blue-600 text-white rounded-tr-sm' : 'bg-white border border-gray-200 text-gray-800 rounded-tl-sm'}`}>
                  {msg.text}
                </div>
              </div>
            ))
          )}
          <div ref={chatEndRef} className="h-1" />
        </div>

        <div className="shrink-0 flex justify-center gap-4">
          {!isInterviewing ? (
            <Button onClick={startInterview} size="lg" className="w-64 gap-2 text-base h-12 rounded-full shadow-lg bg-blue-600 hover:bg-blue-700 text-white transition-all hover:scale-105">
              <Play className="h-4 w-4 fill-current" /> 连接语音，开始面试
            </Button>
          ) : (
            <>
              <Button onClick={togglePause} variant="outline" size="lg" className={`w-32 gap-2 text-base h-12 rounded-full shadow-lg transition-all ${isPaused ? 'bg-amber-100 border-amber-300 text-amber-700' : ''}`}>
                {isPaused ? <Play className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                {isPaused ? "继续面试" : "暂停面试"}
              </Button>
              <Button onClick={stopInterview} variant="destructive" size="lg" className="w-32 gap-2 text-base h-12 rounded-full shadow-lg transition-all">
                <X className="h-4 w-4" /> 结束面试
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
