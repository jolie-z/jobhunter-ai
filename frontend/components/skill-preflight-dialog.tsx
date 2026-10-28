"use client"

import {
  AlertTriangle,
  CheckCircle2,
  Coins,
  Database,
  FileText,
  Loader2,
  ShieldCheck,
  Sparkles,
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { SkillPreflightReport } from "@/hooks/use-skill-rewrite"
import { formatTokens } from "@/lib/format-tokens"

interface SkillPreflightDialogProps {
  open: boolean
  report: SkillPreflightReport | null
  skillName?: string
  errorMessage?: string
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}

function fmtChars(n: number): string {
  if (!n) return "0 字"
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)} 万字`
  return `${n} 字`
}

/**
 * 执行前预检弹窗：在消耗用户 token 之前，明确告知
 * - 会加载哪些上下文（SKILL.md / references / JD / 简历 / 诊断）
 * - 预计产出多少文件、什么类型、是否包含简历改写文件
 * - 预计消耗多少 token（历史样本或启发式）
 *
 * 不阻止非简历 skill：只是告知，最终由用户确认。
 */
export function SkillPreflightDialog({
  open,
  report,
  skillName,
  errorMessage,
  loading = false,
  onConfirm,
  onCancel,
}: SkillPreflightDialogProps) {
  const outputs = report?.outputs ?? []
  const warnings = report?.warnings ?? []
  const estimate = report?.estimated_tokens
  const kindLabel =
    report?.result_kind === "resume"
      ? "简历改写"
      : report?.result_kind === "json"
        ? "JSON 结构化产物"
        : "通用 Markdown 产物"

  return (
    <Dialog open={open} onOpenChange={(v) => (!v && !loading ? onCancel() : undefined)}>
      <DialogContent className="sm:max-w-2xl max-h-[86vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="size-4 text-indigo-600" />
            执行前预检{skillName ? ` · ${skillName}` : ""}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            执行会消耗你自己的 token。系统先扫描该技能包的输出结构，并把本次会加载的上下文与预估消耗提前告知。
          </DialogDescription>
        </DialogHeader>

        {!report ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
            <div className="flex items-center gap-1.5 font-semibold">
              <AlertTriangle className="size-4" />
              预检失败
            </div>
            <p className="mt-1 break-words">{errorMessage || "无法读取技能包信息。"}</p>
            <p className="mt-1 text-rose-600/80">你仍然可以继续执行，但无法提前预估产物与 token；如果这是校验类错误，执行阶段可能同样失败。</p>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-2.5">
                <div className="text-[11px] text-slate-500">执行引擎</div>
                <div className="mt-0.5 font-semibold text-slate-800">
                  {report.engine === "agent" ? "多轮渐进式 Agent" : "官方单轮引擎"}
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-2.5">
                <div className="text-[11px] text-slate-500">结果类型</div>
                <div className="mt-0.5 font-semibold text-slate-800">{kindLabel}</div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-2.5">
                <div className="text-[11px] text-slate-500">预计产物</div>
                <div className="mt-0.5 font-semibold text-slate-800">
                  {report.expected_artifact_count > 0
                    ? `${report.expected_artifact_count} 份`
                    : "未识别到明确数量"}
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-2.5">
                <div className="text-[11px] text-slate-500">是否包含简历文件</div>
                <div className={`mt-0.5 font-semibold ${report.has_resume_output ? "text-emerald-700" : "text-amber-700"}`}>
                  {report.has_resume_output ? "是" : "未检测到"}
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 p-3">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
                <Database className="size-3.5 text-indigo-500" />
                本次将加载
              </div>
              <div className="mt-1.5 grid grid-cols-2 gap-1.5 text-[11px] text-slate-600">
                <div>📖 SKILL.md（{fmtChars(report.will_load.skill_chars)}）</div>
                <div>📚 References：{report.will_load.references_count} 篇</div>
                <div>
                  🎯 {report.will_load.resume_library_mode ? "A级岗位画像" : "岗位 JD"}：
                  {fmtChars(report.will_load.jd_chars)}
                </div>
                <div>
                  👤 {report.will_load.resume_library_mode ? "选中的简历" : "启用中的简历"}：
                  {fmtChars(report.will_load.resume_chars)}
                </div>
                <div className="col-span-2">
                  🩺 岗位诊断：{report.will_load.diagnosis_injected ? "已注入" : "不注入（简历库模式或未开启）"}
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
                  <FileText className="size-3.5 text-indigo-500" />
                  预计产出文件
                </div>
                {report.final_artifact && (
                  <Badge className="bg-indigo-50 text-indigo-700 border-indigo-200 text-[10px] font-normal">
                    最终：{report.final_artifact}
                  </Badge>
                )}
              </div>
              {outputs.length === 0 ? (
                <p className="mt-1.5 text-[11px] text-slate-500">
                  未识别到明确产物清单，执行时将遵循 SKILL.md，并由模型标记最终交付物。
                </p>
              ) : (
                <div className="mt-1.5 max-h-40 overflow-y-auto space-y-1">
                  {outputs.slice(0, 20).map((o) => (
                    <div key={o.filename} className="flex items-center justify-between gap-2 text-[11px]">
                      <span className="truncate font-mono text-slate-700">{o.filename}</span>
                      <div className="flex shrink-0 items-center gap-1">
                        {o.is_resume && (
                          <Badge className="bg-emerald-50 text-emerald-700 border-emerald-200 text-[9px] h-4 px-1 font-normal">
                            简历
                          </Badge>
                        )}
                        {o.is_final && (
                          <Badge className="bg-indigo-50 text-indigo-700 border-indigo-200 text-[9px] h-4 px-1 font-normal">
                            最终
                          </Badge>
                        )}
                        <Badge variant="outline" className="text-[9px] h-4 px-1 font-normal text-slate-500">
                          {o.kind || "markdown"}
                        </Badge>
                      </div>
                    </div>
                  ))}
                  {outputs.length > 20 && (
                    <p className="text-[11px] text-slate-400">还有 {outputs.length - 20} 份未展示…</p>
                  )}
                </div>
              )}
            </div>

            <div className="rounded-lg border border-indigo-200 bg-indigo-50/60 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-indigo-800">
                  <Coins className="size-3.5" />
                  预计 token 消耗
                </div>
                <span className="text-[10px] text-indigo-600/80">
                  {estimate?.source === "history"
                    ? `基于 ${estimate.sample_count || 1} 次历史运行`
                    : "启发式估算"}
                </span>
              </div>
              <div className="mt-1 text-lg font-bold text-indigo-800">
                {formatTokens(estimate?.low ?? 0)} ~ {formatTokens(estimate?.high ?? 0)}
                <span className="ml-1 text-[11px] font-normal text-indigo-600/80">tokens</span>
              </div>
              <p className="mt-0.5 text-[10px] text-indigo-600/70">
                预估仅供参考；实际消耗受模型思考、参考资料读取轮次与输出长度影响。
              </p>
            </div>

            {warnings.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50/80 p-3 text-[11px] text-amber-800">
                <div className="flex items-center gap-1.5 font-semibold">
                  <AlertTriangle className="size-3.5" />
                  需要注意
                </div>
                <ul className="mt-1 list-disc pl-4 space-y-0.5">
                  {warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" size="sm" className="text-xs h-8" onClick={onCancel} disabled={loading}>
            取消
          </Button>
          <Button
            size="sm"
            className="text-xs h-8 bg-indigo-600 hover:bg-indigo-700 text-white gap-1.5"
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
            {loading ? "正在启动…" : "确认执行"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
