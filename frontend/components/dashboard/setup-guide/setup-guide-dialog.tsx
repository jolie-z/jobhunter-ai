"use client"

// 新手引导 · 三步配置体检弹窗
// 数据源 GET /api/settings/setup-status（base 最小字段清单 / 简历库 / 指挥中心模块清单）
// 深链约定：/strategy 页内用 CustomEvent('strategy:set-section') 免刷新切换，跨页 router.push

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import {
  ArrowRight,
  CheckCircle2,
  Circle,
  FileText,
  RefreshCw,
  Rocket,
  Settings2,
  Zap,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { apiFetch } from "@/lib/api"
import { dispatchStrategySetSection } from "@/lib/strategy-events"

export const SETUP_GUIDE_FLAG_KEY = "jobhunter:setup-guide:v1"

type SetupField = { key: string; group: string; label: string; filled: boolean }
type SetupStatus = {
  base: { done: boolean; fields: SetupField[] }
  resume: { done: boolean }
  pipeline: { done: boolean; modules: Record<string, boolean> }
  vision_ready: boolean
  complete: boolean
}

const PIPELINE_MODULE_LABELS: Record<string, string> = {
  scraping: "平台抓取",
  cleaning: "规则清洗",
  feishu_sync: "飞书推送",
  evaluating: "AI初评",
  deep_eval: "深度评估",
  rewriting: "简历改写",
  greeting: "打招呼语",
  review: "待审批",
  delivering: "自动投递",
}

type SetupGuideDialogProps = {
  open: boolean
  onClose: () => void
  /** 检测到配置已齐时回调（Provider 据此熄灭入口提醒点） */
  onComplete?: () => void
}

export function SetupGuideDialog({ open, onClose, onComplete }: SetupGuideDialogProps) {
  const router = useRouter()
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const completeRef = useRef(false)

  const fetchStatus = useCallback(async () => {
    setRefreshing(true)
    try {
      const res = await apiFetch(`/api/settings/setup-status`)
      if (res.ok) {
        const data = await res.json()
        if (data?.code === 0) {
          setStatus(data.data as SetupStatus)
          if (data.data?.complete === true && !completeRef.current) {
            completeRef.current = true
            onComplete?.()
          }
        }
      }
    } catch {
      // 后端未启动时保持上次状态，弹窗内不额外报错
    } finally {
      setRefreshing(false)
    }
  }, [onComplete])

  // 页内免刷新直达 /strategy 指定板块；跨页带参跳转（store 挂载时读取 URL 参数）
  const goStrategySection = (section: string) => {
    if (window.location.pathname.startsWith("/strategy")) {
      dispatchStrategySetSection(section)
    } else {
      router.push(`/strategy?section=${section}`)
    }
  }

  // 打开时拉取 + 打开期间每 8s 静默刷新（用户去配置后回来能看到状态点亮）
  useEffect(() => {
    if (!open) return
    fetchStatus()
    timerRef.current = setInterval(fetchStatus, 8000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [open, fetchStatus])

  const steps = [
    {
      id: "base",
      icon: Settings2,
      title: "第一步 · 系统底层配置",
      desc: "把系统底层配置中标出的最小启动必填项逐一配齐（推理通道与飞书凭证/数据表），项目才能跑起来。",
      done: status?.base.done,
      actionLabel: "去配置",
      onAction: () => { onClose(); goStrategySection("system") },
    },
    {
      id: "resume",
      icon: FileText,
      title: "第二步 · 上传一份简历",
      desc: "在 配置大盘 → 简历库 上传你的简历（PDF/Word），全链路的简历改写、投递都基于它。",
      done: status?.resume.done,
      actionLabel: "去简历库",
      onAction: () => { onClose(); goStrategySection("resume") },
    },
    {
      id: "pipeline",
      icon: Zap,
      title: "第三步 · 全链路指挥中心",
      desc: "配置抓取关键词、打招呼语、投递平台等全部模块，解锁从抓取到自动投递的完整自动化体验。",
      done: status?.pipeline.done,
      actionLabel: "去指挥中心",
      onAction: () => { onClose(); router.push("/prototype/command-center") },
    },
  ]

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg max-h-[88vh] overflow-y-auto border-slate-200 bg-white">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg font-bold text-slate-900">
            <span className="flex size-8 items-center justify-center rounded-xl bg-slate-900">
              <Rocket className="size-4 text-white" />
            </span>
            新手引导 · 三步跑起来
          </DialogTitle>
          <DialogDescription className="mt-1 text-[13px] leading-relaxed text-slate-500">
            必配项已为你收拢成一张体检单：按顺序走完三步，即可原汁原味体验整个项目。去配置后回到这里，状态会自动点亮。
          </DialogDescription>
        </DialogHeader>

        {!status ? (
          <div className="flex items-center justify-center gap-2 py-10 text-xs text-slate-400">
            <RefreshCw className="size-4 animate-spin" />
            正在读取配置体检结果...
          </div>
        ) : (
          <div className="space-y-3">
            {steps.map((step, i) => {
              const Icon = step.icon
              const done = step.done === true
              return (
                <div
                  key={step.id}
                  className={`rounded-xl border p-4 transition-all ${
                    done ? "border-emerald-200/70 bg-emerald-50/40" : "border-slate-200 bg-white"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={`flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                        done ? "bg-emerald-500 text-white" : "bg-slate-900 text-white"
                      }`}
                    >
                      {done ? <CheckCircle2 className="size-4" /> : i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[13px] font-semibold text-slate-900">{step.title}</p>
                        <Button
                          size="sm"
                          variant={done ? "outline" : "default"}
                          className={`h-7 shrink-0 gap-1 text-[11px] ${done ? "text-slate-500" : "bg-slate-900 text-white hover:bg-slate-800"}`}
                          onClick={step.onAction}
                        >
                          {done ? "再看看" : step.actionLabel}
                          <ArrowRight className="size-3" />
                        </Button>
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-slate-500">{step.desc}</p>

                      {/* 第一步：最小字段逐一显示（清单由后端下发） */}
                      {step.id === "base" && status.base.fields.length > 0 && (
                        <div className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1">
                          {status.base.fields.map((f) => (
                            <div key={f.key} className="flex items-center gap-1.5 text-[11px]">
                              {f.filled ? (
                                <CheckCircle2 className="size-3 shrink-0 text-emerald-500" />
                              ) : (
                                <Circle className="size-3 shrink-0 text-slate-300" />
                              )}
                              <span className={f.filled ? "text-slate-500" : "font-medium text-slate-800"}>
                                {f.label}
                              </span>
                              <span className="truncate text-[10px] text-slate-400">{f.group}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* 第三步：指挥中心模块格子（清单由后端下发） */}
                      {step.id === "pipeline" && Object.keys(status.pipeline.modules).length > 0 && (
                        <div className="mt-2.5 flex flex-wrap gap-1.5">
                          {Object.entries(status.pipeline.modules).map(([mod, ok]) => (
                            <span
                              key={mod}
                              className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${
                                ok
                                  ? "bg-emerald-50 text-emerald-700 ring-emerald-200/60"
                                  : "bg-slate-50 text-slate-400 ring-slate-200/70"
                              }`}
                            >
                              {ok ? <CheckCircle2 className="size-2.5" /> : <Circle className="size-2.5" />}
                              {PIPELINE_MODULE_LABELS[mod] || mod}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}

            <div className="flex items-center justify-between pt-1">
              <button
                type="button"
                onClick={fetchStatus}
                disabled={refreshing}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-medium text-slate-600 transition-all hover:bg-slate-50 disabled:opacity-50"
              >
                <RefreshCw className={`size-3 ${refreshing ? "animate-spin" : ""}`} />
                重新检测
              </button>

              {status.complete ? (
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-[11px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200/60">
                    <CheckCircle2 className="size-3.5" />
                    启动条件已齐！
                  </span>
                  <Button size="sm" onClick={onClose} className="h-7 bg-slate-900 text-white hover:bg-slate-800">
                    开始使用
                  </Button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    try { localStorage.setItem(SETUP_GUIDE_FLAG_KEY, JSON.stringify({ dismissed: true, ts: Date.now() })) } catch {}
                    onClose()
                  }}
                  className="text-[11px] text-slate-400 underline-offset-2 hover:text-slate-600 hover:underline"
                >
                  暂时不配，不再自动弹出
                </button>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
