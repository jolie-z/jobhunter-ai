"use client"

import { useState, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Sparkles, Target, XCircle } from "lucide-react"
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
import { WizardStatusPanel } from "./components/wizard-status-panel"
import { runSkillRewrite, startAsyncSkillRewrite } from "@/hooks/use-skill-rewrite"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
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

    setIsTestingSkill(true)
    try {
      // 🚀 优先启动异步 Agent 推演通道并建立 SSE 实时看板
      const taskId = await startAsyncSkillRewrite({
        job_id: job.id,
        jd_text: job.jobDescription || "",
        job_name: `${job.jobTitle || ""} ${job.companyName || ""}`,
        skill_id: skillToUse,
        include_diagnosis: includeDiagnosis,
      })

      setLiveTaskId(taskId)
      setLiveModalOpen(true)
    } catch (err: any) {
      console.warn("启动异步推演失败，回退至同步等待模式:", err)
      try {
        const data = await runSkillRewrite({
          job_id: job.id,
          jd_text: job.jobDescription || "",
          job_name: `${job.jobTitle || ""} ${job.companyName || ""}`,
          skill_id: skillToUse,
          include_diagnosis: includeDiagnosis,
        })
        
        if (data.parsed_json) {
          const { setResumeData } = useResumeV2Store.getState()
          setResumeData(data.parsed_json as ResumeDataV2)
        }
        if (onUpdateJob && data.parsed_json) {
          onUpdateJob({ ...job, aiRewriteJson: JSON.stringify(data.parsed_json, null, 2) })
        }

        const isCustomSkill = !!skillToUse && skillToUse !== "resume_rewrite"
        if (isCustomSkill) {
          setArtifactsOpen(true)
        } else {
          alert(`✅ 官方标准简历改写完成，已实时铺入简历画布！`)
        }
      } catch (syncErr: any) {
        alert("❌ 简历改写失败: " + syncErr.message)
      }
    } finally {
      setIsTestingSkill(false)
    }
  }

  // 🌟 弹窗确认重复改写：带原 skill 参数 force 继续
  const confirmRerunRewrite = () => {
    const skillId = rerunSkillRef.current
    rerunSkillRef.current = undefined
    setRerunGateOpen(false)
    void handleSkillRewriteAndSave(skillId, true)
  }

  const handleLiveModalComplete = (data: { parsed_json: any; markdown: string; usage: any }) => {
    if (data.parsed_json) {
      const { setResumeData } = useResumeV2Store.getState()
      setResumeData(data.parsed_json)
      if (onUpdateJob && job) {
        onUpdateJob({ ...job, aiRewriteJson: JSON.stringify(data.parsed_json, null, 2) })
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

      <main className="flex-1 overflow-y-auto">
        <div
          data-resume-canvas="true"
          data-testid="v2-resume-canvas"
          className="mx-auto flex max-w-4xl flex-col gap-4 px-4 py-4 sm:px-6 sm:py-6"
        >
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
