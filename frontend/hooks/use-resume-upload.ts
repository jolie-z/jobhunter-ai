"use client"

// 简历文件上传解析（上传 → SSE 进度 → 失败重试）hook
// 从 use-strategy-store.tsx 拆出（Q-M4-6 行数治理）；状态回调由 store 注入

import { useRef } from "react"
import { apiFetch, getApiBase } from "@/lib/api"

type UseResumeUploadOptions = {
    /** 解析成功：写入完整 Markdown 与结构化数据（SSE JSON 原样透传，结构由消费方定义） */
    onParsed: (fullMarkdown: string, structuredJson: any) => void
    /** 解析失败/中断：登记错误并复位解析态 */
    onError: (msg: string, taskId?: string) => void
    /** 解析态复位 */
    onParsingChange: (parsing: boolean) => void
    /** 新一次上传发起时回调（清空上一轮残留的失败状态，R1 审查 P1 等价性修复） */
    onUploadStart?: () => void
    fileInputRef: React.RefObject<HTMLInputElement | null>
}

export function useResumeUpload({ onParsed, onError, onParsingChange, onUploadStart, fileInputRef }: UseResumeUploadOptions) {
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
                    alert("✅ 解析成功！已提取个人信息、完成智能排版并生成结构化数据。")
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

        eventSource.addEventListener("ping", (event) => {
            // 保持连接的心跳
        })

        eventSource.onerror = (err) => {
            console.error("SSE Error:", err)
            eventSource.close()
            connectedTaskRef.current = null
            onParsingChange(false)
            alert("❌ 解析连接异常中断，请稍后重试。")
        }
    }

    const handleFileImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return

        const MAX_FILE_SIZE = 4 * 1024 * 1024
        if (file.size > MAX_FILE_SIZE) {
            alert(`❌ 文件过大（${(file.size / 1024 / 1024).toFixed(1)}MB），最大支持 4MB`)
            if (fileInputRef.current) fileInputRef.current.value = ""
            return
        }
        const ACCEPTED_TYPES = ['application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
        if (file.type && !ACCEPTED_TYPES.includes(file.type)) {
            alert(`❌ 不支持的文件类型（${file.type}），仅支持 PDF / DOC / DOCX`)
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
            if (!res.ok) throw new Error(data.detail || `上传失败（HTTP ${res.status}）`)
            if (data.status !== "processing" || !data.task_id) throw new Error(data.detail || "上传未返回任务ID")
            connectSSE(data.task_id)
        } catch (err) {
            alert("❌ 上传失败: " + (err instanceof Error ? err.message : String(err)))
            onParsingChange(false)
        } finally {
            if (fileInputRef.current) fileInputRef.current.value = ""
        }
    }

    return { connectSSE, handleFileImport }
}
