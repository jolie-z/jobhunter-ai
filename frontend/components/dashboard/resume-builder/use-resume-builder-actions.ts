"use client"

// 简历库顶栏动作集合 hook（从 resume-builder/index.tsx 拆出，Q-M4-6 行数治理）
// 覆盖：Skill 母版改写 / 保存 PDF / 保存图片 / 单模块排版
// 全局排版已迁移至编辑区同款 useGlobalFormat（2026-09-23 七项修复#3：旧串行实现删除），由 toolbar 直接消费

import { useCallback, useState } from "react"
import { toast } from "sonner"
import { useStrategyStore } from "@/hooks/use-strategy-store"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import type { ResumeDataV2 } from "@/types/resume"
import { API_BASE } from "@/lib/api"
import {
    startAsyncSkillRewrite,
    fetchGlobalJdReport,
    preflightSkillRewrite,
    type SkillRewriteParams,
    type SkillPreflightReport,
} from "@/hooks/use-skill-rewrite"
import type { SkillAgentCompletePayload } from "@/hooks/use-skill-agent-stream"

/** 多文件技能包判定（与 index.tsx 的进度坞 skillLabel 共用，口径唯一）：
 * 官方剧本 resume_rewrite 是单文件单轮引擎，其余 skill_id 均按多文件技能包对待 */
export function isSkillPack(skillId: string | null | undefined): boolean {
    return Boolean(skillId) && skillId !== "resume_rewrite"
}

export function useResumeBuilderActions(opts: {
    activeId: string
    resumeName: string
    selectedSkill: string | null
    setArtifactsOpen: (open: boolean) => void
}) {
    const { activeId, resumeName, selectedSkill, setArtifactsOpen } = opts
    const { fetchConfig, handleSave } = useStrategyStore()
    const { resumeData, setResumeData } = useResumeV2Store()

    // 🌟 Skill 智能体改写状态：isTestingSkill 由进度坞的完成/失败回调复位（异步链路）
    const [isTestingSkill, setIsTestingSkill] = useState(false)
    // 当前改写任务 ID：非空即挂载右下角进度坞并订阅 SSE
    const [skillTaskId, setSkillTaskId] = useState<string | null>(null)
    // 执行前预检：确认后才真正消耗 token
    const [preflight, setPreflight] = useState<{
        report: SkillPreflightReport | null
        params: SkillRewriteParams
        errorMessage?: string
    } | null>(null)
    const [preflightLoading, setPreflightLoading] = useState(false)

    // AI 排版状态
    const [formattingModuleId, setFormattingModuleId] = useState<string | null>(null)

    // 🌟 PDF 生成状态
    const [isGeneratingPdf, setIsGeneratingPdf] = useState(false)

    // 🌟 图片长图生成状态
    const [isGeneratingImages, setIsGeneratingImages] = useState(false)

    // 🌟 执行 Skill 母版改写（异步 + SSE 进度坞）
    // 此前走同步 /skill_rewrite_and_save：1-3 分钟零反馈、结束弹 alert，用户完全黑盒；
    // 现启动 /skill_rewrite_async 拿 task_id，进度坞实时展示 7 步轨道，完成/失败回调收尾
    const handleSkillRewrite = async () => {
        if (!activeId) {
            toast.error("请先选择一份简历")
            return
        }
        if (activeId.startsWith("temp_")) {
            toast.error("该简历为未保存的本地草稿，请先点击右上角「保存并同步」")
            return
        }
        // 只拦「真正进行中」；失败坞未关 / 完成后 4s 收起窗口内再点，直接顶替旧任务重新发起
        //（进度坞按 key=taskId 重新挂载），不逼用户先手动关坞
        if (isTestingSkill) {
            toast.info("已有一次改写正在进行中，请等待其完成")
            return
        }

        setIsTestingSkill(true)
        try {
            const jdReport = await fetchGlobalJdReport()
            if (!jdReport || !jdReport.trim()) {
                toast.error("尚未生成 A 级岗位画像，请先点击「A级岗位画像」生成后再执行改写")
                setIsTestingSkill(false)
                return
            }

            const params: SkillRewriteParams = {
                jd_text: jdReport,
                job_name: `${resumeName || "通用母版简历"}（简历库全局改写）`,
                resume_record_id: activeId,
                skill_id: selectedSkill || undefined,
            }
            try {
                const report = await preflightSkillRewrite(params)
                setPreflight({ report, params })
            } catch (preflightErr: any) {
                // 预检失败不阻断执行，但必须让用户知道无法提前预估
                setPreflight({
                    report: null,
                    params,
                    errorMessage: preflightErr?.message || "预检失败",
                })
            }
        } catch (err: any) {
            toast.error("Skill 改写启动失败: " + (err?.message || "未知错误"))
            setIsTestingSkill(false)
        }
    }

    const confirmPreflight = useCallback(async () => {
        if (!preflight) return
        const params = preflight.params
        setPreflightLoading(true)
        try {
            const taskId = await startAsyncSkillRewrite(params)
            setSkillTaskId(taskId)
            setPreflight(null)
        } catch (err: any) {
            toast.error("Skill 改写启动失败: " + (err?.message || "未知错误"))
            setIsTestingSkill(false)
        } finally {
            setPreflightLoading(false)
        }
    }, [preflight])

    const cancelPreflight = useCallback(() => {
        setPreflight(null)
        setIsTestingSkill(false)
    }, [])

    const handleSkillStreamComplete = useCallback(async (data: SkillAgentCompletePayload) => {
        // 回调在 SSE onmessage 链里执行，无外层兜底：铺画布/刷配置抛错必须就地接住并转失败态，
        // 否则进度坞会停在运行态、isTestingSkill 卡死
        try {
            const isResume = data?.result_kind === undefined || data.result_kind === "resume"
            if (isResume && data?.parsed_json) {
                setResumeData(data.parsed_json as ResumeDataV2)
                // fetchConfig 是 async：必须 await 才能让 reject 落进本块 catch（兜底文案才成立）
                await fetchConfig(activeId)
            }
            const expected = data?.expected_artifact_count ?? 0
            const produced = data?.artifact_count ?? 0
            const countText = expected > 0 ? `${produced}/${expected}` : `${produced}`
            if (data?.partial) {
                toast.warning(
                    `Skill ${isResume ? "改写" : "执行"}部分完成（${countText} 份产物），` +
                    (isResume
                        ? "06 主稿已写回简历库；缺少的产物可重新运行补齐"
                        : "产物已归档到产物库；缺少的产物可重新运行补齐")
                )
            } else if (isResume) {
                toast.success("Skill 母版简历改写完成，已实时写回底稿")
            } else {
                toast.success("Skill 执行完成，产物已归档到产物库")
            }
            if (data?.engine === "agent" || (!data?.engine && isSkillPack(selectedSkill))) {
                setArtifactsOpen(true)
            }
        } catch (err: any) {
            toast.error(`Skill 已完成，但画布刷新失败: ${err?.message || "未知错误"}，请手动刷新页面`)
        } finally {
            setIsTestingSkill(false)
        }
    }, [activeId, selectedSkill, setResumeData, fetchConfig, setArtifactsOpen])

    const handleSkillStreamError = useCallback((message: string) => {
        // 含写回保底闸的拦截说明（如「改写结果丢失了原有模块…已拒绝写回并保留原简历数据」）
        toast.error(`Skill 改写未完成: ${message}`)
        setIsTestingSkill(false)
    }, [])

    const dismissSkillTask = useCallback(() => {
        setSkillTaskId(null)
        setIsTestingSkill(false)
    }, [])

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
            const controller = new AbortController()
            // 单模块排版实测约 60s（上游网关生成速度），120s 前端超时防挂死（旧实现无超时最坏 12 分钟）
            const timeoutId = setTimeout(() => controller.abort(), 120000)
            let data: any
            try {
                const res = await fetch(`${API_BASE}/api/strategy/format_markdown`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ module_title: title, current_content: content }),
                    signal: controller.signal,
                })
                data = await res.json()
            } finally {
                clearTimeout(timeoutId)
            }
            if (data.status === "success" && data.data?.formatted_content) {
                onChange(data.data.formatted_content)
            }
        } catch (e) {
            console.error("Format markdown failed:", e)
        } finally {
            setFormattingModuleId(null)
        }
    }

    return {
        isTestingSkill, handleSkillRewrite,
        skillTaskId, handleSkillStreamComplete, handleSkillStreamError, dismissSkillTask,
        preflight, preflightLoading, confirmPreflight, cancelPreflight,
        isGeneratingPdf, handleSavePdf,
        isGeneratingImages, handleSaveImages,
        formattingModuleId, handleFormatMarkdown,
    }
}

export type ResumeBuilderActions = ReturnType<typeof useResumeBuilderActions>
