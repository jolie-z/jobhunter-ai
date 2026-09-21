"use client"

// 「LLM 大模型」分组 · 测试连通性按钮 + 诊断结果弹窗
// 后端 POST /api/settings/diagnose/llm（真实极小探活，含视觉选填项），结构对齐飞书诊断 checks[]

import { useState } from "react"
import { AlertTriangle, CheckCircle2, Circle, HelpCircle, Stethoscope } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { apiFetch } from "@/lib/api"

type DiagCheck = {
  key: string
  label: string
  ok: boolean
  detail: string
  fix?: string
  optional?: boolean
}

type DiagData = {
  all_ok: boolean
  checked_at: string
  checks: DiagCheck[]
}

export function LlmDiagnoseButton({ hasDirtyEdits }: { hasDirtyEdits: boolean }) {
  const [open, setOpen] = useState(false)
  const [running, setRunning] = useState(false)
  const [diag, setDiag] = useState<DiagData | null>(null)
  const [error, setError] = useState("")

  const runDiagnose = async () => {
    setRunning(true)
    setError("")
    try {
      const res = await apiFetch(`/api/settings/diagnose/llm`, { method: "POST" })
      const data = await res.json()
      if (!res.ok || data.code !== 0) {
        setError(typeof data.detail === "string" ? data.detail : "诊断请求失败，请确认后端服务已启动")
        return
      }
      setDiag(data.data as DiagData)
    } catch {
      setError("网络请求失败，请检查后端服务是否在运行")
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => { setOpen(true); setDiag(null); setError("") }}
        className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 shadow-xs transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 hover:shadow-sm active:scale-[0.98]"
      >
        <Stethoscope className={`size-3 text-sky-500 ${running ? "animate-spin" : ""}`} />
        测试连通性
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-xl max-h-[85vh] overflow-y-auto border-slate-200 bg-white">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold text-slate-900">LLM 链路诊断</DialogTitle>
            <DialogDescription className="mt-1 text-[13px] leading-relaxed text-slate-500">
              真实发送一次极小请求（成本可忽略）验证推理链路与视觉通道。之后调用大模型再报错，可直接回到这里复测定位。
            </DialogDescription>
          </DialogHeader>

          {hasDirtyEdits && (
            <div className="flex items-start gap-2 rounded-xl border border-amber-200/80 bg-amber-50/80 px-4 py-3 text-xs leading-relaxed text-amber-800">
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              检测到有未保存的修改，诊断结果按「最近一次保存」的配置执行——请先保存再测试。
            </div>
          )}

          {!diag && !error && (
            <button
              type="button"
              onClick={runDiagnose}
              disabled={running}
              className="mt-2 inline-flex items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-xs font-semibold text-white transition-all hover:bg-slate-800 active:scale-[0.98] disabled:opacity-50"
            >
              <Stethoscope className={`size-3.5 ${running ? "animate-spin" : ""}`} />
              {running ? "链路探测中..." : "开始诊断"}
            </button>
          )}

          {error && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-xs leading-relaxed text-rose-700">
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              {error}
            </div>
          )}

          {diag && (
            <div className="mt-1 space-y-2.5">
              {diag.checks.map((c) => (
                <div
                  key={c.key}
                  className={`rounded-xl border px-4 py-3 ${
                    c.ok
                      ? "border-emerald-200/70 bg-emerald-50/50"
                      : c.optional
                        ? "border-slate-200 bg-slate-50/60"
                        : "border-rose-200/70 bg-rose-50/40"
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    {c.ok ? (
                      <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
                    ) : c.optional ? (
                      <HelpCircle className="mt-0.5 size-4 shrink-0 text-slate-400" />
                    ) : (
                      <Circle className="mt-0.5 size-4 shrink-0 text-rose-500" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-slate-900">
                        {c.label}
                        {c.optional && (
                          <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                            选填
                          </span>
                        )}
                      </p>
                      <p className={`mt-1 text-[11px] leading-relaxed ${c.ok ? "text-emerald-700" : c.optional ? "text-slate-500" : "text-rose-600"}`}>
                        {c.detail}
                      </p>
                      {!c.ok && c.fix && (
                        <p className="mt-1 text-[11px] leading-relaxed text-slate-600">
                          <span className="font-medium text-slate-800">修复建议：</span>{c.fix}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              <button
                type="button"
                onClick={runDiagnose}
                disabled={running}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-medium text-slate-600 transition-all hover:bg-slate-50 disabled:opacity-50"
              >
                <Stethoscope className={`size-3 ${running ? "animate-spin" : ""}`} />
                {running ? "探测中..." : "重新诊断"}
              </button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
