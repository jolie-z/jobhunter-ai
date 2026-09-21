"use client"

// 简历文件上传解析（上传 → SSE 真进度 → 失败重试）hook
// 从 use-strategy-store.tsx 拆出（Q-M4-6 行数治理）；状态回调由 store 注入
// 进度事件由后端 upload_stream 的 progress 事件透出（stage/字数），错误一律走回调不再 alert

import { useRef } from "react"
import { apiFetch, getApiBase } from "@/lib/api"
import { fetchMissingKeys } from "@/lib/readiness"

export type ParseProgress = {
    stage: string
    stageLabel: string
    /** structuring 阶段的流式已生成字符数（其他阶段为 0） */
    chars: number
}

type UseResumeUploadOptions = {
    /** 解析成功：写入完整 Markdown 与结构化数据（SSE JSON 原样透传，结构由消费方定义） */
    onParsed: (fullMarkdown: string, structuredJson: any) => void
    /** 解析失败/中断/上传失败：登记错误并复位解析态 */
    onError: (msg: string, taskId?: string) => void
    /** 解析态复位 */
    onParsingChange: (parsing: boolean) => void
    /** SSE 真进度（阶段 + 流式字数） */
    onProgress?: (p: ParseProgress) => void
    /** 主 LLM 未配置被闸门拦截（不发请求），由消费方弹配置引导 */
    onGateBlocked?: (missing: string[]) => void
    /** 新一次上传发起时回调（清空上一轮残留的失败状态，R1 审查 P1 等价性修复） */
    onUploadStart?: () => void
    fileInputRef: React.RefObject<HTMLInputElement | null>
}

export function useResumeUpload({
    onParsed,
    onError,
    onParsingChange,
    onProgress,
    onGateBlocked,
    onUploadStart,
    fileInputRef,
}: UseResumeUploadOptions) {
    // 已建立连接的任务登记，防重复连接
    const connectedTaskRef = useRef<string | null>(null)

    const connectSSE = (taskId: string) => {
        if (connectedTaskRef.current === taskId) return
        connectedTaskRef.current = taskId
        const eventSource = new EventSource(`${getApiBase()}/api/strategy/upload_stream/${taskId}`)

        eventSource.onmessage = (event) => {
            try {
                const t = JSON.parse(event.data)
                if (t.status === "ready") {
                    connectedTaskRef.current = null
                    onParsed(t.full_markdown || "", t.structured_json || {})
                    onParsingChange(false)
                    eventSource.close()
                } else if (t.status === "failed") {
                    connectedTaskRef.current = null
                    onError(t.error || "解析失败", taskId)
                    onParsingChange(false)
                    eventSource.close()
                }
            } catch (e) {
                console.error("解析 SSE 数据失败", e)
            }
        }

        eventSource.addEventListener("progress", (event) => {
            try {
                const p = JSON.parse((event as MessageEvent).data)
                onProgress?.({
                    stage: p.stage || "",
                    stageLabel: p.stage_label || p.stage || "",
                    chars: Number(p.progress_chars) || 0,
                })
            } catch {
                // 进度事件解析失败不影响主流程
            }
        })

        eventSource.addEventListener("ping", (event) => {
            // 保持连接的心跳
        })

        eventSource.onerror = (err) => {
            console.error("SSE Error:", err)
            eventSource.close()
            connectedTaskRef.current = null
            onError("解析连接异常中断，请稍后重试", taskId)
            onParsingChange(false)
        }
    }

    const handleFileImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return

        const MAX_FILE_SIZE = 4 * 1024 * 1024
        if (file.size > MAX_FILE_SIZE) {
            onError(`文件过大（${(file.size / 1024 / 1024).toFixed(1)}MB），最大支持 4MB`)
            if (fileInputRef.current) fileInputRef.current.value = ""
            return
        }
        const ACCEPTED_TYPES = ['application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
        if (file.type && !ACCEPTED_TYPES.includes(file.type)) {
            onError(`不支持的文件类型（${file.type}），仅支持 PDF / DOC / DOCX`)
            if (fileInputRef.current) fileInputRef.current.value = ""
            return
        }

        // 主 LLM 前置闸门：解析的唯一重活是结构化调用，未配置时不发请求，直接引导配置
        // （预检返回 null = 后端不可达，不拦截，由后端 400 兜底）
        const llmMissing = await fetchMissingKeys("llm")
        if (llmMissing && llmMissing.length > 0) {
            onGateBlocked?.(llmMissing)
            if (fileInputRef.current) fileInputRef.current.value = ""
            return
        }

        onUploadStart?.()
        onParsingChange(true)
        const formData = new FormData()
        formData.append("file", file)
        try {
            const res = await apiFetch(`/api/strategy/upload_resume_vision`, { method: "POST", body: formData })
            const data = await res.json()
            if (!res.ok) {
                if (data.detail?.code === "llm_not_configured") {
                    onParsingChange(false)
                    onGateBlocked?.(data.detail.missing || ["OPENAI_API_KEY"])
                    return
                }
                throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || `上传失败（HTTP ${res.status}）`)
            }
            if (data.status !== "processing" || !data.task_id) throw new Error(data.detail || "上传未返回任务ID")
            connectSSE(data.task_id)
        } catch (err) {
            onError("上传失败: " + (err instanceof Error ? err.message : String(err)))
            onParsingChange(false)
        } finally {
            if (fileInputRef.current) fileInputRef.current.value = ""
        }
    }

    return { connectSSE, handleFileImport }
}
