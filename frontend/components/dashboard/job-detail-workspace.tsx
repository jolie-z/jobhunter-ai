"use client"

import { API_BASE } from "@/lib/api"
import React, { useCallback, useEffect, useMemo, useState, useRef } from "react"
import type { ReactNode } from "react"
import {
  ArrowLeft,
  Save,
  Image,
  FileText,
  ExternalLink,
  Copy,
  Sparkles,
  Search,
  Replace,
  Bold,
  ArrowUp,
  ArrowDown,
  GripVertical,
  Loader2,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronDown,
  X,
  Mic,
  Download,
  ImageIcon,
  FileDown,
  Eye,
  Plus, // 🚀 修复第3处：从 lucide-react 补充导入 Plus 图标
  MapPin,
  Building2,
  Wallet,
  Gauge,
  ThumbsUp,
  ThumbsDown,
  Users,
  Factory,
  GraduationCap,
  Briefcase,
  Activity,
  CalendarDays,
  UserRound,
  Navigation,
  Crown,
  Send,
  Clock,
  Target,
  Flame,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area" // 🚀 修复第2、4处：补充 shadcn 的 ScrollArea 组件
import type { JobData } from "@/types/job"
import { ResumeCanvasColumn } from "./resume-canvas/resume-canvas-column"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { parsePersonalInfo, PersonalInfo } from "@/lib/personal-info-parser"
import { AtsAligner } from "./resume-builder/ats-aligner"
import { ExperienceGriller } from "./resume-builder/experience-griller"
import { toast } from "@/hooks/use-toast"
import { AiModuleSyncInline } from "./resume-builder/ai-module-sync-inline"
import type { ResumeSection, ResumeData, RewriteAnnotItem, RewriteAnnotGroup } from "@/types/resume"
import { parseResumeData, parseAiRewriteAnnotations, DEFAULT_RESUME } from "@/lib/utils/resume-parser"
import { splitTagString, formatDateMaybeTimestamp } from "@/lib/utils/text-formatters"
import { LinkifyText } from "@/components/shared/linkify-text"
import { HighlightText } from "@/components/shared/highlight-text"
import { MdPreview } from "@/components/shared/md-preview"
import { AiGradeDashboard } from "./features/ai-grade-dashboard"
import { InterviewPrepColumn } from "./features/interview-prep-column"
import { JobArchiveColumn } from "./features/job-archive-column"
import { AICopilotColumn } from "./features/ai-copilot-column"
import { V2ResumeEditor } from "./features/v2-resume-editor"

import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { resumeDataToResumeDataV2 } from "@/lib/resume-converter"
import type { ResumeDataV2 } from "@/types/resume"
import { buildResumeExportRequest } from "@/lib/resume-export"

// 兼容转发：历史引用方从这里 import API_BASE，权威出口已收敛到 lib/api
export { API_BASE }

// 🌟 将原本在 resume-types.ts 中的旧接口定义移回本地，供 PDF 导出和面试辅导模块继续使用
// 状态颜色映射表
export const getStatusBadgeColor = (status: string): string => {
  const colorMap: Record<string, string> = {
    "新线索": "bg-blue-100 text-blue-800 hover:bg-blue-100",
    "不合适": "bg-red-100 text-red-800 hover:bg-red-100",
    "已完成初步评估": "bg-teal-100 text-teal-800 hover:bg-teal-100",
    "已完成深度评估": "bg-cyan-100 text-cyan-800 hover:bg-cyan-100",
    "简历人工复核": "bg-orange-100 text-orange-800 hover:bg-orange-100",
    "疑似重复": "bg-amber-100 text-amber-800 hover:bg-amber-100",
    "待投递": "bg-indigo-100 text-indigo-800 hover:bg-indigo-100",
    "已投递": "bg-purple-100 text-purple-800 hover:bg-purple-100",
    "面试中": "bg-green-100 text-green-800 hover:bg-green-100",
    "Offer": "bg-emerald-100 text-emerald-800 hover:bg-emerald-100",
    "已下架": "bg-gray-200 text-gray-600 hover:bg-gray-200",
    "待人工复核": "bg-yellow-100 text-yellow-800 hover:bg-yellow-100",
    "准备投递": "bg-cyan-100 text-cyan-800 hover:bg-cyan-100",
    "已拒绝": "bg-gray-100 text-gray-800 hover:bg-gray-100",
  }
  // 如果状态不在映射表中，返回默认的紫色
  return colorMap[status] || "bg-purple-100 text-purple-800 hover:bg-purple-100"
}

interface JobDetailWorkspaceProps {
  job: JobData
  onUpdateJob: (job: JobData | null, action?: 'remove') => void
  onBack: () => void
  hasPrevious: boolean
  hasNext: boolean
  onPrevious: () => void
  onNext: () => void
  dynamicStatuses: string[]
  onRefreshJobs?: () => Promise<void>
  // 🌟 新增：多 Agent 并发状态流与日志流 TS 声明
  processingJobs?: Record<string, string>
  jobLiveLogs?: Record<string, string[]>
  globalTaskStatus?: "idle" | "running" | "completed" | "interrupted"
}

// ============================================================
// 🌟 修复后的三级渲染与数据拉取
// ============================================================
async function fetchDefaultResumeData(): Promise<ResumeDataV2 | null> {
  try {
    const resumeRes = await fetch(`${API_BASE}/api/get_active_resume`);
    if (resumeRes.ok) {
      const resData = await resumeRes.json();
      if (resData.status === "success" && resData.data) {
        try {
          return JSON.parse(resData.data) as ResumeDataV2;
        } catch(e) {
          console.error("JSON Parse Error for active resume data:", e);
        }
      }
    }
  } catch (e) {
    console.error("加载简历异常:", e);
  }
  return null;
}

// 🌟 全局极其坚固的 JSON 解析器

// ── 视窗控制器：模块类型与坑位布局 ─────────────────────────
type ModuleKey = 'A' | 'B' | 'C' | 'D'
type PanelSlot = { content: ModuleKey | 'AD_TAB'; defaultSize: number }

/**
 * 纯计算函数：根据当前开启的模块集合，推导出应渲染的 Panel 坑位数组。
 * 规则：A 固定左、B 固定中、C 固定右；D 智能补位；4 个全开时 A/D 共享左坑（Tab 模式）。
 */
function getPanelSlots(open: Set<ModuleKey>): PanelSlot[] {
  const hasA = open.has('A'), hasB = open.has('B'), hasC = open.has('C'), hasD = open.has('D')
  const count = open.size

  if (count === 0) return []

  // 4 个全开 → 拼桌：左坑 A/D Tab，中坑 B，右坑 C
  if (count === 4) return [
    { content: 'AD_TAB', defaultSize: 25 },
    { content: 'B', defaultSize: 50 },
    { content: 'C', defaultSize: 25 },
  ]

  if (count === 3) {
    if (hasA && hasB && hasC) return [
      { content: 'A', defaultSize: 25 },
      { content: 'B', defaultSize: 50 },
      { content: 'C', defaultSize: 25 },
    ]
    if (hasA && hasB && hasD) return [ // D 补右坑（C 的坑）
      { content: 'A', defaultSize: 25 },
      { content: 'B', defaultSize: 50 },
      { content: 'D', defaultSize: 25 },
    ]
    if (hasB && hasC && hasD) return [ // D 补左坑（A 的坑）
      { content: 'D', defaultSize: 25 },
      { content: 'B', defaultSize: 50 },
      { content: 'C', defaultSize: 25 },
    ]
    if (hasA && hasC && hasD) return [ // D 补中坑（B 的坑）
      { content: 'A', defaultSize: 25 },
      { content: 'D', defaultSize: 50 },
      { content: 'C', defaultSize: 25 },
    ]
  }

  if (count === 2) {
    // 按 A < B < C < D 顺序左右排列，各占 50%
    const ordered = (['A', 'B', 'C', 'D'] as ModuleKey[]).filter(m => open.has(m))
    return ordered.map(m => ({ content: m, defaultSize: 50 }))
  }

  // count === 1：唯一模块铺满
  return [{ content: Array.from(open)[0] as ModuleKey, defaultSize: 100 }]
}
// ─────────────────────────────────────────────────────────

// ── 面板关闭按鈕包裹器 ───────────────────────────────────
function PanelCloseWrapper({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div className="h-full relative group">
      <button
        onClick={onClose}
        className="absolute top-1.5 right-2 z-10 h-5 w-5 rounded-sm flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-background/90 border border-border hover:bg-red-50 hover:text-red-500 hover:border-red-200 text-muted-foreground"
        title={`关闭 ${title}`}
      >
        <X className="h-3 w-3" />
      </button>
      {children}
    </div>
  )
}


export function JobDetailWorkspace({
  job,
  onUpdateJob,
  onBack,
  hasPrevious,
  hasNext,
  onPrevious,
  onNext,
  dynamicStatuses,
  onRefreshJobs,
  // 🌟 新增：接管 page.tsx 传下来的状态
  processingJobs,
  jobLiveLogs,
  globalTaskStatus,
}: JobDetailWorkspaceProps) {
  const [status, setStatus] = useState(job?.followStatus || "")
  const setResumeDataV2 = useResumeV2Store(state => state.setResumeData)
  const resumeDataV2 = useResumeV2Store(state => state.resumeData)
  // For V1 fallback rendering (if any old component still needs it, though we will phase them out)
  const [resumeData, setResumeData] = useState<ResumeData>(DEFAULT_RESUME)

  // 🌟 核心阀门重构：只用多Agent数据状态来决定是否进入新版排版
  const hasNewMultiAgentData = Boolean(job?.multiAgentRewrite && String(job.multiAgentRewrite).trim() !== "");

  // 💡 注：不再需要 hasAnyAiData 和 hasOldAiData 变量，旧版组件 LegacyRawResumeEditor 内部的 useEffect 
  // 已经能完美处理“AI改写JSON”的数据读取逻辑了。

  const [selectedText, setSelectedText] = useState("")
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null)
  const [exportingType, setExportingType] = useState<"pdf" | "image" | null>(null)
  const [isExportingPdf, setIsExportingPdf] = useState(false)
  const [isExportingImage, setIsExportingImage] = useState(false)
  const [exportSuccess, setExportSuccess] = useState<{ type: "pdf" | "image"; time: number } | null>(null)
  const [qaReport, setQaReport] = useState<any>(null)

  // ── 视窗控制器状态 ──────────────────────────────────────
  // 当前开启的模块集合（A/B/C 默认开，D 默认关）
  const [openModules, setOpenModules] = useState<Set<ModuleKey>>(() => new Set<ModuleKey>(['A', 'B', 'C']))
  // 4 个模块全开时，左侧坑位的 Tab 激活项
  const [leftPanelTab, setLeftPanelTab] = useState<'A' | 'D'>('A')
  // 由 openModules 推导出当前应渲染的 Panel 坑位数组
  const panelSlots = useMemo(() => getPanelSlots(openModules), [openModules])
  // D 模块面试辅导所需的简历文本，随 resumeData 实时计算
  const resumeText = useMemo(() => {
    if (!resumeDataV2) return "";
    return JSON.stringify(resumeDataV2, null, 2); // Dump as JSON string for D module
  }, [resumeDataV2])
  // ────────────────────────────────────────────────────────

  // 容错处理：确保当前状态始终在选项中
  const availableStatuses = useMemo(() => {
    const currentStatus = job?.followStatus?.trim()
    if (currentStatus && !dynamicStatuses.includes(currentStatus)) {
      return [...dynamicStatuses, currentStatus].sort()
    }
    return dynamicStatuses
  }, [dynamicStatuses, job?.followStatus])

  useEffect(() => {
    if (job) {
      setStatus(job.followStatus || "")

      // 🌟 初始化 QA 报告：优先从飞书的 secondQaReport 字段读取
      if (job.secondQaReport && job.secondQaReport.trim()) {
        try {
          const parsedReport = JSON.parse(job.secondQaReport)
          setQaReport(parsedReport)
        } catch (e) {
          console.error("解析 QA 报告失败:", e)
          setQaReport(null)
        }
      } else {
        setQaReport(null)
      }
    }
  }, [job?.followStatus, job?.id, job?.secondQaReport])

  // 🌟 LocalStorage 姓名记忆功能：客户端挂载后安全读取
  useEffect(() => {
    if (typeof window === 'undefined') return; // SSR 安全检查

    const savedName = localStorage.getItem('candidateName');
    if (savedName && savedName.trim()) {
      setResumeData((prev) => ({
        ...prev,
        header: { ...prev.header, name: savedName.trim() }
      }));
    }
  }, []); // 仅在组件挂载时执行一次

  useEffect(() => {
    if (!job) return;
    
    // helper to inject title into ResumeDataV2
    const injectDynamicJobTitleV2 = (data: ResumeDataV2 | null): ResumeDataV2 | null => {
      if (!data) return null;
      const newData = { ...data, personalInfo: { ...data.personalInfo } };
      // Not strongly needed since V2 relies on personalInfo.title, but let's keep it safe
      newData.personalInfo.title = job.jobTitle || newData.personalInfo.title || "";
      return newData;
    };

    const loadData = async () => {
      let finalDataV2: ResumeDataV2 | null = null;
      
      // 1. Try manualRefinedResume
      if (job.manualRefinedResume) {
        const text = job.manualRefinedResume.trim();
        if (text.startsWith("{")) {
          // JSON (V2)
          try {
            finalDataV2 = JSON.parse(text) as ResumeDataV2;
          } catch(e) {}
        } else {
          // Markdown (V1)
          const v1 = parseResumeData(text);
          if (v1) finalDataV2 = resumeDataToResumeDataV2(v1);
        }
      }
      
      // 2. Try aiRewriteJson
      if (!finalDataV2 && job.aiRewriteJson) {
        const text = job.aiRewriteJson.trim();
        if (text.startsWith("{")) {
          try {
            finalDataV2 = JSON.parse(text) as ResumeDataV2;
          } catch(e) {}
        } else {
          const v1 = parseResumeData(text);
          if (v1) finalDataV2 = resumeDataToResumeDataV2(v1);
        }
      }
      
      // 3. Fallback to active resume from Config Dashboard
      if (!finalDataV2) {
        finalDataV2 = await fetchDefaultResumeData();
      }
      
      // 🌟 新版 Skill 的改写 markdown 不含个人信息（隐私不入模型），
      // 解析结果带默认占位（如「候选人」）时，从用户默认简历回填真实个人信息
      if (finalDataV2) {
        const p = finalDataV2.personalInfo;
        const looksPlaceholder = !p?.name || p.name === "候选人";
        if (looksPlaceholder) {
          const defaultV2 = await fetchDefaultResumeData();
          if (defaultV2?.personalInfo?.name && defaultV2.personalInfo.name !== "候选人") {
            finalDataV2.personalInfo = {
              ...defaultV2.personalInfo,
              ...(p?.title ? { title: p.title } : {}),
            };
          }
        } else if (!p?.avatar_url) {
          // 🌟 即使姓名不是候选人占位，若当前简历缺失照片但默认母本有照片，一次性对齐，杜绝子组件挂载后异步写 store 污染撤销栈
          const defaultV2 = await fetchDefaultResumeData();
          if (defaultV2?.personalInfo?.avatar_url) {
            finalDataV2.personalInfo = {
              ...finalDataV2.personalInfo,
              avatar_url: defaultV2.personalInfo.avatar_url,
            };
          }
        }
        finalDataV2 = injectDynamicJobTitleV2(finalDataV2);
        setResumeDataV2(finalDataV2);
      }
    };
    
    loadData();
    
    return () => {
      setResumeDataV2(null);
    }
  }, [job?.id, job?.aiRewriteJson, job?.manualRefinedResume, job?.jobTitle])

  const handlePolishSelected = useCallback(
    async (instruction: string) => {
      if (!selectedText.trim() || !selectedSectionId) {
        alert("请先在简历正文中选中一段文字")
        return
      }
      try {
        const response = await fetch(`${API_BASE}/ai_polish`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ selected_text: selectedText, instruction }),
        })
        const data = await response.json()
        const polished = typeof data?.polished_text === "string" ? data.polished_text : selectedText
        if (data?.error) {
          console.warn(data.error)
        }
        setResumeData((prev) => ({
          ...prev,
          sections: prev.sections.map((s) =>
            s.id === selectedSectionId
              ? { ...s, content: s.content.split(selectedText).join(polished) }
              : s,
          ),
        }))
        setSelectedText(polished)
      } catch {
        alert("润色请求失败，请确认后端已启动")
      }
    },
    [selectedText, selectedSectionId],
  )

  const handleExport = async (type: "pdf" | "image", template: "classic" | "color" | "color_v2" = "classic") => {
    // 导出前强制保存，确保 headless browser 拿到最新数据
    if (resumeDataV2) {
      try {
        const saveResponse = await fetch(`${API_BASE}/api/update_job_resume`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_id: job.id,
            resume_data: JSON.stringify(resumeDataV2, null, 2),
            current_status: job.followStatus,
          })
        })
        if (!saveResponse.ok) {
          const errorData = await saveResponse.json().catch(() => ({}))
          let errMsg = "保存当前简历失败"
          if (typeof errorData.detail === "string") {
            errMsg = errorData.detail
          } else if (Array.isArray(errorData.detail) && errorData.detail.length > 0) {
            errMsg = errorData.detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ")
          } else if (errorData.message) {
            errMsg = errorData.message
          }
          throw new Error(errMsg)
        }
        onUpdateJob({ ...job, manualRefinedResume: JSON.stringify(resumeDataV2, null, 2) })
      } catch (e: any) {
        toast({
          variant: "destructive",
          title: "❌ 简历保存失败",
          description: e.message || "无法保存当前简历，已取消导出",
        })
        return
      }
    }

    if (!job?.id) {
      toast({
        variant: "destructive",
        title: "导出失败",
        description: "无法获取当前岗位 ID",
      })
      return
    }
    
    const typeLabel = type === "pdf" ? "PDF" : "长图"
    
    if (type === "pdf") setIsExportingPdf(true)
    else setIsExportingImage(true)
    setExportingType(type)

    try {
      const exportRequest = buildResumeExportRequest(job, resumeDataV2, type, template)
      
      const res = await fetch(`${API_BASE}${exportRequest.endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(exportRequest.body)
      })
      
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        let errMsg = "生成失败"
        if (typeof errorData.detail === "string") {
          errMsg = errorData.detail
        } else if (Array.isArray(errorData.detail) && errorData.detail.length > 0) {
          errMsg = errorData.detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ")
        } else if (errorData.message) {
          errMsg = errorData.message
        }
        throw new Error(errMsg)
      }
      
      const targetField = type === "pdf" ? "PDF备份" : "图片保存"
      setExportSuccess({ type, time: Date.now() })
      toast({
        title: `🎉 ${typeLabel} 导出成功`,
        description: `已通过高清引擎渲染，并自动归档至飞书多维表格「${targetField}」字段。`,
      })
    } catch (e: any) {
      toast({
        variant: "destructive",
        title: `❌ ${typeLabel} 导出失败`,
        description: e.message || "请求失败，请稍后重试",
      })
    } finally {
      if (type === "pdf") setIsExportingPdf(false)
      else setIsExportingImage(false)
      setExportingType(null)
    }
  }

  const [isSavingResume, setIsSavingResume] = useState(false)
  const handleSaveResume = async () => {
    if (!job?.id || !resumeDataV2) return
    setIsSavingResume(true)
    try {
      const res = await fetch(`${API_BASE}/api/update_job_resume`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.id,
          resume_data: JSON.stringify(resumeDataV2, null, 2),
          current_status: job.followStatus,
        })
      })
      if (!res.ok) throw new Error("保存失败")
      // 更新本地
      onUpdateJob({ ...job, manualRefinedResume: JSON.stringify(resumeDataV2, null, 2) })
      alert("✅ 简历已保存并同步至飞书")
    } catch (e: any) {
      alert("❌ " + e.message)
    } finally {
      setIsSavingResume(false)
    }
  }

  // 🌟 防止白屏崩溃
  if (!job) {
    return <div className="h-full flex items-center justify-center text-sm text-muted-foreground">正在加载岗位数据...</div>
  }

  return (
    <div className="h-full flex flex-col bg-muted/30">
      {/* Apple-style frosted glass header */}
      <header className="shrink-0 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between px-4 py-2">
          {/* 左侧：返回 + 导航 */}
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={onBack}
              className="h-8 px-2.5 gap-1.5 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg">
              <ArrowLeft className="h-4 w-4" />
              <span className="text-xs">返回</span>
            </Button>
            <div className="flex items-center ml-1">
              <Button variant="ghost" size="icon" onClick={onPrevious} disabled={!hasPrevious}
                className="h-7 w-7 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-md disabled:opacity-30">
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button variant="ghost" size="icon" onClick={onNext} disabled={!hasNext}
                className="h-7 w-7 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-md disabled:opacity-30">
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

          {/* 中间：标题 + 状态 */}
          <div className="absolute left-1/2 -translate-x-1/2 flex items-center gap-2.5 max-w-[50%]">
            <div className="flex flex-col items-center">
              <span className="text-sm font-semibold text-slate-800 truncate max-w-[300px]">
                {job?.jobTitle || "-"}
              </span>
              <span className="text-[11px] text-slate-400">{job?.companyName || "-"}</span>
            </div>
            <Select
              value={status}
              onValueChange={(newStatus) => {
                setStatus(newStatus);
                if (newStatus === (job?.followStatus || "")) return;
                if (newStatus === "不合适") {
                  onUpdateJob(null, 'remove');
                } else {
                  onUpdateJob({ ...job, followStatus: newStatus });
                }
                fetch(`${API_BASE}/api/update_job_status`, {
                  method: "PUT",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    job_id: job?.id || "",
                    status: newStatus,
                    platform: job?.platform || "BOSS直聘"
                  }),
                }).then(async (response) => {
                  const data = await response.json();
                  if (!response.ok || data.status !== "success") {
                    console.error("❌ 状态同步失败:", data.message || data.detail);
                  }
                }).catch(error => {
                  console.error("网络错误:", error);
                });
              }}
            >
              <SelectTrigger className="w-24 h-7 text-[11px] bg-slate-50 border-slate-200 rounded-lg">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {availableStatuses.map((s) => (
                  <SelectItem key={s} value={s}>{s}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* 右侧：模块 Dock */}
          <div className="flex items-center gap-1">
            {([
              { key: 'A' as ModuleKey, label: '岗位详情', icon: '📋' },
              { key: 'B' as ModuleKey, label: '简历编辑', icon: '✏️' },
              { key: 'C' as ModuleKey, label: '简历诊断', icon: '🔍' },
              { key: 'D' as ModuleKey, label: '面试资料', icon: '🎯' },
            ]).map(({ key, label, icon }) => {
              const isActive = openModules.has(key)
              return (
                <button
                  key={key}
                  onClick={() => setOpenModules(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n })}
                  className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
                    isActive
                      ? "bg-slate-100 text-slate-800 shadow-sm border border-slate-200"
                      : "text-slate-400 hover:text-slate-600 hover:bg-slate-50"
                  }`}
                  title={isActive ? `收起 ${label}` : `展开 ${label}`}
                >
                  <span className="text-[11px]">{icon}</span>
                  <span className="hidden sm:inline">{label}</span>
                </button>
              )
            })}
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-hidden p-2">
        {panelSlots.length === 0 ? (
          // 空状态：所有模块均已关闭
          <div className="h-full flex flex-col items-center justify-center gap-4 rounded-lg border border-dashed border-border text-muted-foreground">
            <p className="text-sm">请从顶部选择要开启的工作区</p>
            <div className="flex gap-2">
              {(['A', 'B', 'C', 'D'] as ModuleKey[]).map((key) => {
                const lbl = ({ A: '岗位详情', B: '简历编辑', C: '简历诊断', D: '面试资料' } as Record<ModuleKey, string>)[key]
                return (
                  <Button
                    key={key}
                    variant="outline"
                    size="sm"
                    className="text-xs"
                    onClick={() => setOpenModules(prev => { const n = new Set(prev); n.add(key); return n })}
                  >
                    {key} · {lbl}
                  </Button>
                )
              })}
            </div>
          </div>
        ) : (
          <ResizablePanelGroup direction="horizontal" className="h-full rounded-lg border border-border">
            {panelSlots.flatMap((slot, idx) => {
              const minSz = panelSlots.length === 1 ? 0 : panelSlots.length === 2 ? 20 : 15
              const closeModule = (key: ModuleKey) =>
                setOpenModules(prev => { const n = new Set(prev); n.delete(key); return n })
              const { content, defaultSize } = slot
              const elements: ReactNode[] = []

              if (idx > 0) {
                elements.push(<ResizableHandle key={`h-${idx}`} withHandle />)
              }

              if (content === 'AD_TAB') {
                // 4个全开：左坑用 Tabs 承载 A 和 D
                elements.push(
                  <ResizablePanel key="AD_TAB" id="AD_TAB" order={idx} defaultSize={defaultSize} minSize={minSz}>
                    <Tabs
                      value={leftPanelTab}
                      onValueChange={(v) => setLeftPanelTab(v as 'A' | 'D')}
                      className="h-full flex flex-col"
                    >
                      <div className="shrink-0 px-2 py-1 border-b border-border bg-card">
                        <TabsList className="h-7 gap-0.5">
                          <TabsTrigger value="A" className="text-xs h-6 px-2 gap-1">
                            A · 岗位详情
                            <span
                              role="button"
                              aria-label="关闭岗位详情"
                              className="ml-1 inline-flex items-center transition-colors hover:text-red-500 text-muted-foreground/50 cursor-pointer"
                              onClick={(e) => { e.stopPropagation(); closeModule('A') }}
                            >
                              <X className="h-2.5 w-2.5" />
                            </span>
                          </TabsTrigger>
                          <TabsTrigger value="D" className="text-xs h-6 px-2 gap-1">
                            D · 面试资料
                            <span
                              role="button"
                              aria-label="关闭面试资料"
                              className="ml-1 inline-flex items-center transition-colors hover:text-red-500 text-muted-foreground/50 cursor-pointer"
                              onClick={(e) => { e.stopPropagation(); closeModule('D') }}
                            >
                              <X className="h-2.5 w-2.5" />
                            </span>
                          </TabsTrigger>
                        </TabsList>
                      </div>
                      <TabsContent value="A" className="flex-1 overflow-hidden mt-0 p-0 border-0">
                        <JobArchiveColumn job={job} />
                      </TabsContent>
                      <TabsContent value="D" className="flex-1 overflow-hidden mt-0 p-0 border-0">
                        <InterviewPrepColumn job={job} resumeText={resumeText} />
                      </TabsContent>
                    </Tabs>
                  </ResizablePanel>
                )
              } else {
                // 常规单模块面板，hover 时显示 X 关闭按鈕
                const titles: Record<ModuleKey, string> = { A: '岗位详情', B: '简历编辑', C: '简历诊断', D: '面试资料' }
                elements.push(
                  <ResizablePanel key={content} id={content} order={idx} defaultSize={defaultSize} minSize={minSz}>
                    <PanelCloseWrapper title={titles[content]} onClose={() => closeModule(content)}>
                      {content === 'A' ? (
                        <JobArchiveColumn job={job} />
                      ) : content === 'B' ? (
                        <V2ResumeEditor
                          selectedText={selectedText}
                          selectedSectionId={selectedSectionId}
                          onClearSelection={() => {
                            setSelectedText("")
                            setSelectedSectionId(null)
                          }}
                          onTextSelect={(text: string, sectionId: string | null) => {
                            setSelectedText(text)
                            setSelectedSectionId(sectionId)
                          }}
                          job={job}
                          onQAComplete={(report: any) => setQaReport(report)}
                          onUpdateJob={onUpdateJob}
                          onExport={(type: "pdf" | "image", template: "classic" | "color" | "color_v2") => { handleExport(type, template) }}
                          isExportingPdf={isExportingPdf}
                          isExportingImage={isExportingImage}
                          exportingType={exportingType}
                          exportSuccess={exportSuccess}
                          processingJobs={processingJobs}
                          jobLiveLogs={jobLiveLogs}
                          globalTaskStatus={globalTaskStatus}
                        />
                      ) : content === 'C' ? (
                        <AICopilotColumn
                          job={job}
                          onUpdateJob={onUpdateJob}
                          selectedText={selectedText}
                          onPolish={handlePolishSelected}
                          qaReport={qaReport}
                        />
                      ) : content === 'D' ? (
                        <InterviewPrepColumn job={job} resumeText={resumeText} />
                      ) : null}
                    </PanelCloseWrapper>
                  </ResizablePanel>
                )
              }

              return elements
            })}
          </ResizablePanelGroup>
        )}
      </div>
    </div>
  )
}

// ============================================================================
// 🌟 新版 岗位存档 (JobArchiveColumn) 及其专属 UI 子组件
// ============================================================================

