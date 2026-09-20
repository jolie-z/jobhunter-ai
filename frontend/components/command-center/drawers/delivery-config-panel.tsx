"use client"

import { useState, useEffect, useCallback } from "react"
import { Save, CheckCircle2, AlertCircle, RefreshCw } from "lucide-react"
import { API_BASE } from "@/lib/api"
import { DeliveryScheduleCard } from "./delivery/delivery-schedule-card"
import { DeliveryPlatformCard } from "./delivery/delivery-platform-card"
import { DeliveryGradeCard } from "./delivery/delivery-grade-card"
import { DeliverySecurityCard } from "./delivery/delivery-security-card"
import { DeliveryLiveStreamCard, DeliveredJobItem } from "./delivery/delivery-live-stream-card"

interface DeliveryConfigPanelProps {
  onSaved: () => void
}

export function DeliveryConfigPanel({ onSaved }: DeliveryConfigPanelProps) {
  const [platforms, setPlatforms] = useState<string[]>(["boss", "liepin", "51job", "zhilian"])
  const [grades, setGrades] = useState<string[]>(["C", "D", "E", "F"])
  const [massDeliverTime, setMassDeliverTime] = useState("09:30")
  const [customDeliverMode, setCustomDeliverMode] = useState<"immediate" | "scheduled">("immediate")
  const [customDeliverTime, setCustomDeliverTime] = useState("14:00")
  const [deliveryTimeoutSec, setDeliveryTimeoutSec] = useState(45)
  const [batchLimit, setBatchLimit] = useState(20)
  const [deliveredJobs, setDeliveredJobs] = useState<DeliveredJobItem[]>([])

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ type: "success" | "error"; text: string } | null>(null)

  // 1. 获取投递规则与物料搭载流水
  const fetchConfigAndJobs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/delivery-config`)
      const data = await res.json()
      if (data.code === 0 && data.data) {
        const d = data.data
        if (d.auto_deliver_platforms) setPlatforms(d.auto_deliver_platforms)
        if (d.auto_deliver_grades) setGrades(d.auto_deliver_grades)
        if (d.mass_deliver_time) setMassDeliverTime(d.mass_deliver_time)
        if (d.custom_deliver_mode) setCustomDeliverMode(d.custom_deliver_mode)
        if (d.custom_deliver_time) setCustomDeliverTime(d.custom_deliver_time)
        if (d.delivery_timeout_sec) setDeliveryTimeoutSec(d.delivery_timeout_sec)
        if (d.batch_limit) setBatchLimit(d.batch_limit)
        if (d.delivered_jobs) setDeliveredJobs(d.delivered_jobs)
      }
    } catch (e) {
      console.error("加载自动投递配置异常:", e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConfigAndJobs()
  }, [fetchConfigAndJobs])

  // 2. 保存配置
  const handleSave = async () => {
    setSaving(true)
    setMsg(null)
    try {
      const payload = {
        auto_deliver_platforms: platforms,
        auto_deliver_grades: grades,
        mass_deliver_time: massDeliverTime,
        custom_deliver_mode: customDeliverMode,
        custom_deliver_time: customDeliverTime,
        delivery_timeout_sec: deliveryTimeoutSec,
        batch_limit: batchLimit,
      }
      const res = await fetch(`${API_BASE}/api/pipeline/delivery-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      if (data.code === 0) {
        setMsg({ type: "success", text: "✓ 自动投递规则已保存生效" })
        onSaved()
      } else {
        setMsg({ type: "error", text: data.msg || "保存失败" })
      }
    } catch {
      setMsg({ type: "error", text: "网络异常，保存失败" })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3.5 pb-6">
      {/* 1. 双轨定时发射时间与模式 */}
      <DeliveryScheduleCard
        massDeliverTime={massDeliverTime}
        onChangeMassDeliverTime={setMassDeliverTime}
        customDeliverMode={customDeliverMode}
        onChangeCustomDeliverMode={setCustomDeliverMode}
        customDeliverTime={customDeliverTime}
        onChangeCustomDeliverTime={setCustomDeliverTime}
      />

      {/* 2. 目标平台与多平台串行规则 */}
      <DeliveryPlatformCard
        platforms={platforms}
        onChangePlatforms={setPlatforms}
      />

      {/* 2.5 海投自动投递等级白名单 */}
      <DeliveryGradeCard
        grades={grades}
        onChangeGrades={setGrades}
      />

      {/* 3. 防封风控与超时熔断看门狗 */}
      <DeliverySecurityCard
        deliveryTimeoutSec={deliveryTimeoutSec}
        onChangeTimeout={setDeliveryTimeoutSec}
        batchLimit={batchLimit}
        onChangeBatchLimit={setBatchLimit}
      />

      {/* 4. 实时投递流水与物料搭载审计看板 */}
      <DeliveryLiveStreamCard
        jobs={deliveredJobs}
        onRefresh={fetchConfigAndJobs}
        loading={loading}
      />

      {/* 底部保存条 */}
      <div className="sticky bottom-0 z-10 -mx-4 -mb-6 mt-4 flex items-center justify-between border-t border-border/70 bg-background/95 p-3.5 backdrop-blur-md">
        <div>
          {msg && (
            <div
              className={`flex items-center gap-1.5 text-xs font-medium ${
                msg.type === "success"
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-600 dark:text-rose-400"
              }`}
            >
              {msg.type === "success" ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : (
                <AlertCircle className="h-3.5 w-3.5" />
              )}
              <span>{msg.text}</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={fetchConfigAndJobs}
            disabled={loading}
            className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-border px-3 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-all cursor-pointer disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>重置/刷新</span>
          </button>

          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="inline-flex h-8 items-center gap-1.5 rounded-xl bg-violet-600 hover:bg-violet-500 px-4 text-xs font-semibold text-white shadow-xs transition-all active:scale-95 cursor-pointer disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            <span>{saving ? "保存中..." : "保存投递规则"}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
