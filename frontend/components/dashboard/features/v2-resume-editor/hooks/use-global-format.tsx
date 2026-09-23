"use client"

import { API_BASE } from "@/lib/api"
import { useState, useRef, useCallback } from "react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { toast } from "@/hooks/use-toast"
import { ToastAction } from "@/components/ui/toast"
import { formatMarkdownPangu, normalizeBulletLines } from "../utils/resume-search-utils"
import type { ResumeDataV2 } from "@/types/resume"

interface FormatTask {
  id: string
  title: string
  content: string
  apply: (formatted: string) => void
  isStale: () => boolean
}

export function useGlobalFormat() {
  const {
    updateSummary,
    updateAdditional,
    updateWorkExperience,
    updateProject,
    updateEducation,
  } = useResumeV2Store()

  const [isGlobalFormatting, setIsGlobalFormatting] = useState(false)
  const [globalFormatProgress, setGlobalFormatProgress] = useState("")

  const sessionRef = useRef<number>(0)
  const abortControllerRef = useRef<AbortController | null>(null)

  const handleGlobalFormat = useCallback(async () => {
    const { resumeData } = useResumeV2Store.getState()
    if (!resumeData) return

    // 1. 保存排版前深度快照，用于支持「智能差异化撤销」
    const preFormatSnapshot: ResumeDataV2 = JSON.parse(JSON.stringify(resumeData))

    // 2. 初始化会话令牌与中断控制器
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const abortController = new AbortController()
    abortControllerRef.current = abortController
    const sessionId = ++sessionRef.current

    setIsGlobalFormatting(true)
    setGlobalFormatProgress("正在应用基础排版规范...")

    try {
      // 3. 【L1 级秒级排版】：本地盘古空格、标点和 Markdown 快速规范化 (<10ms)
      // 严格遵循保型规则：string 进 string 出，string[] 进 string[] 出
      let l1Summary = ""
      if (resumeData.summary) {
        l1Summary = formatMarkdownPangu(resumeData.summary)
        updateSummary(l1Summary)
      }

      let l1Skills: string[] = []
      if (resumeData.additional?.technicalSkills?.length) {
        l1Skills = resumeData.additional.technicalSkills.map((s) => formatMarkdownPangu(s))
        updateAdditional({ technicalSkills: l1Skills })
      }

      const l1WorkList: Array<{ isString: boolean; lines: string[] }> = []
      if (resumeData.workExperience?.length) {
        resumeData.workExperience.forEach((exp, i) => {
          const rawDesc = (exp as any).description
          const isString = typeof rawDesc === "string"
          const lines: string[] = Array.isArray(rawDesc)
            ? rawDesc
            : isString
            ? rawDesc.split("\n")
            : []
          // 盘古空格 → bullet 规范化：经历描述逐行补齐 '- ' 前缀（已在全局排版 fix 排版丑观感）
          const formattedLines = normalizeBulletLines(lines.map((line: string) => formatMarkdownPangu(line)).join("\n")).split("\n")
          l1WorkList.push({ isString, lines: formattedLines })
          updateWorkExperience(i, {
            description: (isString ? formattedLines.join("\n") : formattedLines) as any,
          })
        })
      }

      const l1ProjectList: Array<{ isString: boolean; lines: string[] }> = []
      if (resumeData.personalProjects?.length) {
        resumeData.personalProjects.forEach((proj, i) => {
          const rawDesc = (proj as any).description
          const isString = typeof rawDesc === "string"
          const lines: string[] = Array.isArray(rawDesc)
            ? rawDesc
            : isString
            ? rawDesc.split("\n")
            : []
          const formattedLines = normalizeBulletLines(lines.map((line: string) => formatMarkdownPangu(line)).join("\n")).split("\n")
          l1ProjectList.push({ isString, lines: formattedLines })
          updateProject(i, {
            description: (isString ? formattedLines.join("\n") : formattedLines) as any,
          })
        })
      }

      const l1EduList: string[] = []
      if (resumeData.education?.length) {
        resumeData.education.forEach((edu, i) => {
          const desc = Array.isArray(edu.description)
            ? edu.description.join("\n")
            : edu.description || ""
          const formattedDesc = formatMarkdownPangu(desc)
          l1EduList.push(formattedDesc)
          updateEducation(i, { description: formattedDesc })
        })
      }

      toast({
        title: "⚡ 基础排版已生效",
        description: "盘古空格与中英文排版已秒级就绪，正在后台并发精细排版...",
      })

      // 4. 组装 【L2 级 AI 精细排版】 任务队列
      const tasks: FormatTask[] = []

      if (l1Summary.trim()) {
        tasks.push({
          id: "summary",
          title: "个人总结",
          content: l1Summary,
          apply: (res) => updateSummary(res),
          isStale: () => {
            const current = useResumeV2Store.getState().resumeData?.summary
            return sessionRef.current !== sessionId || current !== l1Summary
          },
        })
      }

      if (l1Skills.length > 0) {
        const skillsContent = l1Skills.join("\n")
        tasks.push({
          id: "skills",
          title: "专业技能",
          content: skillsContent,
          apply: (res) => updateAdditional({ technicalSkills: res.split("\n") }),
          isStale: () => {
            const current = useResumeV2Store.getState().resumeData?.additional?.technicalSkills?.join("\n")
            return sessionRef.current !== sessionId || current !== skillsContent
          },
        })
      }

      if (resumeData.workExperience?.length) {
        resumeData.workExperience.forEach((exp, i) => {
          const item = l1WorkList[i]
          const content = item?.lines.join("\n") || ""
          if (content.trim()) {
            const title = exp.company || exp.title || `工作经历 ${i + 1}`
            tasks.push({
              id: `work-${i}`,
              title,
              content,
              apply: (res) => {
                const finalDesc = item.isString ? res : res.split("\n")
                updateWorkExperience(i, { description: finalDesc as any })
              },
              isStale: () => {
                const curDesc = (useResumeV2Store.getState().resumeData?.workExperience?.[i]?.description as any)
                const curContent = Array.isArray(curDesc) ? curDesc.join("\n") : (curDesc || "")
                return sessionRef.current !== sessionId || curContent !== content
              },
            })
          }
        })
      }

      if (resumeData.personalProjects?.length) {
        resumeData.personalProjects.forEach((proj, i) => {
          const item = l1ProjectList[i]
          const content = item?.lines.join("\n") || ""
          if (content.trim()) {
            const title = proj.name || `项目经历 ${i + 1}`
            tasks.push({
              id: `proj-${i}`,
              title,
              content,
              apply: (res) => {
                const finalDesc = item.isString ? res : res.split("\n")
                updateProject(i, { description: finalDesc as any })
              },
              isStale: () => {
                const curDesc = (useResumeV2Store.getState().resumeData?.personalProjects?.[i]?.description as any)
                const curContent = Array.isArray(curDesc) ? curDesc.join("\n") : (curDesc || "")
                return sessionRef.current !== sessionId || curContent !== content
              },
            })
          }
        })
      }

      if (resumeData.education?.length) {
        resumeData.education.forEach((edu, i) => {
          const content = l1EduList[i] || ""
          if (content.trim()) {
            const title = edu.institution || `教育背景 ${i + 1}`
            tasks.push({
              id: `edu-${i}`,
              title,
              content,
              apply: (res) => updateEducation(i, { description: res }),
              isStale: () => {
                const current = useResumeV2Store.getState().resumeData?.education?.[i]?.description
                return sessionRef.current !== sessionId || current !== content
              },
            })
          }
        })
      }

      if (tasks.length === 0) {
        setIsGlobalFormatting(false)
        setGlobalFormatProgress("")
        return
      }

      // 5. 【受控并发调度】：并发限制为 2，单任务 180s 超时与错误强隔离
      const formatApiWithTimeout = async (task: FormatTask): Promise<{ ok: boolean; formatted: string }> => {
        const timeoutController = new AbortController()
        const timeoutId = setTimeout(() => timeoutController.abort(), 180000)

        const onAbort = () => timeoutController.abort()
        abortControllerRef.current?.signal.addEventListener("abort", onAbort)

        try {
          const res = await fetch(`${API_BASE}/api/strategy/format_markdown`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ module_title: task.title, current_content: task.content }),
            signal: timeoutController.signal,
          })
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          const data = await res.json()
          if (data.status === "success" && data.data?.formatted_content) {
            return { ok: true, formatted: data.data.formatted_content }
          }
          return { ok: false, formatted: task.content }
        } catch (err) {
          console.warn(`[L2 Format] 模块「${task.title}」排版未完成，保留 L1 结果:`, err)
          return { ok: false, formatted: task.content }
        } finally {
          clearTimeout(timeoutId)
          abortControllerRef.current?.signal.removeEventListener("abort", onAbort)
        }
      }

      let completedCount = 0
      let successCount = 0
      let failedCount = 0

      // 简易滑动窗口并发池 (concurrency limit = 2)
      const concurrency = 2
      let activeIndex = 0

      const runWorker = async () => {
        while (activeIndex < tasks.length) {
          if (sessionRef.current !== sessionId) return
          const currentTaskIndex = activeIndex++
          const task = tasks[currentTaskIndex]
          if (!task) break

          const result = await formatApiWithTimeout(task)
          if (sessionRef.current !== sessionId) return

          completedCount++
          setGlobalFormatProgress(`AI精细排版 (${completedCount}/${tasks.length})...`)

          if (result.ok) {
            successCount++
            // 竞态守卫：确保此期间用户未打字编辑该模块
            if (!task.isStale()) {
              task.apply(result.formatted)
            } else {
              console.info(`[L2 Format] 模块「${task.title}」内容已被用户编辑或会话已过期，丢弃覆盖`)
            }
          } else {
            failedCount++
          }
        }
      }

      const workers = Array.from({ length: Math.min(concurrency, tasks.length) }, () => runWorker())
      await Promise.all(workers)

      if (sessionRef.current === sessionId) {
        toast({
          title: "✅ 全局排版已完成",
          description: `AI 排版完成 (成功 ${successCount} 个模块${failedCount > 0 ? `，${failedCount} 个保留基础规范` : ""})`,
          action: (
            <ToastAction
              altText="撤销本次排版"
              onClick={() => {
                const current = useResumeV2Store.getState().resumeData
                if (!current) return

                // 智能差异化局部回滚：先做结构防呆校验，杜绝用户在排版期间删减条目后点撤销导致下标错位串条
                const isWorkLengthMatch = (current.workExperience?.length || 0) === (preFormatSnapshot.workExperience?.length || 0)
                const isProjLengthMatch = (current.personalProjects?.length || 0) === (preFormatSnapshot.personalProjects?.length || 0)
                const isEduLengthMatch = (current.education?.length || 0) === (preFormatSnapshot.education?.length || 0)

                const revertedWork = isWorkLengthMatch
                  ? (current.workExperience || []).map((w, idx) => {
                      const snapW = preFormatSnapshot.workExperience?.[idx]
                      // 双重防线：条目名称对齐才还原描述，若条目被置换则保留当前
                      if (snapW && (w.company === snapW.company || w.title === snapW.title || !w.company)) {
                        return { ...w, description: snapW.description }
                      }
                      return w
                    })
                  : current.workExperience

                const revertedProj = isProjLengthMatch
                  ? (current.personalProjects || []).map((p, idx) => {
                      const snapP = preFormatSnapshot.personalProjects?.[idx]
                      if (snapP && (p.name === snapP.name || p.role === snapP.role || !p.name)) {
                        return { ...p, description: snapP.description }
                      }
                      return p
                    })
                  : current.personalProjects

                const revertedEdu = isEduLengthMatch
                  ? (current.education || []).map((e, idx) => {
                      const snapE = preFormatSnapshot.education?.[idx]
                      if (snapE && (e.institution === snapE.institution || e.major === snapE.major || !e.institution)) {
                        return { ...e, description: snapE.description }
                      }
                      return e
                    })
                  : current.education

                const revertedData: ResumeDataV2 = {
                  ...current,
                  summary: preFormatSnapshot.summary,
                  additional: {
                    ...current.additional,
                    technicalSkills: preFormatSnapshot.additional?.technicalSkills || [],
                  },
                  workExperience: revertedWork,
                  personalProjects: revertedProj,
                  education: revertedEdu,
                }
                useResumeV2Store.getState().setResumeData(revertedData)
                const hasStructureChange = !isWorkLengthMatch || !isProjLengthMatch || !isEduLengthMatch
                toast({
                  title: "已撤销排版",
                  description: hasStructureChange
                    ? "已安全回滚未增删的模块格式，并保留您在排版期间新增/删除的条目与手动编辑"
                    : "已安全回滚排版格式，保留您在排版期间的手动编辑",
                })
              }}
            >
              撤销排版
            </ToastAction>
          ),
        })
      }
    } catch (e: any) {
      console.error("[useGlobalFormat] 全局排版异常:", e)
      toast({
        variant: "destructive",
        title: "❌ 全局自动排版发生错误",
        description: e.message || "请检查网络或后端状态",
      })
    } finally {
      if (sessionRef.current === sessionId) {
        setIsGlobalFormatting(false)
        setGlobalFormatProgress("")
      }
    }
  }, [
    updateSummary,
    updateAdditional,
    updateWorkExperience,
    updateProject,
    updateEducation,
  ])

  return {
    isGlobalFormatting,
    globalFormatProgress,
    handleGlobalFormat,
  }
}
