"use client"

import { useEffect, useState } from "react"
import { X } from "lucide-react"
import { toast } from "sonner"
import { StageKey, STAGES_META } from "./types"
import { ScrapeConfigPanel } from "./drawers/scrape-config-panel"
import { CleaningConfigPanel } from "./drawers/cleaning-config-panel"
import { FeishuConfigPanel } from "./drawers/feishu-config-panel"
import { EvalConfigPanel } from "./drawers/eval-config-panel"
import { DeepEvalConfigPanel } from "./drawers/deep-eval-config-panel"
import { RewriteConfigPanel } from "./drawers/rewrite-config-panel"
import { GreetingConfigPanel } from "./drawers/greeting-config-panel"
import { ReviewConfigPanel } from "./drawers/review-config-panel"
import { DeliveryConfigPanel } from "./drawers/delivery-config-panel"

interface StageConfigDrawerProps {
  stageKey: StageKey | null
  onClose: () => void
  onSaved: () => void
}

/**
 * 全链路阶段规则设置抽屉（骨架与 Tab 路由分发）
 * 各模块规则面板已拆分为独立深模块，遵守 <500 行规范。
 */
export function StageConfigDrawer({
  stageKey,
  onClose,
  onSaved,
}: StageConfigDrawerProps) {
  const [activeTab, setActiveTab] = useState<StageKey>("scraping")
  const [prevStageKey, setPrevStageKey] = useState(stageKey)
  // 面板保存进行中时拦截抽屉关闭：页面级卸载会静默杀掉排队中的保存请求（刷新/关标签），导致「明明保存了却失效」
  const [panelSaving, setPanelSaving] = useState(false)
  // 抽屉打开目标阶段变化时同步 Tab（渲染期间调整，避免 effect 内同步 setState）。
  // STAGES_META 只收录 9 个可配置阶段：done 等终态阶段没有规则面板，不进入 Tab
  if (stageKey && STAGES_META.some((s) => s.key === stageKey) && stageKey !== prevStageKey) {
    setPrevStageKey(stageKey)
    setActiveTab(stageKey)
  }

  // 抽屉关闭时复位保存锁，避免下次打开被残留状态锁死
  useEffect(() => {
    if (!stageKey) setPanelSaving(false)
  }, [stageKey])

  const requestClose = () => {
    if (panelSaving) {
      toast.info("正在保存配置，请等保存完成后关闭，避免保存请求被中断丢失")
      return
    }
    onClose()
  }

  // 打开时锁定背景滚动 + 支持 Esc 关闭（stageKey 变化或卸载时还原/解绑）
  useEffect(() => {
    if (!stageKey) return
    document.body.style.overflow = "hidden"
    const handleKeydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose()
    }
    document.addEventListener("keydown", handleKeydown)
    return () => {
      document.body.style.overflow = ""
      document.removeEventListener("keydown", handleKeydown)
    }
    // requestClose 随 panelSaving 变化重建监听，保证锁状态即时生效
  }, [stageKey, requestClose])

  if (!stageKey) return null
  // 防御：未收录在 STAGES_META 的阶段（如 done）没有配置面板，直接不开抽屉
  if (!STAGES_META.some((s) => s.key === stageKey)) return null

  const currentMeta = STAGES_META.find((s) => s.key === activeTab)

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-xs animate-in fade-in duration-200"
      onClick={requestClose}
    >
      <div
        className="relative h-full w-full max-w-xl border-l border-border bg-background shadow-2xl flex flex-col animate-in slide-in-from-right duration-300"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 抽屉顶栏 */}
        <div className="flex h-16 items-center justify-between border-b border-border/80 px-6 shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-xl">{currentMeta?.icon || "⚙️"}</span>
            <div>
              <h2 className="text-sm font-semibold text-foreground">
                {currentMeta?.label} · 规则设置
              </h2>
              <p className="text-[11px] text-muted-foreground">
                {currentMeta?.desc}
              </p>
            </div>
          </div>

          <button
            onClick={requestClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 抽屉内容区 */}
        <div className="flex-1 overflow-y-auto p-6">
          {activeTab === "scraping" && <ScrapeConfigPanel onSaved={onSaved} />}
          {activeTab === "cleaning" && <CleaningConfigPanel onSaved={onSaved} />}
          {activeTab === "feishu_sync" && <FeishuConfigPanel onSaved={onSaved} />}
          {activeTab === "evaluating" && <EvalConfigPanel onSaved={onSaved} />}
          {activeTab === "deep_eval" && <DeepEvalConfigPanel onSaved={onSaved} />}
          {activeTab === "rewriting" && <RewriteConfigPanel onSaved={onSaved} />}
          {activeTab === "greeting" && (
            <GreetingConfigPanel onSaved={onSaved} onSavingChange={setPanelSaving} />
          )}
          {activeTab === "review" && <ReviewConfigPanel onSaved={onSaved} />}
          {activeTab === "delivering" && <DeliveryConfigPanel onSaved={onSaved} />}
        </div>
      </div>
    </div>
  )
}
