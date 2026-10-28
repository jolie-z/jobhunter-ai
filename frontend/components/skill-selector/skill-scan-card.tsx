"use client"

import { AlertTriangle, Coins, FileText, ShieldCheck } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import type { SkillScanReport } from "@/hooks/use-skill-rewrite"
import { formatTokens } from "@/lib/format-tokens"

/**
 * 上传后扫描卡片：告知预计产物数/类型、是否含简历、token 预估。
 * 只做告知，不阻止非简历 skill（token 是用户自己的）。
 */
export function SkillScanCard({ scan }: { scan: SkillScanReport | null }) {
  if (!scan) return null
  const contract = scan.contract
  const outputs = contract.outputs || []
  const warnings = scan.warnings?.length ? scan.warnings : (contract.warnings || [])
  const est = scan.estimated_tokens || { point: 0, low: 0, high: 0, source: "heuristic" as const }

  return (
    <div className="rounded-md border border-indigo-200 bg-indigo-50/50 p-3 space-y-2 text-xs text-slate-700">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 font-semibold text-indigo-800">
          <ShieldCheck className="size-4" />
          输出扫描与预估
        </div>
        <Badge className="bg-white/70 text-indigo-700 border-indigo-200 text-[10px] font-normal">
          {contract.engine === "agent" ? "多轮 Agent" : "单轮引擎"}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div>
          🎯 预计产物：
          <span className="font-semibold text-indigo-800">
            {contract.expected_artifact_count > 0 ? `${contract.expected_artifact_count} 份` : "未识别到明确数量"}
          </span>
        </div>
        <div>
          📄 是否含简历：
          <span className={`font-semibold ${contract.has_resume_output ? "text-emerald-700" : "text-amber-700"}`}>
            {contract.has_resume_output ? "是" : "未检测到"}
          </span>
        </div>
      </div>

      {outputs.length > 0 && (
        <div className="rounded border border-indigo-100 bg-white/70 p-2 max-h-32 overflow-y-auto space-y-1">
          {outputs.slice(0, 12).map((o) => (
            <div key={o.filename} className="flex items-center justify-between gap-2 text-[11px]">
              <span className="font-mono truncate text-slate-700">{o.filename}</span>
              <div className="flex shrink-0 items-center gap-1">
                {o.is_resume && (
                  <Badge className="bg-emerald-50 text-emerald-700 border-emerald-200 text-[9px] h-4 px-1 font-normal">简历</Badge>
                )}
                {o.is_final && (
                  <Badge className="bg-indigo-50 text-indigo-700 border-indigo-200 text-[9px] h-4 px-1 font-normal">最终</Badge>
                )}
                <Badge variant="outline" className="text-[9px] h-4 px-1 font-normal text-slate-500">
                  {o.kind || "markdown"}
                </Badge>
              </div>
            </div>
          ))}
          {outputs.length > 12 && (
            <p className="text-[10px] text-slate-400">还有 {outputs.length - 12} 份未展示…</p>
          )}
        </div>
      )}

      <div className="flex items-start gap-1.5 rounded border border-indigo-100 bg-white/70 p-2 text-[11px]">
        <Coins className="size-3.5 shrink-0 text-indigo-500 mt-0.5" />
        <div>
          <span className="font-semibold text-indigo-800">
            {formatTokens(est.low)} ~ {formatTokens(est.high)} tokens
          </span>
          <span className="ml-1 text-slate-500">
            {est.source === "history"
              ? `（基于 ${est.sample_count || 1} 次历史完整运行，含当时的 JD/简历）`
              : "（启发式估算；仅技能包，不含本次 JD/简历）"}
          </span>
        </div>
      </div>

      <div className="flex items-start gap-1.5 rounded border border-slate-200 bg-white/70 p-2 text-[11px] text-slate-600">
        <FileText className="size-3.5 shrink-0 text-slate-400 mt-0.5" />
        <span>
          执行时会把 <b>JD/A级画像</b> 与 <b>{contract.has_resume_output ? "简历底稿" : "当前启用简历（作为上下文）"}</b> 一并加载；
          执行前还会再弹一次预检，展示本次实际上下文与 token 预估。
        </span>
      </div>

      {warnings.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50/80 p-2 text-[11px] text-amber-800">
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
  )
}
