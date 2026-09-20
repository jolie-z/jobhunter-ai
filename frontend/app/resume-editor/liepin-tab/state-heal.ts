/**
 * Liepin Tab 自愈 Agent handler 簇（自 state.tsx 机械拆出，行为零变化）。
 * 由 useLiepinTabState 组合调用并经 ctx 透出，组件侧消费方式不变。
 */
"use client"

import { API_BASE } from "@/lib/api"
import type { Dispatch, SetStateAction } from "react"
import type { WritebackFeedbackState } from "./constants"

interface LiepinHealDeps {
  writebackFeedback: WritebackFeedbackState | null
  selectedModuleKeys: () => string[]
  showToast: (message: string, type?: "success" | "error") => void
  liepinAgentReport: any | null
  setLiepinAgentDiagnosing: Dispatch<SetStateAction<boolean>>
  setLiepinAgentReport: Dispatch<SetStateAction<any | null>>
  setLiepinAgentModalOpen: Dispatch<SetStateAction<boolean>>
  setLiepinAgentApplying: Dispatch<SetStateAction<boolean>>
  setLiepinRollbackFeedback: Dispatch<SetStateAction<{ msg: string; ok: boolean; snapshotId?: string } | null>>
  setLiepinRollingBack: Dispatch<SetStateAction<boolean>>
  handleWritebackModules: () => Promise<void>
}

export function useLiepinHealHandlers(deps: LiepinHealDeps) {
  const {
    writebackFeedback,
    selectedModuleKeys,
    showToast,
    liepinAgentReport,
    setLiepinAgentDiagnosing,
    setLiepinAgentReport,
    setLiepinAgentModalOpen,
    setLiepinAgentApplying,
    setLiepinRollbackFeedback,
    setLiepinRollingBack,
    handleWritebackModules,
  } = deps

  const handleDispatchLiepinHealerAgent = async (targetModule?: string) => {
    const failedDetails = (writebackFeedback?.details || []).filter(d => !d.success)
    const mod = targetModule || (failedDetails.length > 0 ? failedDetails[0].module : (selectedModuleKeys()[0] || "languages"))
    setLiepinAgentDiagnosing(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/liepin/agent-diagnose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_module: mod,
          error_context: {
            message: writebackFeedback?.msg,
            output: writebackFeedback?.output,
            details: writebackFeedback?.details,
          },
          port: 9226,
        }),
      })
      const data = await res.json()
      if (data.ok) {
        setLiepinAgentReport(data)
        setLiepinAgentModalOpen(true)
      } else {
        showToast(data.error || "Agent 诊断失败，请确认 9226 端口浏览器已启动", "error")
      }
    } catch (e: any) {
      showToast("Agent 运行异常: " + (e.message || e), "error")
    } finally {
      setLiepinAgentDiagnosing(false)
    }
  }

  const handleLiepinAgentApplyHeal = async () => {
    if (!liepinAgentReport || !liepinAgentReport.recipe) return
    setLiepinAgentApplying(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/liepin/agent-apply-heal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipe: liepinAgentReport.recipe, port: 9226 }),
      })
      const result = await res.json()
      if (result.ok) {
        setLiepinAgentModalOpen(false)
        setLiepinRollbackFeedback({
          msg: result.message || `已成功应用自愈处方`,
          ok: true,
          snapshotId: result.snapshot_id,
        })
        showToast("自愈处方已生效，正在为您重新发起猎聘回传...", "success")
        setTimeout(() => {
          handleWritebackModules()
        }, 500)
      } else {
        showToast(result.error || "执行自愈处方失败", "error")
      }
    } catch (e: any) {
      showToast("处方执行异常: " + (e.message || e), "error")
    } finally {
      setLiepinAgentApplying(false)
    }
  }

  const handleRollbackLiepinSnapshot = async (snapshotId?: string) => {
    setLiepinRollingBack(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/liepin/rollback-snapshot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshot_id: snapshotId }),
      })
      const result = await res.json()
      if (result.ok) {
        setLiepinRollbackFeedback(null)
        showToast(result.message || "已成功撤销并恢复至上一版本", "success")
      } else {
        showToast(result.error || "撤销恢复失败", "error")
      }
    } catch (e: any) {
      showToast("撤销异常: " + (e.message || e), "error")
    } finally {
      setLiepinRollingBack(false)
    }
  }

  return {
    handleDispatchLiepinHealerAgent,
    handleLiepinAgentApplyHeal,
    handleRollbackLiepinSnapshot,
  }
}
