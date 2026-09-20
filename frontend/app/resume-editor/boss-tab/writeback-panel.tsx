/**
 * BOSS 模块勾选回写栏（机械搬迁自主 JSX 回写区，行为零变化）
 */
"use client"

import { Loader2, Save, Upload, Lock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { BOSS_MODULES, BOSS_MODULE_MAP, BOSS_PRIMARY } from "./constants"
import { useBossCtx } from "./context"
import { SnapshotPicker } from "../snapshot-picker"

export function BossWritebackPanel() {
  const {
    data, localData, bossOptions, saving, report, reportLoading, showToast,
    handleApplyReport, handleSaveWritebackSource, handleWritebackModules,
    handleRollbackBossSnapshot, handleBossAgentApplyHeal, handleDispatchBossHealerAgent,
    selectedModules, setSelectedModules, selectedModuleKeys, toggleAllModules,
    writebacking, writebackConfirm, setWritebackConfirm, writebackFeedback,
    showWritebackDetails, setShowWritebackDetails, savingSnapshot, snapshotFeedback,
    bossAgentDiagnosing, bossAgentReport, bossAgentModalOpen, setBossAgentModalOpen,
    bossAgentApplying, bossRollbackFeedback, bossRollingBack,
  } = useBossCtx()

  return (
    <>
        {/* 0b. 模块勾选回写（部分模块/全部模块 → BOSS 官网；姓名/电话/邮箱/微信号/工作年限为 HARD_SKIP 仅可通过官网修改） */}
        <div className="sticky top-0 z-40 bg-white/95 backdrop-blur border border-gray-200 rounded-lg p-3 shadow-sm">
          <div className="flex items-center justify-between gap-2 mb-2">
            <h3 className="text-sm font-bold text-gray-900 shrink-0">BOSS 模块回写</h3>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={toggleAllModules}
                className="text-xs text-gray-500 hover:opacity-80 cursor-pointer"
              >
                {BOSS_MODULES.every(m => selectedModules[m.key]) ? "全不选" : "全选"}
              </button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleSaveWritebackSource}
                disabled={savingSnapshot}
                className="h-7 text-xs"
                style={{ borderColor: `${BOSS_PRIMARY}66`, color: BOSS_PRIMARY }}
              >
                {savingSnapshot ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}
                {savingSnapshot ? "保存中..." : "保存快照"}
              </Button>
              <SnapshotPicker platform="boss" onRollback={handleRollbackBossSnapshot} rollingBack={bossRollingBack} />
              {!writebackConfirm ? (
                <Button
                  size="sm"
                  className="h-7 text-xs text-white"
                  style={{ backgroundColor: BOSS_PRIMARY }}
                  onClick={() => setWritebackConfirm(true)}
                  disabled={writebacking}
                >
                  {writebacking ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Upload className="w-3 h-3 mr-1" />}
                  {writebacking ? "回写中..." : `回写选中模块（${selectedModuleKeys().length}）`}
                </Button>
              ) : (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200">
                  <span className="text-xs text-amber-700">将把勾选的 {selectedModuleKeys().length} 个模块写入 BOSS直聘 官网在线简历，确认？</span>
                  <button type="button" onClick={handleWritebackModules} disabled={writebacking} className="text-xs px-2 py-0.5 rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50">
                    {writebacking ? "回写中..." : "确认回写"}
                  </button>
                  <button type="button" onClick={() => setWritebackConfirm(false)} className="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {BOSS_MODULES.map(m => (
              <div key={m.key} className={cn(
                "flex items-center gap-1 px-2 py-1 rounded-md border text-xs cursor-pointer select-none transition-colors",
                selectedModules[m.key] ? "text-[#00beab]" : "border-gray-200 bg-white text-gray-500"
              )} style={selectedModules[m.key] ? { borderColor: `${BOSS_PRIMARY}80`, backgroundColor: "#F0FDFB" } : undefined}>
                <Checkbox
                  checked={selectedModules[m.key]}
                  onCheckedChange={(v) => setSelectedModules(prev => ({ ...prev, [m.key]: !!v }))}
                  className="w-3.5 h-3.5"
                />
                {m.label}
              </div>
            ))}
            <div className="flex items-center gap-1 px-2 py-1 rounded-md border border-gray-100 bg-gray-50 text-xs text-gray-400 select-none" title="姓名/电话/邮箱/微信号/工作年限为官网核心字段（HARD_SKIP），仅可通过官网修改">
              <Lock className="w-3 h-3" />
              姓名/电话/邮箱等
            </div>
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

              {/* 结构化模块回写状态明细 */}
              {Array.isArray(writebackFeedback.details) && writebackFeedback.details.length > 0 && (
                <div className="mt-2 pt-2 border-t border-black/5 space-y-1">
                  {writebackFeedback.details.map((m, idx) => (
                    <div key={idx} className="flex items-start gap-1.5 text-[11px]">
                      <span className={m.success ? "text-emerald-600 font-bold" : "text-rose-600 font-bold"}>
                        {m.success ? "✓" : "✗"}
                      </span>
                      <span className="font-medium text-gray-700">
                        {BOSS_MODULE_MAP[m.module] || m.module}:
                      </span>
                      <span className={m.success ? "text-gray-600" : "text-rose-700 font-medium"}>
                        {m.message}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* 可折叠底层原始日志输出 */}
              {showWritebackDetails && writebackFeedback.output && (
                <pre className="mt-2.5 p-2 rounded bg-black/85 text-gray-200 text-[10px] font-mono whitespace-pre-wrap max-h-40 overflow-y-auto leading-relaxed border border-black/10 select-text">
                  {writebackFeedback.output}
                </pre>
              )}
            </div>
          )}

          {/* BOSS 智能分级诊断与自愈 Agent 行动卡片 */}
          {writebackFeedback && !writebackFeedback.ok && (() => {
            const failedDetails = (writebackFeedback.details || []).filter(d => !d.success)
            const targetModKey = failedDetails.length > 0 ? failedDetails[0].module : (selectedModuleKeys()[0] || "projects")
            const targetModLabel = BOSS_MODULE_MAP[targetModKey] || targetModKey

            return (
              <div className="mt-2.5 rounded-lg border border-[#00beab]/30 bg-gradient-to-r from-teal-50/90 via-emerald-50/70 to-cyan-50/60 p-3.5 shadow-sm text-xs">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-[#00beab]/15 text-[#00beab] border border-[#00beab]/30">
                        🤖 BOSS直聘 自愈 Agent 待命
                      </span>
                      <span className="font-medium text-teal-950">
                        检测到【{targetModLabel}】回写复核存在差异或异常
                      </span>
                    </div>
                    <p className="text-[11px] text-teal-900/80 leading-relaxed">
                      若数据实际已在 BOSS 官网生效，刷新官网即可；若确未生效或遭遇 项目职务必填/字符超限/起止时间契约，可立即派出 BOSS 自愈 Agent 进行现场深度取证与自愈修复。
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
                      onClick={() => handleDispatchBossHealerAgent(targetModKey)}
                      disabled={bossAgentDiagnosing}
                      className="px-3 py-1.5 rounded-md bg-gradient-to-r from-[#00beab] to-teal-600 hover:from-[#00a897] hover:to-teal-700 text-white font-semibold text-[11px] transition-all cursor-pointer shadow-sm hover:shadow flex items-center gap-1.5 disabled:opacity-50"
                    >
                      {bossAgentDiagnosing ? "Agent 诊断中..." : `🤖 派出自愈 Agent 深度排查「${targetModLabel}」`}
                    </button>
                  </div>
                </div>
              </div>
            )
          })()}

          {/* BOSS 自愈备份与撤销条 */}
          {bossRollbackFeedback && (
            <div className="mt-2.5 flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-xs bg-emerald-50 border border-emerald-200 text-emerald-900 shadow-xs">
              <span className="font-medium">
                ✅ {bossRollbackFeedback.msg}
              </span>
              <button
                type="button"
                onClick={() => handleRollbackBossSnapshot(bossRollbackFeedback.snapshotId)}
                disabled={bossRollingBack}
                className="px-2.5 py-1 rounded bg-white hover:bg-gray-50 text-gray-700 font-semibold text-[11px] border border-gray-200 shadow-xs transition-all cursor-pointer shrink-0"
              >
                {bossRollingBack ? "正在恢复..." : "↩️ 撤销本次自愈 / 恢复备份"}
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
