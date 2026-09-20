/**
 * Job51 Tab 自愈 Agent handler 簇（自 state.tsx 机械拆出，行为零变化）。
 */
"use client"

import { API_BASE } from "@/lib/api"
import type { Dispatch, SetStateAction } from "react"
import type { WritebackFeedbackState } from "./constants"

interface Job51HealDeps {
  writebackFeedback: WritebackFeedbackState | null
  selectedModuleKeys: () => string[]
  showToast: (message: string, type?: "success" | "error") => void
  job51AgentReport: any | null
  setJob51AgentDiagnosing: Dispatch<SetStateAction<boolean>>
  setJob51AgentReport: Dispatch<SetStateAction<any | null>>
  setJob51AgentModalOpen: Dispatch<SetStateAction<boolean>>
  setJob51AgentApplying: Dispatch<SetStateAction<boolean>>
  setJob51RollbackFeedback: Dispatch<SetStateAction<{ msg: string; ok: boolean; snapshotId?: string } | null>>
  setJob51RollingBack: Dispatch<SetStateAction<boolean>>
  handleWritebackModules: () => Promise<void>
}

export function useJob51HealHandlers(deps: Job51HealDeps) {
  const {
    writebackFeedback,
    selectedModuleKeys,
    showToast,
    job51AgentReport,
    setJob51AgentDiagnosing,
    setJob51AgentReport,
    setJob51AgentModalOpen,
    setJob51AgentApplying,
    setJob51RollbackFeedback,
    setJob51RollingBack,
    handleWritebackModules,
  } = deps

  const handleDispatchJob51HealerAgent = async (targetModule?: string) => {
    const failedDetails = (writebackFeedback?.details || []).filter(d => !d.success)
    const mod = targetModule || (failedDetails.length > 0 ? failedDetails[0].module : (selectedModuleKeys()[0] || "certifications"))
    setJob51AgentDiagnosing(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/51job/agent-diagnose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_module: mod,
          error_context: {
            message: writebackFeedback?.msg,
            output: writebackFeedback?.output,
            details: writebackFeedback?.details,
          },
          port: 9227,
        }),
      })
      const data = await res.json()
      if (data.ok) {
        setJob51AgentReport(data)
        setJob51AgentModalOpen(true)
      } else {
        showToast(data.error || "Agent 诊断失败，请确认 9227 端口浏览器已启动", "error")
      }
    } catch (e: any) {
      showToast("Agent 运行异常: " + (e.message || e), "error")
    } finally {
      setJob51AgentDiagnosing(false)
    }
  }

  const handleJob51AgentApplyHeal = async () => {
    if (!job51AgentReport || !job51AgentReport.recipe) return
    setJob51AgentApplying(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/51job/agent-apply-heal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipe: job51AgentReport.recipe, port: 9227 }),
      })
      const result = await res.json()
      if (result.ok) {
        setJob51AgentModalOpen(false)
        setJob51RollbackFeedback({
          msg: result.message || `已成功应用自愈处方`,
          ok: true,
          snapshotId: result.snapshot_id,
        })
        showToast("自愈处方已生效，正在为您重新发起 51job 回传...", "success")
        setTimeout(() => {
          handleWritebackModules()
        }, 500)
      } else {
        showToast(result.error || "执行自愈处方失败", "error")
      }
    } catch (e: any) {
      showToast("处方执行异常: " + (e.message || e), "error")
    } finally {
      setJob51AgentApplying(false)
    }
  }

  const handleRollbackJob51Snapshot = async (snapshotId?: string) => {
    setJob51RollingBack(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/51job/rollback-snapshot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshot_id: snapshotId }),
      })
      const result = await res.json()
      if (result.ok) {
        setJob51RollbackFeedback(null)
        showToast(result.message || "已成功撤销并恢复至上一版本", "success")
      } else {
        showToast(result.error || "撤销恢复失败", "error")
      }
    } catch (e: any) {
      showToast("撤销异常: " + (e.message || e), "error")
    } finally {
      setJob51RollingBack(false)
    }
  }

  return {
    handleDispatchJob51HealerAgent,
    handleJob51AgentApplyHeal,
    handleRollbackJob51Snapshot,
  }
}
