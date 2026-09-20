"use client"

// 简历库顶栏动作集合 hook（从 resume-builder/index.tsx 拆出，Q-M4-6 行数治理）
// 覆盖：Skill 母版改写 / 保存 PDF / 保存图片 / 单模块排版 / 全局排版

import { useState } from "react"
import { useStrategyStore } from "@/hooks/use-strategy-store"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import type { ResumeDataV2 } from "@/types/resume"
import { API_BASE } from "@/lib/api"
import { runSkillRewrite, fetchGlobalJdReport } from "@/hooks/use-skill-rewrite"

export function useResumeBuilderActions(opts: {
    activeId: string
    resumeName: string
    selectedSkill: string | null
    setArtifactsOpen: (open: boolean) => void
}) {
    const { activeId, resumeName, selectedSkill, setArtifactsOpen } = opts
    const { fetchConfig, handleSave } = useStrategyStore()
    const { resumeData, setResumeData, updateSummary, updateAdditional, updateWorkExperience, updateProject, updateEducation } = useResumeV2Store()

    // 🌟 Skill 智能体改写状态
    const [isTestingSkill, setIsTestingSkill] = useState(false)

    // AI 排版状态
    const [formattingModuleId, setFormattingModuleId] = useState<string | null>(null)

    // 全局排版状态
    const [isGlobalFormatting, setIsGlobalFormatting] = useState(false)
    const [globalFormatProgress, setGlobalFormatProgress] = useState("")

    // 🌟 PDF 生成状态
    const [isGeneratingPdf, setIsGeneratingPdf] = useState(false)

    // 🌟 图片长图生成状态
    const [isGeneratingImages, setIsGeneratingImages] = useState(false)

    // 🌟 执行 Skill 母版改写
    const handleSkillRewrite = async () => {
        if (!activeId) {
            alert("请先选择一份简历！")
            return
        }
        if (activeId.startsWith("temp_")) {
            alert("该简历为未保存的本地草稿，请先点击右上角「保存并同步」！")
            return
        }

        setIsTestingSkill(true)
        try {
            const jdReport = await fetchGlobalJdReport()
            if (!jdReport || !jdReport.trim()) {
                alert("⚠️ 尚未生成 A 级岗位画像！请先点击「A级岗位画像」生成后，再执行改写。")
                return
            }

            const res = await runSkillRewrite({
                jd_text: jdReport,
                job_name: `${resumeName || "通用母版简历"}（简历库全局改写）`,
                resume_record_id: activeId,
                skill_id: selectedSkill || undefined,
            })

            if (res.parsed_json) {
                setResumeData(res.parsed_json as ResumeDataV2)
                fetchConfig(activeId)
            }

            alert("✅ Skill 母版简历改写完成，已实时写回底稿！")
            if (selectedSkill && selectedSkill !== "resume_rewrite") {
                setArtifactsOpen(true)
            }
        } catch (err: any) {
            alert("❌ Skill 改写失败: " + (err?.message || "未知错误"))
        } finally {
            setIsTestingSkill(false)
        }
    }

    // 🌟 导出公共链路（R1 审查 P2 去重）：先保存拿真实 record_id（新建简历保存前是 temp_ 本地草稿，
    // 后端无法渲染），再用保存后的 ID 请求渲染端点
    const exportResumeArtifact = async (
        endpoint: "resume-pdf" | "resume-images",
        template: "classic" | "color",
        artifactLabel: string,
    ): Promise<string> => {
        const savedId = await handleSave()
        if (!savedId) throw new Error(`简历未保存成功，无法生成${artifactLabel}`)
        const res = await fetch(`${API_BASE}/api/strategy/${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ record_id: savedId, page_size: "A4", template })
        })
        if (!res.ok) throw new Error(`生成${artifactLabel}失败`)
        const data = await res.json()
        return data.message || `${artifactLabel}已生成并保存至飞书`
    }

    const handleSavePdf = async (template: "classic" | "color" = "classic") => {
        try {
            setIsGeneratingPdf(true)
            alert(await exportResumeArtifact("resume-pdf", template, "PDF"))
        } catch (error: any) {
            alert(error.message)
        } finally {
            setIsGeneratingPdf(false)
        }
    }

    const handleSaveImages = async (template: "classic" | "color" = "classic") => {
        try {
            setIsGeneratingImages(true)
            alert(await exportResumeArtifact("resume-images", template, "图片"))
        } catch (error: any) {
            alert(error.message)
        } finally {
            setIsGeneratingImages(false)
        }
    }

    const handleFormatMarkdown = async (id: string, title: string, content: string, onChange: (val: string) => void) => {
        if (!content.trim()) return
        setFormattingModuleId(id)
        try {
            const res = await fetch(`${API_BASE}/api/strategy/format_markdown`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ module_title: title, current_content: content })
            })
            const data = await res.json()
            if (data.status === "success" && data.data?.formatted_content) {
                onChange(data.data.formatted_content)
            }
        } catch (e) {
            console.error("Format markdown failed:", e)
        } finally {
            setFormattingModuleId(null)
        }
    }

    const handleGlobalFormat = async () => {
        if (!resumeData) return
        setIsGlobalFormatting(true)
        try {
            const formatApi = async (title: string, content: string) => {
                if (!content.trim()) return content
                const res = await fetch(`${API_BASE}/api/strategy/format_markdown`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ module_title: title, current_content: content })
                })
                const data = await res.json()
                if (data.status === "success" && data.data?.formatted_content) {
                    return data.data.formatted_content
                }
                return content
            }

            // 个人总结
            if (resumeData.summary) {
                setGlobalFormatProgress("排版个人总结...")
                const res = await formatApi("个人总结", resumeData.summary)
                updateSummary(res)
            }

            // 专业技能
            if (resumeData.additional?.technicalSkills?.length) {
                setGlobalFormatProgress("排版专业技能...")
                const content = resumeData.additional.technicalSkills.join('\n')
                const res = await formatApi("专业技能", content)
                updateAdditional({ technicalSkills: res.split('\n') })
            }

            // 工作经历
            if (resumeData.workExperience?.length) {
                for (let i = 0; i < resumeData.workExperience.length; i++) {
                    const exp = resumeData.workExperience[i]
                    setGlobalFormatProgress(`排版工作经历 ${i + 1}/${resumeData.workExperience.length}...`)
                    const content = Array.isArray(exp.description) ? exp.description.join('\n') : (exp.description || "")
                    if (content) {
                        const title = exp.company || exp.title || "工作经历"
                        const res = await formatApi(title, content)
                        updateWorkExperience(i, { description: res.split('\n') })
                    }
                }
            }

            // 项目经历
            if (resumeData.personalProjects?.length) {
                for (let i = 0; i < resumeData.personalProjects.length; i++) {
                    const proj = resumeData.personalProjects[i]
                    setGlobalFormatProgress(`排版项目经历 ${i + 1}/${resumeData.personalProjects.length}...`)
                    const content = Array.isArray(proj.description) ? proj.description.join('\n') : (proj.description || "")
                    if (content) {
                        const title = proj.name || "项目经历"
                        const res = await formatApi(title, content)
                        updateProject(i, { description: res.split('\n') })
                    }
                }
            }

            // 教育背景
            if (resumeData.education?.length) {
                for (let i = 0; i < resumeData.education.length; i++) {
                    const edu = resumeData.education[i]
                    setGlobalFormatProgress(`排版教育背景 ${i + 1}/${resumeData.education.length}...`)
                    const content = Array.isArray(edu.description) ? edu.description.join('\n') : (edu.description || "")
                    if (content) {
                        const title = edu.institution || "教育背景"
                        const res = await formatApi(title, content)
                        updateEducation(i, { description: res })
                    }
                }
            }

            alert("全局自动排版完成！")
        } catch (e) {
            console.error(e)
            alert("全局自动排版发生错误")
        } finally {
            setIsGlobalFormatting(false)
            setGlobalFormatProgress("")
        }
    }

    return {
        isTestingSkill, handleSkillRewrite,
        isGeneratingPdf, handleSavePdf,
        isGeneratingImages, handleSaveImages,
        formattingModuleId, handleFormatMarkdown,
        isGlobalFormatting, globalFormatProgress, handleGlobalFormat,
    }
}

export type ResumeBuilderActions = ReturnType<typeof useResumeBuilderActions>
