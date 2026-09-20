/**
 * Zhilian 模块勾选回写面板（机械搬迁自 zhilian-tab.tsx 主布局，行为零变化）
 */
"use client"

import { Button } from "@/components/ui/button"
import { Loader2, Save, Upload, ScanSearch } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { PRIMARY, ZHILIAN_MODULES, ZHILIAN_MODULE_MAP } from "./constants"
import { useZhilianCtx } from "./context"
import { SnapshotPicker } from "../snapshot-picker"

export function ZhilianWritebackPanel() {
  const {
    selectedModules, setSelectedModules, toggleAllModules, selectedModuleKeys, scrollToModule,
    handleSaveWritebackSource, savingSnapshot, snapshotFeedback,
    writebackConfirm, setWritebackConfirm, writebacking, handleWritebackModules,
    writebackFeedback, showWritebackDetails, setShowWritebackDetails,
    agentDiagnosing, handleDispatchHealerAgent,
    rollbackFeedback, rollingBack, handleRollbackSnapshot,
    probingSchema, handleOpenSchemaProbe,
  } = useZhilianCtx()

  return (
    <>
        {/* 0. 模块勾选回写（部分模块/全部模块 → 智联官网；基本信息 HARD_SKIP 仅可通过官网修改） */}
        <div className="sticky top-0 z-40 bg-white/95 backdrop-blur border border-gray-200 rounded-lg p-3 mb-4 shadow-sm">
          <div className="flex items-center justify-between gap-2 mb-2">
            <h3 className="text-sm font-bold text-gray-900 shrink-0">智联模块回写</h3>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={toggleAllModules}
                className="text-xs text-gray-500 hover:opacity-80 cursor-pointer"
                style={{ color: "#6b7280" }}
              >
                {ZHILIAN_MODULES.every(m => selectedModules[m.key]) ? "全不选" : "全选"}
              </button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleSaveWritebackSource}
                disabled={savingSnapshot}
                className="h-7 text-xs"
                style={{ borderColor: `${PRIMARY}66`, color: PRIMARY }}
              >
                {savingSnapshot ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}
                {savingSnapshot ? "保存中..." : "保存快照"}
              </Button>
              <SnapshotPicker platform="zhilian" onRollback={handleRollbackSnapshot} rollingBack={rollingBack} />
              <Button
                variant="outline"
                size="sm"
                onClick={handleOpenSchemaProbe}
                disabled={probingSchema}
                className="h-7 text-xs"
                style={{ borderColor: `${PRIMARY}66`, color: PRIMARY }}
                title="0-Token 反射探测智联官网当前字段结构，与本地数据模型比对后弹出差分审核抽屉（官网改版自愈入口）"
              >
                {probingSchema ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <ScanSearch className="w-3 h-3 mr-1" />}
                {probingSchema ? "探测中..." : "探测官网结构"}
              </Button>
              {!writebackConfirm ? (
                <Button
                  size="sm"
                  className="h-7 text-xs text-white"
                  style={{ backgroundColor: PRIMARY }}
                  onClick={() => setWritebackConfirm(true)}
                  disabled={writebacking}
                >
                  {writebacking ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Upload className="w-3 h-3 mr-1" />}
                  {writebacking ? "回写中..." : `回写选中模块（${selectedModuleKeys().length}）`}
                </Button>
              ) : (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200">
                  <span className="text-xs text-amber-700">将把勾选的 {selectedModuleKeys().length} 个模块写入智联官网在线简历，确认？</span>
                  <button type="button" onClick={handleWritebackModules} disabled={writebacking} className="text-xs px-2 py-0.5 rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50">
                    {writebacking ? "回写中..." : "确认回写"}
                  </button>
                  <button type="button" onClick={() => setWritebackConfirm(false)} className="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {ZHILIAN_MODULES.map(m => (
              <div key={m.key} className={cn(
                "flex items-center gap-1 px-2 py-1 rounded-md border text-xs cursor-pointer select-none transition-colors",
                selectedModules[m.key] ? "text-[#2A7BFF]" : "border-gray-200 bg-white text-gray-500"
              )} style={selectedModules[m.key] ? { borderColor: `${PRIMARY}80`, backgroundColor: "#F0F6FF" } : undefined}>
                <Checkbox
                  checked={selectedModules[m.key]}
                  onCheckedChange={(v) => setSelectedModules(prev => ({ ...prev, [m.key]: !!v }))}
                  className="w-3.5 h-3.5"
                />
                <button type="button" onClick={() => scrollToModule(m.anchor)} className="hover:text-[#1a6ae8]">
                  {m.label}
                </button>
              </div>
            ))}
          </div>
          {/* 就地反馈：常驻展示执行时间戳，结构化排版与错误解析 */}
          {writebackFeedback && (
            <div
              role="status"
              className={`mt-2.5 rounded-lg text-xs border p-3 shadow-sm transition-all ${
                writebackFeedback.ok
                  ? "bg-emerald-50/90 border-emerald-200 text-emerald-900"
                  : "bg-rose-50/90 border-rose-200 text-rose-900"
              }`}
            >
              <div className="flex items-center gap-2">
                {writebackFeedback.time && (
                  <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-black/5 font-semibold shrink-0 select-none">
                    [{writebackFeedback.time}]
                  </span>
                )}
                <span className="font-semibold flex-1 leading-snug">
                  {writebackFeedback.ok ? "✓ " : "✗ "}
                  {writebackFeedback.msg}
                </span>
                {writebackFeedback.output && (
                  <button
                    type="button"
                    onClick={() => setShowWritebackDetails(v => !v)}
                    className="text-[11px] text-gray-500 hover:text-gray-900 underline decoration-dotted ml-auto shrink-0 cursor-pointer"
                  >
                    {showWritebackDetails ? "收起日志" : "查看日志"}
                  </button>
                )}
              </div>

              {/* 字数超限拦截专属诊断卡片 */}
              {writebackFeedback.overflow_violations && writebackFeedback.overflow_violations.length > 0 && (
                <div className="mt-2.5 rounded-lg bg-red-100/80 border border-red-300/80 p-3 text-xs text-red-950 space-y-2">
                  <div className="flex items-center gap-1.5 font-bold text-red-900">
                    <span className="px-1.5 py-0.5 rounded bg-red-600 text-white text-[10px] tracking-wide">字数超限拦截</span>
                    <span>检测到以下字段超出智联官方上限，系统已阻止提交以防内容丢失：</span>
                  </div>
                  <div className="space-y-1.5">
                    {writebackFeedback.overflow_violations.map((v: any, vIdx: number) => (
                      <div key={vIdx} className="bg-white/90 border border-red-200 rounded-md p-2 text-[11px] space-y-1 shadow-2xs">
                        <div className="font-medium text-red-700 flex items-center gap-1.5">
                          <span className="w-4 h-4 rounded-full bg-red-100 text-red-600 text-center leading-4 text-[10px] font-bold shrink-0">{vIdx + 1}</span>
                          <span>{v.reason}</span>
                        </div>
                        <div className="text-gray-700 pl-5">
                          💡 <span className="font-medium text-gray-900">解决指引：</span>{v.suggestion}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 结构化模块回写状态明细 */}
              {Array.isArray(writebackFeedback.details) && writebackFeedback.details.length > 0 && (
                <div className="mt-2 pt-2 border-t border-black/5 space-y-1">
                  {writebackFeedback.details.map((m, idx) => (
                    <div key={idx} className="flex items-start gap-1.5 text-[11px]">
                      <span className={m.success ? "text-emerald-600 font-bold" : "text-rose-600 font-bold"}>
                        {m.success ? "✓" : "✗"}
                      </span>
                      <span className="font-medium text-gray-700">
                        {ZHILIAN_MODULE_MAP[m.module] || m.module}:
                      </span>
                      <span className={m.success ? "text-gray-600" : "text-rose-700 font-medium"}>
                        {m.message}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* 可折叠底层原始日志输出（三阶段人性化排版） */}
              {showWritebackDetails && writebackFeedback.output && (
                <div className="mt-2.5 rounded-md bg-gray-950 text-gray-200 p-3 text-[11px] font-mono whitespace-pre-wrap max-h-56 overflow-y-auto leading-relaxed border border-gray-800 select-text">
                  <div className="text-[10px] text-gray-400 font-bold pb-1.5 mb-1.5 border-b border-gray-800 flex items-center justify-between">
                    <span>📋 智联回写全链路执行日志</span>
                    <span className="text-gray-500 font-normal">三阶段日志流</span>
                  </div>
                  {writebackFeedback.output}
                </div>
              )}
            </div>
          )}

          {/* 智能分级诊断与行动建议卡片 */}
          {writebackFeedback && !writebackFeedback.ok && (() => {
            const failedDetails = (writebackFeedback.details || []).filter(d => !d.success)
            const targetModKey = failedDetails.length > 0 ? failedDetails[0].module : (selectedModuleKeys()[0] || "certificates")
            const targetModLabel = ZHILIAN_MODULE_MAP[targetModKey] || targetModKey

            return (
              <div className="mt-2.5 rounded-lg border border-indigo-200/90 bg-gradient-to-r from-indigo-50/90 via-purple-50/70 to-amber-50/60 p-3.5 shadow-sm text-xs">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-100 text-indigo-800 border border-indigo-300/60">
                        🤖 自愈 Agent 待命
                      </span>
                      <span className="font-medium text-indigo-950">
                        检测到【{targetModLabel}】回写复核存在差异或异常
                      </span>
                    </div>
                    <p className="text-[11px] text-indigo-900/80 leading-relaxed">
                      若数据实际已在官网正常生效（缓存时延），刷新官网页面即可；若确未生效，可立即派出自愈 Agent 进行现场深度取证与自动修复。
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={handleWritebackModules}
                      disabled={writebacking}
                      className="px-2.5 py-1.5 rounded-md border border-gray-300 bg-white hover:bg-gray-50 text-gray-700 font-medium text-[11px] transition-colors cursor-pointer shadow-xs disabled:opacity-50"
                    >
                      🔄 重新尝试
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDispatchHealerAgent(targetModKey)}
                      disabled={agentDiagnosing}
                      className="px-3 py-1.5 rounded-md bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white font-semibold text-[11px] transition-all cursor-pointer shadow-sm hover:shadow flex items-center gap-1.5 disabled:opacity-50"
                    >
                      {agentDiagnosing ? "Agent 诊断中..." : `🤖 派出自愈 Agent 深度排查「${targetModLabel}」`}
                    </button>
                  </div>
                </div>
              </div>
            )
          })()}

          {/* 自愈备份与撤销条 */}
          {rollbackFeedback && (
            <div className="mt-2.5 flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-xs bg-emerald-50 border border-emerald-200 text-emerald-900 shadow-xs">
              <span className="font-medium">
                ✅ {rollbackFeedback.msg}
              </span>
              <button
                type="button"
                onClick={() => handleRollbackSnapshot(rollbackFeedback.snapshotId)}
                disabled={rollingBack}
                className="px-2.5 py-1 rounded bg-white hover:bg-gray-50 text-gray-700 font-semibold text-[11px] border border-gray-200 shadow-xs transition-all cursor-pointer shrink-0"
              >
                {rollingBack ? "正在恢复..." : "↩️ 撤销本次自愈 / 恢复备份"}
              </button>
            </div>
          )}
          {snapshotFeedback && (
            <div
              role="status"
              className={`mt-2 flex items-start gap-1.5 px-2.5 py-1.5 rounded-md text-xs border ${
                snapshotFeedback.ok
                  ? "bg-emerald-50/90 border-emerald-200 text-emerald-800"
                  : "bg-rose-50/90 border-rose-200 text-rose-800"
              }`}
            >
              {snapshotFeedback.time && (
                <span className="font-mono text-[11px] px-1 py-0.5 rounded bg-black/5 font-semibold shrink-0 select-none">
                  [{snapshotFeedback.time}]
                </span>
              )}
              <span className="leading-tight flex-1 break-all">{snapshotFeedback.msg}</span>
            </div>
          )}
        </div>
    </>
  )
}
