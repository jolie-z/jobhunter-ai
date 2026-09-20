"use client"

/**
 * 全链路指挥中心 (Command Deck)
 * =========================================================================
 * 架构重构版：模块化拆分、高内聚低耦合（遵守 <500 行规范与现代 UI 审美）
 * 顶栏控制 + 漏斗转化指标 + 9 阶段执行导轨 + 实时岗位流转看板 + 白盒日志抽屉
 */

import { useState, useEffect, useCallback } from "react"
import { usePipelineStore } from "@/store/pipeline-store"
import { PipelineSseConnection } from "@/components/dashboard/pipeline/pipeline-sse-connection"
import { CommandHeader } from "@/components/command-center/command-header"
import { MissionFunnelCard } from "@/components/command-center/mission-funnel-card"
import { PipelineStepper } from "@/components/command-center/pipeline-stepper"
import { LiveJobsBoard } from "@/components/command-center/live-jobs-board"
import { StageConfigDrawer } from "@/components/command-center/stage-config-drawer"
import { StageKey } from "@/components/command-center/types"
import { API_BASE } from "@/lib/api"

const REQUIRED_MODULES = [
  "scraping",
  "cleaning",
  "feishu_sync",
  "evaluating",
  "rewriting",
  "greeting",
  "review",
  "delivering",
]

export default function VariantB() {
  const [configDrawerStage, setConfigDrawerStage] = useState<StageKey | null>(null)
  const [configStatus, setConfigStatus] = useState<Record<string, boolean>>({
    scraping: false,
    cleaning: false,
    feishu_sync: false,
    evaluating: false,
    deep_eval: true,
    rewriting: false,
    greeting: false,
    review: false,
    delivering: false,
  })

  const [isRefreshing, setIsRefreshing] = useState(false)

  // 聚合同步：一次请求带回 配置状态 + 当前链路 + 抓取台账 + 岗位快照。
  // 替代原 4s config-status + 6s 三连快照共 4 个离散轮询——浏览器对同主机仅 6 条
  // 并发连接（SSE 长连接占大半），高频离散轮询会挤占连接池，拖慢保存等短请求
  const reloadDashboardSync = useCallback(async () => {
    setIsRefreshing(true)
    try {
      const r = await fetch(`${API_BASE}/api/automation/dashboard-sync`)
      const sync = await r.json()
      const payload = sync?.data

      const cs = payload?.config_status
      if (cs?.code === 0 && cs.data?.modules) {
        setConfigStatus(cs.data.modules)
      }

      const cur = payload?.current_pipeline?.data
      if (cur?.running && cur.task_id) {
        const st = usePipelineStore.getState()
        if (st.pipelineTaskId !== cur.task_id) {
          st.startPipeline(cur.task_id)
        }
      }

      const platforms = payload?.run_snapshot?.data?.platforms
      if (platforms?.length) {
        usePipelineStore.getState().mergeScrapeSnapshot(platforms)
      }

      const js = payload?.jobs_snapshot
      if (Array.isArray(js?.data)) {
        usePipelineStore.getState().mergeJobsSnapshot(js.data, js.task_id, js.delivery_schedule)
      }
    } catch {}
    finally {
      setTimeout(() => setIsRefreshing(false), 400)
    }
  }, [])

  useEffect(() => {
    reloadDashboardSync()
    const timer = setInterval(reloadDashboardSync, 12000)
    return () => clearInterval(timer)
  }, [reloadDashboardSync])

  // 支持 URL 参数直达抽屉：例如 ?drawer=greeting
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search)
      const drawer = params.get("drawer") as StageKey | null
      if (drawer && REQUIRED_MODULES.includes(drawer)) {
        setConfigDrawerStage(drawer)
      }
    }
  }, [])

  // 监听全链路深层组件唤起阶段规则抽屉事件（如待投递 Banner 唤起平台抓取面板）
  useEffect(() => {
    const handleOpenDrawer = (e: Event) => {
      const customEvent = e as CustomEvent<{ stageKey: StageKey }>
      if (customEvent.detail?.stageKey) {
        setConfigDrawerStage(customEvent.detail.stageKey)
      }
    }
    window.addEventListener("open-stage-config-drawer", handleOpenDrawer)
    return () => window.removeEventListener("open-stage-config-drawer", handleOpenDrawer)
  }, [])

  // 自动挂接正在运行的全链路并恢复岗位流转快照已并入上方 reloadDashboardSync 聚合轮询

  const allConfigured = REQUIRED_MODULES.every((k) => configStatus[k])

  return (
    <div className="h-screen w-screen overflow-hidden flex flex-col bg-background text-foreground select-none">
      {/* SSE 实时消息接收连接器 */}
      <PipelineSseConnection />

      {/* 现代化顶栏控制舱 */}
      <CommandHeader
        allConfigured={allConfigured}
        configStatus={configStatus}
        onOpenConfig={(stageKey) => setConfigDrawerStage(stageKey)}
      />

      {/* 主工作区 */}
      <main className="flex-1 overflow-y-auto p-6 space-y-5 max-w-7xl mx-auto w-full">
        {/* 全链路转化漏斗与统计大盘 */}
        <MissionFunnelCard />

        {/* 9 阶段执行导轨与状态指示 */}
        <PipelineStepper
          configStatus={configStatus}
          onOpenConfig={(stageKey) => setConfigDrawerStage(stageKey)}
          onRefreshStatus={reloadDashboardSync}
          isRefreshing={isRefreshing}
        />

        {/* 实时岗位流转看板与审批操作 */}
        <LiveJobsBoard onOpenConfig={(stageKey) => setConfigDrawerStage(stageKey)} />
      </main>

      {/* 阶段配置抽屉 */}
      <StageConfigDrawer
        stageKey={configDrawerStage}
        onClose={() => {
          setConfigDrawerStage(null)
          reloadDashboardSync()
        }}
        onSaved={reloadDashboardSync}
      />

    </div>
  )
}
