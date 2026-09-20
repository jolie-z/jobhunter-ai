/**
 * Zhilian Tab 结构探针与自愈 Agent handler 簇（自 state.tsx 机械拆出，行为零变化）。
 */
"use client"

import { API_BASE } from "@/lib/api"
import type { Dispatch, SetStateAction } from "react"
import type { WritebackFeedbackState } from "./constants"

interface ZhilianHealDeps {
  probeReport: any | null
  selectedDiffIndices: number[]
  writebackFeedback: WritebackFeedbackState | null
  agentReport: any | null
  selectedModuleKeys: () => string[]
  showToast: (message: string, type?: "success" | "error") => void
  setProbingSchema: Dispatch<SetStateAction<boolean>>
  setProbeReport: Dispatch<SetStateAction<any | null>>
  setSelectedDiffIndices: Dispatch<SetStateAction<number[]>>
  setDiffDrawerOpen: Dispatch<SetStateAction<boolean>>
  setSelfHealing: Dispatch<SetStateAction<boolean>>
  setRollbackFeedback: Dispatch<SetStateAction<{ msg: string; ok: boolean; snapshotId?: string } | null>>
  setRollingBack: Dispatch<SetStateAction<boolean>>
  setAgentDiagnosing: Dispatch<SetStateAction<boolean>>
  setAgentReport: Dispatch<SetStateAction<any | null>>
  setAgentModalOpen: Dispatch<SetStateAction<boolean>>
  setAgentApplying: Dispatch<SetStateAction<boolean>>
  handleWritebackModules: () => Promise<void>
}

export function useZhilianHealHandlers(deps: ZhilianHealDeps) {
  const {
    probeReport,
    selectedDiffIndices,
    writebackFeedback,
    agentReport,
    selectedModuleKeys,
    showToast,
    setProbingSchema,
    setProbeReport,
    setSelectedDiffIndices,
    setDiffDrawerOpen,
    setSelfHealing,
    setRollbackFeedback,
    setRollingBack,
    setAgentDiagnosing,
    setAgentReport,
    setAgentModalOpen,
    setAgentApplying,
    handleWritebackModules,
  } = deps

  // 触发 0-Token 探针并打开差分审核抽屉
  const handleOpenSchemaProbe = async () => {
    setProbingSchema(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/zhilian/probe-schema`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ port: 9250 }),
      })
      const data = await res.json()
      if (data.ok) {
        setProbeReport(data)
        const diffs = data.fields?.diffs || []
        setSelectedDiffIndices(diffs.map((_: any, idx: number) => idx))
        setDiffDrawerOpen(true)
        showToast("已成功反射获取智联官网最新结构", "success")
      } else {
        showToast(data.error || "探测官网结构失败，请确认已打开 9250 端口浏览器", "error")
      }
    } catch (e: any) {
      showToast("探测异常: " + (e.message || e), "error")
    } finally {
      setProbingSchema(false)
    }
  }

  // 确认执行自愈修复
  const handleConfirmSelfHeal = async () => {
    if (!probeReport) return
    const diffs = probeReport.fields?.diffs || []
    const selected = selectedDiffIndices.map(idx => diffs[idx]).filter(Boolean)
    setSelfHealing(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/zhilian/self-heal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selected_diffs: selected, use_llm: false }),
      })
      const result = await res.json()
      if (result.ok) {
        setRollbackFeedback({
          msg: result.message || `已成功补齐 ${result.applied_count} 项新字段结构`,
          ok: true,
          snapshotId: result.snapshot_id,
        })
        setDiffDrawerOpen(false)
        showToast("本地数据模型自愈同步成功！", "success")
      } else {
        showToast(result.error || "自愈执行失败", "error")
      }
    } catch (e: any) {
      showToast("自愈异常: " + (e.message || e), "error")
    } finally {
      setSelfHealing(false)
    }
  }

  // 撤销回滚至上一快照
  const handleRollbackSnapshot = async (snapshotId?: string) => {
    setRollingBack(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/zhilian/rollback-snapshot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshot_id: snapshotId }),
      })
      const result = await res.json()
      if (result.ok) {
        setRollbackFeedback(null)
        showToast(result.message || "已成功撤销并恢复至上一版本", "success")
      } else {
        showToast(result.error || "撤销恢复失败", "error")
      }
    } catch (e: any) {
      showToast("撤销异常: " + (e.message || e), "error")
    } finally {
      setRollingBack(false)
    }
  }

  // 派出自愈 Agent 对指定失败模块进行真机深度排查
  const handleDispatchHealerAgent = async (targetModule?: string) => {
    const failedDetails = (writebackFeedback?.details || []).filter(d => !d.success)
    const mod = targetModule || (failedDetails.length > 0 ? failedDetails[0].module : (selectedModuleKeys()[0] || "certificates"))
    setAgentDiagnosing(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/zhilian/agent-diagnose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_module: mod,
          error_context: {
            message: writebackFeedback?.msg,
            output: writebackFeedback?.output,
            details: writebackFeedback?.details,
          },
          port: 9250,
        }),
      })
      const data = await res.json()
      if (data.ok) {
        setAgentReport(data)
        setAgentModalOpen(true)
      } else {
        showToast(data.error || "Agent 诊断失败，请确认 9250 端口浏览器已启动", "error")
      }
    } catch (e: any) {
      showToast("Agent 运行异常: " + (e.message || e), "error")
    } finally {
      setAgentDiagnosing(false)
    }
  }

  // 执行 Agent 产出的自愈处方并自动重新回传
  const handleAgentApplyHeal = async () => {
    if (!agentReport || !agentReport.recipe) return
    setAgentApplying(true)
    try {
      const res = await fetch(`${API_BASE}/api/platforms/zhilian/agent-apply-heal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipe: agentReport.recipe, port: 9250 }),
      })
      const result = await res.json()
      if (result.ok) {
        setAgentModalOpen(false)
        setRollbackFeedback({
          msg: result.message || `已成功应用自愈处方`,
          ok: true,
          snapshotId: result.snapshot_id,
        })
        showToast("自愈处方已生效，正在为您重新发起回写验证...", "success")
        setTimeout(() => {
          handleWritebackModules()
        }, 500)
      } else {
        showToast(result.error || "执行自愈处方失败", "error")
      }
    } catch (e: any) {
      showToast("处方执行异常: " + (e.message || e), "error")
    } finally {
      setAgentApplying(false)
    }
  }

  return {
    handleOpenSchemaProbe,
    handleConfirmSelfHeal,
    handleRollbackSnapshot,
    handleDispatchHealerAgent,
    handleAgentApplyHeal,
  }
}
