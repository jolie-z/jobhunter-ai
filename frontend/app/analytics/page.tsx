"use client"

import { useState } from "react"
import { useAnalyticsData } from "./hooks/use-analytics-data"
import { AnalyticsHeader } from "./components/analytics-header"
import { KpiMetricsGrid } from "./components/kpi-metrics-grid"
import { ConversionFunnelCard } from "./components/conversion-funnel-card"
import { PlatformMatrixCard } from "./components/platform-matrix-card"
import { TrendAnalyticsChart } from "./components/trend-analytics-chart"
import { GoalTrackerCard } from "./components/goal-tracker-card"
import { TokenMonitorSection } from "./components/token-monitor-section"
import { Loader2 } from "lucide-react"

export default function AnalyticsPage() {
  const [activeSection, setActiveSection] = useState("overview")

  const {
    ov,
    funnel,
    funnelCrawled,
    platforms,
    initialTrend,
    goals,
    loading,
    refreshing,
    lastSyncTime,
    refreshAll,
  } = useAnalyticsData()

  return (
    <div className="min-h-screen bg-background text-foreground transition-colors duration-200">
      {/* 顶部极简导航与状态栏 */}
      <AnalyticsHeader
        onRefresh={refreshAll}
        refreshing={refreshing}
        lastSyncTime={lastSyncTime}
        activeSection={activeSection}
        onSectionChange={setActiveSection}
      />

      {/* 主视图区 */}
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 space-y-6">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-32 text-muted-foreground gap-3">
            <Loader2 className="size-6 animate-spin text-primary" />
            <span className="text-xs font-medium">正在拉取全网岗位与漏斗流转数据...</span>
          </div>
        ) : (
          <>
            {/* 1. 全景核心指标卡网格 + 转化率仪表条 */}
            <div id="section-overview" className="scroll-mt-20">
              {ov && <KpiMetricsGrid ov={ov} />}
            </div>

            {/* 1.5 求职目标进度跟踪（数据源 /api/v2/goals/current，编辑入口在配置大盘） */}
            {goals && goals.status === "active" && <GoalTrackerCard goals={goals} />}

            {/* 2. 双核看板：全生命周期流转漏斗 + 平台转化矩阵 */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <ConversionFunnelCard funnel={funnel} totalCrawled={funnelCrawled} />
              <PlatformMatrixCard platforms={platforms} />
            </div>

            {/* 3. 时序多维趋势大盘（内部支持日/周/月独立原地无感切换） */}
            <TrendAnalyticsChart initialTrend={initialTrend} />

            {/* 4. 大模型 Token 算力与成本审计 */}
            <TokenMonitorSection />
          </>
        )}
      </main>
    </div>
  )
}
