"use client"

// 定制面板-简历编辑区顶部工具栏
// （顶部加粗按钮已下线 2026-09-24：vditor 所见即所得后 activeElement 非 textarea/input，
//  主路径本就不生效，加粗统一走各编辑器自带工具栏；与简历库 edit-tools-cluster 同批）

import React, { useState } from "react"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  Undo2,
  Redo2,
  ChevronDown,
  Save,
  Sparkles,
  Target,
  Eye,
  Loader2,
  Paintbrush,
  Wand2,
  FolderArchive,
  BrainCircuit,
} from "lucide-react"
import { ToastAction } from "@/components/ui/toast"
import { SkillSelector } from "@/components/skill-selector"
import { ExportActionGroup } from "./export-action-group"
import { useGlobalFormat } from "../hooks/use-global-format"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { toast } from "@/hooks/use-toast"
import { searchResumeMatches, replaceResumeText } from "../utils/resume-search-utils"
import { useEditorSearchHighlight } from "../hooks/use-editor-search-highlight"
import { SearchReplacePopover } from "./search-replace-popover"
import { useResumeUndoRedo } from "../hooks/use-resume-undo-redo"

export interface EditorToolbarProps {
  findText: string
  setFindText: (val: string) => void
  replaceText: string
  setReplaceText: (val: string) => void
  totalMatches: number
  currentMatchIndex: number
  setCurrentMatchIndex: (val: number) => void

  onExport?: (type: "pdf" | "image", template: "classic" | "color" | "color_v2") => void
  isExportingPdf?: boolean
  isExportingImage?: boolean
  exportingType?: "pdf" | "image" | null
  exportSuccess?: { type: "pdf" | "image"; time: number } | null
  onQAEvaluate?: () => void
  isQAEvaluating?: boolean
  onGlobalDiagnosis?: () => void
  isDiagnosing?: boolean
  setPreviewOpen: (open: boolean) => void

  handleSaveResume: () => void
  isSavingResume?: boolean
  hasManualRefinedResume?: boolean

  job?: { id?: string; [key: string]: any }
  selectedSkill?: string | null
  setSelectedSkill?: (skillId: string) => void
  onTestSkillRewrite?: (skillId?: string) => void
  isTestingSkill?: boolean
  includeDiagnosis?: boolean
  setIncludeDiagnosis?: (include: boolean) => void
  onOpenArtifacts?: () => void

  onStartWizard?: () => void
  wizardStep?: string
}

export function EditorToolbar({
  findText,
  setFindText,
  replaceText,
  setReplaceText,
  totalMatches,
  currentMatchIndex,
  setCurrentMatchIndex,
  onExport,
  isExportingPdf,
  isExportingImage,
  exportingType,
  exportSuccess,
  onQAEvaluate,
  isQAEvaluating,
  onGlobalDiagnosis,
  isDiagnosing,
  setPreviewOpen,
  handleSaveResume,
  isSavingResume,
  hasManualRefinedResume,
  job,
  selectedSkill,
  setSelectedSkill,
  onTestSkillRewrite,
  isTestingSkill,
  includeDiagnosis = true,
  setIncludeDiagnosis,
  onOpenArtifacts,
  onStartWizard,
  wizardStep,
}: EditorToolbarProps) {
  const {
    isGlobalFormatting,
    globalFormatProgress,
    handleGlobalFormat,
  } = useGlobalFormat()

  const { resumeData, setResumeData } = useResumeV2Store()

  // 🌟 全局历史栈（撤销与重做）管理
  const {
    canUndo,
    canRedo,
    undo,
    redo,
    takeSnapshot,
  } = useResumeUndoRedo({ resumeKey: job?.id })

  // 动态检索全简历树的匹配项
  const searchResult = React.useMemo(() => {
    return searchResumeMatches(resumeData, findText)
  }, [resumeData, findText])

  const matches = searchResult.matches

  // 🌟 全画布双轨高亮与精准光标导航
  // 直接传递 currentMatchIndex，由 Hook 内部基于 DOM 实际匹配列表做越界防护，杜绝数据层提前截断导致的索引锁死
  const { scrollToCurrentMatch, matches: domMatches } = useEditorSearchHighlight({
    findText,
    currentMatchIndex,
  })

  // 当 DOM 已挂载且成功扫描出匹配项时，以视图层可见匹配数为准；否则以数据层为准
  const effectiveTotalMatches =
    domMatches.length > 0 ? domMatches.length : searchResult.totalMatches

  // 派生安全索引，彻底杜绝 5/4 等任何越界显示
  const safeMatchIndex =
    effectiveTotalMatches > 0 ? Math.min(currentMatchIndex, effectiveTotalMatches - 1) : 0

  React.useEffect(() => {
    setCurrentMatchIndex(0)
  }, [findText, setCurrentMatchIndex])

  // 当总匹配数变小（如替换后），自动收敛游标
  React.useEffect(() => {
    if (effectiveTotalMatches === 0) {
      setCurrentMatchIndex(0)
    } else if (currentMatchIndex >= effectiveTotalMatches) {
      setCurrentMatchIndex(effectiveTotalMatches - 1)
    }
  }, [effectiveTotalMatches, currentMatchIndex, setCurrentMatchIndex])

  const scrollToMatch = (n: number) => {
    // 1. 优先使用 DOM 级字级精准居中与呼吸光标信标
    const handled = scrollToCurrentMatch(n)

    // 2. 结构化兜底：仅当未能命中 DOM 精确坐标（例如目标处于折叠状态未渲染）时，才回退到卡片级居中
    if (!handled && matches.length > 0 && n >= 0 && n < matches.length) {
      const match = matches[n]
      const el =
        document.querySelector(`[data-section-id="${match.sectionId}"]`) ||
        document.getElementById(match.sectionId)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" })
      }
    }
  }

  const handleReplace = (replaceAll: boolean) => {
    if (!findText) {
      toast({ title: "提示", description: "请输入要查找的内容" })
      return
    }
    if (!resumeData) return

    const result = replaceResumeText(resumeData, findText, replaceText, replaceAll, safeMatchIndex)
    if (result.replacedCount === 0) {
      toast({ title: "未找到匹配项", description: `未在简历中找到「${findText}」` })
      return
    }

    // 仅在确认发生真实替换且即将写入新数据时，将替换前的原数据定格入栈，绝对杜绝 0 命中产生空步或误清空重做栈
    takeSnapshot(resumeData)
    setResumeData(result.nextData)
    toast({
      title: replaceAll ? "✅ 全部替换成功" : "✅ 替换成功",
      description: `已完成 ${result.replacedCount} 处「${findText}」的替换`,
      action: (
        <ToastAction altText="撤销本次替换" onClick={undo}>
          撤销
        </ToastAction>
      ),
    })
  }
  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex items-center justify-between border-b border-border/80 bg-card/95 backdrop-blur-md px-2 py-1.5 shadow-xs sticky top-0 z-20 gap-1 overflow-x-auto min-w-0">
        {/* 1️⃣ 基础编辑与排版岛 (左侧安静区) */}
        <div className="flex items-center gap-0.5 shrink-0">
          {/* 撤销 (Undo) */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className={`size-7 rounded-md ${
                  canUndo
                    ? "text-slate-600 hover:text-slate-900 hover:bg-slate-100/80"
                    : "text-slate-300 opacity-40 cursor-not-allowed"
                }`}
                onClick={() => canUndo && undo()}
              >
                <Undo2 className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>撤销全局修改 (⌘Z / Ctrl+Z)</TooltipContent>
          </Tooltip>

          {/* 重做 (Redo) */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className={`size-7 rounded-md ${
                  canRedo
                    ? "text-slate-600 hover:text-slate-900 hover:bg-slate-100/80"
                    : "text-slate-300 opacity-40 cursor-not-allowed"
                }`}
                onClick={() => canRedo && redo()}
              >
                <Redo2 className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>重做全局修改 (⌘⇧Z / Ctrl+Y)</TooltipContent>
          </Tooltip>

          <SearchReplacePopover
            findText={findText}
            setFindText={setFindText}
            replaceText={replaceText}
            setReplaceText={setReplaceText}
            effectiveTotalMatches={effectiveTotalMatches}
            safeMatchIndex={safeMatchIndex}
            setCurrentMatchIndex={setCurrentMatchIndex}
            scrollToMatch={scrollToMatch}
            handleReplace={handleReplace}
          />

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="size-7 text-slate-600 hover:text-amber-600 hover:bg-amber-50/80 rounded-md"
                onClick={handleGlobalFormat}
                disabled={isGlobalFormatting}
              >
                {isGlobalFormatting ? (
                  <Loader2 className="size-3.5 animate-spin text-amber-500" />
                ) : (
                  <Paintbrush className="size-3.5" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {isGlobalFormatting ? globalFormatProgress : "全局自动排版"}
            </TooltipContent>
          </Tooltip>

          <Separator orientation="vertical" className="mx-0.5 h-4 bg-slate-200" />

          {/* 保存到飞书 (纯图标风格，与替换/排版彻底统一) */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="size-7 text-slate-600 hover:text-indigo-600 hover:bg-indigo-50/80 rounded-md"
                onClick={handleSaveResume}
                disabled={isSavingResume}
              >
                {isSavingResume ? (
                  <Loader2 className="size-3.5 animate-spin text-indigo-500" />
                ) : (
                  <Save className="size-3.5" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>保存写回飞书多维表格</TooltipContent>
          </Tooltip>
        </div>

        {/* 2️⃣ 🌟 Skill 智能体作战中枢 (强化外框与一体化岛屿感) */}
        <div className="flex items-center gap-1.5 bg-gradient-to-r from-amber-50/95 via-orange-50/80 to-amber-50/95 border border-amber-300/80 shadow-xs ring-1 ring-amber-400/25 rounded-xl p-0.5 px-1.5 shrink-0">
          {/* 剧本选择器 (自适应紧凑) */}
          <SkillSelector
            selectedSkill={selectedSkill || null}
            onChange={(skillId) => setSelectedSkill?.(skillId)}
            compact={true}
            className="h-6.5 text-xs border-0 bg-transparent shadow-none"
          />

          {/* 诊断情报注入微开关 */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="sm"
                variant="ghost"
                className={`h-6.5 px-2 text-[11px] font-medium rounded-lg transition-all flex items-center gap-1 shadow-2xs ${
                  includeDiagnosis
                    ? "text-blue-700 bg-white/95 hover:bg-white border border-blue-200/80 font-semibold"
                    : "text-slate-500 bg-black/5 hover:bg-black/10 border border-transparent"
                }`}
                onClick={() => setIncludeDiagnosis?.(!includeDiagnosis)}
              >
                <span
                  className={`size-1.5 rounded-full shrink-0 ${
                    includeDiagnosis ? "bg-blue-500 animate-pulse" : "bg-slate-400"
                  }`}
                />
                <span className="hidden sm:inline">{includeDiagnosis ? "带入诊断" : "纯净"}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent className="bg-slate-900 text-white p-2.5 max-w-[260px] text-xs">
              {includeDiagnosis
                ? "已开启：自动将毒点预警、高杠杆点与 ATS 词典作为上下文注入 Skill"
                : "已关闭：纯净改写模式"}
            </TooltipContent>
          </Tooltip>

          {/* 主行动按钮：✨ 执行改写 */}
          <Button
            size="sm"
            className="h-6.5 px-2.5 text-xs font-semibold bg-gradient-to-r from-amber-500 via-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white rounded-lg shadow-xs active:scale-[0.97] transition-all flex items-center gap-1"
            onClick={() => onTestSkillRewrite?.(selectedSkill || undefined)}
            disabled={isTestingSkill}
          >
            {isTestingSkill ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Sparkles className="size-3.5" />
            )}
            <span>执行改写</span>
          </Button>

          {/* 📂 作战产物库直达 */}
          <Button
            variant="outline"
            size="sm"
            className="h-6.5 px-2 text-[11px] font-medium text-amber-900 bg-white/90 hover:bg-white hover:text-amber-950 border-amber-300/80 rounded-lg active:scale-[0.97] transition-all flex items-center gap-1 shadow-2xs"
            onClick={onOpenArtifacts}
          >
            <FolderArchive className="size-3.5 text-amber-600" />
            <span className="hidden md:inline font-medium">产物库</span>
          </Button>
        </div>

        {/* 3️⃣ AI 实验室收纳 + 4️⃣ 预览与导出岛 (右侧收尾区) */}
        <div className="flex items-center gap-0.5 shrink-0">
          {/* 🧠 更多 AI 工具 (下拉整合：靶心诊断、AI向导、QA评估) */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-1.5 text-xs font-medium text-slate-600 hover:text-indigo-600 hover:bg-indigo-50/80 rounded-md flex items-center gap-1"
              >
                <BrainCircuit className="size-3.5 text-indigo-500" />
                <span className="hidden lg:inline">AI 实验室</span>
                <ChevronDown className="size-3 opacity-60" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56 p-1.5 shadow-xl rounded-xl border-slate-200">
              <DropdownMenuItem
                className="flex items-center gap-2.5 py-2 px-2.5 cursor-pointer text-xs rounded-lg"
                onClick={onGlobalDiagnosis}
                disabled={isDiagnosing}
              >
                <Target className="size-4 text-blue-500 shrink-0" />
                <div className="flex flex-col">
                  <span className="font-medium text-slate-800">AI 全局扫描诊断</span>
                  <span className="text-[10px] text-slate-400">检测当前简历与 JD 毒点</span>
                </div>
              </DropdownMenuItem>

              <DropdownMenuItem
                className="flex items-center gap-2.5 py-2 px-2.5 cursor-pointer text-xs rounded-lg"
                onClick={onStartWizard}
              >
                <Wand2 className="size-4 text-emerald-500 shrink-0" />
                <div className="flex flex-col">
                  <span className="font-medium text-slate-800">AI 深度改写向导</span>
                  <span className="text-[10px] text-slate-400">引导式经历裁剪与折叠</span>
                </div>
              </DropdownMenuItem>

              <DropdownMenuItem
                className="flex items-center gap-2.5 py-2 px-2.5 cursor-pointer text-xs rounded-lg"
                onClick={onQAEvaluate}
                disabled={isQAEvaluating}
              >
                <Sparkles className="size-4 text-purple-500 shrink-0" />
                <div className="flex flex-col">
                  <span className="font-medium text-slate-800">再次 AI 评估打分</span>
                  <span className="text-[10px] text-slate-400">重新量化匹配度得分</span>
                </div>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <Separator orientation="vertical" className="mx-0.5 h-4 bg-slate-200" />

          {/* 👁️ 预览 */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="sm"
                variant="ghost"
                className="size-7 p-0 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-md flex items-center justify-center gap-1"
                onClick={() => setPreviewOpen(true)}
              >
                <Eye className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>高清 A4 排版预览</TooltipContent>
          </Tooltip>

          {/* 📥 独立解耦的导出操作组（分轨并行、微胶囊进度与完成提示） */}
          <ExportActionGroup
            onExport={onExport}
            isExportingPdf={isExportingPdf}
            isExportingImage={isExportingImage}
            exportingType={exportingType}
            exportSuccess={exportSuccess}
          />
        </div>
      </div>
    </TooltipProvider>
  )
}
