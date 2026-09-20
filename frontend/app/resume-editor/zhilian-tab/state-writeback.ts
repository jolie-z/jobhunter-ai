/**
 * Zhilian Tab 回写 handler 簇（自 state.tsx 机械拆出，行为零变化）。
 */
"use client"

import { API_BASE } from "@/lib/api"
import type { Dispatch, SetStateAction } from "react"
import { ZHILIAN_MODULES, ZHILIAN_MODULE_MAP, type WritebackFeedbackState, type FeedbackDetail } from "./constants"

interface ZhilianWritebackDeps {
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

export function useZhilianWritebackHandlers(deps: ZhilianWritebackDeps) {
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
        body: JSON.stringify({ platform: "zhilian" }),
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
  const selectedModuleKeys = () => ZHILIAN_MODULES.filter(m => selectedModules[m.key]).map(m => m.key)

  const toggleAllModules = () => {
    const allOn = ZHILIAN_MODULES.every(m => selectedModules[m.key])
    const next: Record<string, boolean> = {}
    ZHILIAN_MODULES.forEach(m => { next[m.key] = !allOn })
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
    try {
      const res = await fetch(`${API_BASE}/api/agent-map/write-back`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: "zhilian", paths }),
      })
      const result = await res.json()
      if (result.success) {
        const verifyBad = (result.verify || []).filter((v: any) => !v.match)
        const failedResults = (result.results || []).filter((r: any) => !r.ok)
        const failureMsg = (fr: any) =>
          fr.detail || fr.resp_message || (fr.resp_code != null ? `接口返回码 ${fr.resp_code}` : "回写接口未返回成功状态")
        const details: FeedbackDetail[] = (result.verify || []).map((v: any) => ({
          module: v.module,
          success: !!v.match,
          message: v.note || (v.match ? "已生效" : "官网值不一致")
        }))
        // verify 缺失但执行失败的模块也要进明细，避免部分失败被掩盖
        for (const fr of failedResults) {
          if (fr.module && !details.some((d) => d.module === fr.module)) {
            details.push({ module: fr.module, success: false, message: failureMsg(fr) })
          }
        }
        const allOk = !verifyBad.length && !failedResults.length
        setWritebackFeedback({
          msg: allOk
            ? `✓ ${result.message}`
            : `回写未全部成功：${[
                ...verifyBad.map((v: any) => `${ZHILIAN_MODULE_MAP[v.module] || v.module} ${v.note || "复核不一致"}`),
                ...failedResults.map((fr: any) => `${ZHILIAN_MODULE_MAP[fr.module] || fr.module} ${failureMsg(fr)}`),
              ].join("; ")}`,
          ok: allOk,
          time: now,
          details: details.length > 0 ? details : undefined,
          output: result.output || undefined,
          diagnostic: result.diagnostic,
          overflow_violations: result.overflow_violations,
        })
      } else {
        const failedResults = (result.results || []).filter((r: any) => !r.ok)
        const details: FeedbackDetail[] = (result.verify || []).map((v: any) => ({
          module: v.module,
          success: !!v.match,
          message: v.note || "执行异常"
        }))
        for (const fr of failedResults) {
          if (fr.module && !details.some((d) => d.module === fr.module)) {
            details.push({ module: fr.module, success: false, message: fr.detail || fr.resp_message || "执行异常" })
          }
        }
        setWritebackFeedback({
          msg: result.message || "回写失败",
          ok: false,
          time: now,
          details: details.length > 0 ? details : undefined,
          output: result.output || result.stderr || undefined,
          diagnostic: result.diagnostic,
          overflow_violations: result.overflow_violations,
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
