"use client"

/**
 * 全链路指挥中心 (Command Deck)
 * =========================================================================
 * 架构重构版：模块化拆分、高内聚低耦合（遵守 <500 行规范与现代 UI 审美）
 * 顶栏控制 + 漏斗转化指标 + 9 阶段执行导轨 + 实时岗位流转看板 + 白盒日志抽屉
 */

import { useState, useEffect, useCallback, useRef } from "react"
import { usePipelineStore } from "@/store/pipeline-store"
import { PipelineSseConnection } from "@/components/dashboard/pipeline/pipeline-sse-connection"
import { CommandHeader } from "@/components/command-center/command-header"
import { MissionFunnelCard } from "@/components/command-center/mission-funnel-card"
import { PipelineStepper } from "@/components/command-center/pipeline-stepper"
import { LiveJobsBoard } from "@/components/command-center/live-jobs-board"
import { BlockedBanner } from "@/components/command-center/blocked-banner"
import { PlatformFailureDialog } from "@/components/command-center/platform-failure-dialog"
import { StageConfigDrawer } from "@/components/command-center/stage-config-drawer"
import { StageKey, STAGES_META } from "@/components/command-center/types"
import { API_BASE } from "@/lib/api"

// 深链白名单（审计 P2-25）：用全部阶段 key 集合（含 deep_eval），与 REQUIRED_MODULES
// （配置缺失判定，8 键无 deep_eval）解耦——此前 ?drawer=deep_eval 深链被误拦
const DRAWER_STAGES = Object.keys(STAGES_META) as StageKey[]
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
  // 轮询时序守卫（2026-11-02 审计 P1-8 第一层）：快照构建含飞书扇出可达数秒，
  // 手动刷新与 12s 轮询并发时旧响应可能后到，按序号丢弃过期落地
  const reloadSeqRef = useRef(0)

  // 聚合同步：一次请求带回 配置状态 + 当前链路 + 抓取台账 + 岗位快照。
  // 替代原 4s config-status + 6s 三连快照共 4 个离散轮询——浏览器对同主机仅 6 条
  // 并发连接（SSE 长连接占大半），高频离散轮询会挤占连接池，拖慢保存等短请求
  const reloadDashboardSync = useCallback(async () => {
    const seq = ++reloadSeqRef.current
    setIsRefreshing(true)
    try {
      const r = await fetch(`${API_BASE}/api/automation/dashboard-sync`)
      if (!r.ok) {
        console.warn(`⚠️ [dashboard-sync] 聚合接口异常 HTTP ${r.status}，本轮跳过（轮询自愈）`)
        return
      }
      const sync = await r.json()
      if (seq !== reloadSeqRef.current) {
        return // 已有更新的刷新在途/落地，本次为过期响应，整体丢弃
      }
      const payload = sync?.data

      const cs = payload?.config_status
      if (cs?.code === 0 && cs.data?.modules) {
        setConfigStatus(cs.data.modules)
      }

      const st = usePipelineStore.getState()
      // 深评/改写分母依赖真实自动化阈值（A/B/C），不能在前端硬编码 A/B
      const threshold = payload?.pipeline_settings?.auto_eval_threshold
      if (threshold) {
        st.setAutoEvalThreshold(threshold)
      }

      const cur = payload?.current_pipeline?.data
      if (cur?.running && cur.task_id) {
        if (st.pipelineTaskId !== cur.task_id) {
          st.startPipeline(cur.task_id)
        }
      }

      const platforms = payload?.run_snapshot?.data?.platforms
      if (platforms?.length) {
        st.mergeScrapeSnapshot(platforms)
      }

      const js = payload?.jobs_snapshot
      if (Array.isArray(js?.data)) {
        st.mergeJobsSnapshot(js.data, js.task_id, js.delivery_schedule)
      }

      // 刷新页面后没有 SSE 历史可回放：用后端实时阶段快照恢复导轨状态/清洗进度
      const stageSnapshot = payload?.stage_snapshot
      if (stageSnapshot) {
        st.seedStageSnapshot(stageSnapshot)
      }
    } catch (err) {
      console.warn("⚠️ [dashboard-sync] 刷新失败（轮询自愈）:", err)
    } finally {
      // 仅最新一次调用有权收口 spinner，避免并发刷新互相提前复位
      if (seq === reloadSeqRef.current) {
        setTimeout(() => setIsRefreshing(false), 400)
      }
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
      if (drawer && DRAWER_STAGES.includes(drawer)) {
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

      {/* 平台抓取失败弹窗：右下角常驻，用户手动关闭（全平台通用） */}
      <PlatformFailureDialog />

      {/* 主工作区 */}
      <main className="flex-1 overflow-y-auto p-6 space-y-5 max-w-7xl mx-auto w-full">
        {/* 全局 LLM 阻塞横幅：阻塞/恢复中显著告知，含修复建议与继续任务入口 */}
        <BlockedBanner />

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
