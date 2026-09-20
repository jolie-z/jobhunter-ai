"use client"

import { useState } from "react"
import { usePipelineStore, PipelineJob } from "@/store/pipeline-store"
import { API_BASE } from "@/lib/api"
import { toast } from "sonner"

/**
 * 专用于「已投递」岗位微聊打招呼语一键补发的 Hook
 */
export function useResendGreeting(job: PipelineJob) {
  const [resending, setResending] = useState(false)

  const resendGreeting = async (e?: React.MouseEvent) => {
    if (e) {
      e.stopPropagation()
      e.preventDefault()
    }
    if (resending) return
    setResending(true)
    const toastId = toast.loading(`正在为【${job.job_name || "该岗位"}】唤起微聊补发打招呼语...`)

    try {
      const res = await fetch(`${API_BASE}/api/automation/resend-greeting`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.job_id,
          job_url: job.job_url || "",
        }),
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        toast.success(data.message || "打招呼语已成功送达 HR 微聊！", { id: toastId })
        // 乐观更新全局 store 状态：解除 greeting_failed 警告，标记专属欢迎语送达
        const st = usePipelineStore.getState()
        if (st.jobs[job.job_id]) {
          st.updateJob(job.job_id, {
            delivery_materials: {
              ...(job.delivery_materials || {}),
              greeting: true,
              greeting_failed: false,
            },
          })
        }
      } else {
        toast.error(`补发未成功: ${data.message || data.detail || "请检查智联网页登录态后重试"}`, { id: toastId })
      }
    } catch (err: any) {
      toast.error(`网络异常: ${err?.message || "无法连接后端服务"}`, { id: toastId })
    } finally {
      setResending(false)
    }
  }

  return { resending, resendGreeting }
}
