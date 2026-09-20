"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect } from "react"
import { Bold, Replace, Save, FileText, ImageIcon, FileDown, Eye, X, Plus, ArrowUp, ArrowDown, GripVertical, Loader2, Sparkles, Search, ChevronUp, ChevronDown, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Input } from "@/components/ui/input"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ResumeDiffBlock } from "./resume-diff-block"
import { RewriteDashboard } from "./rewrite-dashboard"
import { type ResumeModule, adapterJobToModules } from "@/lib/resume-types"
import type { JobData } from "@/types/job"
import { PersonalInfoHeader } from "./personal-info-header"
import { type PersonalInfo, parsePersonalInfo, serializePersonalInfo, DEFAULT_PERSONAL_INFO } from "@/lib/personal-info-parser"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { SkillSelector } from "@/components/skill-selector"
import type { SkillMeta } from "@/components/skill-selector"

interface ResumeCanvasColumnProps {
  job: JobData
  onUpdateJob: (job: JobData | null, action?: 'remove') => void
  onExport: (type: "pdf" | "image") => void
  exportingType: "pdf" | "image" | null
  onClose?: () => void
  onQAComplete?: (qaReport: any) => void
}

interface MatchLocation {
  moduleId: string;
  blockId: string;
  field: 'original' | 'rewritten';
  index: number;
}


// ============================================================
// 🌟 独家定制：工业级多 Agent Markdown 提取与拆解引擎
// ============================================================
export function parseMultiAgentMarkdownToModules(rawMarkdown: string, fallbackText: string = ""): ResumeModule[] {
  if (!rawMarkdown) return [];
  const text = rawMarkdown.replace(/\r\n/g, '\n');
  const blocks = text.split(/(?:^|\n)#\s+/).filter(Boolean);

  // 1. 预解析原始简历，用于二级模块的精准匹配
  const origText = fallbackText.replace(/\r\n/g, '\n');
  const origModules = origText.split(/(?:^|\n)#\s+/).filter(Boolean).map(block => {
    const lines = block.split('\n');
    const title = lines[0].trim();
    const content = lines.slice(1).join('\n').trim();
    
    // 按 ## 拆分原始子块
    const parts = content.split(/(?:^|\n)##\s+/);
    const origSubBlocks: any[] = [];
    if (parts[0].trim()) {
       origSubBlocks.push({ title: '概述', content: parts[0].trim(), fullText: parts[0].trim() });
    }
    for (let i = 1; i < parts.length; i++) {
       const subLines = parts[i].split('\n');
       origSubBlocks.push({
          title: subLines[0].trim(),
          content: subLines.slice(1).join('\n').trim(),
          fullText: parts[i].trim()
       });
    }
    return { title, content, origSubBlocks };
  });

  // 🌟 固定置顶模块：从原始简历中提取「个人信息」模块
  const personalInfoModule: ResumeModule[] = [];
  const personalInfoOrig = origModules.find(om => 
    om.title.includes('个人信息') || om.title.includes('基本信息') || om.title.includes('联系方式')
  );
  if (personalInfoOrig) {
    personalInfoModule.push({
      id: `ma-mod-personal-info-fixed`,
      title: '个人信息',
      blocks: [{
        id: `ma-blk-personal-info-fixed`,
        title: '个人信息',
        mode: 'editable' as const,
        original: personalInfoOrig.content,
      }]
    });
  }

  const normalizeTitle = (t: string) => t.replace(/\s+/g, '').replace('经历', '经验').toLowerCase();

  const agentModules = blocks.map((block, index) => {
    const lines = block.split('\n');
    const moduleTitle = lines[0].trim();
    let body = lines.slice(1).join('\n').trim();

    body = body.replace(/^\s*\*{4}\s*\n?/m, '').trim();

    const agent1Reasons: string[] = [];
    const agent2Reasons: string[] = [];

    const a1Regex = /(?:^|\n)>\s*💡\s*\*\*\[Agent 1[^\]]*\]\*\*[：:]\s*([\s\S]*?)(?=(?:\n>\s*💡|\n>\s*🧠|\n>\s*🔴|#|$))/ig;
    body = body.replace(a1Regex, (match, p1) => {
      agent1Reasons.push(p1.trim());
      return '';
    });

    const a2Regex = /(?:^|\n)>\s*🧠\s*\*\*\[Agent 2[^\]]*\]\*\*[：:]\s*([\s\S]*?)(?=(?:\n>\s*💡|\n>\s*🧠|\n>\s*🔴|#|$))/ig;
    body = body.replace(a2Regex, (match, p1) => {
      let logicText = p1.trim();
      logicText = logicText.replace(/(?<!\n)(?:\s*)(\d+\.\s+\*\*)/g, '\n\n$1');
      agent2Reasons.push(logicText);
      return '';
    });

    const cleanBody = body.trim();

    const timeRegex = /(19|20)\d{2}[.\-/年]\d{1,2}(?:\s*月)?\s*(?:-|~|至|–)\s*(?:(19|20)\d{2}[.\-/年]\d{1,2}(?:\s*月)?|至今|现在|Present)/i;

    // 2. 匹配对应的原始大模块（严格匹配，因为一级标题不允许修改）
    const t1 = normalizeTitle(moduleTitle);
    const matchedOrigModule = origModules.find(om => {
       const t2 = normalizeTitle(om.title);
       return t1 === t2;
    });

    // 3. 按 ## 拆分改写后的正文（只有包含时间的模块，才会被拆解为二级模块，如专业技能则保持整个大块）
    const hasSubBlocks = /(?:^|\n)##\s+/.test(cleanBody) && timeRegex.test(cleanBody);
    const parsedBlocks: any[] = [];
    let currentSubIdx = 0;

    const buildNotes = (isFirst: boolean) => {
       if (!isFirst) return undefined;
       if (agent1Reasons.length === 0 && agent2Reasons.length === 0) return undefined;
       return {
         agent1: agent1Reasons.length > 0 ? { reason: agent1Reasons.join('\n\n---\n\n'), matchedPoints: [] } : undefined,
         agent2: agent2Reasons.length > 0 ? { logic: agent2Reasons.join('\n\n---\n\n'), dataRequests: [] } : undefined,
       };
    };

    if (!hasSubBlocks) {
        parsedBlocks.push({
          id: `ma-blk-${Date.now()}-${index}-0`,
          title: `${moduleTitle}`,
          original: matchedOrigModule ? matchedOrigModule.content : "💡 未找到对应的原始模块内容...",
          rewritten: cleanBody,
          notes: buildNotes(true)
        });
    } else {
        const parts = cleanBody.split(/(?:^|\n)##\s+/);
        
        if (parts[0].trim()) {
            parsedBlocks.push({
              id: `ma-blk-${Date.now()}-${index}-${currentSubIdx++}`,
              title: `${moduleTitle} - 概述`,
              original: matchedOrigModule ? matchedOrigModule.content : "💡 未找到对应的原始模块内容...",
              rewritten: parts[0].trim(),
              notes: buildNotes(true)
            });
        }

        for (let i = 1; i < parts.length; i++) {
            const sub = parts[i];
            const subLines = sub.split('\n');
            const subTitle = subLines[0].trim();
            const subContent = subLines.slice(1).join('\n').trim();
            
            let matchedOrigText = "💡 未找到对应的原始经历内容，或该段为 AI 新增。";
            if (matchedOrigModule && matchedOrigModule.origSubBlocks.length > 0) {
              const subTimeMatch = subTitle.match(timeRegex) || subContent.match(timeRegex);
              
              if (subTimeMatch) {
                 const timeStr = subTimeMatch[0].replace(/[^\d至今现在Present]/g, ''); 
                 
                 // 先找出所有时间精确匹配的原始子块
                 const origMatches = matchedOrigModule.origSubBlocks.filter(ob => {
                    const obTimeMatch = ob.title.match(timeRegex) || ob.content.match(timeRegex);
                    if (obTimeMatch) {
                       return obTimeMatch[0].replace(/[^\d至今现在Present]/g, '') === timeStr;
                    }
                    return false;
                 });

                 if (origMatches.length === 1) {
                    matchedOrigText = `## ${origMatches[0].fullText}`;
                 } else if (origMatches.length > 1) {
                    // 时间雷同，再执行模糊匹配对应 title 是否符合
                    const keywords = subTitle.split(/\s+/).filter(k => k.length > 1);
                    const bestMatch = origMatches.find(ob => 
                        ob.title.includes(subTitle) || subTitle.includes(ob.title) || 
                        (keywords.length > 0 && keywords.some(k => ob.title.includes(k)))
                    );
                    if (bestMatch) {
                        matchedOrigText = `## ${bestMatch.fullText}`;
                    } else {
                        matchedOrigText = `## ${origMatches[0].fullText}`; // fallback
                    }
                 }
              }
              // 注意：如果没有识别出时间，就直接跳过（不再模糊匹配全局），符合只有时间才匹配的原则
            }

            parsedBlocks.push({
               id: `ma-blk-${Date.now()}-${index}-${currentSubIdx}`,
               title: `${subTitle}`,
               original: matchedOrigText,
               rewritten: subContent,
               notes: buildNotes(parsedBlocks.length === 0)
            });
            currentSubIdx++;
        }
    }

    return {
      id: `ma-mod-${Date.now()}-${index}`,
      title: moduleTitle,
      blocks: parsedBlocks
    } as unknown as ResumeModule;
  });

  // 🌟 将固定的「个人信息」模块置顶，其余 Agent 改写模块紧随其后
  return [...personalInfoModule, ...agentModules];
}

export function ResumeCanvasColumn({ job, onUpdateJob, onExport, exportingType, onClose, onQAComplete }: ResumeCanvasColumnProps) {
  const [modules, setModules] = useState<ResumeModule[]>([])
  const [isSaving, setIsSaving] = useState(false)
  const [isQAEvaluating, setIsQAEvaluating] = useState(false)
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)
  const [skillList, setSkillList] = useState<SkillMeta[]>([])
  const [isSkillDialogOpen, setIsSkillDialogOpen] = useState(false)

  // 🌟 核心状态修复：判别多 Agent 专属状态，接管渲染层级
  const hasMultiAgentData = Boolean((job as any)?.multiAgentRewrite && String((job as any).multiAgentRewrite).trim() !== "");
  // 如果有多 Agent 数据，则必定不是原始简历；否则检查旧字段
  const isRaw = hasMultiAgentData ? false : (!job?.aiRewriteJson || (typeof job.aiRewriteJson === 'string' ? job.aiRewriteJson.trim() === "" : Object.keys(job.aiRewriteJson).length === 0));

  // 🌟 加载 Skill 列表（仅当 job 变化时刷新）
  useEffect(() => {
    if (!job) return
    const loadSkills = async () => {
      try {
        const res = await fetch(`${API_BASE}/resume-editor/skills/`)
        if (res.ok) {
          const data = await res.json()
          if (data.success) {
            setSkillList(data.skills || [])
          }
        }
      } catch (error) {
        console.error("加载 Skill 失败:", error)
      }
    }
    loadSkills()
  }, [job])
  const [isPreviewOpen, setIsPreviewOpen] = useState(false)
  const [matches, setMatches] = useState<MatchLocation[]>([])
  const [currentMatchIndex, setCurrentMatchIndex] = useState(-1)
  const [findText, setFindText] = useState("")
  const [replaceText, setReplaceText] = useState("")
  const [personalInfo, setPersonalInfo] = useState<PersonalInfo>(DEFAULT_PERSONAL_INFO)

  useEffect(() => {
    if (!job) return

    const loadData = async () => {
      let fallbackText = ""

      // 🌟 即使有多 Agent 数据，我们也尝试拉取默认简历，作为 Agent 的原始参照本放入第一模块
      if (!job.manualRefinedResume || hasMultiAgentData) {
        try {
          const res = await fetch(`${API_BASE}/api/strategy/config`)
          if (res.ok) {
            const data = await res.json()
            // 找出我们在"我的简历库"中设置状态为"启用"的底稿
            const activeResume = data.resumes?.find((r: any) => r.status === "启用")
            if (activeResume) {
              fallbackText = activeResume.content
            }
          }
        } catch (e) {
          console.error("拉取大盘默认简历失败", e)
        }
      }

      // 🌟 核心分流：如果是多 Agent 数据，走专属 Markdown 拆解引擎；否则走老版旧解析器
      let parsedModules = []
      if (hasMultiAgentData) {
        parsedModules = parseMultiAgentMarkdownToModules((job as any).multiAgentRewrite, fallbackText)
      } else {
        parsedModules = adapterJobToModules(job, fallbackText)
      }
      
      // 剥离个人信息模块，交给顶层组件独立渲染
      const piModule = parsedModules.find(m => m.title.includes('个人信息') || m.title.includes('基本信息') || m.title.includes('联系方式'));
      if (piModule && piModule.blocks.length > 0) {
        setPersonalInfo(parsePersonalInfo(piModule.blocks[0].original));
      } else {
        setPersonalInfo(DEFAULT_PERSONAL_INFO);
      }
      
      setModules(parsedModules.filter(m => !m.title.includes('个人信息') && !m.title.includes('基本信息') && !m.title.includes('联系方式')));
    }

    loadData()
  }, [job, isRaw, hasMultiAgentData])

  const moveCategory = (id: string, direction: "up" | "down") => {
    const index = modules.findIndex((m) => m.id === id)
    if (index === -1) return
    const nextIndex = direction === "up" ? index - 1 : index + 1
    if (nextIndex < 0 || nextIndex >= modules.length) return
    const newModules = [...modules]
    const [removed] = newModules.splice(index, 1)
    newModules.splice(nextIndex, 0, removed)
    setModules(newModules)
  }

  // 🌟 新增：删除整个大模块
  const deleteCategory = (id: string) => {
    if (window.confirm("确定要删除这个大模块吗？操作不可恢复！")) {
      setModules(modules.filter((m) => m.id !== id))
    }
  }

  const moveBlock = (moduleId: string, blockId: string, direction: "up" | "down") => {
    setModules(modules.map((mod) => {
      if (mod.id !== moduleId) return mod
      const index = mod.blocks.findIndex((b) => b.id === blockId)
      if (index === -1) return mod
      const nextIndex = direction === "up" ? index - 1 : index + 1
      if (nextIndex < 0 || nextIndex >= mod.blocks.length) return mod
      const newBlocks = [...mod.blocks]
      const [removed] = newBlocks.splice(index, 1)
      newBlocks.splice(nextIndex, 0, removed)
      return { ...mod, blocks: newBlocks }
    }))
  }

  const addCustomModule = () => {
    const newModule: ResumeModule = {
      id: `cat-custom-${Date.now()}`,
      title: "新自定义模块",
      blocks: [{ id: `block-custom-${Date.now()}`, title: "自定义内容条目", mode: "editable", original: "点击在此处编写新内容..." }],
    }
    setModules([...modules, newModule])
  }

  // 6. 核心功能：查找与替换
  useEffect(() => {
    if (!findText) {
      setMatches([])
      setCurrentMatchIndex(-1)
      return
    }

    const newMatches: MatchLocation[] = []
    modules.forEach((mod) => {
      mod.blocks.forEach((b) => {
        if (b.mode === "editable") {
          let pos = b.original.indexOf(findText)
          while (pos !== -1) {
            newMatches.push({ moduleId: mod.id, blockId: b.id, field: 'original', index: pos })
            pos = b.original.indexOf(findText, pos + findText.length)
          }
        } else if (b.mode !== "cut") {
          const targetText = b.rewritten !== undefined ? b.rewritten : b.original
          const field = b.rewritten !== undefined ? 'rewritten' : 'original'
          let pos = targetText.indexOf(findText)
          while (pos !== -1) {
            newMatches.push({ moduleId: mod.id, blockId: b.id, field, index: pos })
            pos = targetText.indexOf(findText, pos + findText.length)
          }
        }
      })
    })

    setMatches(newMatches)
    setCurrentMatchIndex((prev) => {
      if (newMatches.length === 0) return -1
      if (prev >= newMatches.length) return newMatches.length - 1
      return prev >= 0 ? prev : 0
    })
  }, [modules, findText])

  const handleFindNext = () => {
    if (matches.length > 0) setCurrentMatchIndex((prev) => (prev + 1) % matches.length)
  }

  const handleFindPrev = () => {
    if (matches.length > 0) setCurrentMatchIndex((prev) => (prev - 1 + matches.length) % matches.length)
  }

  const handleReplaceOne = () => {
    if (currentMatchIndex >= 0 && currentMatchIndex < matches.length) {
      const match = matches[currentMatchIndex]
      setModules((prevModules) => prevModules.map((mod) => {
        if (mod.id !== match.moduleId) return mod
        return {
          ...mod,
          blocks: mod.blocks.map((b) => {
            if (b.id !== match.blockId) return b
            const targetText = b[match.field] as string
            const newText = targetText.substring(0, match.index) + replaceText + targetText.substring(match.index + findText.length)
            return { ...b, [match.field]: newText }
          })
        }
      }))
    }
  }

  const handleReplaceAll = () => {
    if (!findText) {
      alert("请输入要查找的内容");
      return;
    }
    let replaceCount = 0;
    const newModules = modules.map(m => ({
      ...m,
      blocks: m.blocks.map(b => {
        if (b.mode === "editable") {
          if (b.original.includes(findText)) {
            replaceCount += b.original.split(findText).length - 1;
            return { ...b, original: b.original.split(findText).join(replaceText) };
          }
        } else if (b.mode !== "cut") {
          const targetText = b.rewritten !== undefined ? b.rewritten : b.original;
          if (targetText.includes(findText)) {
            replaceCount += targetText.split(findText).length - 1;
            const field = b.rewritten !== undefined ? 'rewritten' : 'original';
            return { ...b, [field]: targetText.split(findText).join(replaceText) };
          }
        }
        return b;
      })
    }));

    if (replaceCount > 0) {
      setModules(newModules);
      alert(`✅ 成功替换 ${replaceCount} 处内容`);
    } else {
      alert(`ℹ️ 未在当前简历中找到匹配的文本`);
    }
  }

  // 7. 核心功能：选中文字后一键加粗 (Markdown语法)
  const handleBold = () => {
    const activeEl = document.activeElement as HTMLTextAreaElement;
    if (activeEl && activeEl.tagName === 'TEXTAREA') {
      const start = activeEl.selectionStart;
      const end = activeEl.selectionEnd;
      if (start !== end) {
        const selectedText = activeEl.value.substring(start, end);
        // 使用 execCommand 可以保留历史记录并完美触发 React 的 onChange 数据同步
        document.execCommand('insertText', false, `**${selectedText}**`);
      } else {
        alert("请先选中文本，再点击加粗");
      }
    } else {
      alert("请先点击进入想要编辑的段落，选中文本后再点击加粗");
    }
  }

  const handleSaveResume = async () => {
    setIsSaving(true)
    try {
      const piMarkdown = `# 个人信息\n\n${serializePersonalInfo(personalInfo)}\n\n`
      const resumeMarkdown = piMarkdown + modules.map((m) => `# ${m.title}\n\n${m.blocks.map((b) => isRaw ? b.original : (b.rewritten || b.original)).join("\n\n")}`).join("\n\n")
      const response = await fetch(`${API_BASE}/api/save_manual_resume`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.id, resume_text: resumeMarkdown, platform: job.platform || "BOSS直聘" }),
      })
      const data = await response.json()
      if (response.ok && data.status === "success") {
        onUpdateJob({ ...job, manualRefinedResume: resumeMarkdown })
        alert("✅ 简历修改已成功持久化同步到飞书多维表格！")
      } else alert("❌ 保存失败：" + (data.detail || "未知错误"))
    } catch { alert("❌ 网络异常，保存失败") }
    finally { setIsSaving(false) }
  }

  const handleQAEvaluate = async () => {
    setIsQAEvaluating(true)
    try {
      const flatText = `# 个人信息\n${serializePersonalInfo(personalInfo)}\n\n` + modules.map((m) => `${m.title}\n${m.blocks.map((b) => b.rewritten).join("\n")}`).join("\n\n")
      const response = await fetch(`${API_BASE}/api/qa_evaluate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.id, job_description: job.jobDescription, resume_text: flatText, platform: job.platform || "BOSS直聘" }),
      })
      const data = await response.json()
      if (response.ok && data.status === "success") {
        onQAComplete?.(data.qa_report)
        onUpdateJob({ ...job, secondQaReport: JSON.stringify(data.qa_report) })
        alert("🔍 AI 自动化质检完成！反幻觉与数据合规报告已回写。")
      }
    } catch { alert("❌ 质检请求失败") }
    finally { setIsQAEvaluating(false) }
  }

  // 🌟 新增：触发自定义 Skill 执行
  const handleExecuteSkill = async () => {
    if (!selectedSkill) {
      alert("⚠️ 请先选择一个技能！")
      return
    }
  
    if (!job?.id) {
      alert("⚠️ 当前岗位信息异常")
      return
    }
  
    try {
      // 1. 组装当前简历文本
      const mdParts: string[] = []
      mdParts.push(`# 个人信息\n\n${serializePersonalInfo(personalInfo)}\n`)
        
      for (const mod of modules) {
        if (!mod.title.trim() && mod.blocks.length === 0) continue
        const blockContents = mod.blocks.map(b => isRaw ? b.original : (b.rewritten || b.original)).filter(Boolean).join("\n\n")
        if (blockContents) {
          mdParts.push(`# ${mod.title}\n\n${blockContents}\n`)
        }
      }
      const currentResumeMarkdown = mdParts.join("\n").trim()
  
      // 2. 获取岗位 JD
      const jdText = job.jobDescription || ""
      const diagnosisReport = job.compositeDiagnosisReport || null
  
      // 3. 调用 Skill Executor API
      const formData = new FormData()
      formData.append("skill_id", selectedSkill)
      formData.append("resume_data", JSON.stringify({ resume_text: currentResumeMarkdown }))
      formData.append("jd_text", jdText)
      formData.append("include_diagnosis", diagnosisReport ? "true" : "false")
  
      // 4. 发送到后台队列
      const response = await fetch(`${API_BASE}/api/resume-editor/skills/execute/${selectedSkill}`, {
        method: "POST",
        body: formData,
      })
  
      const data = await response.json()
      if (!response.ok || !data.success) {
        throw new Error(data.error || data.detail || "Skill 执行请求失败")
      }
  
      // 5. 通知前端监听进度
      const event = new CustomEvent('START_SKILL_TASK', {
        detail: {
          skillId: selectedSkill,
          taskId: data.task_id || data.storage_dir,
          jobId: job.id
        }
      })
      window.dispatchEvent(event)
  
      alert(`✅ Skill "${selectedSkill}" 已开始执行！\n\n完成后将在简历画布中显示结果。`)
    } catch (err: any) {
      alert(`❌ Skill 执行失败：${err.message || err}`)
    }
  }
  
  // 🌟 新增：监听飞书数据更新，自动回填到画布
  useEffect(() => {
    // 当用户从飞书刷新时，检查是否有新的改写结果
    if (!job || modules.length === 0) return
    
    const multiAgentData = (job as any)?.multiAgentRewrite
    if (!multiAgentData) return
    
    // 解析多 Agent 改写结果（复用现有解析器）
    const fallbackText = job.manualRefinedResume || ""
    const parsedModules = parseMultiAgentMarkdownToModules(multiAgentData, fallbackText)
    
    // 提取除「个人信息」外的所有模块
    const resumeModules = parsedModules.filter(m => 
      !m.title.includes('个人信息') && !m.title.includes('基本信息') && !m.title.includes('联系方式')
    )
    
    if (resumeModules.length > 0) {
      console.log(`🔄 [Skill] 检测到新改写结果，准备回填画布（模块数：${resumeModules.length}）`)
      setModules(resumeModules)
      
      // 显示 Toast 提示
      setTimeout(() => {
        alert(`✨ 已检测到外部改写结果！\n\n共 ${resumeModules.length} 个模块已自动更新到简历画布。`)
      }, 500)
    }
  }, [job?.manualRefinedResume, job?.multiAgentRewrite])

  return (
    <div data-resume-canvas className="relative flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-slate-100/60">
      <Toolbar
        onPreview={() => setIsPreviewOpen(true)}
        onSave={handleSaveResume} isSaving={isSaving}
        onQA={handleQAEvaluate} isQA={isQAEvaluating} onExport={onExport}
        findText={findText} setFindText={setFindText}
        replaceText={replaceText} setReplaceText={setReplaceText}
        onReplaceAll={handleReplaceAll} // 👈 传入替换事件
        onReplaceOne={handleReplaceOne}
        onFindNext={handleFindNext}
        onFindPrev={handleFindPrev}
        matchCount={matches.length}
        currentMatchIndex={currentMatchIndex}
        onBold={handleBold}             // 👈 传入加粗事件
        selectedSkill={selectedSkill} setSelectedSkill={setSelectedSkill} setIsSkillDialogOpen={setIsSkillDialogOpen}
      />
      
      {/* 🌟 Skill Selector Dialog */}
      <Dialog open={isSkillDialogOpen} onOpenChange={setIsSkillDialogOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>🧬 选择 AI 技能执行</DialogTitle>
            <DialogDescription>
              选择一个技能来处理当前简历。技能将在后台异步执行，完成后结果会显示在简历画布中。
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">技能选择</label>
              <Select value={selectedSkill || ""} onValueChange={(val) => setSelectedSkill(val)}>
                <SelectTrigger>
                  <SelectValue placeholder="请选择一个技能" />
                </SelectTrigger>
                <SelectContent>
                  {skillList.map(skill => (
                    <SelectItem key={skill.id} value={skill.id}>
                      {skill.name} {skill.is_official && "⭐官方"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">上传自定义技能</label>
              <Button variant="outline" size="sm" onClick={() => alert("上传功能即将实现")}>📤 上传.md 文件</Button>
            </div>
            
            <Separator />
            
            <div className="bg-blue-50 p-3 rounded-lg text-sm text-blue-800">
              <p className="font-semibold mb-1">💡 使用说明：</p>
              <ul className="list-disc list-inside space-y-1 text-xs">
                <li>点击技能名称可选择不同的 AI 技能</li>
                <li>技能执行需要一些时间，请耐心等待</li>
                <li>执行结果会自动保存到简历画布中</li>
              </ul>
            </div>
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsSkillDialogOpen(false)}>取消</Button>
            <Button 
              onClick={() => {
                if (selectedSkill) {
                  handleExecuteSkill()
                  setIsSkillDialogOpen(false)
                } else {
                  alert("请先选择一个技能！")
                }
              }}
              disabled={!selectedSkill}
            >
              执行所选技能 (${selectedSkill})
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ScrollArea className="min-h-0 flex-1">
        <div className="mx-auto flex max-w-4xl flex-col gap-6 p-5 pb-24">
          
          {/* 🌟 WOW UI Top Dashboard */}
          {!isRaw && modules.length > 0 && hasMultiAgentData && (
            <RewriteDashboard 
              rawResumeText={modules.map(m => m.blocks.map(b => b.original).join("\n")).join("\n")} 
              rewrittenText={modules.map(m => m.blocks.map(b => b.rewritten).join("\n")).join("\n")} 
            />
          )}

          {/* 🌟 个人信息头 (Hero Banner) */}
          <PersonalInfoHeader 
            info={personalInfo} 
            onChange={setPersonalInfo} 
            isRaw={isRaw} 
          />

          {modules.map((module, mIndex) => (
            <section key={module.id} className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white/40 p-3 shadow-xs">
              <div className="flex items-center gap-2 rounded-xl bg-slate-200/50 px-3 py-1.5 focus-within:bg-slate-200/80 transition-colors">
                <span className="h-3.5 w-1 rounded-full bg-indigo-600 shrink-0" />
                {/* 🌟 替换为原生 Input，点击即可直接编辑标题名称 */}
                <input
                  value={module.title}
                  onChange={(e) => setModules(modules.map((m) => m.id === module.id ? { ...m, title: e.target.value } : m))}
                  className="flex-1 bg-transparent text-xs font-bold tracking-tight text-slate-800 outline-none hover:bg-slate-300/40 px-1.5 py-0.5 rounded transition-colors focus:bg-white focus:ring-1 focus:ring-indigo-300"
                  placeholder="请输入模块名称"
                />
                <CategoryReorderBar
                  onMoveUp={() => moveCategory(module.id, "up")}
                  onMoveDown={() => moveCategory(module.id, "down")}
                  onDelete={() => deleteCategory(module.id)} // 👈 传入删除事件
                  canMoveUp={mIndex > 0}
                  canMoveDown={mIndex < modules.length - 1}
                />
              </div>
              <div className="flex flex-col gap-3">
                {module.blocks.map((block, index) => (
                  <ResumeDiffBlock
                    key={block.id}
                    block={block}
                    isRaw={isRaw}
                    // 👇 新增传递的属性：供底层高亮和定位使用
                    moduleId={module.id}
                    findText={findText}
                    matches={matches}
                    currentMatchIndex={currentMatchIndex}
                    // 👆 --------------------------------
                    onChangeRewritten={(val) => setModules(modules.map((m) => m.id === module.id ? { ...m, blocks: m.blocks.map((b) => (b.id === block.id ? { ...b, rewritten: val } : b)) } : m))}
                    onChangeOriginal={(val) => setModules(modules.map((m) => m.id === module.id ? { ...m, blocks: m.blocks.map((b) => (b.id === block.id ? { ...b, original: val } : b)) } : m))}
                    onMoveUp={() => moveBlock(module.id, block.id, "up")}
                    onMoveDown={() => moveBlock(module.id, block.id, "down")}
                    canMoveUp={index > 0}
                    canMoveDown={index < module.blocks.length - 1}
                  />
                ))}
              </div>
            </section>
          ))}
          <button type="button" onClick={addCustomModule} className="flex w-full items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300 bg-white/50 py-3 text-xs font-medium text-slate-500 hover:border-indigo-400 hover:bg-indigo-50/30 hover:text-indigo-600"><Plus className="size-4" />添加自定义模块</button>
        </div>
      </ScrollArea>
      {isPreviewOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs">
          <div className="flex h-[90vh] w-[840px] flex-col rounded-2xl bg-white p-5 shadow-2xl">
            <div className="flex items-center justify-between border-b pb-2">
              <h3 className="text-sm font-bold text-slate-800">👁️ 简历渲染纸张标准排版预览 (A4 Sheet 模拟)</h3>
              <Button variant="ghost" size="icon" onClick={() => setIsPreviewOpen(false)}><X className="size-4" /></Button>
            </div>
            <div className="flex-1 overflow-y-auto bg-slate-100 p-6 flex justify-center">
              <div className="w-[595px] min-h-[842px] bg-white p-8 shadow-md border border-slate-200 text-[11px] leading-relaxed text-slate-900 font-sans space-y-4">
                <div className="text-center border-b pb-2">
                  <h1 className="text-base font-bold tracking-wide">{personalInfo.name || "候选人"}</h1>
                  <p className="text-slate-500 text-[10px] mt-1">{personalInfo.jobTitle} | {personalInfo.fields.map(f => f.value).join(" | ")}</p>
                </div>
                {modules.map(m => (
                  <div key={m.id} className="space-y-1"><h2 className="font-bold text-xs border-b border-slate-300 pb-0.5 text-indigo-900">{m.title}</h2><p className="whitespace-pre-wrap text-slate-700 text-[10.5px]">{m.blocks.map(b => b.rewritten || b.original).join("\n")}</p></div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// 替换现有的 Toolbar 组件
function Toolbar({
  onPreview,
  onSave,
  isSaving,
  onQA,
  isQA,
  onExport,
  findText,
  setFindText,
  replaceText,
  setReplaceText,
  onReplaceAll,
  onReplaceOne,
  onFindNext,
  onFindPrev,
  matchCount,
  currentMatchIndex,
  onBold,
  isMultiAgentRewriting,
  selectedSkill,
  setSelectedSkill,
  setIsSkillDialogOpen
}: any) {
  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex items-center gap-1 border-b border-border bg-card px-3 py-2 pr-12 shadow-sm">
        <span className="mr-3 text-sm font-semibold text-slate-800">
          简历编辑区
        </span>

        {/* 🌟 Skill Selector */}
        <SkillSelector 
          selectedSkill={selectedSkill}
          onChange={(skillId) => setSelectedSkill(skillId)}
          className="h-7"
        />

        {/* 🌟 真实加粗功能 */}
        <Tooltip>
          <TooltipTrigger asChild>
            {/* 注意这里的 onMouseDown: 极度关键的黑科技，防止点击按钮时输入框失去焦点导致选区消失 */}
            <Button size="icon" variant="ghost" className="size-8 text-slate-600" onClick={onBold} onMouseDown={(e) => e.preventDefault()}>
              <Bold className="size-4" />
              <span className="sr-only">加粗</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>加粗 (选中文字后点击)</TooltipContent>
        </Tooltip>

        {/* 🌟 Word 同款查找与替换小弹窗 (Popover) */}
        <Popover>
          <Tooltip>
            <TooltipTrigger asChild>
              <PopoverTrigger asChild>
                <Button size="icon" variant="ghost" className="size-8 text-slate-600">
                  <Replace className="size-4" />
                  <span className="sr-only">查找与替换</span>
                </Button>
              </PopoverTrigger>
            </TooltipTrigger>
            <TooltipContent>查找与替换</TooltipContent>
          </Tooltip>

          <PopoverContent className="w-80 p-4 shadow-xl rounded-xl border-slate-200" align="start">
            <div className="flex flex-col gap-3.5">
              <h4 className="text-sm font-bold text-slate-800">查找与替换</h4>
              <div className="flex flex-col gap-2.5">
                <div className="relative flex items-center">
                  <Search className="absolute left-2.5 size-4 text-slate-400" />
                  <Input
                    placeholder="要查找的词..."
                    value={findText}
                    onChange={(e) => setFindText(e.target.value)}
                    className="h-8 pl-8 pr-20 text-xs focus-visible:ring-indigo-500"
                  />
                  {findText && (
                    <div className="absolute right-1 flex items-center gap-0.5 text-[10px] text-slate-400">
                      <span className="mr-1">{matchCount > 0 ? currentMatchIndex + 1 : 0}/{matchCount}</span>
                      <Button variant="ghost" size="icon" className="size-6 p-0 hover:bg-slate-100" onClick={onFindPrev}>
                        <ChevronUp className="size-3" />
                      </Button>
                      <Button variant="ghost" size="icon" className="size-6 p-0 hover:bg-slate-100" onClick={onFindNext}>
                        <ChevronDown className="size-3" />
                      </Button>
                    </div>
                  )}
                </div>
                <Input
                  placeholder="替换为..."
                  value={replaceText}
                  onChange={(e) => setReplaceText(e.target.value)}
                  className="h-8 text-xs focus-visible:ring-indigo-500"
                />
              </div>
              <div className="flex items-center gap-2">
                <Button variant="secondary" size="sm" className="flex-1 h-8 text-xs font-medium" onClick={onReplaceOne}>
                  替换
                </Button>
                <Button size="sm" className="flex-1 h-8 text-xs bg-indigo-600 hover:bg-indigo-700 font-medium" onClick={onReplaceAll}>
                  全部替换
                </Button>
              </div>
            </div>
          </PopoverContent>
        </Popover>

        <Separator orientation="vertical" className="mx-2 h-5" />

        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="icon" variant="ghost" className="size-8 text-slate-600 hover:bg-indigo-50 hover:text-indigo-600" onClick={onSave} disabled={isSaving}>
              {isSaving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
              <span className="sr-only">保存到飞书</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>保存到飞书</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="icon" variant="ghost" className="size-8 text-slate-600 hover:text-purple-600 hover:bg-purple-50" onClick={onQA} disabled={isQA}>
              {isQA ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
              <span className="sr-only">再次 AI 评估</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>再次 AI 评估 (QA 质检)</TooltipContent>
        </Tooltip>
        
        {/* 🌟 新增：Skill Selector - 点击打开技能选择对话框 */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="size-8 text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 font-bold border border-indigo-100 bg-indigo-50/30 animate-pulse animate-duration-1000"
              onClick={() => setIsSkillDialogOpen(true)}
            >
              <Sparkles className="size-4 text-indigo-600" />
            </Button>
          </TooltipTrigger>
          <TooltipContent><span className="font-semibold text-indigo-600">🧬 选择并执行 AI 技能</span></TooltipContent>
        </Tooltip>

        <Separator orientation="vertical" className="mx-2 h-5" />

        <ToolbarButton icon={<ImageIcon className="size-4" />} label="导出图片" onClick={() => onExport("image")} />
        <ToolbarButton icon={<FileDown className="size-4" />} label="导出 PDF" onClick={() => onExport("pdf")} />

        <Separator orientation="vertical" className="mx-2 h-5" />

        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="sm" onClick={onPreview} className="ml-auto h-8 gap-1.5 bg-slate-900 text-white hover:bg-slate-800">
              <Eye className="size-4" />
              纸张排版预览
            </Button>
          </TooltipTrigger>
          <TooltipContent>模拟 A4 纸张排版间距</TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>
  )
}

// 新增的辅助图标按钮组件（v0 原生风格）
function ToolbarButton({
  icon,
  label,
  onClick
}: {
  icon: React.ReactNode
  label: string
  onClick?: () => void
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button size="icon" variant="ghost" className="size-8 text-slate-600" onClick={onClick}>
          {icon}
          <span className="sr-only">{label}</span>
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

function CategoryReorderBar({ onMoveUp, onMoveDown, onDelete, canMoveUp, canMoveDown }: any) {
  return (
    <div className="ml-auto flex items-center gap-0.5 rounded-md bg-white/80 p-0.5 shadow-xs ring-1 ring-slate-200">
      <span className="flex size-6 cursor-grab items-center justify-center text-slate-400 active:cursor-grabbing"><GripVertical className="size-3" /></span>
      <Button variant="ghost" size="icon" className="size-6 text-slate-400 hover:text-slate-700" disabled={!canMoveUp} onClick={onMoveUp}><ArrowUp className="size-3" /></Button>
      <Button variant="ghost" size="icon" className="size-6 text-slate-400 hover:text-slate-700" disabled={!canMoveDown} onClick={onMoveDown}><ArrowDown className="size-3" /></Button>

      {/* 🌟 增加一条细分割线和垃圾桶删除按钮 */}
      <div className="w-px h-3 bg-slate-300 mx-0.5" />
      <Button variant="ghost" size="icon" className="size-6 text-slate-400 hover:text-red-600 hover:bg-red-50" onClick={onDelete}>
        <Trash2 className="size-3" />
      </Button>
    </div>
  )
}