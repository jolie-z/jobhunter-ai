/**
 * Job51 Tab 回写 handler 簇（自 state.tsx 机械拆出，行为零变化）。
 * 由 useJob51TabState 组合调用并经 ctx 透出，组件侧消费方式不变。
 */
"use client"

import { API_BASE } from "@/lib/api"
import type { Dispatch, SetStateAction } from "react"
import { JOB51_MODULES, type WritebackFeedbackState, type FeedbackDetail } from "./constants"

interface Job51WritebackDeps {
  getNowTime: () => string
  selectedModules: Record<string, boolean>
  setSelectedModules: Dispatch<SetStateAction<Record<string, boolean>>>
  setSavingSnapshot: Dispatch<SetStateAction<boolean>>
  setSnapshotFeedback: Dispatch<SetStateAction<{ msg: string; ok: boolean; time?: string } | null>>
  setWritebacking: Dispatch<SetStateAction<boolean>>
  setWritebackFeedback: Dispatch<SetStateAction<WritebackFeedbackState | null>>
  setWritebackConfirm: Dispatch<SetStateAction<boolean>>
}

export function useJob51WritebackHandlers(deps: Job51WritebackDeps) {
  const {
    getNowTime,
    selectedModules,
    setSelectedModules,
    setSavingSnapshot,
    setSnapshotFeedback,
    setWritebacking,
    setWritebackFeedback,
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
        body: JSON.stringify({ platform: "51job" }),
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

  const selectedModuleKeys = () => JOB51_MODULES.filter((m: any) => selectedModules[m.key]).map((m: any) => m.key)

  const toggleAllModules = () => {
    const allOn = JOB51_MODULES.every((m: any) => selectedModules[m.key])
    const next: Record<string, boolean> = {}
    JOB51_MODULES.forEach((m: any) => { next[m.key] = !allOn })
    setSelectedModules(next)
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
        body: JSON.stringify({ platform: "51job", paths }),
      })
      const result = await res.json()
      if (result.success) {
        const verifyBad = (result.verify || []).filter((v: any) => !v.match)
        const failedResults = (result.results || []).filter((r: any) => !r.ok)
        // 失败模块的接口级原因（resp_code/resp_message 在后端契约内）
        const failureMsg = (fr: any) =>
          fr.detail || fr.resp_message || (fr.resp_code != null ? `接口返回码 ${fr.resp_code}` : "回写接口未返回成功状态")

        const details: FeedbackDetail[] = (result.verify || []).map((v: any) => ({
          module: v.module,
          success: !!v.match,
          message: v.note || (v.match ? "已生效" : "官网值不一致"),
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
                ...verifyBad.map((v: any) => `${v.module} ${v.note || "复核不一致"}`),
                ...failedResults.map((fr: any) => `${fr.module} ${failureMsg(fr)}`),
              ].join("; ")}`,
          ok: allOk,
          time: now,
          details: details.length > 0 ? details : undefined,
          output: result.output || undefined,
        })
        // 不调 onRefresh：它会置 loading=true 使整个 Tab 闪 loading 并冲掉刚出现的反馈；
        // 回写脚本内部已重新拉官网数据复核，本地展示无需重拉
      } else {
        const failedResults = (result.results || []).filter((r: any) => !r.ok)
        const details: FeedbackDetail[] = (result.verify || []).map((v: any) => ({
          module: v.module,
          success: !!v.match,
          message: v.note || "执行异常",
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
