"use client"

import { useState, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Sparkles, Target, XCircle  } from "lucide-react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"

import type { JobData } from "@/types/job"
import type { ResumeDataV2 } from "@/types/resume"
import { API_BASE } from "@/lib/api"
import { useEditorState } from "./hooks/use-editor-state"
import { useAiWizard } from "./hooks/use-ai-wizard"

import { EditorToolbar } from "./components/editor-toolbar"
import { EditorModuleRenderer } from "./components/editor-module-renderer"
import { PdfPreviewDialog } from "./components/pdf-preview-dialog"
import { SkillArtifactsSheet } from "./components/skill-artifacts-sheet"
import { SkillAgentLiveModal } from "./components/skill-agent-live-modal"
import { SkillRewriteInlineStatus } from "./components/skill-rewrite-inline-status"
import { WizardStatusPanel } from "./components/wizard-status-panel"
import {
  runSkillRewrite,
  startAsyncSkillRewrite,
  isPackageSkill,
  isOfficialSkillId,
  skillDisplayName,
  preflightSkillRewrite,
  type SkillRewriteParams,
  type SkillPreflightReport,
} from "@/hooks/use-skill-rewrite"
import { SkillPreflightDialog } from "@/components/skill-preflight-dialog"
import type { SkillAgentCompletePayload } from "@/hooks/use-skill-agent-stream"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { PendingSummaryBar } from "./components/pending-summary-bar"
import { toast } from "@/hooks/use-toast"
import { hasAiArtifact } from "@/lib/ai-artifacts"
import { AiRerunConfirmModal } from "@/components/dashboard/ai-rerun-confirm-modal"

export interface V2ResumeEditorProps {
  job?: JobData | null
  selectedText?: string
  selectedSectionId?: string | null
  onClearSelection?: () => void
  onTextSelect?: (text: string, sectionId: string | null) => void
  processingJobs?: Record<string, string>
  jobLiveLogs?: Record<string, string[]>
  globalTaskStatus?: "idle" | "running" | "completed" | "interrupted"
  onExport?: (type: "pdf" | "image", template: "classic" | "color" | "color_v2") => void
  isExportingPdf?: boolean
  isExportingImage?: boolean
  exportingType?: "pdf" | "image" | null
  exportSuccess?: { type: "pdf" | "image"; time: number } | null
  onQAComplete?: (report: any) => void
  onUpdateJob?: (job: JobData | null, action?: "remove") => void
}

export function V2ResumeEditor({
  job,
  selectedText,
  selectedSectionId,
  onClearSelection,
  onTextSelect,
  processingJobs,
  jobLiveLogs,
  globalTaskStatus,
  onExport, isExportingPdf, isExportingImage, exportingType, exportSuccess, onQAComplete, onUpdateJob
}: V2ResumeEditorProps) {

  const { state: editorState, actions: editorActions } = useEditorState()
  const { state: wizardState, actions: wizardActions } = useAiWizard(job)

  const [isSavingResume, setIsSavingResume] = useState(false)

  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)
  const [includeDiagnosis, setIncludeDiagnosis] = useState(true)
  const [isTestingSkill, setIsTestingSkill] = useState(false)
  const [artifactsOpen, setArtifactsOpen] = useState(false)
  const [liveModalOpen, setLiveModalOpen] = useState(false)
  const [liveTaskId, setLiveTaskId] = useState<string | null>(null)
  // 官方剧本/单文件技能改写：不弹看板，行内状态条承接（多文件包才走 liveModalOpen）
  const [inlineTaskId, setInlineTaskId] = useState<string | null>(null)
  const [inlineSkillLabel, setInlineSkillLabel] = useState<string>("官方标准剧本")
  // 执行前预检：确认后才真正消耗 token
  const [preflightState, setPreflightState] = useState<{
    report: SkillPreflightReport | null
    params: SkillRewriteParams
    skillToUse?: string
    errorMessage?: string
  } | null>(null)
  const [preflightLoading, setPreflightLoading] = useState(false)
  const inlineTaskSkillRef = useRef<string | undefined>(undefined)
  const [isDiagnosing, setIsDiagnosing] = useState(false)
  const [diagnosisSuggestions, setDiagnosisSuggestions] = useState<any[]>([])
  const [isQAEvaluating, setIsQAEvaluating] = useState(false)
  // 🌟 重复改写二次确认：该岗位已有「AI改写JSON」产物时，再次改写会覆盖并消耗 Token
  const [rerunGateOpen, setRerunGateOpen] = useState(false)
  const rerunSkillRef = useRef<string | undefined>(undefined)

  const handleQAEvaluate = async () => {
    if (!job?.id) {
      toast({ title: "提示", description: "请先选择一个岗位再进行评估" })
      return
    }
    setIsQAEvaluating(true)
    try {
      const { resumeData } = useResumeV2Store.getState()
      const response = await fetch(`${API_BASE}/api/qa_evaluate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.id,
          job_description: job.jobDescription || "",
          resume_text: JSON.stringify(resumeData),
          platform: job.platform || "BOSS直聘",
        }),
      })
      const data = await response.json()
      if (response.ok && data.status === "success") {
        onQAComplete?.(data.qa_report)
        toast({
          title: "✅ AI 评估完成",
          description: "最新匹配度报告已生成并同步飞书「二次质检报告」字段",
        })
      } else {
        toast({
          variant: "destructive",
          title: "❌ 评估失败",
          description: data.message || "后端评估接口异常",
        })
      }
    } catch (e: any) {
      toast({
        variant: "destructive",
        title: "❌ 评估失败",
        description: e.message || "网络请求异常，请检查后端服务",
      })
    } finally {
      setIsQAEvaluating(false)
    }
  }

  const handleGlobalDiagnosis = async () => {
    if (!job?.id) return
    setIsDiagnosing(true)
    try {
      const { resumeData } = useResumeV2Store.getState()
      const resumeText = JSON.stringify(resumeData)
      const response = await fetch(`${API_BASE}/api/strategy/global_diagnosis`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jd_text: job.jobDescription, full_resume_context: resumeText }),
      })
      const data = await response.json()
      if (response.ok && data.status === "success") {
        setDiagnosisSuggestions(data.data || [])
        if (!data.data || data.data.length === 0) {
          toast({ title: "✅ 扫描完成", description: "本轮 AI 全局诊断未发现需要靶向处理的毒点" })
        }
      } else {
        alert("诊断失败: " + data.message)
      }
    } catch (err: any) { alert("诊断异常: " + err.message) } finally { setIsDiagnosing(false) }
  }

  const startSkillRewrite = async (params: SkillRewriteParams, skillToUse?: string) => {
    try {
      // 🚀 启动异步 Agent 推演通道；按「是否多文件技能包」分流呈现（与后端引擎路由同判据）：
      // 多文件包 → 实时作战看板（多轮 Agent，日志密集）；官方剧本/单文件 → 行内状态条（单轮引擎）
      const taskId = await startAsyncSkillRewrite(params)

      if (await isPackageSkill(skillToUse)) {
        setLiveTaskId(taskId)
        setLiveModalOpen(true)
        setIsTestingSkill(false)
      } else {
        // 单轮引擎：行内状态条承接，按钮保持禁用至终局（防重复触发）
        inlineTaskSkillRef.current = skillToUse
        setInlineSkillLabel(await skillDisplayName(skillToUse))
        setInlineTaskId(taskId)
      }
    } catch (err: any) {
      console.warn("启动异步推演失败，回退至同步等待模式:", err)
      try {
        const data = await runSkillRewrite(params)
        const isResume = data.result_kind === undefined || data.result_kind === "resume"
        if (isResume && data.parsed_json) {
          const { setResumeData } = useResumeV2Store.getState()
          setResumeData(data.parsed_json as ResumeDataV2)
          if (onUpdateJob) {
            onUpdateJob({ ...job!, aiRewriteJson: JSON.stringify(data.parsed_json, null, 2) })
          }
        }

        const isCustomSkill = !!skillToUse && skillToUse !== "resume_rewrite"
        if (!isResume) {
          setArtifactsOpen(true)
          toast({
            title: "✅ 技能执行完成",
            description: "产物已归档到产物库，可在「作战产物库」查看",
          })
        } else if (isCustomSkill) {
          setArtifactsOpen(true)
        } else {
          alert(`✅ 官方标准简历改写完成，已实时铺入简历画布！`)
        }
      } catch (syncErr: any) {
        alert("❌ 简历改写失败: " + syncErr.message)
      } finally {
        setIsTestingSkill(false)
      }
    }
  }

  const handleSkillRewriteAndSave = async (overrideSkillId?: string, force = false) => {
    if (!job?.id) {
      alert("请先选择一个岗位！")
      return
    }
    if (!force && hasAiArtifact(job, "rewrite")) {
      rerunSkillRef.current = overrideSkillId
      setRerunGateOpen(true)
      return
    }
    const skillToUse = overrideSkillId || selectedSkill || undefined
    const params: SkillRewriteParams = {
      job_id: job.id,
      jd_text: job.jobDescription || "",
      job_name: `${job.jobTitle || ""} ${job.companyName || ""}`,
      skill_id: skillToUse,
      include_diagnosis: includeDiagnosis,
    }

    setIsTestingSkill(true)
    try {
      const report = await preflightSkillRewrite(params)
      setPreflightState({ report, params, skillToUse })
    } catch (err: any) {
      // 预检失败不阻断执行，但要让用户知道无法提前预估
      setPreflightState({
        report: null,
        params,
        skillToUse,
        errorMessage: err?.message || "预检失败",
      })
    }
  }

  const confirmPreflight = async () => {
    if (!preflightState) return
    const { params, skillToUse } = preflightState
    setPreflightLoading(true)
    try {
      await startSkillRewrite(params, skillToUse)
      setPreflightState(null)
    } finally {
      setPreflightLoading(false)
    }
  }

  const cancelPreflight = () => {
    setPreflightState(null)
    setIsTestingSkill(false)
  }

  // 行内状态条失败终局：toast 真实报错 + 释放按钮/任务态（状态条随 inlineTaskId 清空卸载）
  const handleInlineError = (message: string) => {
    setInlineTaskId(null)
    setIsTestingSkill(false)
    toast({ title: "❌ 简历改写失败", description: message })
  }

  // 行内状态条完成：铺画布 + 写回岗位（与看板 onComplete 同一套落点）+ 释放任务态
  // （画布已填 + toast 已弹，状态条功成身退，避免终局横幅常驻/收起语义歧义）
  const handleInlineComplete = (data: SkillAgentCompletePayload) => {
    setInlineTaskId(null)
    setIsTestingSkill(false)
    const isResume = data.result_kind === undefined || data.result_kind === "resume"
    if (!isResume) {
      handleLiveModalComplete(data)
      setArtifactsOpen(true)
      toast({
        title: "✅ 技能执行完成",
        description: "产物已归档到产物库，可在「作战产物库」查看",
      })
      return
    }
    handleLiveModalComplete(data)
    const usedSkill = inlineTaskSkillRef.current
    if (!isOfficialSkillId(usedSkill)) {
      toast({
        title: "✅ 简历改写完成",
        description: "已自动写入飞书「AI改写JSON」+ 跟进状态=简历人工复核；退出不再提醒保存",
      })
      setArtifactsOpen(true)
    } else {
      toast({
        title: "✅ 官方标准简历改写完成",
        description: "已自动写入飞书「AI改写JSON」+ 跟进状态=简历人工复核；退出不再提醒保存",
      })
    }
  }

  // 行内状态条手动收起（仅运行中可见）：SSE 停订但任务在服务端继续执行
  const handleInlineDismiss = () => {
    setInlineTaskId(null)
    setIsTestingSkill(false)
    toast({
      title: "改写任务转入后台",
      description: "任务仍在执行，完成后自动写入飞书「AI改写JSON」与跟进状态",
    })
  }

  // 🌟 弹窗确认重复改写：带原 skill 参数 force 继续
  const confirmRerunRewrite = () => {
    const skillId = rerunSkillRef.current
    rerunSkillRef.current = undefined
    setRerunGateOpen(false)
    void handleSkillRewriteAndSave(skillId, true)
  }

  const handleLiveModalComplete = (data: SkillAgentCompletePayload) => {
    const isResume = data.result_kind === undefined || data.result_kind === "resume"
    if (!isResume) {
      // 通用 skill：只归档产物，不碰简历画布 / AI改写JSON / 跟进状态
      setArtifactsOpen(true)
      if (data.partial) {
        toast({
          title: "⚠️ 技能部分完成",
          description: "已产出的文件已归档到产物库；缺少的产物可重新运行补齐",
        })
      }
      return
    }
    if (data.parsed_json) {
      const store = useResumeV2Store.getState()
      // 铺画布+基线同事务（基线取 withKeys 转换后形态，原始 parsed_json 直转会让
      // dirty 恒真——R1 P1）：后端 persisted 回执确认已落飞书，此刻画布=已保存内容；
      // 后续 loadData 重载以注入 title/头像后的最终形态再校准
      store.setResumeDataWithBaseline(data.parsed_json)
      if (onUpdateJob && job) {
        // followStatus 同步自 persisted 权威回执（此前只更新 aiRewriteJson，定制面板
        // 状态下拉整个会话显示旧值，用户误以为跟进状态没改）
        onUpdateJob({
          ...job,
          aiRewriteJson: JSON.stringify(data.parsed_json, null, 2),
          // 清旧稿镜像：manualRefinedResume 与 aiRewriteJson 后端同列（AI改写JSON），
          // 但本地镜像在完成回调后仍是旧值，loadData 优先读它会把画布/基线铺回旧稿
          manualRefinedResume: "",
          followStatus: data.persisted?.follow_status || job.followStatus,
          _localRewriteAt: Date.now(),
        })
      }
    }
  }

  const handleSaveResume = async () => {
    if (!job) return
    setIsSavingResume(true)
    try {
      const { resumeData } = useResumeV2Store.getState()
      const resumeJson = JSON.stringify(resumeData)
      const requestBody: any = { 
        job_id: job.id, 
        resume_text: resumeJson, 
        platform: job.platform || "BOSS直聘" 
      }
      const response = await fetch(`${API_BASE}/api/save_manual_resume`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: 后端保存接口异常`)
      }
      const data = await response.json()
      if (data.status === "success") {
        const nextJob = { ...job, manualRefinedResume: resumeJson }
        onUpdateJob?.(nextJob)
        toast({
          title: "✅ 简历已成功保存",
          description: "已同步写回飞书多维表格「AI改写JSON」字段与本地缓存",
        })
      } else {
        toast({
          variant: "destructive",
          title: "❌ 保存失败",
          description: data.message || "后端返回保存异常",
        })
      }
    } catch (e: any) {
      console.error("[handleSaveResume] 保存简历异常:", e)
      toast({
        variant: "destructive",
        title: "❌ 保存失败",
        description: e.message || "网络请求异常，请检查后端服务",
      })
    } finally {
      setIsSavingResume(false)
    }
  }


  // 定位 handler — 平滑滚动到目标 section，并打开对应面板
  const handleLocate = (sectionId: string) => {
    // Step 1/2 的工具面板：先确保面板打开
    if (sectionId === "prune") editorActions.setPruneOpen(true)
    if (sectionId === "compress") editorActions.setCompressOpen(true)
    if (sectionId === "draft-work") editorActions.setWorkInitialDraftOpen(true)
    if (sectionId === "draft-project") editorActions.setProjectInitialDraftOpen(true)

    // 延迟一帧让面板渲染后再滚动
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-section-id="${sectionId}"]`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" })
        el.classList.add("ring-2", "ring-blue-400", "ring-offset-2")
        setTimeout(() => el.classList.remove("ring-2", "ring-blue-400", "ring-offset-2"), 2000)
      }
    })
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background relative">
      <EditorToolbar
        findText={editorState.findText} setFindText={editorActions.setFindText}
        replaceText={editorState.replaceText} setReplaceText={editorActions.setReplaceText}
        totalMatches={editorState.totalMatches}
        currentMatchIndex={editorState.currentMatchIndex} setCurrentMatchIndex={editorActions.setCurrentMatchIndex}
        job={job || undefined}
        onExport={onExport}
        isExportingPdf={isExportingPdf}
        isExportingImage={isExportingImage}
        exportingType={exportingType}
        exportSuccess={exportSuccess}
        onGlobalDiagnosis={handleGlobalDiagnosis}
        isDiagnosing={isDiagnosing}
        onQAEvaluate={handleQAEvaluate}
        isQAEvaluating={isQAEvaluating}
        setPreviewOpen={editorActions.setPreviewOpen}
        handleSaveResume={handleSaveResume}
        isSavingResume={isSavingResume}
        hasManualRefinedResume={!!job?.manualRefinedResume}
        selectedSkill={selectedSkill}
        setSelectedSkill={setSelectedSkill}
        onTestSkillRewrite={handleSkillRewriteAndSave}
        isTestingSkill={isTestingSkill}
        includeDiagnosis={includeDiagnosis}
        setIncludeDiagnosis={setIncludeDiagnosis}
        onOpenArtifacts={() => setArtifactsOpen(true)}
        onStartWizard={wizardActions.handleStartWizard}
        wizardStep={wizardState.wizardStep}
      />

      {wizardState.wizardStep !== 'idle' && !wizardState.wizardHidden && (
        <WizardStatusPanel
          wizardStep={wizardState.wizardStep}
          wizardProgress={wizardState.wizardProgress}
          wizardHidden={wizardState.wizardHidden}
          setWizardHidden={wizardActions.setWizardHidden}
          setWizardStep={wizardActions.setWizardStep}
          setWizardProgress={wizardActions.setWizardProgress}
          wizardStorageKey={wizardState.wizardStorageKey}
          saveWizardProgress={wizardActions.saveWizardProgress}
          grillPanelOpen={wizardState.grillPanelOpen}
          setGrillPanelOpen={wizardActions.setGrillPanelOpen}
          grillQueue={wizardState.grillQueue}
          setGrillQueue={wizardActions.setGrillQueue}
          atsQueue={wizardState.atsQueue}
          syncQueue={wizardState.syncQueue}
          grillSuggestions={wizardState.grillSuggestions}
          isLoadingGrillSuggestions={wizardState.isLoadingGrillSuggestions}
          handleStartGrillQueue={wizardActions.handleStartGrillQueue}
          handleSaveResume={handleSaveResume}
          isSavingResume={isSavingResume}
          grillSectionsList={wizardState.grillSectionsList}
          sectionTitles={wizardState.sectionTitles}
          handleLocate={handleLocate}
        />
      )}

      {/* 🌟 建议卡片浮层面板 */}
      {diagnosisSuggestions.length > 0 && (
        <div className="absolute right-4 top-16 z-50 w-80 max-h-[70vh] overflow-y-auto rounded-xl border border-amber-200 bg-white/95 backdrop-blur-md shadow-2xl p-4 animate-in slide-in-from-right-4 duration-300">
          <div className="flex items-center justify-between mb-3 border-b border-amber-100 pb-2">
            <h4 className="text-sm font-bold text-amber-800 flex items-center gap-1.5"><Target className="h-4 w-4" /> 靶向微操建议</h4>
            <Button variant="ghost" size="icon" className="h-6 w-6 text-slate-400 hover:text-slate-600" onClick={() => setDiagnosisSuggestions([])}>
              <XCircle className="h-4 w-4" />
            </Button>
          </div>
          <div className="space-y-3">
            {diagnosisSuggestions.map((s, idx) => (
              <div key={idx} className="p-3 bg-amber-50/50 border border-amber-100 rounded-lg">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-semibold text-slate-700 bg-white px-1.5 py-0.5 rounded border border-slate-200">{s.section_title}</span>
                  <span className="text-[10px] font-mono text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">{s.action}</span>
                </div>
                <p className="text-xs text-slate-600 leading-relaxed mb-2.5">{s.reason}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 执行前预检：确认后才消耗用户 token；非简历 skill 只告知，不阻止 */}
      <SkillPreflightDialog
        open={Boolean(preflightState)}
        report={preflightState?.report ?? null}
        skillName={preflightState?.report?.name || selectedSkill || "官方剧本"}
        errorMessage={preflightState?.errorMessage}
        loading={preflightLoading}
        onConfirm={confirmPreflight}
        onCancel={cancelPreflight}
      />

      {/* 官方剧本/单文件技能改写：轻量行内进度（多文件技能包才弹实时作战看板） */}
      {inlineTaskId && (
        <SkillRewriteInlineStatus
          taskId={inlineTaskId}
          skillLabel={inlineSkillLabel}
          onComplete={handleInlineComplete}
          onError={handleInlineError}
          onDismiss={handleInlineDismiss}
        />
      )}

      <main className="flex-1 overflow-y-auto">
        <div
          data-resume-canvas="true"
          data-testid="v2-resume-canvas"
          className="mx-auto flex max-w-4xl flex-col gap-4 px-4 py-4 sm:px-6 sm:py-6"
        >
          <PendingSummaryBar />
          <EditorModuleRenderer
            job={job}
                                                                                    handleFormatMarkdown={editorActions.handleFormatMarkdown}
            compressOpen={editorState.compressOpen}
            setCompressOpen={editorActions.setCompressOpen}
            pruneOpen={editorState.pruneOpen}
            setPruneOpen={editorActions.setPruneOpen}
            trashOpen={editorState.trashOpen}
            setTrashOpen={editorActions.setTrashOpen}
            workRestoreOpen={editorState.workRestoreOpen}
            setWorkRestoreOpen={editorActions.setWorkRestoreOpen}
            workInitialDraftOpen={editorState.workInitialDraftOpen}
            setWorkInitialDraftOpen={editorActions.setWorkInitialDraftOpen}
            projectInitialDraftOpen={editorState.projectInitialDraftOpen}
            setProjectInitialDraftOpen={editorActions.setProjectInitialDraftOpen}
            wizardStep={wizardState.wizardStep}
            wizardProgress={wizardState.wizardProgress}
            handleWizardComplete={wizardActions.handleWizardComplete}
            syncQueue={wizardState.syncQueue}
            atsQueue={wizardState.atsQueue}
            grillQueue={wizardState.grillQueue}
          />
        </div>
      </main>

      <PdfPreviewDialog
        previewOpen={editorState.previewOpen}
        setPreviewOpen={editorActions.setPreviewOpen}
      />

      <SkillArtifactsSheet
        open={artifactsOpen}
        onOpenChange={setArtifactsOpen}
        jobId={job?.id}
        jobTitle={`${job?.companyName || ""} ${job?.jobTitle || ""}`}
        onFillSuccess={(parsed) => {
          if (onUpdateJob && job) {
            onUpdateJob({ ...job, aiRewriteJson: JSON.stringify(parsed, null, 2) })
          }
        }}
      />

      <SkillAgentLiveModal
        open={liveModalOpen}
        onOpenChange={setLiveModalOpen}
        taskId={liveTaskId}
        jobTitle={`${job?.companyName || ""} ${job?.jobTitle || ""}`}
        skillId={selectedSkill || "官方标准剧本"}
        onComplete={handleLiveModalComplete}
        onOpenStudio={() => {
          setLiveModalOpen(false)
          setArtifactsOpen(true)
        }}
      />

      {/* 重复发起简历改写二次确认弹窗（该岗位已有 AI改写JSON 产物时） */}
      <AiRerunConfirmModal
        open={rerunGateOpen}
        kind="rewrite"
        existingJobs={job ? [job] : []}
        onConfirm={confirmRerunRewrite}
        onCancel={() => {
          rerunSkillRef.current = undefined
          setRerunGateOpen(false)
        }}
      />
    </div>
  )
}

