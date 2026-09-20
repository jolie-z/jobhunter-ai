"use client"

import { useState } from "react"
import {
  Radio, CheckCircle2, XCircle, Circle, RefreshCw, Eye, EyeOff,
  Stethoscope, Send, AlertTriangle, ShieldCheck, BookOpen, Lightbulb
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { FeishuChat, DiagResult, DiagCheck } from "./types"
import { FEISHU_CHATOPS_CHECKLIST, type ChatOpsChecklistItem } from "../strategy-lab/system-config-meta"

interface FeishuConnectCardProps {
  apiBase: string
  chats: FeishuChat[]
  receiveId: string
  receiveIdSaved: string
  setReceiveId: (v: string) => void
  onSaveReceiveId: () => Promise<void>
  savingReceiveId: boolean
  diag: DiagResult | null
  diagRunning: boolean
  onRunDiag: () => Promise<void>
}

export function FeishuConnectCard({
  chats,
  receiveId,
  receiveIdSaved,
  setReceiveId,
  onSaveReceiveId,
  savingReceiveId,
  diag,
  diagRunning,
  onRunDiag,
}: FeishuConnectCardProps) {
  const [receiveRevealed, setReceiveRevealed] = useState(false)
  const [showTutorial, setShowTutorial] = useState(false)
  const isDirty = receiveId !== receiveIdSaved

  // 映射自检清单状态（安全防崩溃）
  const getChecklistState = (item: ChatOpsChecklistItem): { state: "ok" | "fail" | "idle"; reason?: string } => {
    if (!diag) return { state: "idle" }
    const key = item.autoKey
    if (key === "ws_running" || key === "ws") {
      return diag.ws_running ? { state: "ok" } : { state: "fail", reason: "长连接未建立，请确保后端服务正常运行" }
    }
    if (key === "bot_in_group" || (item.label.includes("拉入群聊") && (diag.chats_count ?? 0) > 0)) {
      return (diag.chats_count ?? 0) > 0 ? { state: "ok" } : { state: "fail", reason: "未在任何群中发现机器人，请在群设置中添加机器人应用" }
    }
    const checks = Array.isArray(diag.checks) ? diag.checks : []
    const found = checks.find((c: DiagCheck) => c.key === key)
    if (!found) {
      if (diag.all_ok) return { state: "ok" }
      return { state: "idle" }
    }
    return { state: found.ok ? "ok" : "fail", reason: found.fix || found.detail }
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card p-6 shadow-sm">
      {/* 头部 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600">
            <Radio className="size-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-foreground">飞书通道与连接</h2>
              {diag?.ws_running ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-600">
                  <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  长连接活跃
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-600">
                  <span className="size-1.5 rounded-full bg-amber-500" />
                  待检测 / 未连接
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              基于 WebSocket 双向长连接，无需内网穿透或公网 IP，实时同步飞书群事件与战报调度。
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => setShowTutorial(true)}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-medium text-slate-700 shadow-xs transition-all hover:bg-slate-50 hover:border-slate-300 active:scale-[0.98]"
          >
            <BookOpen className="size-3.5 text-blue-600" />
            教程说明
          </button>

          <button
            type="button"
            onClick={onRunDiag}
            disabled={diagRunning}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-border bg-background px-4 py-2 text-xs font-medium text-foreground transition-all hover:bg-muted hover:border-foreground/20 active:scale-[0.98] disabled:opacity-50"
          >
            <Stethoscope className={`size-3.5 text-primary ${diagRunning ? "animate-spin" : ""}`} />
            {diagRunning ? "全链路体检中..." : "一键检测连通性"}
          </button>
        </div>
      </div>

      {/* 诊断信息栏 */}
      {diag && (
        <div className={`mt-4 rounded-xl border px-4 py-3 text-xs ${
          diag.all_ok
            ? "border-emerald-500/20 bg-emerald-500/5 text-emerald-700"
            : "border-amber-500/20 bg-amber-500/5 text-amber-700"
        }`}>
          <div className="flex items-center gap-2 font-medium">
            {diag.all_ok ? (
              <ShieldCheck className="size-4 text-emerald-600" />
            ) : (
              <AlertTriangle className="size-4 text-amber-600" />
            )}
            <span>
              {diag.all_ok
                ? "全链路检测通过！机器人长连接正常，事件监听及权限均配置正确。"
                : "检测到部分配置或权限缺失，请根据下方诊断提示进行修复。"}
            </span>
          </div>
        </div>
      )}

      {/* 检查清单 */}
      <div className="mt-5 grid gap-2.5 sm:grid-cols-2">
        {FEISHU_CHATOPS_CHECKLIST.map((item) => {
          const { state, reason } = getChecklistState(item)
          return (
            <div
              key={item.label}
              className="flex items-start gap-2.5 rounded-xl bg-muted/40 p-3 ring-1 ring-inset ring-border/40 transition-colors hover:bg-muted/60"
            >
              {state === "ok" ? (
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
              ) : state === "fail" ? (
                <XCircle className="mt-0.5 size-4 shrink-0 text-rose-500" />
              ) : (
                <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground/40" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-foreground">{item.label}</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{item.detail}</p>
                {state === "fail" && reason && (
                  <p className="mt-1 text-[11px] font-medium leading-relaxed text-rose-600 dark:text-rose-400">
                    {reason}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* 战报接收群 Chat ID 绑定 */}
      <div className="mt-6 rounded-xl border border-border/80 bg-background/80 p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
              <Send className="size-3.5 text-primary" />
              战报与推送目标群 (Chat ID)
            </label>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              日常求职战报（日报、周报、月报）及关键事件通知将自动推送到所选群。
            </p>
          </div>
          <div className="flex items-center gap-2">
            {receiveIdSaved ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-600">
                <span className="size-1 rounded-full bg-emerald-500" />
                已绑定群
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                未绑定
              </span>
            )}
            {isDirty && (
              <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-600">
                待保存
              </span>
            )}
          </div>
        </div>

        <div className="mt-3 flex flex-col gap-2.5 sm:flex-row">
          <div className="relative flex-1">
            {chats.length > 0 ? (
              <select
                value={receiveId}
                onChange={(e) => setReceiveId(e.target.value)}
                className="w-full rounded-xl border border-border bg-background px-3.5 py-2 text-xs font-mono text-foreground transition-colors focus:border-primary focus:outline-none"
              >
                <option value="">-- 请选择要推送的飞书群聊 --</option>
                {receiveId && !chats.some((c) => c.chat_id === receiveId) && (
                  <option value={receiveId}>手动指定群: {receiveId}</option>
                )}
                {chats.map((c) => (
                  <option key={c.chat_id} value={c.chat_id}>
                    {c.name} ({c.chat_id})
                  </option>
                ))}
              </select>
            ) : (
              <div className="relative">
                <input
                  type={receiveRevealed ? "text" : "password"}
                  placeholder="oc_xxxxxxxxxx (点击一键检测连通性可自动发现群聊)"
                  value={receiveId}
                  onChange={(e) => setReceiveId(e.target.value)}
                  className="w-full rounded-xl border border-border bg-background px-3.5 py-2 pr-9 text-xs font-mono text-foreground placeholder:text-muted-foreground/50 transition-colors focus:border-primary focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => setReceiveRevealed(!receiveRevealed)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/60 transition-colors hover:text-foreground"
                >
                  {receiveRevealed ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                </button>
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={onSaveReceiveId}
            disabled={savingReceiveId || !isDirty}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-medium text-primary-foreground shadow-sm transition-all hover:bg-primary/90 active:scale-[0.98] disabled:opacity-40"
          >
            {savingReceiveId ? <RefreshCw className="size-3.5 animate-spin" /> : <CheckCircle2 className="size-3.5" />}
            {savingReceiveId ? "保存中..." : "保存接收群"}
          </button>
        </div>

        <p className="mt-2 text-[11px] text-muted-foreground">
          {chats.length > 0
            ? `已通过飞书 Open API 发现 ${chats.length} 个已添加机器人的群聊。`
            : "若下拉列表为空，请先在飞书开放平台填好凭证，并将机器人拉入你的求职群，点击上方「一键检测连通性」将自动读取群列表。"}
        </p>
      </div>

      {/* 教程说明弹窗 */}
      <Dialog open={showTutorial} onOpenChange={setShowTutorial}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto border-slate-200 bg-white">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <Radio className="size-5 text-blue-600" />
              飞书通道与 WebSocket 长连接接入指南
            </DialogTitle>
            <DialogDescription className="mt-1 text-xs leading-relaxed text-slate-500">
              系统采用飞书官方 WebSocket 双向长连接技术，无需内网穿透（如 Cloudflare/Ngrok）、公网 IP 或 SSL 证书，只要本地服务在运行，即可实时接收飞书群指令并推送求职战报。
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4 space-y-4">
            <div className="space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">7 步极速接入指引</h3>
              <ol className="space-y-2.5">
                <li className="flex gap-3 rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[11px] font-semibold text-white">1</span>
                  <div className="text-xs">
                    <p className="font-semibold text-slate-900">获取 App ID 与 App Secret</p>
                    <p className="mt-0.5 text-slate-500 leading-relaxed">访问飞书开放平台 <code className="text-blue-600">open.feishu.cn</code> 开发者后台，创建企业自建应用。在「凭证与基础信息」复制 App ID（cli_ 开头）和 Secret，写入「系统底层配置」保存。</p>
                  </div>
                </li>
                <li className="flex gap-3 rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[11px] font-semibold text-white">2</span>
                  <div className="text-xs">
                    <p className="font-semibold text-slate-900">开启「机器人」应用能力</p>
                    <p className="mt-0.5 text-slate-500 leading-relaxed">进入应用详情页 → 左侧导航「添加应用能力」→ 勾选启用「机器人」能力并保存。只有开通机器人，应用才能被拉入群聊并在群里对话。</p>
                  </div>
                </li>
                <li className="flex gap-3 rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[11px] font-semibold text-white">3</span>
                  <div className="text-xs">
                    <p className="font-semibold text-slate-900">将事件订阅切换为「使用长连接接收事件」</p>
                    <p className="mt-0.5 text-slate-500 leading-relaxed">进入「事件与回调」→「事件配置」→ 将订阅方式从「请求地址」修改为「使用长连接接收事件」并保存。长连接免去公网配置，稳定性极高。</p>
                  </div>
                </li>
                <li className="flex gap-3 rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[11px] font-semibold text-white">4</span>
                  <div className="text-xs">
                    <p className="font-semibold text-slate-900">添加消息接收事件</p>
                    <p className="mt-0.5 text-slate-500 leading-relaxed">在事件配置中点击「添加事件」→ 搜索勾选 <code className="bg-slate-200/70 px-1 py-0.5 rounded text-slate-800">im.message.receive_v1</code>（接收消息 v2.0）以及 <code className="bg-slate-200/70 px-1 py-0.5 rounded text-slate-800">card.action.trigger</code>（卡片回传交互），保存生效。</p>
                  </div>
                </li>
                <li className="flex gap-3 rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[11px] font-semibold text-white">5</span>
                  <div className="text-xs">
                    <p className="font-semibold text-slate-900">开通 IM 权限并「创建版本发布」⚠️</p>
                    <p className="mt-0.5 text-slate-500 leading-relaxed">在「权限管理」搜索开通 <code className="bg-slate-200/70 px-1 py-0.5 rounded text-slate-800">im:message</code>（收发消息）与 <code className="bg-slate-200/70 px-1 py-0.5 rounded text-slate-800">im:chat</code>（获取群信息）读写权限。随后务必点击「版本管理与发布」创建并发布新版本！（未发布权限不生效）</p>
                  </div>
                </li>
                <li className="flex gap-3 rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[11px] font-semibold text-white">6</span>
                  <div className="text-xs">
                    <p className="font-semibold text-slate-900">将机器人拉入目标飞书群</p>
                    <p className="mt-0.5 text-slate-500 leading-relaxed">打开你的日常求职监控飞书群 → 点击群设置 →「群机器人」→「添加机器人」→ 搜索选择你刚创建的应用添加到群里。</p>
                  </div>
                </li>
                <li className="flex gap-3 rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[11px] font-semibold text-white">7</span>
                  <div className="text-xs">
                    <p className="font-semibold text-slate-900">一键检测与绑定战报群</p>
                    <p className="mt-0.5 text-slate-500 leading-relaxed">点击卡片右上角「一键检测连通性」，系统会自动发现该群聊。在下方下拉框选中该群并点击「保存接收群」即可完成自动化战报闭环！</p>
                  </div>
                </li>
              </ol>
            </div>

            <div className="flex gap-2.5 rounded-xl border border-amber-200/80 bg-amber-50/80 p-3.5">
              <Lightbulb className="size-4 shrink-0 text-amber-600 mt-0.5" />
              <div className="text-xs text-amber-800 space-y-1">
                <p className="font-semibold">排错黄金法则：</p>
                <p>1. 如果群内 @机器人 发送 <code className="bg-amber-100 px-1 py-0.5 rounded text-amber-900">ping</code> 无响应，90% 是因为在飞书后台修改权限或事件后<strong>未在「版本管理与发布」发布版本</strong>；</p>
                <p>2. 如果一键检测提示长连接未建立，可在终端确认 <code className="bg-amber-100 px-1 py-0.5 rounded text-amber-900">pm2 status</code> 后端服务是否正常运行。</p>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
