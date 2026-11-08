/**
 * pipeline-store 纯函数层（2026-11-02 拆分子任务）。
 *
 * 从 pipeline-store.ts（原 1004 行，超仓库 <500 行门禁）抽离全部无副作用纯逻辑：
 * - PipelineJob 类型 + FAILED_TERMINAL_STATUSES 词表
 * - end 帧 reason 分诊（classifyEndFrame，store 与 SSE toast 共用唯一实现）
 * - 阶段推进/进度秩/文案映射（advanceStages/nodeProgressRank/actionDescForNode）
 * - 岗位实体同判（isSameJobEntity，同司同名去重口径）
 * - mergeProgress（进度合并工具）
 *
 * 仅类型依赖，不 import zustand——保证可被 vitest 直接单测。
 */
export type StageStatus = "pending" | "running" | "done" | "blocked"


export interface PlatformProgress {
  current: number
  total: number
  /** 本轮重复岗位跳过累计（SSE scrape_progress 事件增量上报，Math.max 只增不减） */
  skipped?: number
}

export type PipelineStatus = "idle" | "running" | "done" | "error" | "blocked"

/** 任务级 LLM 阻塞明细（后端 pipeline_blocked 登记表下发，见 emit_stage extra / end summary / stage 快照）。 */
export interface BlockedDetail {
  blocked?: boolean
  task_id?: string
  kind: string          // rate_limited / quota / auth / timeout / connection / server / bad_request / unknown
  model?: string
  message?: string      // 错误类别人话解释
  gateway_hint?: string // 上游原始提示（如 "503 no_healthy_account"）
  retry_after?: number | null
  failed_count?: number
  first_seen?: string
  min_rowid?: number | null
}

/** dashboard-sync 下发的导轨快照：刷新页面后没有 SSE 历史可回放，用它恢复阶段状态。 */
export interface PipelineStageSnapshot {
  task_id?: string | null
  stage_status?: Record<string, StageStatus>
  phases?: {
    hard_clean?: { current: number; total: number }
    ai_scout?: { current: number; total: number }
    feishu_sync?: { current: number; total: number }
  }
  current_stage?: string | null
  blocked?: BlockedDetail | null
}

/** 平台抓取失败通知（SSE platform_failure 事件）：右下角弹窗数据源，用户手动关闭前常驻。 */
export interface PlatformFailure {
  id: string
  platform: string
  platform_name: string
  reason: string
  keyword?: string
  city?: string
  salary?: string
  cursor_note?: string
  /** 后端发射时刻（毫秒）：TaskChannel 断线重连会回放历史导致同载荷二次投递，按 ts 精确去重 */
  ts?: number
  time: string
}

export const PIPELINE_STAGES: { key: string; label: string }[] = [
  { key: "scraping", label: "平台抓取" },
  { key: "cleaning", label: "规则清洗" },
  { key: "feishu_sync", label: "飞书推送" },
  { key: "evaluating", label: "AI初评" },
  { key: "deep_eval", label: "深度评估" },
  { key: "rewriting", label: "简历改写" },
  { key: "greeting", label: "欢迎语" },
  { key: "review", label: "待审批" },
  { key: "delivering", label: "自动投递" },
  { key: "done", label: "完成" },
]

export interface PipelineStore {
  // 当前链路标识
  pipelineTaskId: string | null
  status: PipelineStatus

  // 任务级 LLM 阻塞明细：SSE stage/end 与 12 秒轮询快照三路都会写入，刷新恢复不丢
  blockedDetail: BlockedDetail | null
  setBlocked: (detail: BlockedDetail) => void
  clearBlocked: () => void
  // 「继续任务」受理后置回 running：保留 jobs/logs/blockedDetail（横幅转进行中态）
  resumePipeline: () => void

  // 发射配置时刻
  deliverySchedule: { mass_time: string; custom_time: string }
  setDeliverySchedule: (schedule: { mass_time: string; custom_time: string }) => void

  // 阶段推进
  currentStage: string | null
  stageStatus: Record<string, StageStatus>
  // 已用哪个任务的 stage_snapshot 做过刷新恢复：同一任务只种一次，避免 12 秒轮询
  // 的旧响应覆盖 SSE 已经推进的新阶段。
  stageSnapshotTaskId: string | null

  // 深评/改写的实际门槛（A/B/C，来自后端 job_preferences，前端不得硬编码 A/B）
  autoEvalThreshold: string
  setAutoEvalThreshold: (threshold: string) => void

  // 抓取阶段：各平台并发进度
  scrapeProgress: Record<string, PlatformProgress>

  // 已按指令终止的平台（按平台终止成功后本地置灰标注用）
  abortedPlatforms: string[]

  // 清洗阶段：硬规则 + AI 初筛进度（来自 step1 的 phase_progress）
  hardCleanProgress: PlatformProgress | null
  aiScoutProgress: PlatformProgress | null

  // 飞书推送阶段：同步进度（来自 step2 的 phase_progress phase=feishu_sync）
  feishuSyncProgress: PlatformProgress | null

  // 岗位流转表（job_id -> PipelineJob）
  jobs: Record<string, PipelineJob>

  // 用户已确认淘汰/移除的岗位 id 墓碑：jobs-snapshot 轮询不得再把它们拉回看板
  removedJobIds: string[]

  // 文本日志流
  logs: string[]

  // 平台抓取失败弹窗（右下角，手动关闭前常驻；新任务 startPipeline 时清空）
  platformFailures: PlatformFailure[]
  dismissPlatformFailure: (id: string) => void

  // 结束摘要
  summary: Record<string, any> | null

  // ── Actions ─
  startPipeline: (taskId: string) => void
  handleEvent: (data: any) => void
  updateJob: (jobId: string, partial: Partial<PipelineJob>) => void
  removeJob: (jobId: string) => void
  reset: () => void
  // 按平台终止成功后登记（本地置灰标注「已终止」）
  markPlatformAborted: (platform: string) => void
  // 用后端台账（查库权威值）合并抓取进度：刷新页面后数字不丢不假
  mergeScrapeSnapshot: (entries: { key: string; current: number; total: number }[]) => void
  // 用后端阶段快照恢复导轨状态（不改动 jobs，避免覆盖已合并的岗位快照）
  seedStageSnapshot: (snapshot: PipelineStageSnapshot) => void
  // 全量合并岗位快照（包含 SQLite 淘汰岗位、飞书待审批与已投递记录）
  mergeJobsSnapshot: (
    incomingJobs: PipelineJob[],
    taskId?: string | null,
    schedule?: { mass_time: string; custom_time: string }
  ) => void
}

const initialStageStatus = (): Record<string, StageStatus> =>
  Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, "pending" as StageStatus]))

// 阶段单调秩：快照不得把 SSE 已推进的 done 阶段倒回 running/pending。
// blocked 介于 running 与 done 之间：可覆盖 running（LLM 挂了），不可覆盖 done（已收口）。
export const STAGE_RANK: Record<StageStatus, number> = { pending: 0, running: 1, blocked: 2, done: 3 }

// 🌟 失败终态集合（单一真理源）：执行失败/投递失败等状态，用于阻断乐观运行与卡片分诊
export const FAILED_TERMINAL_STATUSES = new Set([
  "error", "failed", "执行失败", "投递失败",
])

// jobs-snapshot 中代表岗位已到终点的状态（后端台账权威值，优先于本地乐观状态）
// 🌟 error/failed 也算终态：投递失败若不能穿透本地乐观的 delivering，
// 卡片会永久死锁在「正在自动投递中」（重试接口发起时即清失败台账，无状态乒乓风险）
// 🌟 waiting / 待审批 也是权威断点阶段：初评或改写完成进入审批断点时，必须权威穿透本地初评 running，
// 杜绝岗位被误锁在「评估/改写/投递中」Tab 的 Pinning Bug
export const SNAPSHOT_TERMINAL_STATUSES = new Set([
  "delivered", "已投递", "rejected", "rejected_auto", "清洗淘汰", "ai清洗淘汰", ...FAILED_TERMINAL_STATUSES,
  "waiting", "海投人工复核", "简历人工复核", "待审批",
])

export const emptyState = () => ({
  pipelineTaskId: null as string | null,
  status: "idle" as PipelineStatus,
  blockedDetail: null as BlockedDetail | null,
  deliverySchedule: { mass_time: "09:30", custom_time: "14:00" },
  currentStage: null as string | null,
  stageStatus: initialStageStatus(),
  stageSnapshotTaskId: null as string | null,
  autoEvalThreshold: "A",
  scrapeProgress: {} as Record<string, PlatformProgress>,
  abortedPlatforms: [] as string[],
  hardCleanProgress: null as PlatformProgress | null,
  aiScoutProgress: null as PlatformProgress | null,
  feishuSyncProgress: null as PlatformProgress | null,
  jobs: {} as Record<string, PipelineJob>,
  removedJobIds: [] as string[],
  logs: [] as string[],
  platformFailures: [] as PlatformFailure[],
  summary: null as Record<string, any> | null,
})

// 给定当前阶段，把它之前的所有阶段标记为 done，自身标记为 running
export function advanceStages(stageStatus: Record<string, StageStatus>, stageKey: string): Record<string, StageStatus> {
  const idx = PIPELINE_STAGES.findIndex(s => s.key === stageKey)
  if (idx < 0) return stageStatus
  const next = { ...stageStatus }
  for (let i = 0; i < idx; i++) {
    next[PIPELINE_STAGES[i].key] = "done"
  }
  next[stageKey] = "running"
  return next
}

// 节点进度秩：快照若把本地在途岗位降回更早节点（典型：rewrite 中被 Feishu
// 「已完成初步评估」映射成 done/evaluate_node），本地实时态必须获胜。
// 清洗/飞书推送节点必须登记：流式链路下快照仍可能把在途卡打回清洗态，
// 没有秩就失去前端侧的最后一道防降级防线。
const NODE_PROGRESS_RANK: Record<string, number> = {
  scrape_node: 0,
  clean_rule_node: 1,
  clean_ai_node: 2,
  feishu_sync: 3,
  evaluate_node: 4,
  deep_eval_node: 5,
  rewrite_node: 6,
  greeting_node: 7,
  quick_greeting_node: 7,
  manual_review_node: 8,
  ready_to_deliver: 8,
  delivery_node: 9,
}

export function nodeProgressRank(node?: string): number {
  return NODE_PROGRESS_RANK[node || ""] ?? 0
}

// 运行态文案兜底：与后端 pipeline_broadcast.NODE_ACTION_DESC 同源同值。
// 快照缺 last_action_desc 时必须按节点生成文案——曾用固定「正在自动投递中…」兜底，
// 清洗/初评中的岗位会被误标成投递中（2026-10-30 看板实测）。
const NODE_ACTION_DESC: Record<string, string> = {
  clean_rule_node: "硬规则清洗中",
  clean_ai_node: "AI排雷评估中",
  feishu_sync: "正在推送飞书多维表格",
  evaluate_node: "AI初评进行中",
  deep_eval_node: "深度画像评估中",
  rewrite_node: "定制简历改写中",
  greeting_node: "生成打招呼语中",
  quick_greeting_node: "生成打招呼语中",
  manual_review_node: "待老板审批",
  delivery_node: "正在自动投递中",
}

// 子状态文案优先级高于节点（与后端 SUB_STATUS_ACTION_DESC 同源同值）
const SUB_STATUS_ACTION_DESC: Record<string, string> = {
  ai_eval_queued: "AI初评排队中",
  clean_rule_passed: "硬规则通过，排队AI排雷",
  clean_ai_passed: "AI排雷通过，等待推送飞书",
  clean_ai_preserved: "AI排雷未完成，保留待重试",
  feishu_synced: "已推送飞书，等待评估",
  feishu_synced_existing: "已存在于飞书，跳过重复推送",
  feishu_sync_failed: "飞书推送失败，等待下轮重试",
}

export function actionDescForNode(node?: string, subStatus?: string): string {
  if (subStatus && SUB_STATUS_ACTION_DESC[subStatus]) return SUB_STATUS_ACTION_DESC[subStatus]
  return NODE_ACTION_DESC[node || ""] || "流水线运行中"
}

// phase 进度：同一总数下 current 只增不减；总数被重新规划时接受新计划，
// 否则清洗/飞书同步总数变小后进度条会长期显示超额分母。
export function mergeProgress(
  prev: PlatformProgress | null,
  incoming?: { current: number; total: number },
): PlatformProgress | null {
  if (!incoming) return prev
  const incomingTotal = Number(incoming.total) || 0
  const prevTotal = prev?.total ?? 0
  const totalChanged = incomingTotal > 0 && prevTotal > 0 && incomingTotal !== prevTotal
  const incomingCurrent = Number(incoming.current) || 0
  return {
    ...(prev ?? {}),
    current: totalChanged
      ? Math.max(0, incomingCurrent)
      : Math.max(prev?.current ?? 0, incomingCurrent),
    total: incomingTotal || prevTotal,
    skipped: prev?.skipped,
  }
}

function normalizeStr(s?: string | null): string {
  if (!s) return ""
  return s
    .toLowerCase()
    .replace(/[\s\-_—·（）\(\)【】\[\]、，,]/g, "")
    .replace(/股份有限公司|有限公司|有限责任公司|分公司|集团/g, "")
    .trim()
}

// 判断两个岗位是否为同一个现实中的岗位（支持跨阶段 ID 迁移：raw_{rowid} -> rec_{feishu_id}）
export function isSameJobEntity(
  a?: { job_id?: string; job_url?: string; company_name?: string; job_name?: string; raw_job_id?: string } | null,
  b?: { job_id?: string; job_url?: string; company_name?: string; job_name?: string; raw_job_id?: string } | null
): boolean {
  if (!a || !b) return false
  if (a.job_id && b.job_id && a.job_id === b.job_id) return true
  // 强主键关联：如果一个卡片的 raw_job_id 指向另一个卡片的 job_id
  if (a.raw_job_id && b.job_id && a.raw_job_id === b.job_id) return true
  if (b.raw_job_id && a.job_id && b.raw_job_id === a.job_id) return true

  // URL 匹配 (去除 query 参数及尾部斜杠)
  const urlA = (a.job_url || "").split("?")[0].replace(/\/+$/, "").trim()
  const urlB = (b.job_url || "").split("?")[0].replace(/\/+$/, "").trim()
  if (urlA && urlB && urlA === urlB) return true

  // 归一化公司与岗位名匹配
  const compA = normalizeStr(a.company_name)
  const compB = normalizeStr(b.company_name)
  const nameA = normalizeStr(a.job_name)
  const nameB = normalizeStr(b.job_name)
  if (compA && compB && nameA && nameB && compA === compB && nameA === nameB) {
    return true
  }
  return false
}

// 最近一次 jobs-snapshot 所属任务：用于识别任务切换，触发看板「新任务覆盖上一轮岗位」
// 守卫位写入器（CR-B3 拆分子任务）：let 变量跨模块赋值需经函数（ESM live binding 只读）
export let _lastSnapshotTaskId: string | null = null
// 最近一次 startPipeline 时刻（2026-11-02 审计 P1-8 双保险守卫）：快照构建含飞书扇出
// 可耗时数秒，旧任务的在途响应会在新任务启动后才落地。守卫仅在启动后短窗（30s ≈
// 两个轮询周期）内生效——窗口内「载荷 task_id ≠ 本地链路」即判定为在途旧响应，跳过
// 整板清空与链路劫持；窗口过期后恢复既有接管分支（服务端当前任务 ≠ 本地 → 本地已陈旧）。
export const _TASK_SWITCH_GUARD_MS = 30_000
export let _lastStartPipelineAt = 0

export function markSnapshotTask(taskId: string) {
  _lastSnapshotTaskId = taskId
}
export function markPipelineStart() {
  _lastStartPipelineAt = Date.now()
}
export function isWithinTaskSwitchGuard(): boolean {
  return Date.now() - _lastStartPipelineAt < _TASK_SWITCH_GUARD_MS
}
export function currentSnapshotTaskId(): string | null {
  return _lastSnapshotTaskId
}

// end 帧 reason 分诊唯一实现（2026-11-02 审计 P1-9）：store 状态机与 SSE toast 共用，
// 避免双份逻辑漂移。白名单语义——仅 aborted/task_expired/no_resume 三种已知 reason
// 特殊分诊，未知 reason（后端未来给正常收口加 reason 的场景）走既有 done/error 判定，
// 不误报异常。
export type EndFrameKind = "blocked" | "aborted" | "expired" | "no_resume" | "error" | "done"

export function classifyEndFrame(data: any): { kind: EndFrameKind; message: string } {
  // 任务级 LLM 阻塞收口优先级最高：链路是「暂停」而非完成/异常
  if (data?.summary?.outcome === "blocked") {
    return { kind: "blocked", message: "" }
  }
  const err = data?.error ?? data?.summary?.error
  if (err) {
    return { kind: "error", message: String(err) }
  }
  const reason = data?.reason ?? data?.summary?.reason
  const msg = String(data?.message ?? data?.summary?.message ?? "").trim()
  if (reason === "aborted") {
    return { kind: "aborted", message: msg || "任务已终止" }
  }
  if (reason === "task_expired") {
    return { kind: "expired", message: msg || "任务不存在或已过期（后端可能已重启）" }
  }
  if (reason === "no_resume") {
    return { kind: "no_resume", message: msg || "未找到启用状态的基础简历，请前往配置表检查" }
  }
  return { kind: "done", message: "" }
}


export interface PipelineJob {
  job_id: string       // == 飞书 record_id == LangGraph thread_id / raw_{rowid}
  job_name: string
  node: string         // scrape_node / evaluate_node / deep_eval_node / rewrite_node / greeting_node / manual_review_node / delivery_node / error
  status: string       // scraped / running / done / waiting / delivered / rejected / rejected_manual(老板拒绝,仅全部岗位) / error
  sub_status?: string  // 细化子状态：ai_eval | ai_eval_queued | deep_eval | rewriting | greeting | delivering | eval_done(历史兼容)
  grade?: string
  score?: number
  platform?: string
  company_name?: string
  company_scale?: string
  salary?: string
  city?: string
  education?: string
  experience?: string
  job_url?: string
  jd_text?: string
  reject_reason?: string
  reject_type?: "ai" | "rule" | "manual"
  /** 飞书跟进状态原文（快照透传）：疑似重复等特殊审批态据此渲染专属徽章 */
  follow_status?: string
  review_type?: "custom_tailored" | "mass_apply"
  /** 飞书「AI改写JSON」是否有真实产物：区分评级 A/B 但走海投轨的岗位 */
  has_rewrite?: boolean
  greeting_msg?: string
  delivery_materials?: {
    pdf?: boolean
    image?: boolean
    greeting?: boolean
    /** 真实回执：配置了打招呼语但引擎未确认微聊送达（渲染灰色「打招呼未送达」警示） */
    greeting_failed?: boolean
    delivered_at?: string
  }
  failure_info?: {
    step?: string
    reason?: string
    suggestion?: string
    can_retry?: boolean
  }
  is_current_run?: boolean
  pipeline_task_id?: string
  created_at?: string
  crawl_time?: string
  last_action_time?: string
  last_action_desc?: string
  is_today?: boolean
  /** 深度评估是否已完成（跨事件保留：深评结束后紧接 rewrite running，最后一条事件无法回看） */
  deep_eval_done?: boolean
}
