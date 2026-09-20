/**
 * Liepin Tab 回写 handler 簇（自 state.tsx 机械拆出，行为零变化）。
 * 由 useLiepinTabState 组合调用并经 ctx 透出，组件侧消费方式不变。
 */
"use client"

import { API_BASE } from "@/lib/api"
import type { Dispatch, SetStateAction } from "react"
import { LIEPIN_MODULES, type WritebackFeedbackState } from "./constants"

interface LiepinWritebackDeps {
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

export function useLiepinWritebackHandlers(deps: LiepinWritebackDeps) {
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

  const handleSaveWritebackSource = async () => {
    setSavingSnapshot(true)
    setSnapshotFeedback(null)
    const now = getNowTime()
    try {
      const res = await fetch(`${API_BASE}/api/agent-map/writeback-save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: "liepin" }),
      })
      const result = await res.json()
      if (result.success) {
        setSnapshotFeedback({ msg: `✓ ${result.message}`, ok: true, time: now })
      } else {
        setSnapshotFeedback({ msg: result.message || "保存失败", ok: false, time: now })
      }
    } catch (e) {
      setSnapshotFeedback({ msg: "保存失败: " + e, ok: false, time: now })
    } finally {
      setSavingSnapshot(false)
    }
  }

  const selectedModuleKeys = () => LIEPIN_MODULES.filter(m => selectedModules[m.key]).map(m => m.key)

  const toggleAllModules = () => {
    const allOn = LIEPIN_MODULES.every(m => selectedModules[m.key])
    const next: Record<string, boolean> = {}
    LIEPIN_MODULES.forEach(m => { next[m.key] = !allOn })
    setSelectedModules(next)
  }

  const scrollToModule = (anchor: string) => {
    const el = document.getElementById(anchor)
    if (el) {
      const stickyHeader = document.querySelector(".sticky.top-0") as HTMLElement | null
      const headerHeight = stickyHeader ? stickyHeader.getBoundingClientRect().height : 200
      const elementPosition = el.getBoundingClientRect().top + window.pageYOffset
      const offsetPosition = elementPosition - headerHeight - 16
      window.scrollTo({
        top: Math.max(0, offsetPosition),
        behavior: "smooth",
      })
    }
  }

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
      // 猎聘回写唯一入口是 /api/unified/sync-back（agent-map/write-back 不支持 liepin）
      const res = await fetch(`${API_BASE}/api/unified/sync-back`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platforms: ["liepin"], paths }),
      })
      const result = await res.json()
      const first = (result.results && result.results.find((r: any) => r.platform === "liepin")) || {}
      // sync-back 的 details 是 liepin_pusher RESULT_JSON 的 modules 字典 {模块名: {success, message}}
      const rawDetails = first.details
      let details: any[] = []
      if (rawDetails && !Array.isArray(rawDetails) && typeof rawDetails === "object") {
        details = Object.entries(rawDetails).map(([module, v]: any) => ({
          module,
          success: !!v?.success,
          message: v?.message || (v?.success ? "已回写" : "失败"),
        }))
      } else if (Array.isArray(rawDetails)) {
        details = rawDetails
      } else if (Array.isArray(result.verify)) {
        details = result.verify.map((v: any) => ({
          module: v.module,
          success: !!v.match,
          message: v.note || (v.match ? "已生效" : "未生效"),
        }))
      }

      if (result.success && first.success !== false) {
        setWritebackFeedback({
          msg: first.message || result.message || `✓ 已回写 ${paths.length} 个模块到猎聘官网`,
          ok: true,
          time: now,
          details: details.length ? details : undefined,
          output: first.output || result.output,
        })
      } else {
        const errMsg = first.message || result.message || "回写失败"
        setWritebackFeedback({
          msg: errMsg,
          ok: false,
          time: now,
          details: details.length ? details : undefined,
          output: first.output || result.output,
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
    scrollToModule,
    handleWritebackModules,
  }
}
