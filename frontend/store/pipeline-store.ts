import { create } from 'zustand'

/**
 * 全链路指挥中心 · 实时状态库
 * ============================
 * 与 crawler-task-store 解耦：全链路事件协议（stage/progress/job/log/end）
 * 与单平台爬虫任务模型不同，故单独建库，避免互相污染。
 *
 * 事件来源：GET /api/tasks/logs?task_id=pipeline_xxx（复用现有 SSE 总线）。
 * 事件协议见 backend/app/automation/pipeline_broadcast.py。
 */

// 与后端 PIPELINE_STAGES 完全一致（顺序即渲染顺序）
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

export type StageStatus = "pending" | "running" | "done"

export interface PipelineJob {
  job_id: string       // == 飞书 record_id == LangGraph thread_id / raw_{rowid}
  job_name: string
  node: string         // scrape_node / evaluate_node / deep_eval_node / rewrite_node / greeting_node / manual_review_node / delivery_node / error
  status: string       // scraped / running / done / waiting / delivered / rejected / rejected_manual(老板拒绝,仅全部岗位) / error
  sub_status?: string  // 细化子状态：ai_eval | deep_eval | rewriting | greeting
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
  review_type?: "custom_tailored" | "mass_apply"
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
}

export interface PlatformProgress {
  current: number
  total: number
}

export type PipelineStatus = "idle" | "running" | "done" | "error"

interface PipelineStore {
  // 当前链路标识
  pipelineTaskId: string | null
  status: PipelineStatus

  // 发射配置时刻
  deliverySchedule: { mass_time: string; custom_time: string }
  setDeliverySchedule: (schedule: { mass_time: string; custom_time: string }) => void

  // 阶段推进
  currentStage: string | null
  stageStatus: Record<string, StageStatus>

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
  // 全量合并岗位快照（包含 SQLite 淘汰岗位、飞书待审批与已投递记录）
  mergeJobsSnapshot: (
    incomingJobs: PipelineJob[],
    taskId?: string | null,
    schedule?: { mass_time: string; custom_time: string }
  ) => void
}

const initialStageStatus = (): Record<string, StageStatus> =>
  Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, "pending" as StageStatus]))

// 🌟 失败终态集合（单一真理源）：执行失败/投递失败等状态，用于阻断乐观运行与卡片分诊
export const FAILED_TERMINAL_STATUSES = new Set([
  "error", "failed", "执行失败", "投递失败",
])

// jobs-snapshot 中代表岗位已到终点的状态（后端台账权威值，优先于本地乐观状态）
// 🌟 error/failed 也算终态：投递失败若不能穿透本地乐观的 delivering，
// 卡片会永久死锁在「正在自动投递中」（重试接口发起时即清失败台账，无状态乒乓风险）
// 🌟 waiting / 待审批 也是权威断点阶段：初评或改写完成进入审批断点时，必须权威穿透本地初评 running，
// 杜绝岗位被误锁在「评估/改写/投递中」Tab 的 Pinning Bug
const SNAPSHOT_TERMINAL_STATUSES = new Set([
  "delivered", "已投递", "rejected", "rejected_auto", "清洗淘汰", "ai清洗淘汰", ...FAILED_TERMINAL_STATUSES,
  "waiting", "海投人工复核", "简历人工复核", "待审批",
])

const emptyState = () => ({
  pipelineTaskId: null as string | null,
  status: "idle" as PipelineStatus,
  deliverySchedule: { mass_time: "09:30", custom_time: "14:00" },
  currentStage: null as string | null,
  stageStatus: initialStageStatus(),
  scrapeProgress: {} as Record<string, PlatformProgress>,
  abortedPlatforms: [] as string[],
  hardCleanProgress: null as PlatformProgress | null,
  aiScoutProgress: null as PlatformProgress | null,
  feishuSyncProgress: null as PlatformProgress | null,
  jobs: {} as Record<string, PipelineJob>,
  removedJobIds: [] as string[],
  logs: [] as string[],
  summary: null as Record<string, any> | null,
})

// 给定当前阶段，把它之前的所有阶段标记为 done，自身标记为 running
function advanceStages(stageStatus: Record<string, StageStatus>, stageKey: string): Record<string, StageStatus> {
  const idx = PIPELINE_STAGES.findIndex(s => s.key === stageKey)
  if (idx < 0) return stageStatus
  const next = { ...stageStatus }
  for (let i = 0; i < idx; i++) {
    next[PIPELINE_STAGES[i].key] = "done"
  }
  next[stageKey] = "running"
  return next
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
function isSameJobEntity(
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
let _lastSnapshotTaskId: string | null = null

export const usePipelineStore = create<PipelineStore>((set) => ({
  ...emptyState(),

  startPipeline: (taskId) => {
    _lastSnapshotTaskId = taskId
    set({
      ...emptyState(),
      pipelineTaskId: taskId,
      status: "running",
    })
  },

  reset: () => set({ ...emptyState() }),

  updateJob: (jobId, partial) => set((state) => {
    const prev = state.jobs[jobId]
    if (!prev) return state
    return {
      jobs: {
        ...state.jobs,
        [jobId]: { ...prev, ...partial },
      }
    }
  }),

  removeJob: (jobId) => set((state) => {
    const { [jobId]: _, ...rest } = state.jobs
    // 登记墓碑并限长，防止 jobs-snapshot 轮询把已确认淘汰的岗位复活
    const tombstones = [...state.removedJobIds.filter((id) => id !== jobId), jobId].slice(-500)
    return { jobs: rest, removedJobIds: tombstones }
  }),

  markPlatformAborted: (platform) => set((state) =>
    state.abortedPlatforms.includes(platform)
      ? state
      : { abortedPlatforms: [...state.abortedPlatforms, platform] }
  ),

  setDeliverySchedule: (schedule) => set({ deliverySchedule: schedule }),

  mergeScrapeSnapshot: (entries) => set((state) => {
    if (!Array.isArray(entries) || entries.length === 0) return state
    const next = { ...state.scrapeProgress }
    for (const e of entries) {
      if (!e || !e.key) continue
      const prev = next[e.key]
      next[e.key] = {
        current: Math.max(prev?.current ?? 0, Number(e.current) || 0),
        total: Number(e.total) || prev?.total || 0,
      }
    }
    return { scrapeProgress: next }
  }),

  mergeJobsSnapshot: (incomingJobs, taskId, schedule) => set((state) => {
    // 任务切换即覆盖：快照携带新的 task_id 时清掉上一轮岗位（含墓碑），
    // 看板只保留最近一次任务（定时或手动）的岗位；历史岗位在岗位列表里处理
    let base = state
    if (typeof taskId === "string" && taskId && taskId !== _lastSnapshotTaskId) {
      _lastSnapshotTaskId = taskId
      base = {
        ...state,
        // 轮询先于 SSE 识别到新任务（如定时触发）时同步切换链路标识
        pipelineTaskId: taskId !== state.pipelineTaskId ? taskId : state.pipelineTaskId,
        jobs: {},
        removedJobIds: [],
      }
    }
    if (schedule && (schedule.mass_time || schedule.custom_time)) {
      base = {
        ...base,
        deliverySchedule: {
          mass_time: schedule.mass_time || base.deliverySchedule.mass_time,
          custom_time: schedule.custom_time || base.deliverySchedule.custom_time,
        }
      }
    }
    if (!Array.isArray(incomingJobs)) return base
    // 后端 jobs-snapshot 是权威快照：
    // 看板岗位集合严格同步为 incomingJobs 中的有效记录，
    // 不在快照里的历史僵尸岗位直接丢弃，彻底解决历史残留
    const next: Record<string, PipelineJob> = {}

    for (const j of incomingJobs) {
      if (!j || !j.job_id) continue
      if (base.removedJobIds.includes(j.job_id)) continue

      // 查找已有集合中是否已有相同岗位
      let matchedKey = j.job_id
      let prev = base.jobs[j.job_id]

      if (!prev) {
        for (const k of Object.keys(base.jobs)) {
          if (isSameJobEntity(base.jobs[k], j)) {
            matchedKey = k
            prev = base.jobs[k]
            break
          }
        }
      }

      // 如果已有的是 raw_ 卡，而 incoming 是高级卡（非 raw_），升级 key 为 incoming 的 ID
      let finalKey = j.job_id
      if (matchedKey && matchedKey !== j.job_id) {
        if (matchedKey.startsWith("raw_") && !j.job_id.startsWith("raw_")) {
          delete next[matchedKey]
          finalKey = j.job_id
        } else if (!matchedKey.startsWith("raw_") && j.job_id.startsWith("raw_")) {
          finalKey = matchedKey
        }
      }

      const isSnapshotTerminal = SNAPSHOT_TERMINAL_STATUSES.has(j.status)
      const isFailedTerminal = FAILED_TERMINAL_STATUSES.has(j.status)
      // 仅在快照非终态且本地处于投递中 (delivering)，或后端明确在 running 时，本地乐观 running 才能作为防倒流守卫；
      // 初评/改写等非投递状态不得阻断后端权威快照
      const isDeliveringRunning = prev?.status === "running" && (prev?.sub_status === "delivering" || prev?.node === "delivery_node")
      const isOptimisticRunning = !isSnapshotTerminal && (isDeliveringRunning || (j.status === "running" && !SNAPSHOT_TERMINAL_STATUSES.has(prev?.status || "")))

      next[finalKey] = {
        ...prev,
        ...j,
        job_id: finalKey,
        job_name: j.job_name || prev?.job_name || "未知岗位",
        company_name: j.company_name || prev?.company_name || "",
        company_scale: j.company_scale || (j as any).company_size || (j as any).scale || prev?.company_scale || "",
        job_url: j.job_url || prev?.job_url || "",
        platform: j.platform || prev?.platform || "",
        salary: j.salary || prev?.salary || "",
        city: j.city || prev?.city || "",
        education: j.education || prev?.education || "",
        experience: j.experience || prev?.experience || "",
        jd_text: j.jd_text || prev?.jd_text || "",
        grade: prev?.grade || j.grade,
        score: typeof j.score === 'number' && !isNaN(j.score)
          ? j.score
          : (typeof prev?.score === 'number' && !isNaN(prev.score) ? prev.score : undefined),
        status: isSnapshotTerminal
          ? j.status
          : (isOptimisticRunning ? "running" : (j.status || prev?.status)),
        node: isSnapshotTerminal
          ? j.node
          : (isOptimisticRunning
              ? ((j.node && j.node !== "ready_to_deliver" && j.node !== "error" && j.node !== "clean_rejected" && j.node !== "manual_review_node")
                  ? j.node
                  : ((prev?.node && prev.node !== "ready_to_deliver" && prev.node !== "error") ? prev.node : "delivery_node"))
              : (j.node || prev?.node)),
        sub_status: isSnapshotTerminal
          ? j.sub_status
          : (isOptimisticRunning ? (prev?.sub_status || j.sub_status || "delivering") : (j.sub_status || prev?.sub_status)),
        review_type: prev?.review_type || j.review_type,
        reject_reason: prev?.reject_reason || j.reject_reason,
        reject_type: prev?.reject_type || j.reject_type,
        delivery_materials: prev?.delivery_materials || j.delivery_materials,
        failure_info: isSnapshotTerminal
          ? (isFailedTerminal ? (j.failure_info !== undefined ? j.failure_info : prev?.failure_info) : undefined)
          : (isOptimisticRunning ? undefined : (j.failure_info !== undefined ? j.failure_info : prev?.failure_info)),
        is_current_run: j.is_current_run !== undefined ? j.is_current_run : (prev?.is_current_run ?? true),
        created_at: j.created_at || prev?.created_at,
        is_today: j.is_today !== undefined ? j.is_today : prev?.is_today,
        last_action_desc: isSnapshotTerminal
          ? (j.last_action_desc || prev?.last_action_desc)
          : (isOptimisticRunning ? (prev?.last_action_desc || "正在自动投递中…") : (j.last_action_desc || prev?.last_action_desc)),
      }
    }

    // 全量最终去重保证：确保同一个 (公司+岗位名 / URL) 绝无两张卡片
    const keys = Object.keys(next)
    for (let i = 0; i < keys.length; i++) {
      const k1 = keys[i]
      if (!next[k1]) continue
      for (let m = i + 1; m < keys.length; m++) {
        const k2 = keys[m]
        if (!next[k2]) continue
        if (isSameJobEntity(next[k1], next[k2])) {
          if (k1.startsWith("raw_") && !k2.startsWith("raw_")) {
            delete next[k1]
            break
          } else {
            delete next[k2]
          }
        }
      }
    }

    return { ...base, jobs: next }
  }),

  handleEvent: (data) => set((state) => {
    if (!data || typeof data !== "object") return state
    const type = data.type

    switch (type) {
      case "stage": {
        const stageKey = data.stage as string
        const status = data.status as StageStatus
        const nextStageStatus = { ...state.stageStatus, [stageKey]: status }
        const refined = status === "running"
          ? advanceStages(nextStageStatus, stageKey)
          : nextStageStatus

        return {
          currentStage: stageKey,
          stageStatus: refined,
          status: stageKey === "done" && status === "done" ? "done" : state.status,
        }
      }

      case "scrape_progress": {
        const p = data.platform as string
        if (!p) return state
        const prev = state.scrapeProgress[p]
        const incomingCur = Number(data.current) || 0
        const incomingTot = Number(data.total) || 0
        return {
          scrapeProgress: {
            ...state.scrapeProgress,
            [p]: {
              current: Math.max(prev?.current ?? 0, incomingCur),
              total: Math.max(prev?.total ?? 0, incomingTot),
            },
          },
        }
      }

      case "phase_progress": {
        const phase = data.phase as string
        const prog: PlatformProgress = {
          current: Number(data.current) || 0,
          total: Number(data.total) || 0,
        }
        if (phase === "hard_clean") return { hardCleanProgress: prog }
        if (phase === "ai_scout") return { aiScoutProgress: prog }
        if (phase === "feishu_sync") return { feishuSyncProgress: prog }
        return state
      }

      case "job": {
        const jid = data.job_id as string
        if (!jid) return state

        const jobsNext = { ...state.jobs }
        let matchedKey: string | null = null
        let prevJob: PipelineJob | undefined = undefined

        if (jobsNext[jid]) {
          matchedKey = jid
          prevJob = jobsNext[jid]
        } else {
          for (const k of Object.keys(jobsNext)) {
            if (isSameJobEntity(jobsNext[k], { job_id: jid, job_url: data.job_url, company_name: data.company_name, job_name: data.job_name })) {
              matchedKey = k
              prevJob = jobsNext[k]
              break
            }
          }
        }

        const prev: PipelineJob = prevJob || {
          job_id: jid,
          job_name: data.job_name || "未知岗位",
          node: data.node || "unknown",
          status: data.status || "running",
        }

        const nextJob: PipelineJob = {
          ...prev,
          job_id: jid, // 升级为最新 ID
          // 描述性字段用 falsey 合并：事件缺省/空串时保留已知信息
          job_name: data.job_name || prev.job_name,
          platform: data.platform || prev.platform,
          company_name: data.company_name || prev.company_name,
          company_scale: data.company_scale || (data as any).company_size || (data as any).scale || prev.company_scale,
          salary: data.salary || prev.salary,
          city: data.city || prev.city,
          education: data.education || prev.education,
          experience: data.experience || prev.experience,
          job_url: data.job_url || prev.job_url,
          jd_text: data.jd_text || prev.jd_text,
          // 状态类字段用 !== undefined 合并：后端必须能通过事件清空/改写这些字段，
          // 否则放行后 node 残留 manual_review_node、重试后 failure_info 残留等状态卡死
          node: data.node !== undefined ? data.node : prev.node,
          status: data.status !== undefined ? data.status : prev.status,
          sub_status: data.sub_status !== undefined ? data.sub_status : prev.sub_status,
          grade: data.grade !== undefined ? data.grade : prev.grade,
          score: typeof data.score === 'number' && !isNaN(data.score) ? data.score : prev.score,
          reject_reason: data.reject_reason !== undefined ? data.reject_reason : prev.reject_reason,
          reject_type: data.reject_type !== undefined ? data.reject_type : prev.reject_type,
          review_type: data.review_type !== undefined ? data.review_type : prev.review_type,
          delivery_materials: data.delivery_materials !== undefined ? data.delivery_materials : prev.delivery_materials,
          failure_info: data.failure_info !== undefined ? data.failure_info : prev.failure_info,
        }

        // 如果旧卡片 key 与新 jid 不同（例如旧 key 是 raw_1，新 jid 是 rec_xxx），删除旧 key
        if (matchedKey && matchedKey !== jid) {
          delete jobsNext[matchedKey]
        }

        // 如果明确传了 raw_job_id，直接清理对应的 raw_ 卡
        if (data.raw_job_id && jobsNext[data.raw_job_id] && data.raw_job_id !== jid) {
          delete jobsNext[data.raw_job_id]
        }

        // 清理任何其他同名同公司或同 URL 的 raw_ 旧卡片
        for (const oid of Object.keys(jobsNext)) {
          if (oid !== jid && isSameJobEntity(jobsNext[oid], nextJob)) {
            delete jobsNext[oid]
          }
        }

        return {
          jobs: {
            ...jobsNext,
            [jid]: nextJob,
          },
        }
      }

      case "log":
      case "warning": {
        // 后端 emit_log 在 level=error 时 type=warning，统一并入日志流，错误日志不再丢失
        const msg = data.message as string
        if (!msg) return state
        return {
          logs: [...state.logs.slice(-199), msg],
        }
      }

      case "error": {
        // SSE 总线的错误终态事件：链路异常中断，状态机不能停在 running
        const msg = (data.message as string) || "链路发生未知错误"
        return {
          status: "error",
          logs: [...state.logs.slice(-199), `❌ ${msg}`],
        }
      }

      case "end": {
        // 兼容两种事件形态：错误在顶层 data.error，或嵌在 emit_end 的 summary.error 里
        const err = data.error ?? data.summary?.error
        return {
          status: err ? "error" : "done",
          summary: data,
        }
      }

      default:
        return state
    }
  }),
}))
