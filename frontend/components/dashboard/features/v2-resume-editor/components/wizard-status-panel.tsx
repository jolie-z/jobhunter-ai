import React, { useRef } from "react"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { Target, CheckCircle, Save, Loader2, MapPin, Clock } from "lucide-react"
import { GrillSuggestionPanel, type GrillSuggestion } from "@/components/dashboard/resume-builder/grill-suggestion-panel"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import type { WizardStep, WizardProgress } from "../hooks/use-ai-wizard"
import { DEFAULT_WIZARD_PROGRESS } from "../hooks/use-ai-wizard"

export interface WizardStatusPanelProps {
  wizardStep: WizardStep
  wizardProgress: WizardProgress
  wizardHidden: boolean
  setWizardStep: (step: WizardStep) => void
  setWizardProgress: (fn: React.SetStateAction<WizardProgress>) => void
  setWizardHidden: (hidden: boolean) => void

  grillPanelOpen: boolean
  setGrillPanelOpen: (open: boolean) => void
  grillQueue: string[]
  setGrillQueue: (queue: string[]) => void
  atsQueue: string[]
  syncQueue: string[]

  grillSuggestions: GrillSuggestion[]
  isLoadingGrillSuggestions: boolean
  handleStartGrillQueue: (ids: string[]) => void

  handleSaveResume: () => void
  isSavingResume?: boolean
  wizardStorageKey: string
  saveWizardProgress: (step: WizardStep, progress: WizardProgress) => void

  grillSectionsList: { id: string; title: string; isArchived?: boolean }[]
  sectionTitles: Record<string, string>
  handleLocate: (sectionId: string) => void
}

export function WizardStatusPanel({
  wizardStep, wizardProgress, wizardHidden,
  setWizardStep, setWizardProgress, setWizardHidden,
  grillPanelOpen, setGrillPanelOpen, grillQueue, setGrillQueue, atsQueue, syncQueue,
  grillSuggestions, isLoadingGrillSuggestions, handleStartGrillQueue,
  handleSaveResume, isSavingResume, wizardStorageKey, saveWizardProgress,
  grillSectionsList, sectionTitles, handleLocate
}: WizardStatusPanelProps) {

  // ── 已完成 items 追踪（同步检测，不用 useEffect）──
  // Hooks 必须在提前 return 之前无条件调用（rules-of-hooks）
  const completedRef = useRef<Set<string>>(new Set())
  const prevGrillRef = useRef<string[]>([])
  const prevAtsRef = useRef<string[]>([])
  const prevSyncRef = useRef<string[]>([])
  const prevStepRef = useRef<WizardStep>('idle')

  // 实时判空（零 sticky 状态）：板块空 → 队列显示「已跳过（板块为空）」且门禁放行；
  // 板块由空变非空 → 自动翻回「处理中」并重新锁上门禁，显示永远与事实一致
  const resumeData = useResumeV2Store(state => state.resumeData)
  const hasWork = (resumeData?.workExperience?.length ?? 0) > 0
  const hasProjects = (resumeData?.personalProjects?.length ?? 0) > 0
  // step2 门禁与顶文案共用同一放行条件：空板块天然放行，保证提示与按钮状态永远一致
  const allDraftsDone = (!hasProjects || wizardProgress.initialDraftProjectDone) && (!hasWork || wizardProgress.initialDraftWorkDone)

  if (wizardStep === 'idle' || wizardHidden) return null

  // 步骤切换时清空
  if (prevStepRef.current !== wizardStep) {
    completedRef.current = new Set()
    prevStepRef.current = wizardStep
  }

  // 同步检测从 queue 消失的 item → 标记为 done（在渲染期间执行）
  const goneGrill = prevGrillRef.current.filter(id => !grillQueue.includes(id))
  goneGrill.forEach(id => completedRef.current.add(`grill:${id}`))
  prevGrillRef.current = grillQueue

  const goneAts = prevAtsRef.current.filter(id => !atsQueue.includes(id))
  goneAts.forEach(id => completedRef.current.add(`ats:${id}`))
  prevAtsRef.current = atsQueue

  const goneSync = prevSyncRef.current.filter(id => !syncQueue.includes(id))
  goneSync.forEach(id => completedRef.current.add(`sync:${id}`))
  prevSyncRef.current = syncQueue

  // ── 进度 items 计算 ──────────────────────────────────
  type ItemStatus = "pending" | "processing" | "done" | "skipped"
  interface ProgressItem { id: string; title: string; status: ItemStatus }

  const progressItems: ProgressItem[] = (() => {
    const title = (id: string) => sectionTitles[id] || id

    if (wizardStep === 'step1') {
      // 裁剪/折叠：始终显示两项，根据 flag 判断状态
      const items: ProgressItem[] = []
      items.push({ id: "prune", title: "✂️ 项目裁剪", status: wizardProgress.pruneDone ? "done" : "processing" })
      items.push({ id: "compress", title: "⚖️ 工作经历折叠", status: wizardProgress.compressDone ? "done" : "processing" })
      return items
    }

    if (wizardStep === 'step2') {
      // 初版改写：始终显示两项，实时三态——Done→已完成；!Done 且板块为空→已跳过（板块为空）；否则处理中
      const items: ProgressItem[] = []
      items.push({ id: "draft-work", title: "工作经历初改", status: wizardProgress.initialDraftWorkDone ? "done" : (!hasWork ? "skipped" : "processing") })
      items.push({ id: "draft-project", title: "项目经历初改", status: wizardProgress.initialDraftProjectDone ? "done" : (!hasProjects ? "skipped" : "processing") })
      return items
    }

    if (wizardStep === 'step3') {
      // Grill-me：queue 中的 items + 已完成的 items
      const queueItems: ProgressItem[] = grillQueue.map((id, idx) => ({
        id,
        title: title(id),
        status: (idx === 0 ? "processing" : "pending") as ItemStatus,
      }))
      const doneItems: ProgressItem[] = [...completedRef.current]
        .filter(k => k.startsWith("grill:"))
        .map(k => k.replace("grill:", ""))
        .filter(id => !grillQueue.includes(id))
        .map(id => ({ id, title: title(id), status: "done" as ItemStatus }))
      return [...doneItems, ...queueItems]
    }

    if (wizardStep === 'step4') {
      // ATS 靶向：queue 中的 items + 已完成的 items
      const queueItems: ProgressItem[] = atsQueue.map((id, idx) => ({
        id,
        title: title(id),
        status: (idx < 3 ? "processing" : "pending") as ItemStatus,
      }))
      const doneItems: ProgressItem[] = [...completedRef.current]
        .filter(k => k.startsWith("ats:"))
        .map(k => k.replace("ats:", ""))
        .filter(id => !atsQueue.includes(id))
        .map(id => ({ id, title: title(id), status: "done" as ItemStatus }))
      return [...doneItems, ...queueItems]
    }

    if (wizardStep === 'step5') {
      // 联动更新：queue 中的 items + 已完成的 items
      const queueItems: ProgressItem[] = syncQueue.map((id, idx) => ({
        id,
        title: title(id),
        status: (idx < 3 ? "processing" : "pending") as ItemStatus,
      }))
      const doneItems: ProgressItem[] = [...completedRef.current]
        .filter(k => k.startsWith("sync:"))
        .map(k => k.replace("sync:", ""))
        .filter(id => !syncQueue.includes(id))
        .map(id => ({ id, title: title(id), status: "done" as ItemStatus }))
      return [...doneItems, ...queueItems]
    }

    return []
  })()

  const doneCount = progressItems.filter(i => i.status === "done").length
  const totalCount = progressItems.length
  const progressPct = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0

  function statusColor(s: ItemStatus) {
    return s === "done" ? "text-emerald-600 bg-emerald-50 border-emerald-200"
      : s === "processing" ? "text-blue-600 bg-blue-50 border-blue-200"
      : s === "skipped" ? "text-slate-400 bg-slate-50 border-slate-200"
      : "text-slate-500 bg-slate-50 border-slate-100"
  }
  function statusLabel(s: ItemStatus, step?: string) {
    // 「板块为空」归因仅 step2 产出（空板块免疫语义）；其他步骤未来若产出 skipped 不得错误归因
    if (s === "skipped") return step === 'step2' ? "已跳过（板块为空）" : "已跳过"
    return s === "done" ? "已完成" : s === "processing" ? "处理中" : "等待中"
  }

  const stepIcon: Record<string, string> = { step1: "✂️", step2: "✨", step3: "🔥", step4: "🎯", step5: "🔄", step6: "💾" }
  const stepLabel: Record<string, string> = { step1: "裁剪/折叠", step2: "初版改写", step3: "Grill-me", step4: "ATS 靶向", step5: "联动更新", step6: "保存" }

  return (
    <div className={`absolute inset-x-4 top-14 z-40 max-h-[60vh] overflow-y-auto rounded-xl border p-4 shadow-xl backdrop-blur-md transition-all animate-in fade-in slide-in-from-top-4 duration-300 ${
      wizardStep === 'step6'
        ? "border-emerald-200 bg-emerald-50/95"
        : wizardStep === 'step5' || wizardStep === 'step4'
          ? "border-blue-200 bg-blue-50/95"
          : "border-amber-200 bg-amber-50/95"
    }`}>
      <div className="flex flex-col gap-2">
        <div className={`flex items-center justify-between border-b pb-2 ${
          wizardStep === 'step6' ? "border-emerald-100" : wizardStep === 'step5' || wizardStep === 'step4' ? "border-blue-100" : "border-amber-100"
        }`}>
          <h4 className={`text-sm font-bold flex items-center gap-1.5 ${
            wizardStep === 'step6' ? "text-emerald-800" : wizardStep === 'step5' || wizardStep === 'step4' ? "text-blue-800" : "text-amber-800"
          }`}>
            <Target className="h-4 w-4" />
            {wizardStep === 'step1' ? "向导：第一步 - 宏观裁剪" :
             wizardStep === 'step2' ? "向导：第二步 - 初版改写" :
             wizardStep === 'step3' ? "向导：第三步 - 深度拷问 Grill-me" :
             wizardStep === 'step4' ? "向导：第四步 - ATS 全局靶向" :
             wizardStep === 'step5' ? "向导：第五步 - AI 联动更新" :
             "向导：第六步 - 保存到飞书"}
          </h4>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-100" onClick={() => setWizardHidden(true)}>隐藏向导</Button>
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs text-rose-500 hover:text-rose-700 hover:bg-rose-50" onClick={() => {
              if (window.confirm('确定要退出向导吗？\n\n退出后将清除当前进度，下次需要重新开始。')) {
                setWizardStep('idle')
                setWizardProgress(DEFAULT_WIZARD_PROGRESS)
                setWizardHidden(false)
                if (wizardStorageKey) localStorage.removeItem(wizardStorageKey)
              }
            }}>退出向导</Button>
          </div>
        </div>

        <p className={`text-xs leading-relaxed ${
          wizardStep === 'step6' ? "text-emerald-700" : wizardStep === 'step5' || wizardStep === 'step4' ? "text-blue-700" : "text-amber-700"
        }`}>
          {wizardStep === 'step1' ? (
            !wizardProgress.pruneDone || !wizardProgress.compressDone ? (
              <span>请使用右侧的「✂️ 经历瘦身」和「⚖️ 智能折叠」工具，对项目和工作经历进行宏观裁剪。</span>
            ) : (
              <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 裁剪完成！点击右侧按钮进入下一步。</span>
            )
          ) : wizardStep === 'step2' ? (
            allDraftsDone ? (
              <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 初改完成！点击右侧按钮进入第三步。{(!hasWork || !hasProjects) ? "（空板块无需初改，已自动跳过）" : ""}</span>
            ) : (
              <span>请使用「✨ 经历一键初稿」工具，让 AI 结合 JD 对经历进行基底对齐与结构重组。</span>
            )
          ) : wizardStep === 'step3' ? (
            grillPanelOpen ? (
              <span>下方是 AI 挑出的「内容单薄」经历，请勾选后逐条深挖补充细节。</span>
            ) : grillQueue.length > 0 ? (
              <span>正在逐条深挖经历细节... 剩余 {grillQueue.length} 段待处理。</span>
            ) : wizardProgress.grillDone ? (
              <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 深挖完成！点击右侧按钮进入第四步（ATS）。</span>
            ) : (
              <span>正在准备深挖建议...</span>
            )
          ) : wizardStep === 'step4' ? (
            wizardProgress.atsDone ? (
              <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> ATS 对齐完成！进入第五步 AI 联动更新。</span>
            ) : atsQueue.length > 0 ? (
              <span>正在并行处理 ATS 靶向对齐（每次最多处理 3 个）... 剩余 {atsQueue.length} 个。</span>
            ) : (
              <span>请在每段经历中点击「ATS 靶向对齐」按钮，让 AI 自动注入 JD 关键词。</span>
            )
          ) : wizardStep === 'step5' ? (
            wizardProgress.syncDone ? (
              <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 基础模块联动更新完成！进入第六步保存。</span>
            ) : (
              <span>请对个人总结与专业技能等基础模块使用「AI 联动更新」同步更新。</span>
            )
          ) : wizardStep === 'step6' ? (
            <span className="font-semibold text-emerald-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 全部就绪！点击下方高亮的「保存到飞书」按钮完成收官。</span>
          ) : null}
        </p>

        {/* ── 进度卡片 (Variant B Card Grid) ── */}
        {progressItems.length > 0 && wizardStep !== 'step6' && (
          <div className="flex flex-col gap-2 mt-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-700">
                {stepIcon[wizardStep] || "📋"} {stepLabel[wizardStep] || ""}
              </span>
              <Badge variant="outline" className="text-[10px] font-mono">
                {doneCount}/{totalCount} 完成
              </Badge>
            </div>
            <Progress value={progressPct} className="h-1" />
            <div className="grid grid-cols-1 gap-1 max-h-36 overflow-y-auto">
              {progressItems.map(item => (
                <div
                  key={item.id}
                  className={`flex items-center justify-between px-2 py-1 rounded-lg border transition-all ${
                    item.status === "done"
                      ? "border-emerald-200 bg-emerald-50/50"
                      : item.status === "processing"
                        ? "border-blue-300 bg-blue-50 shadow-sm"
                        : "border-slate-200 bg-white"
                  }`}
                >
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    {item.status === "done" ? (
                      <CheckCircle className="h-3.5 w-3.5 text-emerald-500 flex-shrink-0" />
                    ) : item.status === "processing" ? (
                      <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin flex-shrink-0" />
                    ) : (
                      <Clock className="h-3.5 w-3.5 text-slate-300 flex-shrink-0" />
                    )}
                    <span className={`text-xs truncate ${
                      item.status === "done" ? "text-slate-400" : "text-slate-700"
                    }`}>
                      {item.title}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                    <Badge variant="outline" className={`text-[9px] px-1 py-0 ${statusColor(item.status)}`}>
                      {statusLabel(item.status, wizardStep)}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-5 px-1 text-[10px] text-blue-600 hover:text-blue-800 hover:bg-blue-50"
                      onClick={() => handleLocate(item.id)}
                    >
                      <MapPin className="h-3 w-3" />
                      定位
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 mt-1">
          {wizardStep === 'step1' ? (
            <>
              <Button size="sm" variant="outline" className="h-7 text-xs border-amber-300 text-amber-700 hover:bg-amber-100" onClick={() => {
                setWizardProgress(p => ({...p, pruneDone: true, compressDone: true}))
                setWizardStep('step2')
              }}>一键跳过裁剪</Button>
              <Button size="sm" className="h-7 text-xs bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={!wizardProgress.pruneDone || !wizardProgress.compressDone}
                onClick={() => setWizardStep('step2')}>进入第二步 ➔</Button>
            </>
          ) : wizardStep === 'step2' ? (
            <>
              <Button size="sm" variant="outline" className="h-7 text-xs border-amber-300 text-amber-700 hover:bg-amber-100" onClick={() => {
                setWizardProgress(p => ({...p, initialDraftProjectDone: true, initialDraftWorkDone: true}))
                setWizardStep('step3')
              }}>一键跳过初改</Button>
              <Button size="sm" className="h-7 text-xs bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={!allDraftsDone}
                onClick={() => setWizardStep('step3')}>进入第三步 ➔</Button>
            </>
          ) : wizardStep === 'step3' ? (
            <>
              <Button size="sm" variant="outline" className="h-7 text-xs border-amber-300 text-amber-700 hover:bg-amber-100" onClick={() => {
                setGrillQueue([])
                setGrillPanelOpen(false)
                setWizardProgress(p => ({...p, grillDone: true}))
                setWizardStep('step4')
              }}>一键跳过深挖</Button>
              <Button size="sm" className="h-7 text-xs bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={!wizardProgress.grillDone}
                onClick={() => setWizardStep('step4')}>进入第四步 ➔</Button>
            </>
          ) : wizardStep === 'step4' ? (
            <>
              <Button size="sm" variant="outline" className="h-7 text-xs border-blue-300 text-blue-700 hover:bg-blue-100" onClick={() => {
                setWizardProgress(p => ({...p, atsDone: true}))
                setWizardStep('step5')
              }}>一键跳过ATS</Button>
              <Button size="sm" className="h-7 text-xs bg-blue-500 hover:bg-blue-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={!wizardProgress.atsDone}
                onClick={() => setWizardStep('step5')}>进入第五步 ➔</Button>
            </>
          ) : wizardStep === 'step5' ? (
            <>
              <Button size="sm" variant="outline" className="h-7 text-xs border-blue-300 text-blue-700 hover:bg-blue-100" onClick={() => {
                setWizardProgress(p => ({...p, syncDone: true}))
                setWizardStep('step6')
              }}>一键跳过联动更新</Button>
              <Button size="sm" className="h-7 text-xs bg-blue-500 hover:bg-blue-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={!wizardProgress.syncDone}
                onClick={() => setWizardStep('step6')}>进入第六步 ➔</Button>
            </>
          ) : wizardStep === 'step6' ? (
            <Button size="sm" className="h-7 text-xs bg-emerald-500 hover:bg-emerald-600 text-white animate-pulse" onClick={() => {
              handleSaveResume()
              setWizardProgress(p => ({ ...p, savedDone: true }))
              if (wizardStorageKey) saveWizardProgress('step6', { ...wizardProgress, savedDone: true })
              setTimeout(() => {
                setWizardStep('idle')
                setWizardProgress(DEFAULT_WIZARD_PROGRESS)
                setWizardHidden(false)
                if (wizardStorageKey) localStorage.removeItem(wizardStorageKey)
              }, 1500)
            }} disabled={isSavingResume}>
              {isSavingResume ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Save className="mr-1 h-3 w-3" />}
              保存到飞书并收官
            </Button>
          ) : null}
        </div>

        {wizardStep === 'step3' && grillPanelOpen && (
          <GrillSuggestionPanel
            suggestions={grillSuggestions}
            sections={grillSectionsList}
            isLoading={isLoadingGrillSuggestions}
            onStartGrill={handleStartGrillQueue}
            onSkip={() => {
              setGrillQueue([])
              setGrillPanelOpen(false)
              setWizardProgress(p => ({ ...p, grillDone: true }))
            }}
          />
        )}
      </div>
    </div>
  )
}
