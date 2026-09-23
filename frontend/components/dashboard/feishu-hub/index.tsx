"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import {
  Radio, MessageSquare, Bell, Eye, RefreshCw, CheckCircle2,
  AlertCircle, Sparkles, LayoutGrid
} from "lucide-react"
import type { Goals, GoalsForm, FeishuChat, DiagResult } from "./types"
import { FeishuConnectCard } from "./feishu-connect-card"
import { ChatOpsGuideCard } from "./chatops-guide-card"
import { ReportStudioCard } from "./report-studio-card"
import { API_BASE, apiFetch } from "@/lib/api"

type TabId = "all" | "connect" | "chatops" | "report"

export function FeishuHub() {
  const [activeTab, setActiveTab] = useState<TabId>("all")
  const [goals, setGoals] = useState<Goals | null>(null)
  const [chats, setChats] = useState<FeishuChat[]>([])
  const [receiveId, setReceiveId] = useState("")
  const [receiveIdSaved, setReceiveIdSaved] = useState("")
  const [savingReceiveId, setSavingReceiveId] = useState(false)
  const scrollContainerRef = useRef<HTMLDivElement>(null)

  // 连通性自检状态
  const [diag, setDiag] = useState<DiagResult | null>(null)
  const [diagRunning, setDiagRunning] = useState(false)

  // 战报配置表单
  const [form, setForm] = useState<GoalsForm>({
    daily_deliver_target: 10,
    daily_crawl_target: 50,
    weekly_interview_target: 3,
    total_offer_target: 1,
    plan_days: 60,
    report_time_daily: "21:00",
    report_time_weekly: "09:00",
    report_time_monthly: "09:00",
    report_enabled_daily: true,
    report_enabled_weekly: true,
    report_enabled_monthly: true,
  })
  const [savingSchedule, setSavingSchedule] = useState(false)
  const [savedSchedule, setSavedSchedule] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null)

  const showToast = (msg: string, type: "success" | "error" = "success") => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  // 加载当前目标配置和群聊列表，并静默同步连通性自检状态
  const loadInitialData = useCallback(async () => {
    try {
      const [gRes, cRes, dRes] = await Promise.all([
        apiFetch(`/api/v2/goals/current`).then((r) => r.json()).catch(() => null),
        apiFetch(`/api/v2/feishu/chats`).then((r) => r.json()).catch(() => null),
        apiFetch(`/api/settings/diagnose/feishu`).then((r) => r.json()).catch(() => null),
      ])

      if (dRes?.code === 0 && dRes.data) {
        setDiag(dRes.data)
      } else if (dRes && Array.isArray(dRes.checks)) {
        setDiag(dRes)
      }

      if (gRes?.code === 0 && gRes.data) {
        const d = gRes.data
        setGoals(d)
        setReceiveId(d.feishu_receive_id || "")
        setReceiveIdSaved(d.feishu_receive_id || "")
        setForm((prev) => ({
          ...prev,
          daily_deliver_target: d.daily_deliver_target ?? 10,
          daily_crawl_target: d.daily_crawl_target ?? 50,
          weekly_interview_target: d.weekly_interview_target ?? 3,
          total_offer_target: d.total_offer_target ?? 1,
          plan_days: d.plan_days ?? 60,
          report_time_daily: d.report_time_daily || "21:00",
          report_time_weekly: d.report_time_weekly || "09:00",
          report_time_monthly: d.report_time_monthly || "09:00",
          report_enabled_daily: d.report_enabled_daily ?? true,
          report_enabled_weekly: d.report_enabled_weekly ?? true,
          report_enabled_monthly: d.report_enabled_monthly ?? true,
        }))
      }

      // 提取群聊列表（兼容 cRes.data 为数组或对象包裹 { chats: [...] }，并兜底从自检诊断 dRes 中获取）
      let resolvedChats: FeishuChat[] = []
      if (cRes?.code === 0 && cRes.data) {
        if (Array.isArray(cRes.data)) {
          resolvedChats = cRes.data
        } else if (Array.isArray(cRes.data.chats)) {
          resolvedChats = cRes.data.chats
        }
      }
      if (resolvedChats.length === 0 && dRes) {
        const diagChats = dRes.data?.chats || dRes.chats
        if (Array.isArray(diagChats)) {
          resolvedChats = diagChats
        }
      }
      if (resolvedChats.length > 0) {
        setChats(resolvedChats)
      }
    } catch {
      showToast("加载飞书配置异常", "error")
    }
  }, [])

  useEffect(() => {
    loadInitialData()
  }, [loadInitialData])

  // 执行飞书全链路自检
  const runDiagnose = async () => {
    setDiagRunning(true)
    try {
      const res = await apiFetch(`/api/settings/diagnose/feishu`, { method: "POST" })
      if (res.ok) {
        const json = await res.json()
        const data: DiagResult = json.data || json
        setDiag(data)
        if (Array.isArray(data.chats) && data.chats.length > 0) {
          setChats(data.chats)
        }
        showToast("连通性自检完成！", "success")
      } else {
        showToast("诊断接口调用失败", "error")
      }
    } catch {
      showToast("网络请求异常，请确认后端已启动", "error")
    } finally {
      setDiagRunning(false)
    }
  }

  // 保存战报接收群 ID
  const saveReceiveId = async () => {
    setSavingReceiveId(true)
    try {
      const res = await apiFetch(`/api/v2/goals/update`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feishu_receive_id: receiveId }),
      })
      const data = await res.json()
      if (data.code === 0) {
        setReceiveIdSaved(receiveId)
        showToast("接收群绑定已更新！", "success")
      } else {
        showToast(data.msg || "保存接收群失败", "error")
      }
    } catch {
      showToast("网络请求失败", "error")
    } finally {
      setSavingReceiveId(false)
    }
  }

  // 保存战报目标与定时推送配置
  const saveSchedule = async () => {
    setSavingSchedule(true)
    try {
      let res = await apiFetch(`/api/v2/goals/update`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      }).then((r) => r.json())

      // 首次初始化兼容（Q-M4-4）：仅后端明确提示「尚未设定求职目标」时才补 start 再重试；
      // 其余 code:1（保存异常/无更新内容）如实报错，不再静默吞错假成功
      if (res.code === 1 && typeof res.msg === "string" && res.msg.includes("尚未设定")) {
        await apiFetch(`/api/v2/goals/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(form),
        })
        res = await apiFetch(`/api/v2/goals/update`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(form),
        }).then((r) => r.json())
      }

      if (res.code !== 0) {
        showToast(res.msg || "保存战报调度失败", "error")
        return
      }

      // 触发后端刷新定时任务调度器（仅在保存成功后执行）
      await apiFetch(`/api/v2/report/refresh-scheduler`, { method: "POST" })
      await loadInitialData()
      setSavedSchedule(true)
      showToast("战报调度与求职目标已保存！", "success")
      setTimeout(() => setSavedSchedule(false), 2000)
    } catch {
      showToast("保存战报调度失败", "error")
    } finally {
      setSavingSchedule(false)
    }
  }

  const tabs = [
    { id: "all", label: "完整全景", icon: LayoutGrid },
    { id: "connect", label: "通道连接", icon: Radio },
    { id: "report", label: "战报中心", icon: Bell },
    // ChatOps 纯指令参考、无需配置，垫底收尾
    { id: "chatops", label: "ChatOps", icon: MessageSquare },
  ] as const

  const handleSelectTab = (id: TabId) => {
    setActiveTab(id)
    if (id === "all") {
      scrollContainerRef.current?.scrollTo({ top: 0, behavior: "smooth" })
    }
  }

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden bg-slate-50/60">
      {/* 顶部导览 Header：标题、副标题、4张卡片定位胶囊与刷新按钮 */}
      <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/80 bg-white/85 px-6 py-2.5 backdrop-blur-md">
        <div className="min-w-fit">
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-slate-900">飞书集成中心</h1>
            <span className="inline-flex items-center rounded-md bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700 ring-1 ring-inset ring-sky-600/20">
              通道与自动化
            </span>
          </div>
          <p className="text-xs text-slate-500">长连接机器人、ChatOps 指令集与自动化战报调度</p>
        </div>

        {/* 4张卡片定位导览 + 刷新数据 */}
        <div className="flex items-center gap-2.5">
          <nav className="inline-flex rounded-xl bg-slate-100/90 p-1 ring-1 ring-slate-200/70" aria-label="飞书模块导航">
            {tabs.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => handleSelectTab(tab.id)}
                  className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                    isActive
                      ? "bg-white text-slate-900 shadow-xs ring-1 ring-slate-200/80"
                      : "text-slate-600 hover:bg-white/60 hover:text-slate-900"
                  }`}
                >
                  <Icon className={`size-3.5 ${isActive ? "text-sky-600" : "text-slate-400"}`} />
                  <span>{tab.label}</span>
                </button>
              )
            })}
          </nav>

          <button
            type="button"
            onClick={loadInitialData}
            title="刷新群聊与自检数据"
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200/80 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-xs transition-colors hover:bg-slate-50 hover:text-slate-900 active:scale-95"
          >
            <RefreshCw className="size-3.5 text-slate-400" />
            <span>刷新数据</span>
          </button>
        </div>
      </header>

      {/* 滚动卡片主体 */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-6 px-6 py-6 pb-20">
          {/* 模块 1: 飞书通道与连接 */}
          {(activeTab === "all" || activeTab === "connect") && (
            <div id="card-connect" className="scroll-mt-6">
              <FeishuConnectCard
                apiBase={API_BASE}
                chats={chats}
                receiveId={receiveId}
                receiveIdSaved={receiveIdSaved}
                setReceiveId={setReceiveId}
                onSaveReceiveId={saveReceiveId}
                savingReceiveId={savingReceiveId}
                diag={diag}
                diagRunning={diagRunning}
                onRunDiag={runDiagnose}
              />
            </div>
          )}

          {/* 模块 2: 飞书战报中心 (调度 + 预览 + 发送一体化工作台，需用户设置) */}
          {(activeTab === "all" || activeTab === "report") && (
            <div id="card-report" className="scroll-mt-6">
              <ReportStudioCard
                receiveId={receiveId}
                chats={chats}
                form={form}
                setForm={setForm}
                onSaveSchedule={saveSchedule}
                savingSchedule={savingSchedule}
                savedSchedule={savedSchedule}
              />
            </div>
          )}

          {/* 模块 3: ChatOps 机器人指南与话术（纯指令参考，垫底） */}
          {(activeTab === "all" || activeTab === "chatops") && (
            <div id="card-chatops" className="scroll-mt-6">
              <ChatOpsGuideCard apiBase={API_BASE} />
            </div>
          )}
        </div>
      </div>

      {/* 提示 Toast */}
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-medium text-white shadow-xl transition-all ${
            toast.type === "success" ? "bg-emerald-600" : "bg-rose-600"
          }`}
        >
          {toast.type === "success" ? <CheckCircle2 className="size-4" /> : <AlertCircle className="size-4" />}
          {toast.msg}
        </div>
      )}
    </div>
  )
}
