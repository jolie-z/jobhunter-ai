import { useState, useEffect, useCallback } from "react"
import {
  Bell, Send, RefreshCw, Check, Loader2,
  BookOpen, Clock, Sparkles, CheckCircle2, MessageSquare
} from "lucide-react"
import type { GoalsForm, FeishuChat } from "./types"
import { apiFetch } from "@/lib/api"
import {
  getNextDailyRun,
  getNextWeeklyRun,
  getNextMonthlyRun,
} from "./report-studio-utils"
import { FeishuCardRenderer } from "./feishu-card-renderer"
import { ReportStudioTutorialModal } from "./report-studio-tutorial-modal"

interface ReportStudioCardProps {
  receiveId: string
  chats?: FeishuChat[]
  form: GoalsForm
  setForm: React.Dispatch<React.SetStateAction<GoalsForm>>
  onSaveSchedule: () => Promise<void>
  savingSchedule: boolean
  savedSchedule: boolean
}

type ReportType = "daily" | "weekly" | "monthly"

export function ReportStudioCard({
  receiveId,
  chats,
  form,
  setForm,
  onSaveSchedule,
  savingSchedule,
  savedSchedule,
}: ReportStudioCardProps) {
  const [activeType, setActiveType] = useState<ReportType>("daily")
  const [preview, setPreview] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState<string | null>(null)
  const [sent, setSent] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [showTutorial, setShowTutorial] = useState(false)

  // 匹配群聊名称
  const boundChat = chats?.find((c) => c.chat_id === receiveId)
  const groupName = boundChat?.name || (receiveId ? (receiveId.startsWith("oc_") ? "飞书求职监控群" : receiveId) : null)

  const loadPreview = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch(`/api/v2/report/preview?report_type=${activeType}`)
      if (res.ok) {
        const data = await res.json()
        if (data.code === 0) {
          setPreview(data.data)
        }
      }
    } catch (e) {
      console.warn("加载战报预览异常:", e)
    } finally {
      setLoading(false)
    }
  }, [activeType])

  useEffect(() => {
    loadPreview()
  }, [loadPreview])

  const handleSend = async (reportType: string) => {
    setSending(reportType)
    setSent(null)
    setSendError(null)
    try {
      const res = await apiFetch(`/api/v2/report/send?report_type=${reportType}`, {
        method: "POST",
      })
      const data = await res.json()
      if (data.code === 0) {
        setSent(reportType)
        setTimeout(() => setSent(null), 3000)
      } else {
        setSendError(data.msg || "发送失败，请检查接收群配置")
      }
    } catch {
      setSendError("网络请求异常，无法发送战报")
    } finally {
      setSending(null)
    }
  }

  const reportTabs = [
    { id: "daily", label: "每日求职战报 (日报)", shortLabel: "日报", accent: "bg-sky-500", border: "border-sky-500" },
    { id: "weekly", label: "周度复盘战报 (周报)", shortLabel: "周报", accent: "bg-emerald-500", border: "border-emerald-500" },
    { id: "monthly", label: "月度宏观全景 (月报)", shortLabel: "月报", accent: "bg-purple-500", border: "border-purple-500" },
  ] as const

  const currentTabMeta = reportTabs.find((t) => t.id === activeType)!

  const isCurrentEnabled =
    activeType === "daily"
      ? form.report_enabled_daily
      : activeType === "weekly"
      ? form.report_enabled_weekly
      : form.report_enabled_monthly

  const currentReportTime =
    activeType === "daily"
      ? form.report_time_daily
      : activeType === "weekly"
      ? form.report_time_weekly
      : form.report_time_monthly

  const nextRunText =
    activeType === "daily"
      ? getNextDailyRun(form.report_time_daily, form.report_enabled_daily)
      : activeType === "weekly"
      ? getNextWeeklyRun(form.report_time_weekly, form.report_enabled_weekly)
      : getNextMonthlyRun(form.report_time_monthly, form.report_enabled_monthly)

  const handleTimeChange = (newTime: string) => {
    if (activeType === "daily") setForm({ ...form, report_time_daily: newTime })
    else if (activeType === "weekly") setForm({ ...form, report_time_weekly: newTime })
    else setForm({ ...form, report_time_monthly: newTime })
  }

  const handleToggleCurrent = () => {
    if (activeType === "daily") setForm({ ...form, report_enabled_daily: !form.report_enabled_daily })
    else if (activeType === "weekly") setForm({ ...form, report_enabled_weekly: !form.report_enabled_weekly })
    else setForm({ ...form, report_enabled_monthly: !form.report_enabled_monthly })
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card p-6 shadow-sm space-y-6">
      {/* 头部：标题与目标群 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-sky-500/10 text-sky-600">
            <Bell className="size-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-foreground">飞书战报中心</h2>
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                调度 · 预览 · 即时推送
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              集中配置飞书日报/周报/月报的定时推送时间表，所见即所得实时预览卡片，支持一键发送测试。
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {groupName ? (
            <div className="hidden sm:inline-flex items-center gap-1.5 rounded-xl border border-sky-200/80 bg-sky-50/80 px-3 py-1.5 text-xs text-sky-900 shadow-xs">
              <span className="size-2 rounded-full bg-emerald-500 ring-2 ring-emerald-200 animate-pulse" />
              <span className="text-sky-700">推送目标群:</span>
              <strong className="font-semibold text-slate-900 max-w-[160px] truncate">{groupName}</strong>
            </div>
          ) : (
            <div className="hidden sm:inline-flex items-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-700">
              <span>⚠️ 暂未绑定群聊</span>
            </div>
          )}

          <button
            type="button"
            onClick={() => setShowTutorial(true)}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-medium text-slate-700 shadow-xs transition-all hover:bg-slate-50 hover:border-slate-300 active:scale-[0.98]"
          >
            <BookOpen className="size-3.5 text-sky-600" />
            教程说明
          </button>
        </div>
      </div>

      {/* ── 报表类型选择器 (日报 / 周报 / 月报) ── */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="inline-flex rounded-xl bg-slate-100/90 p-1 ring-1 ring-slate-200/70">
          {reportTabs.map((tab) => {
            const isSelected = activeType === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveType(tab.id)}
                className={`flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-medium transition-all ${
                  isSelected
                    ? "bg-white text-slate-900 shadow-xs ring-1 ring-slate-200/80"
                    : "text-slate-600 hover:bg-white/60 hover:text-slate-900"
                }`}
              >
                <span className={`size-2 rounded-full ${tab.accent}`} />
                <span>{tab.label}</span>
              </button>
            )
          })}
        </div>

        <button
          type="button"
          onClick={loadPreview}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200/80 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-xs transition-colors hover:bg-slate-50 hover:text-slate-900 active:scale-95 disabled:opacity-50"
        >
          <RefreshCw className={`size-3.5 text-slate-400 ${loading ? "animate-spin" : ""}`} />
          <span>刷新预览数据</span>
        </button>
      </div>

      {/* ── 定时调度配置条 ── */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl border border-slate-200/80 bg-slate-50/70 p-3.5">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-800">
              {currentTabMeta.shortLabel}定时调度:
            </span>
            <button
              type="button"
              onClick={handleToggleCurrent}
              className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out ${
                isCurrentEnabled ? "bg-emerald-500" : "bg-slate-300"
              }`}
            >
              <span
                className={`pointer-events-none inline-block size-4 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out ${
                  isCurrentEnabled ? "translate-x-4" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>

          <div className="flex items-center gap-1.5">
            <Clock className="size-3.5 text-slate-400" />
            <input
              type="time"
              value={currentReportTime}
              onChange={(e) => handleTimeChange(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-mono font-medium text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-1 focus:ring-slate-300"
            />
          </div>

          <span className="text-xs text-slate-500 font-mono">
            {nextRunText}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onSaveSchedule}
            disabled={savingSchedule}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-medium text-white shadow-xs transition-all hover:bg-slate-800 active:scale-95 disabled:opacity-50"
          >
            {savingSchedule ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : savedSchedule ? (
              <CheckCircle2 className="size-3.5 text-emerald-400" />
            ) : null}
            <span>{savingSchedule ? "保存中..." : savedSchedule ? "调度已保存" : "保存时间表"}</span>
          </button>
        </div>
      </div>

      {/* ── 核心工作区：卡片实时渲染预览 + 操作按钮 ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* 左侧 2 栏：飞书 Interactive Card 实时渲染 */}
        <div className="lg:col-span-2">
          <FeishuCardRenderer
            activeType={activeType}
            report={preview?.report}
            card={preview?.card}
            loading={loading}
          />
        </div>

        {/* 右侧 1 栏：一键即时推送与调试面板 */}
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-xs space-y-4">
            <div>
              <h3 className="text-xs font-semibold text-slate-900 flex items-center gap-1.5">
                <Send className="size-3.5 text-sky-600" />
                即时推送至飞书群
              </h3>
              <p className="mt-1 text-[11px] text-slate-500">
                配置完毕后可立即触发真实机器人推送，在手机/电脑飞书上即刻核对效果。
              </p>
            </div>

            {/* 目标群信息卡片 */}
            <div className="rounded-xl border border-slate-100 bg-slate-50/80 p-3 space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-500">当前推送目标:</span>
                <span className="font-semibold text-slate-900 truncate max-w-[150px]">
                  {groupName || "未绑定群聊"}
                </span>
              </div>
              {boundChat && (
                <div className="text-[10px] font-mono text-slate-400 truncate">
                  ID: {boundChat.chat_id}
                </div>
              )}
            </div>

            {/* 主推送按钮 */}
            <button
              type="button"
              onClick={() => handleSend(activeType)}
              disabled={sending === activeType || !receiveId}
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-sky-600 px-4 py-2.5 text-xs font-semibold text-white shadow-xs transition-all hover:bg-sky-500 active:scale-[0.98] disabled:opacity-40"
            >
              {sending === activeType ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  <span>正在推送至飞书群...</span>
                </>
              ) : sent === activeType ? (
                <>
                  <Check className="size-4 text-emerald-300" />
                  <span>已成功推送入群！</span>
                </>
              ) : (
                <>
                  <Send className="size-4" />
                  <span>立即推送当前【{currentTabMeta.shortLabel}】到群</span>
                </>
              )}
            </button>

            {/* 发送连通测试卡片 */}
            <button
              type="button"
              onClick={() => handleSend("test")}
              disabled={sending === "test" || !receiveId}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-100 active:scale-95 disabled:opacity-40"
            >
              {sending === "test" ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : sent === "test" ? (
                <Check className="size-3.5 text-emerald-600" />
              ) : (
                <Sparkles className="size-3.5 text-amber-500" />
              )}
              <span>{sent === "test" ? "测试卡片已送达" : "发送一条连通测试卡片"}</span>
            </button>

            {sendError && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 px-3 py-2 text-[11px] text-rose-700 leading-relaxed">
                ❌ {sendError}
              </div>
            )}

            {!receiveId && (
              <div className="rounded-lg bg-amber-50 border border-amber-200 p-2.5 text-[11px] text-amber-800 leading-relaxed">
                ⚠️ 提示：当前未绑定接收群，请先在上方「飞书通道与连接」中选择群聊并保存。
              </div>
            )}

            <div className="border-t border-slate-100 pt-3 space-y-1.5 text-[11px] text-slate-400">
              <p>• 定时调度修改后原地热重载，无需重启服务</p>
              <p>• 测试发送仅影响当前绑定的唯一目标群聊</p>
            </div>
          </div>
        </div>
      </div>

      {/* 教程说明弹窗 */}
      <ReportStudioTutorialModal
        open={showTutorial}
        onOpenChange={setShowTutorial}
      />
    </div>
  )
}
