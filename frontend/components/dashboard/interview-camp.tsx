"use client"

import { useMemo, useState, useEffect } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { BookOpen, Mic, FileText, Swords, Calendar, MapPin, LayoutList, FileSearch, Zap, Activity, Play, X, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import type { JobData } from "@/types/job"

import { CampSidebar } from "./features/interview-camp/camp-sidebar"
import { CampIntelTab } from "./features/interview-camp/camp-intel-tab"
import { CampMockInterviewTab } from "./features/interview-camp/camp-mock-interview-tab"
import { CampHistoryTab } from "./features/interview-camp/camp-history-tab"
import { CampLiveRecordTab } from "./features/interview-camp/camp-live-record-tab"
import { CampQuestionBankTab } from "./features/interview-camp/camp-question-bank-tab"
import { CampModals } from "./features/interview-camp/camp-modals"

import { useInterviewSchedule } from "../../hooks/use-interview-schedule"
import { useInterviewIntel } from "../../hooks/use-interview-intel"
import { useQuestionBank } from "../../hooks/use-question-bank"
import { useInterviewVoice } from "../../hooks/use-interview-voice"
import { useJobDetail } from "../../hooks/use-job-detail"

export function InterviewCamp({ jobs }: { jobs: JobData[] }) {
  // 🌟 必须 memo：若每次渲染都生成新数组，下方 activeJob 的 useMemo 会跟着每次重算，
  // 导致 useInterviewVoice 的同步 effect 无限触发（Maximum update depth exceeded + 输入被回退）
  const interviewJobs = useMemo(() => (
    jobs ? jobs.filter(j =>
      ["待面试","一面", "二面", "三面", "Offer", "已下发Offer"].includes(j.followStatus?.trim() || "")
    ) : []
  ), [jobs])

  const [activeJobId, setActiveJobId] = useState(interviewJobs[0]?.id || "")
  const [activeTab, setActiveTab] = useState("intel")
  const [showList, setShowList] = useState(true)
  const [interviewMode, setInterviewMode] = useState<"hr" | "business" | "boss">("business")
  const [isCoachMode, setIsCoachMode] = useState(true)

  // 🌟 若首次加载时 jobs 尚未就绪，当数据到达时自动补选首个待战岗位
  useEffect(() => {
    if (!activeJobId && interviewJobs.length > 0) {
      setActiveJobId(interviewJobs[0].id)
    }
  }, [interviewJobs, activeJobId])

  // 🌟 列表数据已瘦身，当前训练的岗位按需拉取大文本详情（面试记录/简历QA等）叠加上去
  const activeJobDetail = useJobDetail(activeJobId, true)
  const activeJob = useMemo(() => {
    const base = interviewJobs.find((j) => j.id === activeJobId)
    if (!base) return undefined
    return activeJobDetail && activeJobDetail.id === activeJobId ? { ...base, ...activeJobDetail } : base
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interviewJobs, activeJobId, activeJobDetail])

  // 1. Schedule & Modals Hook
  const {
    displayTime,
    displayLocation,
    shouldShowAmapNav,
    scheduleForm,
    setScheduleForm,
    isSavingSchedule,
    modalType,
    setModalType,
    openScheduleModal,
    handleSaveSchedule
  } = useInterviewSchedule(activeJob)

  // 2. Intel Hook
  const { loadingStates, intelData, fetchFullIntel } = useInterviewIntel(activeJobId, activeJob)

  // 3. Question Bank Hook（入参是 activeTab：切到「专属面经库」时自动拉取题库）
  const qb = useQuestionBank(activeTab)

  // 4. Voice & Mock Interview Hook
  const v = useInterviewVoice(activeJobId, activeJob, intelData, qb.activeDrillQuestion, interviewMode, isCoachMode)

  return (
    <div className="h-full flex p-4 overflow-hidden bg-muted/20 gap-4">
      {/* L1: 折叠式侧边栏 */}
      <CampSidebar
        interviewJobs={interviewJobs}
        activeJobId={activeJobId}
        setActiveJobId={setActiveJobId}
        activeJob={activeJob}
        showList={showList}
        setShowList={setShowList}
      />

      {/* L2: 核心工作区 */}
      <div className="flex-1 flex flex-col h-full bg-card rounded-xl border shadow-sm overflow-hidden min-w-0">
        <div className="p-3 border-b bg-white shrink-0">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-bold tracking-tight text-gray-900 truncate">
              {activeJob?.companyName} <span className="font-normal text-gray-300 mx-2">|</span> {activeJob?.jobTitle}
            </h1>
            <div 
              onClick={openScheduleModal}
              className="flex items-center gap-1.5 bg-amber-50 text-amber-700 px-2.5 py-1 rounded-md border border-amber-200 hover:bg-amber-100 transition-colors shadow-sm cursor-pointer"
            >
              <Calendar className="w-3.5 h-3.5"/>
              <span className="text-[11px] font-bold">面试时间:</span>
              <span className="text-[11px] font-bold">{displayTime ? displayTime.replace('T', ' ') : "未设置"}</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 mt-3">
            <Button size="sm" variant="outline" className="h-7 text-xs bg-blue-50/50 hover:bg-blue-100 border-blue-200 text-blue-700 font-medium" onClick={() => setModalType('resume')}>
              <FileText className="w-3.5 h-3.5 mr-1"/> 我投递的简历
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs bg-purple-50/50 hover:bg-purple-100 border-purple-200 text-purple-700 font-medium" onClick={() => setModalType('jd')}>
              <LayoutList className="w-3.5 h-3.5 mr-1"/> 岗位详细信息
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs bg-emerald-50/50 hover:bg-emerald-100 border-emerald-200 text-emerald-700 font-medium" onClick={() => setModalType('report')}>
              <FileSearch className="w-3.5 h-3.5 mr-1"/> 简历评估报告
            </Button>
            
            <div className="flex-1"></div>
            
            <div 
              onClick={openScheduleModal}
              className="flex items-center gap-1.5 px-2.5 py-1 h-7 text-[11px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-md cursor-pointer hover:bg-gray-100 max-w-[200px]"
              title={displayLocation || "未设置地点，点击编辑"}
            >
              <MapPin className="w-3.5 h-3.5 text-gray-400 shrink-0"/>
              <span className="truncate">{displayLocation || "面试地点: 未设置"}</span>
            </div>

            {shouldShowAmapNav && (
              <Button 
                size="sm" variant="ghost" 
                className="h-7 text-xs text-blue-600 hover:bg-blue-50 font-bold" 
                onClick={() => {
                  const cleanedLink = (activeJob as any)?.amapLink || (activeJob as any)?.amap_link || ""
                  const finalUrl = (typeof cleanedLink === "string" && cleanedLink.includes("http"))
                    ? cleanedLink
                    : `https://uri.amap.com/search?keyword=${encodeURIComponent(displayLocation)}`
                  window.open(finalUrl, '_blank')
                }}
              >
                <Zap className="w-3.5 h-3.5 mr-1"/> 开启导航
              </Button>
            )}
          </div>
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col overflow-hidden">
          <TabsList className="grid w-[700px] grid-cols-5 m-4 shrink-0 bg-gray-100/80 p-1 rounded-lg h-8 text-xs">
            <TabsTrigger value="intel" className="gap-2 rounded-lg data-[state=active]:bg-white data-[state=active]:shadow-sm"><BookOpen size={16}/> 面试资料</TabsTrigger>
            <TabsTrigger value="practice" className="gap-2 rounded-lg data-[state=active]:bg-white data-[state=active]:shadow-sm"><Mic size={16}/> 语音对战</TabsTrigger>
            <TabsTrigger value="history" className="gap-2 rounded-lg data-[state=active]:bg-white data-[state=active]:shadow-sm"><FileText size={16}/> 练习记录</TabsTrigger>
            <TabsTrigger value="live_record" className="gap-2 rounded-lg data-[state=active]:bg-white data-[state=active]:shadow-sm"><Swords size={16}/> 现场面经</TabsTrigger>
            <TabsTrigger value="question_bank" className="gap-2 rounded-lg data-[state=active]:bg-white data-[state=active]:shadow-sm"><BookOpen size={16}/> 专属面经库</TabsTrigger>
          </TabsList>

          <TabsContent value="intel" className="flex-1 overflow-y-auto px-6 pb-6 m-0 custom-scrollbar">
            <CampIntelTab loadingStates={loadingStates} intelData={intelData} activeJob={activeJob} fetchFullIntel={fetchFullIntel} />
          </TabsContent>

          <TabsContent value="practice" className="flex-1 m-0 flex flex-col justify-center overflow-hidden min-h-0 relative bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-blue-50 via-white to-white">
            <CampMockInterviewTab
              activeJob={activeJob}
              activeDrillQuestion={qb.activeDrillQuestion}
              setActiveDrillQuestion={qb.setActiveDrillQuestion}
              interviewMode={interviewMode}
              setInterviewMode={setInterviewMode}
              isCoachMode={isCoachMode}
              setIsCoachMode={setIsCoachMode}
              isInterviewing={v.isInterviewing}
              isPaused={v.isPaused}
              chatLog={v.chatLog}
              startInterview={v.startInterview}
              stopInterview={v.stopInterview}
              togglePause={v.togglePause}
            />
          </TabsContent>

          <TabsContent value="history" className="flex-1 overflow-y-auto px-6 pb-6 m-0 custom-scrollbar">
            <CampHistoryTab
              currentTranscript={v.currentTranscript}
              records={v.parsedRecords}
              isRefreshingHistory={v.isRefreshingHistory}
              refreshHistory={v.refreshHistory}
              handleDeleteRecord={v.handleDeleteRecord}
            />
          </TabsContent>

          <TabsContent value="live_record" className="flex-1 overflow-y-auto px-6 pb-6 m-0 custom-scrollbar">
            <CampLiveRecordTab
              isSavingLive={v.isSavingLive}
              saveLiveError={v.saveLiveError}
              handleShredInterview={async () => {
                // 粉碎入库成功后同步刷新本地题库缓存，让「专属面经库」立即可见新题
                const extracted = await v.handleShredInterview()
                if (extracted > 0) qb.fetchQuestions()
              }}
              isShredding={v.isShredding}
              liveRecord={v.liveRecord}
              setLiveRecord={v.setLiveRecord}
              toggleVoiceRecording={v.toggleVoiceRecording}
              isRecording={v.isRecording}
              debouncedSaveLiveFields={v.debouncedSaveLiveFields}
              activeJob={activeJob}
              fetchQuestions={qb.fetchQuestions}
              questions={qb.questions}
              shreddedQuestions={v.shreddedQuestions}
            />
          </TabsContent>

          <TabsContent value="question_bank" className="flex-1 overflow-y-auto px-6 pb-6 m-0 custom-scrollbar">
            <CampQuestionBankTab
              sourceFilter={qb.sourceFilter}
              setSourceFilter={qb.setSourceFilter}
              fetchQuestions={qb.fetchQuestions}
              isLoadingQs={qb.isLoadingQs}
              questions={qb.questions}
              groupedQuestions={qb.groupedQuestions}
              expandedDemo={qb.expandedDemo}
              setExpandedDemo={qb.setExpandedDemo}
              expandedOriginal={qb.expandedOriginal}
              setExpandedOriginal={qb.setExpandedOriginal}
              savingMap={qb.savingMap}
              cycleMastery={qb.cycleMastery}
              setActiveDrillQuestion={qb.setActiveDrillQuestion}
              setActiveTab={setActiveTab}
              deleteQuestion={qb.deleteQuestion}
              masteryColor={qb.masteryColor}
              updateQuestionField={qb.updateQuestionField}
            />
          </TabsContent>
        </Tabs>
      </div>

      {v.endDialogConfig.show && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="p-6 text-center">
              <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <Sparkles className="w-8 h-8 text-blue-600" />
              </div>
              <h3 className="text-xl font-bold text-gray-900 mb-2">🎉 语音对战结束！</h3>
              <p className="text-sm text-gray-500 mb-6">本次对话已结束。你可以选择让 AI 教练对本次表现进行深度复盘诊断，或者仅存档文字稿。</p>
              <div className="space-y-3">
                <Button onClick={() => v.handleSaveTranscript(true)} disabled={v.isSavingRecord} className="w-full bg-blue-600 hover:bg-blue-700 text-white shadow-lg h-12 rounded-xl text-base">
                  {v.isSavingRecord ? <Spinner className="w-4 h-4 mr-2" /> : <Activity className="w-4 h-4 mr-2" />} 生成 AI 深度复盘报告并存档 (推荐)
                </Button>
                <Button onClick={() => v.handleSaveTranscript(false)} disabled={v.isSavingRecord} variant="outline" className="w-full border-gray-200 text-gray-700 hover:bg-gray-50 h-12 rounded-xl text-base">仅保存对话文字稿</Button>
                <Button onClick={() => { v.setEndDialogConfig(prev => ({ ...prev, show: false, transcript: "" })); v.setChatLog([]); }} disabled={v.isSavingRecord} variant="ghost" className="w-full text-red-500 hover:bg-red-50 hover:text-red-600 h-12 rounded-xl text-base">直接丢弃，不保存</Button>
              </div>
            </div>
          </div>
        </div>
      )}

      <CampModals
        modalType={modalType}
        setModalType={setModalType}
        activeJob={activeJob}
        scheduleForm={scheduleForm}
        setScheduleForm={setScheduleForm}
        isSavingSchedule={isSavingSchedule}
        handleSaveSchedule={handleSaveSchedule}
      />
    </div>
  )
}