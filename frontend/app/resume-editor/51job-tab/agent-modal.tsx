/**
 * Job51 自愈 Agent 深度排查弹窗（机械搬迁自 index.tsx 主布局，行为零变化）
 */
"use client"

import { useJob51Ctx } from "./context"

export function Job51AgentModal() {
  const {
    job51AgentModalOpen, setJob51AgentModalOpen, job51AgentReport, job51AgentApplying, handleJob51AgentApplyHeal,
  } = useJob51Ctx()

  if (!(job51AgentModalOpen && job51AgentReport)) return null

  return (
          <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-200">
            <div className="bg-white rounded-2xl shadow-2xl border border-orange-100 w-full max-w-xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
              {/* Agent Modal Header */}
              <div className="px-6 py-4 bg-gradient-to-r from-orange-600 via-[#FF6B00] to-amber-600 text-white flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-white/15 flex items-center justify-center text-lg shadow-inner">
                    🤖
                  </div>
                  <div>
                    <div className="font-bold text-sm tracking-wide flex items-center gap-2">
                      <span>前程无忧数据回写自愈 Agent</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-white/20 border border-white/30 text-white">
                        v2.0
                      </span>
                    </div>
                    <div className="text-[11px] text-orange-100/90 mt-0.5">
                      9227 端口真机取证与 51job 专属 6 大根因知识库
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setJob51AgentModalOpen(false)}
                  className="text-orange-100 hover:text-white text-sm p-1.5 rounded-lg hover:bg-white/10 transition-colors cursor-pointer"
                >
                  ✕
                </button>
              </div>

              {/* Agent Modal Body */}
              <div className="p-6 space-y-4 text-xs">
                {/* 诊断结论卡片 */}
                <div className="p-4 rounded-xl bg-gradient-to-br from-orange-50/80 to-amber-50/50 border border-orange-200/80 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-gray-900 text-sm flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-[#FF6B00] animate-pulse" />
                      排查目标：【{job51AgentReport.module_label || job51AgentReport.module}】
                    </span>
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-orange-100 text-[#FF6B00] border border-[#FF6B00]/30">
                      置信度 {Math.round((job51AgentReport.confidence || 0.95) * 100)}%
                    </span>
                  </div>

                  <div className="pt-2 border-t border-orange-100 space-y-1.5">
                    <div className="font-semibold text-amber-950 flex items-center gap-1.5">
                      <span>📌 命中 51job 根因法则：</span>
                      <span className="font-mono text-orange-700 bg-orange-100/80 px-1.5 py-0.5 rounded text-[11px]">
                        {job51AgentReport.rule_name || job51AgentReport.rule_code}
                      </span>
                    </div>
                    <p className="text-[12px] text-gray-700 leading-relaxed">
                      {job51AgentReport.root_cause}
                    </p>
                  </div>
                </div>

                {/* 自愈处方与行动卡片 */}
                {job51AgentReport.recipe && (
                  <div className="p-4 rounded-xl bg-emerald-50/60 border border-emerald-100 space-y-2">
                    <div className="font-bold text-emerald-900 text-xs flex items-center gap-1.5">
                      <span>💡 Agent 推荐自愈处方：</span>
                      <span className="text-emerald-700">{job51AgentReport.recipe.title}</span>
                    </div>
                    {job51AgentReport.recipe.details && (
                      <p className="text-[11px] text-emerald-800/80 leading-relaxed">
                        {job51AgentReport.recipe.details}
                      </p>
                    )}
                  </div>
                )}

                {/* 现场取证详情 */}
                {job51AgentReport.evidence && (
                  <div className="p-3 rounded-lg bg-gray-50 border border-gray-200/80 space-y-1">
                    <div className="text-[11px] font-semibold text-gray-600">
                      🔍 现场取证摘要 (Live Forensics):
                    </div>
                    <pre className="text-[10px] text-gray-600 font-mono overflow-x-auto whitespace-pre-wrap">
                      {JSON.stringify(job51AgentReport.evidence, null, 2)}
                    </pre>
                  </div>
                )}
              </div>

              {/* Agent Modal Footer */}
              <div className="px-6 py-3.5 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
                <span className="text-[11px] text-gray-400">
                  执行前自动创建 51job 时间戳备份快照，支持一键撤销
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setJob51AgentModalOpen(false)}
                    className="px-3.5 py-1.5 rounded-lg border border-gray-300 bg-white hover:bg-gray-50 text-gray-700 font-medium text-xs cursor-pointer transition-colors"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={handleJob51AgentApplyHeal}
                    disabled={job51AgentApplying}
                    className="px-4 py-1.5 rounded-lg bg-gradient-to-r from-[#FF6B00] to-orange-600 hover:from-[#e55f00] hover:to-orange-700 text-white font-semibold text-xs shadow-sm hover:shadow transition-all disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
                  >
                    {job51AgentApplying ? "正在应用处方..." : "⚡ 一键应用处方并自动重新回传"}
                  </button>
                </div>
              </div>
            </div>
          </div>
  )
}
