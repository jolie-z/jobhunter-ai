/**
 * BOSS Tab 回写 handler 簇（自 state.tsx 机械拆出，行为零变化）。
 * 由 useBossTabState 组合调用并经 ctx 透出，组件侧消费方式不变。
 */
"use client"

import { API_BASE } from "@/lib/api"
import type { Dispatch, SetStateAction } from "react"
import { BOSS_MODULES, type WritebackFeedbackState, type FeedbackDetail } from "./constants"

interface BossWritebackDeps {
  getNowTime: () => string
  selectedModules: Record<string, boolean>
  setSelectedModules: Dispatch<SetStateAction<Record<string, boolean>>>
  setSavingSnapshot: Dispatch<SetStateAction<boolean>>
  setSnapshotFeedback: Dispatch<SetStateAction<{ msg: string; ok: boolean; time?: string } | null>>
  setWritebacking: Dispatch<SetStateAction<boolean>>
  setWritebackFeedback: Dispatch<SetStateAction<WritebackFeedbackState | null>>
  setShowWritebackDetails: Dispatch<SetStateAction<boolean>>
  setWritebackConfirm: Dispatch<SetStateAction<boolean>>
}

export function useBossWritebackHandlers(deps: BossWritebackDeps) {
  const {
    getNowTime,
    selectedModules,
    setSelectedModules,
    setSavingSnapshot,
    setSnapshotFeedback,
    setWritebacking,
    setWritebackFeedback,
    setShowWritebackDetails,
    setWritebackConfirm,
  } = deps

  // 保存为回写数据源：writeback-save 端点生成 boss_writeback.json 快照，回写脚本优先读它
  const handleSaveWritebackSource = async () => {
    setSavingSnapshot(true)
    setSnapshotFeedback(null)
    const now = getNowTime()
    try {
      const res = await fetch(`${API_BASE}/api/agent-map/writeback-save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: "boss" }),
      })
      const result = await res.json()
      setSnapshotFeedback(result.success
        ? { msg: `✓ ${result.message}`, ok: true, time: now }
        : { msg: result.message || "保存失败", ok: false, time: now })
    } catch (e) {
      setSnapshotFeedback({ msg: "保存失败: " + e, ok: false, time: now })
    } finally {
      setSavingSnapshot(false)
    }
  }

  // 模块级回写：勾选的模块 key 列表（按清单顺序）
  const selectedModuleKeys = () => BOSS_MODULES.filter(m => selectedModules[m.key]).map(m => m.key)

  const toggleAllModules = () => {
    const allOn = BOSS_MODULES.every(m => selectedModules[m.key])
    const next: Record<string, boolean> = {}
    BOSS_MODULES.forEach(m => { next[m.key] = !allOn })
    setSelectedModules(next)
  }

  // 回写勾选模块到 BOSS 官网（破坏性操作：两步确认 → 执行）
  const handleWritebackModules = async () => {
    const paths = selectedModuleKeys()
    const now = getNowTime()
    if (paths.length === 0) {
      setWritebackFeedback({ msg: "请至少勾选一个模块", ok: false, time: now })
      return
    }
    setWritebacking(true)
    setWritebackFeedback(null)
    setShowWritebackDetails(false)
    try {
      const res = await fetch(`${API_BASE}/api/agent-map/write-back`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: "boss", paths }),
      })
      const result = await res.json()

      // 模块级明细组装（结合 results 执行结果与 verify 对账复核）
      const details: FeedbackDetail[] = []
      if (Array.isArray(result.results)) {
        result.results.forEach((r: any) => {
          const v = (result.verify || []).find((x: any) => x.module === r.module)
          const isOk = r.ok && (!v || v.match)
          let note = r.detail || r.resp_message || ""
          if (v && !v.match) {
            note = `复核未对齐（${v.note || "与官网数据不一致"}）`
          } else if (!note && isOk) {
            note = "已成功回写并复核生效"
          } else if (!note && !isOk) {
            note = "回写接口未返回成功状态"
          }
          details.push({
            module: r.module,
            success: !!isOk,
            message: note,
          })
        })
      } else if (Array.isArray(result.verify)) {
        result.verify.forEach((v: any) => {
          details.push({
            module: v.module,
            success: !!v.match,
            message: v.note || (v.match ? "已生效" : "未生效"),
          })
        })
      }

      if (result.success) {
        setWritebackFeedback({
          msg: `✓ ${result.message}`,
          ok: true,
          time: now,
          details: details.length > 0 ? details : undefined,
          output: result.output,
        })
      } else {
        const verifyBad = (result.verify || []).filter((v: any) => !v.match)
        const summaryMsg = verifyBad.length
          ? `回写完成，但有 ${verifyBad.length} 个模块复核未对齐`
          : (result.message || "回写失败")
        setWritebackFeedback({
          msg: summaryMsg,
          ok: false,
          time: now,
          details: details.length > 0 ? details : undefined,
          output: result.output || result.stderr || result.details,
        })
      }
    } catch (e) {
      setWritebackFeedback({ msg: "回写失败: " + e, ok: false, time: now })
    } finally {
      setWritebacking(false)
      setWritebackConfirm(false)
    }
  }

  return {
    handleSaveWritebackSource,
    selectedModuleKeys,
    toggleAllModules,
    handleWritebackModules,
  }
}
