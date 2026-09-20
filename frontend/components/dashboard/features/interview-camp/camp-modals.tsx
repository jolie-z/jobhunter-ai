import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Spinner } from "@/components/ui/spinner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { X, FileText, LayoutList, ExternalLink, Calendar, MapPin, Activity, FileSearch, Sparkles } from "lucide-react"
import ReactMarkdown from "react-markdown"
import type { JobData } from "@/types/job"

const GRADE_STYLE: Record<string, { bg: string; ring: string; label: string; desc: string }> = {
  A: { bg: "from-yellow-400 to-orange-500", ring: "ring-yellow-400", label: "A", desc: "顶级匹配" },
  B: { bg: "from-emerald-400 to-teal-500", ring: "ring-emerald-400", label: "B", desc: "良好匹配" },
  C: { bg: "from-blue-400 to-indigo-500", ring: "ring-blue-400", label: "C", desc: "一般匹配" },
  D: { bg: "from-orange-400 to-red-400", ring: "ring-orange-400", label: "D", desc: "较差匹配" },
  F: { bg: "from-gray-300 to-gray-400", ring: "ring-gray-300", label: "F", desc: "不匹配" },
}

const DIM_CONFIG = [
  { key: "roleMatch" as const,     label: "角色匹配", tag: "核心", dot: "bg-purple-500" },
  { key: "skillsAlign" as const,   label: "技能重合", tag: "核心", dot: "bg-purple-500" },
  { key: "seniority" as const,     label: "职级资历", tag: "高权", dot: "bg-amber-500" },
  { key: "compensation" as const,  label: "薪资契合", tag: "高权", dot: "bg-amber-500" },
  { key: "interviewProb" as const, label: "面试概率", tag: "高权", dot: "bg-amber-500" },
  { key: "companyStage" as const,  label: "公司阶段", tag: "中权", dot: "bg-blue-500" },
  { key: "marketFit" as const,     label: "赛道前景", tag: "中权", dot: "bg-blue-500" },
  { key: "growth" as const,        label: "成长空间", tag: "中权", dot: "bg-blue-500" },
]

const BASE_INTERVIEW_ROUNDS = ["一面", "二面", "三面", "终面", "HR面", "笔试", "机考"]

// 🌟 Q-M8-2：跟进状态可能是 Offer/待面试 等非轮次值。不在轮次清单时追加「当前状态」选项，
// 避免 select 静默回退显示「一面」误导用户（不触碰下拉保存时保持原状态不变）。
function scheduleRoundOptions(current: string): { value: string; label: string }[] {
  const options = BASE_INTERVIEW_ROUNDS.map(s => ({ value: s, label: s }))
  if (current && !BASE_INTERVIEW_ROUNDS.includes(current)) {
    options.unshift({ value: current, label: `${current}（当前状态，保存不变更）` })
  }
  return options
}

export function splitTagString(input: any): string[] {
  if (Array.isArray(input)) {
    const allTags = input.flatMap((item) => splitTagString(item))
    return Array.from(new Set(allTags))
  }
  if (!input || typeof input !== "string") return []
  return Array.from(new Set(input.split(/[\r\n,，、;；/|]+/).map((item) => item.trim()).filter(Boolean)))
}

export function cleanResumeMarkdown(text: string): string {
  if (!text) return ""
  let res = text
  res = res.replace(/\*\*\*\*/g, "\n\n")
  res = res.replace(/^(#\s+.*)$/gm, "\n\n$1\n\n")
  res = res.replace(/\s*·\s*/g, " \u00A0\u00A0·\u00A0\u00A0 ")
  res = res.replace(/\n{3,}/g, "\n\n")
  return res.trim()
}

export function formatDateMaybeTimestamp(value: string | number): string {
  if (!value) return "-"
  const ts = Number(value)
  if (!Number.isNaN(ts) && ts > 100000000000) {
    return new Date(Number(ts)).toLocaleDateString("zh-CN")
  }
  return String(value) || "-"
}

function AiGradeDashboard({ job }: { job: JobData }) {
  const grade = job.grade ?? ""
  const gs = GRADE_STYLE[grade]
  const rawTotal = DIM_CONFIG.reduce((s, d) => s + (Number(job[d.key]) || 0), 0)

  return (
    <div className="space-y-4">
      <div className={`flex items-center gap-4 p-4 rounded-xl bg-gradient-to-r ${gs ? gs.bg : "from-gray-100 to-gray-200"} shadow-sm`}>
        <div className={`h-16 w-16 rounded-xl bg-white/20 flex items-center justify-center font-black text-4xl text-white shadow-inner ring-4 ${gs ? gs.ring : "ring-gray-300"}`}>
          {gs ? gs.label : "?"}
        </div>
        <div>
          <p className="text-white font-bold text-lg tracking-wide">{gs ? gs.desc : "暂未评估"}</p>
          <p className="text-white/90 text-sm font-medium mt-1">{rawTotal > 0 ? `AI 智能评分综合 ${rawTotal}/40 分` : "等待 AI 评估"}</p>
        </div>
      </div>
      {rawTotal > 0 && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 bg-white p-4 rounded-xl border shadow-sm">
          {DIM_CONFIG.map((d) => {
            const score = Number(job[d.key]) || 0
            return (
              <div key={d.key} className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-700">{d.label}</span>
                  <span className={`text-[10px] px-1.5 rounded-sm font-bold ${
                    d.tag === "核心" ? "bg-purple-100 text-purple-700" :
                    d.tag === "高权" ? "bg-amber-100 text-amber-700" :
                    d.tag === "中权" ? "bg-blue-100 text-blue-700" :
                    "bg-gray-100 text-gray-500"
                  }`}>{d.tag}</span>
                </div>
                <div className="flex gap-1">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <div key={i} className={`h-2 flex-1 rounded-full ${i <= score ? d.dot : "bg-gray-100"}`} />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

interface CampModalsProps {
  modalType: "resume" | "jd" | "report" | "schedule" | null
  setModalType: (type: "resume" | "jd" | "report" | "schedule" | null) => void
  activeJob: JobData | undefined
  scheduleForm: { time: string; location: string; status: string }
  setScheduleForm: React.Dispatch<React.SetStateAction<{ time: string; location: string; status: string }>>
  isSavingSchedule: boolean
  handleSaveSchedule: () => void
}

export function CampModals({
  modalType,
  setModalType,
  activeJob,
  scheduleForm,
  setScheduleForm,
  isSavingSchedule,
  handleSaveSchedule
}: CampModalsProps) {
  if (!modalType) return null

  // qaReport 可能是非法 JSON 字符串（如旧的纯文本存档），直接 parse 会炸掉整个弹窗
  let safeQaReport: any = {}
  try {
    safeQaReport = typeof activeJob?.qaReport === 'string' && activeJob.qaReport
      ? JSON.parse(activeJob.qaReport).match_verification || {}
      : (activeJob?.qaReport as any)?.match_verification || {}
  } catch {
    safeQaReport = {}
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      
      {/* 1. 简历 */}
      {modalType === 'resume' && (
        <div className="bg-gray-100 rounded-xl shadow-2xl w-full max-w-4xl h-[95vh] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
          <div className="p-4 border-b flex justify-between items-center bg-white shrink-0">
            <h3 className="font-bold text-lg text-gray-800 flex items-center gap-2"><FileText className="w-5 h-5 text-blue-600"/> 我投递的简历（人工精修最终版）</h3>
            <Button variant="ghost" size="icon" onClick={() => setModalType(null)}><X size={20}/></Button>
          </div>
          <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
            <div className="max-w-[794px] mx-auto bg-white min-h-[1123px] p-12 shadow-xl border border-gray-200 rounded-sm font-sans text-[13px] leading-relaxed text-gray-800 prose prose-sm max-w-none">
              <ReactMarkdown
                components={{
                  h1: ({node, ...props}: any) => <h1 className="text-[16px] font-black text-black mt-6 mb-3 pb-1.5 border-b-[2px] border-black tracking-widest uppercase" {...props} />,
                  h2: ({node, ...props}: any) => <h2 className="text-[14px] font-bold text-gray-900 mt-5 mb-2" {...props} />,
                  strong: ({node, ...props}: any) => <strong className="font-bold text-black" {...props} />,
                  p: ({node, children, ...props}: any) => <p className="my-1.5 leading-relaxed break-words text-justify" {...props}>{children}</p>
                }}
              >
                {cleanResumeMarkdown(activeJob?.manualRefinedResume || activeJob?.latestResumeText || "> 暂无精修简历数据")}
              </ReactMarkdown>
            </div>
          </div>
        </div>
      )}

      {/* 2. JD */}
      {modalType === 'jd' && (
         <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
           <div className="p-4 border-b flex justify-between items-center bg-gray-50 shrink-0">
             <h3 className="font-bold text-gray-800 flex items-center gap-2"><LayoutList className="w-5 h-5 text-purple-600"/> 目标岗位全景档案</h3>
             <Button variant="ghost" size="icon" onClick={() => setModalType(null)}><X size={20}/></Button>
           </div>
           <div className="p-6 overflow-y-auto bg-gray-50 flex-1 space-y-5 custom-scrollbar">
             <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-100">
                <h4 className="font-bold text-gray-900 mb-4 border-l-4 border-blue-600 pl-2 text-sm">基础信息</h4>
                <div className="grid grid-cols-3 gap-y-4 gap-x-6">
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">公司名称</span><span className="text-[13px] font-medium text-gray-900">{activeJob?.companyName || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">岗位名称</span><span className="text-[13px] font-medium text-gray-900">{activeJob?.jobTitle || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">薪资</span><span className="text-[13px] font-bold text-orange-600">{activeJob?.salary || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">城市</span><span className="text-[13px] font-medium text-gray-900">{activeJob?.location || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">经验要求</span><span className="text-[13px] font-medium text-gray-900">{activeJob?.experience || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">学历要求</span><span className="text-[13px] font-medium text-gray-900">{activeJob?.education || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">所属行业</span><span className="text-[13px] font-medium text-gray-900">{activeJob?.industry || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">公司规模</span><span className="text-[13px] font-medium text-gray-900">{activeJob?.companyScale || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">数据来源</span><span className="text-[13px] font-medium text-blue-600">{activeJob?.platform || "-"}</span></div>
                </div>
             </div>

             <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-100">
                <h4 className="font-bold text-gray-900 mb-4 border-l-4 border-amber-500 pl-2 text-sm">寻访与溯源</h4>
                <div className="grid grid-cols-3 gap-y-4 gap-x-6">
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">发布人角色</span><span className={`text-[13px] font-medium ${activeJob?.role === '猎头' ? 'text-orange-600' : 'text-green-600'}`}>{activeJob?.role || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">HR活跃度</span><span className="text-[13px] font-medium text-gray-900">{activeJob?.hrActivity || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">发布日期</span><span className="text-[13px] font-medium text-gray-900">{activeJob?.publishDate || "-"}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">抓取入库时间</span><span className="text-[13px] font-medium text-gray-900">{formatDateMaybeTimestamp(activeJob?.captureTime || "-")}</span></div>
                  <div className="flex flex-col gap-1"><span className="text-xs text-gray-500">实际投递日期</span><span className="text-[13px] font-medium text-gray-900">{formatDateMaybeTimestamp(activeJob?.applyDate || "-")}</span></div>
                  <div className="flex flex-col gap-1">
                    <span className="text-xs text-gray-500">岗位直达链接</span>
                    {activeJob?.directLink && activeJob.directLink !== "#" ? (
                      <a href={activeJob.directLink} target="_blank" rel="noopener noreferrer" className="text-[13px] font-medium text-blue-600 hover:underline flex items-center gap-1">点击跳转原文 <ExternalLink size={12}/></a>
                    ) : <span className="text-[13px] text-gray-400">暂无</span>}
                  </div>
                </div>
                
                <div className="mt-5 pt-4 border-t border-dashed border-gray-200 space-y-3">
                   {splitTagString(activeJob?.hrSkills).length > 0 && (
                     <div>
                       <span className="text-xs text-gray-500 mr-2 block mb-1.5">HR 圈定技能标签:</span>
                       <div className="flex flex-wrap gap-1.5">{splitTagString(activeJob?.hrSkills).map((s, i) => <Badge key={i} className="text-[10px] bg-blue-50 text-blue-700 hover:bg-blue-100">{s}</Badge>)}</div>
                     </div>
                   )}
                   {splitTagString(activeJob?.benefits).length > 0 && (
                     <div className="mt-3">
                       <span className="text-xs text-gray-500 mr-2 block mb-1.5">企业福利标签:</span>
                       <div className="flex flex-wrap gap-1.5">{splitTagString(activeJob?.benefits).map((b, i) => <Badge key={i} className="text-[10px] bg-green-50 text-green-700 hover:bg-green-100">{b}</Badge>)}</div>
                     </div>
                   )}
                </div>
             </div>

             <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-100">
               <h4 className="font-bold text-gray-900 mb-4 border-l-4 border-purple-600 pl-2 text-sm">岗位描述全文 (JD)</h4>
               <div className="whitespace-pre-wrap text-[13px] text-gray-700 leading-relaxed font-sans bg-gray-50/50 p-4 rounded-lg border border-gray-100">
                 {activeJob?.jdText || activeJob?.jobDescription || "暂无描述"}
               </div>
             </div>
           </div>
         </div>
      )}
    
      {/* 3. 日程管理 */}
      {modalType === 'schedule' && (
        <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
          <div className="p-4 border-b flex justify-between items-center bg-amber-50 shrink-0">
            <h3 className="font-bold text-gray-800 flex items-center gap-2"><Calendar className="w-5 h-5 text-amber-600"/> 预约面试日程</h3>
            <Button variant="ghost" size="icon" onClick={() => setModalType(null)}><X size={20}/></Button>
          </div>
          <div className="p-6 space-y-4">
            <div className="space-y-2">
              <Label className="text-xs font-bold text-gray-700">面试轮次</Label>
              <select value={scheduleForm.status} onChange={(e) => setScheduleForm(prev => ({...prev, status: e.target.value}))} className="w-full text-sm border border-gray-300 rounded-lg p-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white">
                {scheduleRoundOptions(scheduleForm.status).map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-bold text-gray-700">面试时间</Label>
              <input type="datetime-local" value={scheduleForm.time} onChange={(e) => setScheduleForm(prev => ({...prev, time: e.target.value}))} className="w-full text-sm border border-gray-300 rounded-lg p-2 focus:outline-none focus:ring-2 focus:ring-blue-500"/>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <Label className="text-xs font-bold text-gray-700">面试地点</Label>
                <Button variant="ghost" size="sm" className="h-6 text-[11px] text-blue-600 hover:text-blue-700 hover:bg-blue-50 px-2 font-medium"
                  onClick={() => {
                    if (!activeJob) return
                    const city = activeJob.location && activeJob.location !== "未知城市" && activeJob.location !== "-" ? activeJob.location : ""
                    const workAddress = (activeJob as any).work_address || (activeJob as any).workAddress || ""
                    if (!workAddress) return alert("飞书总表中该岗位的【工作地址】为空，请手动输入或先在飞书补充。")
                    let finalAddress = workAddress
                    if (city && !workAddress.includes(city)) finalAddress = `${city}${workAddress}`
                    setScheduleForm(prev => ({...prev, location: finalAddress}))
                  }}
                >
                  <MapPin className="w-3 h-3 mr-1"/> 自动提取岗位地址
                </Button>
              </div>
              <Textarea value={scheduleForm.location} onChange={(e) => setScheduleForm(prev => ({...prev, location: e.target.value}))} placeholder="请输入准确的面试地点（可点击右上方自动提取）" className="min-h-[80px] text-sm resize-none"/>
            </div>
            <div className="bg-blue-50 text-blue-700 text-xs p-3 rounded-lg flex gap-2">
              <Activity className="w-4 h-4 shrink-0"/>
              <p>保存后将把所选面试轮次与日程同步至飞书跟进状态。你可以前往飞书利用【自动化工作流】实现提前24小时消息提醒。</p>
            </div>
          </div>
          <div className="p-4 border-t bg-gray-50 flex justify-end gap-3">
            <Button variant="outline" size="sm" onClick={() => setModalType(null)}>取消</Button>
            <Button size="sm" className="bg-blue-600 hover:bg-blue-700 text-white" onClick={handleSaveSchedule} disabled={isSavingSchedule}>
              {isSavingSchedule ? <><Spinner className="w-3.5 h-3.5 mr-1"/> 保存并同步中...</> : "💾 保存并同步飞书"}
            </Button>
          </div>
        </div>
      )}

      {/* 4. 评估报告 */}
      {modalType === 'report' && (
        <div className="bg-gray-50 rounded-xl shadow-2xl w-full max-w-4xl h-[90vh] flex flex-col overflow-hidden">
          <div className="p-4 border-b flex justify-between items-center bg-white shrink-0">
            <h3 className="font-bold text-lg text-gray-800 flex items-center gap-2"><FileSearch className="w-5 h-5 text-emerald-600"/> 简历多维评估与深度报告</h3>
            <Button variant="ghost" size="icon" onClick={() => setModalType(null)}><X size={20}/></Button>
          </div>
          <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
            <h3 className="text-xl font-bold text-gray-800 flex items-center gap-2"><Activity className="text-blue-500 w-5 h-5"/> 初步 10 维度评估诊断</h3>
            {activeJob ? <AiGradeDashboard job={activeJob} /> : null}

            <h3 className="text-xl font-bold text-gray-800 flex items-center gap-2 pt-4 border-t"><Sparkles className="text-purple-500 w-5 h-5"/> AI 深度评估报告</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-4">
                <Card className="border-indigo-200 bg-indigo-50/50 h-full shadow-sm">
                  <CardHeader className="pb-2"><CardTitle className="text-sm text-indigo-800">🎯 理想画像与能力信号</CardTitle></CardHeader>
                  <CardContent className="text-xs text-gray-700 whitespace-pre-wrap">{activeJob?.dreamPicture || "暂无数据"}</CardContent>
                </Card>
              </div>
              <div className="space-y-4">
                <Card className="border-teal-200 bg-teal-50/50 h-full shadow-sm">
                  <CardHeader className="pb-2"><CardTitle className="text-sm text-teal-800">📚 核心能力词典 (ATS)</CardTitle></CardHeader>
                  <CardContent className="text-xs text-gray-700 whitespace-pre-wrap">{activeJob?.atsAbilityAnalysis?.replace(/(?:[,，。;；]?\s*)(必考词|加分词|词汇重合度|缺失核心词|表达错位)/g, '\n$1') || "暂无数据"}</CardContent>
                </Card>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <Card className="border-emerald-200 bg-emerald-50/50 shadow-sm">
                <CardHeader className="pb-2"><CardTitle className="text-sm text-emerald-800">✅ 高杠杆匹配点</CardTitle></CardHeader>
                <CardContent className="text-xs text-gray-700 whitespace-pre-wrap">{activeJob?.strongFitAssessment || "暂无数据"}</CardContent>
              </Card>
              <Card className="border-red-200 bg-red-50/50 shadow-sm">
                <CardHeader className="pb-2"><CardTitle className="text-sm text-red-800">⚠️ 致命硬伤与毒点</CardTitle></CardHeader>
                <CardContent className="text-xs text-gray-700 whitespace-pre-wrap">{activeJob?.riskRedFlags?.replace(/\s*(恶劣后果(?:：|:)?)/g, '\n\n$1') || "暂无数据"}</CardContent>
              </Card>
            </div>

            <Card className="border-blue-200 bg-blue-50/50 shadow-sm">
              <CardHeader className="pb-2"><CardTitle className="text-sm text-blue-800">🚀 破局行动计划</CardTitle></CardHeader>
              <CardContent className="text-xs text-gray-700 whitespace-pre-wrap">{activeJob?.deepActionPlan?.replace(/\s*(项目重新包装(?:：|:)?)/g, '\n\n$1') || "暂无数据"}</CardContent>
            </Card>

            <h3 className="text-xl font-bold text-gray-800 flex items-center gap-2 pt-4 border-t"><FileSearch className="text-amber-500 w-5 h-5"/> 二次质检报告 (QA)</h3>
            <div className="bg-white p-5 rounded-xl border shadow-sm space-y-4">
              {safeQaReport.achieved_points ? (
                <>
                  <div>
                    <h4 className="text-sm font-bold text-green-700 mb-2">✅ 已达成匹配点</h4>
                    <ul className="text-xs text-gray-600 space-y-1 list-disc pl-4">{safeQaReport.achieved_points.map((p:string, i:number)=><li key={i}>{p}</li>)}</ul>
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-red-600 mt-4 mb-2">🚨 缺失或存疑点</h4>
                    <ul className="text-xs text-gray-600 space-y-1 list-disc pl-4">{safeQaReport.missing_points?.map((p:string, i:number)=><li key={i}>{p}</li>)}</ul>
                  </div>
                </>
              ) : (
                <p className="text-sm text-gray-500">暂无质检数据，请在沉浸工作台执行 AI 质检。</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
