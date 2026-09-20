/**
 * BOSS Tab 自愈 Agent handler 簇（自 state.tsx 机械拆出，行为零变化）。
 * 由 useBossTabState 组合调用并经 ctx 透出，组件侧消费方式不变。
 */
"use client"

import { API_BASE } from "@/lib/api"
import type { Dispatch, SetStateAction } from "react"
import type { WritebackFeedbackState } from "./constants"

interface BossHealDeps {
  writebackFeedback: WritebackFeedbackState | null
  selectedModuleKeys: () => string[]
  showToast: (message: string, type?: "success" | "error") => void
  bossAgentReport: any | null
  setBossAgentDiagnosing: Dispatch<SetStateAction<boolean>>
  setBossAgentReport: Dispatch<SetStateAction<any | null>>
  setBossAgentModalOpen: Dispatch<SetStateAction<boolean>>
  setBossAgentApplying: Dispatch<SetStateAction<boolean>>
  setBossRollbackFeedback: Dispatch<SetStateAction<{ msg: string; ok: boolean; snapshotId?: string } | null>>
  setBossRollingBack: Dispatch<SetStateAction<boolean>>
  handleWritebackModules: () => Promise<void>
}

export function useBossHealHandlers(deps: BossHealDeps) {
  const {
    writebackFeedback,
    selectedModuleKeys,
    showToast,
    bossAgentReport,
    setBossAgentDiagnosing,
    setBossAgentReport,
    setBossAgentModalOpen,
    setBossAgentApplying,
    setBossRollbackFeedback,
    setBossRollingBack,
    handleWritebackModules,
  } = deps

  // 派出 BOSS 自愈 Agent 深度排查
  const handleDispatchBossHealerAgent = async (targetModule?: string) => {
    const failedDetails = (writebackFeedback?.details || []).filter(d => !d.success)
    const mod = targetModule || (failedDetails.length > 0 ? failedDetails[0].module : (selectedModuleKeys()[0] || "projects"))
    setBossAgentDiagnosing(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/boss/agent-diagnose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_module: mod,
          error_context: {
            message: writebackFeedback?.msg,
            output: writebackFeedback?.output,
            details: writebackFeedback?.details,
          },
          port: 19222,
        }),
      })
      const data = await res.json()
      if (data.ok) {
        setBossAgentReport(data)
        setBossAgentModalOpen(true)
      } else {
        showToast(data.error || "Agent 诊断失败，请确认 19222 端口浏览器已启动", "error")
      }
    } catch (e: any) {
      showToast("Agent 运行异常: " + (e.message || e), "error")
    } finally {
      setBossAgentDiagnosing(false)
    }
  }

  // 执行 BOSS Agent 产出的自愈处方并自动重新回传
  const handleBossAgentApplyHeal = async () => {
    if (!bossAgentReport || !bossAgentReport.recipe) return
    setBossAgentApplying(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/boss/agent-apply-heal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipe: bossAgentReport.recipe, port: 19222 }),
      })
      const result = await res.json()
      if (result.ok) {
        setBossAgentModalOpen(false)
        setBossRollbackFeedback({
          msg: result.message || `已成功应用自愈处方`,
          ok: true,
          snapshotId: result.snapshot_id,
        })
        showToast("自愈处方已生效，正在为您重新发起 BOSS 回传...", "success")
        setTimeout(() => {
          handleWritebackModules()
        }, 500)
      } else {
        showToast(result.error || "执行自愈处方失败", "error")
      }
    } catch (e: any) {
      showToast("处方执行异常: " + (e.message || e), "error")
    } finally {
      setBossAgentApplying(false)
    }
  }

  // 一键回滚 BOSS 快照
  const handleRollbackBossSnapshot = async (snapshotId?: string) => {
    setBossRollingBack(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/boss/rollback-snapshot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshot_id: snapshotId }),
      })
      const result = await res.json()
      if (result.ok) {
        setBossRollbackFeedback(null)
        showToast(result.message || "已成功撤销并恢复至上一版本", "success")
      } else {
        showToast(result.error || "撤销恢复失败", "error")
      }
    } catch (e: any) {
      showToast("撤销异常: " + (e.message || e), "error")
    } finally {
      setBossRollingBack(false)
    }
  }

  return {
    handleDispatchBossHealerAgent,
    handleBossAgentApplyHeal,
    handleRollbackBossSnapshot,
  }
}
