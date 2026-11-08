import { create } from 'zustand'
import {
  actionDescForNode,
  isWithinTaskSwitchGuard,
  markPipelineStart,
  markSnapshotTask,
  advanceStages,
  classifyEndFrame,
  FAILED_TERMINAL_STATUSES,
  emptyState,
  isSameJobEntity,
  mergeProgress,
  STAGE_RANK,
  nodeProgressRank,
  type PipelineJob,
  type PipelineStore,
  type PipelineStatus,
  type BlockedDetail,
  type PlatformFailure,
  type StageStatus,
  currentSnapshotTaskId,
  SNAPSHOT_TERMINAL_STATUSES,
} from "./pipeline-store-helpers"

// 类型与词表 re-export：既有消费方统一从 @/store/pipeline-store 导入（拆分零消费方改动）
export type {
  BlockedDetail,
  PlatformFailure,
  PipelineJob,
  PipelineStageSnapshot,
  PipelineStatus,
  PlatformProgress,
  StageStatus,
} from "./pipeline-store-helpers"
export { FAILED_TERMINAL_STATUSES, PIPELINE_STAGES } from "./pipeline-store-helpers"
export { classifyEndFrame, type EndFrameKind } from "./pipeline-store-helpers"

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

export const usePipelineStore = create<PipelineStore>((set) => ({
  ...emptyState(),

  startPipeline: (taskId) => {
    markSnapshotTask(taskId)
    markPipelineStart()
    set((state) => ({
      ...emptyState(),
      // 配置类值不随新任务复位：否则刷新后阈值短暂回到 A，深评/改写分母会闪一下
      autoEvalThreshold: state.autoEvalThreshold,
      pipelineTaskId: taskId,
      status: "running",
    }))
  },

  reset: () => set({ ...emptyState() }),

  dismissPlatformFailure: (id) => set((state) => ({
    platformFailures: state.platformFailures.filter((f) => f.id !== id),
  })),

  setBlocked: (detail) => set({ status: "blocked", blockedDetail: detail }),

  clearBlocked: () => set({ blockedDetail: null }),

  resumePipeline: () => set((state) => ({
    // 只切状态不清现场：看板卡片/日志/blockedDetail 保留，横幅转「恢复中」进行时态
    status: "running",
    summary: state.status === "blocked" ? null : state.summary,
  })),

  setAutoEvalThreshold: (threshold) => set({
    autoEvalThreshold: (threshold || "A").toUpperCase(),
  }),

  seedStageSnapshot: (snapshot) => set((state) => {
    if (!snapshot) return state
    const incomingTask = snapshot.task_id ?? null
    const hasStageData = Object.keys(snapshot.stage_status || {}).length > 0 || Boolean(snapshot.phases)
    if (!incomingTask && !hasStageData) return state

    // 🌟 阻塞解除通道（2026-11-03 事故根治，必须先于「只种一次」守卫）：
    // SSE 在 blocked 态被设计为强制断开，轮询是断链后唯一存活通道——后端登记已清
    // （LLM 自愈 / 继续任务重洗成功 / 终止任务）时，横幅必须能被轮询摘下，
    // 否则 blockedDetail 永无清除入口，横幅永久卡死在「链路已暂停」。
    if (!snapshot.blocked?.blocked && state.blockedDetail &&
        state.status !== "done" && state.status !== "error") {
      return {
        status: state.status === "blocked" ? ("running" as PipelineStatus) : state.status,
        blockedDetail: null,
      }
    }

    // 同一任务只种一次：dashboard-sync 每 12 秒轮询，旧响应不得覆盖 SSE 已推进的新阶段
    if (incomingTask && incomingTask === state.stageSnapshotTaskId) return state

    const nextStageStatus = { ...state.stageStatus }
    for (const [key, value] of Object.entries(snapshot.stage_status || {})) {
      if (value !== "pending" && value !== "running" && value !== "done" && value !== "blocked") continue
      // 旧任务的 blocked 阶段态不得污染新一轮运行任务的导轨
      if (value === "blocked" && incomingTask && state.pipelineTaskId && incomingTask !== state.pipelineTaskId) continue
      const current = nextStageStatus[key] || "pending"
      // 单调守卫：done 阶段不被旧快照倒回 running/pending/blocked
      if (STAGE_RANK[value] >= STAGE_RANK[current]) {
        nextStageStatus[key] = value
      }
    }

    // 任务级 LLM 阻塞态（刷新恢复的第二通道）：仅同任务且链路未收口时生效，
    // 防止旧任务的阻塞快照污染新一轮运行或已完成的界面。
    const blockedPayload = snapshot.blocked
    let blockedPatch: { status?: PipelineStatus; blockedDetail?: BlockedDetail | null } = {}
    if (blockedPayload?.blocked) {
      const sameTask = !state.pipelineTaskId || !incomingTask || incomingTask === state.pipelineTaskId
      const notSettled = state.status !== "done" && state.status !== "error"
      if (sameTask && notSettled) {
        blockedPatch = { status: "blocked", blockedDetail: blockedPayload }
      }
    }

    const phases = snapshot.phases || {}
    const snapCurrent = snapshot.current_stage
    const snapCurrentStatus = snapCurrent ? nextStageStatus[snapCurrent] : undefined
    return {
      stageStatus: nextStageStatus,
      // 只把快照中仍在 running 的阶段设为当前阶段；null 不覆盖本地新状态
      currentStage: snapCurrent && snapCurrentStatus === "running" ? snapCurrent : state.currentStage,
      hardCleanProgress: mergeProgress(state.hardCleanProgress, phases.hard_clean),
      aiScoutProgress: mergeProgress(state.aiScoutProgress, phases.ai_scout),
      feishuSyncProgress: mergeProgress(state.feishuSyncProgress, phases.feishu_sync),
      stageSnapshotTaskId: incomingTask ?? state.stageSnapshotTaskId,
      ...blockedPatch,
    }
  }),

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
        // 轮询快照不携带 skipped：保留既有累计值，防被覆盖归零
        skipped: prev?.skipped ?? 0,
      }
    }
    return { scrapeProgress: next }
  }),

  mergeJobsSnapshot: (incomingJobs, taskId, schedule) => set((state) => {
    // 任务切换即覆盖：快照携带新的 task_id 时清掉上一轮岗位（含墓碑），
    // 看板只保留最近一次任务（定时或手动）的岗位；历史岗位在岗位列表里处理
    let base = state
    if (typeof taskId === "string" && taskId && taskId !== currentSnapshotTaskId()) {
      // 双保险守卫（2026-11-02 审计 P1-8）：running 且处于 startPipeline 短窗内时，
      // 与本地链路不一致的载荷判定为「旧任务的在途响应」——其岗位/任务标识全部
      // 陈旧，整体跳过（不清板、不劫持 pipelineTaskId、不并入旧岗位）；窗口过期
      // 后恢复接管分支。单靠请求序号挡不住「请求先发出→期间启动新任务→旧响应后到」。
      if (state.status === "running" && state.pipelineTaskId &&
          taskId !== state.pipelineTaskId &&
          isWithinTaskSwitchGuard()) {
        return state
      }
      markSnapshotTask(taskId)
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
      // 防降级守卫：本地已在更靠后的节点运行，快照却给出更早节点（且非终态）——
      // 典型是 rewrite/greeting 期间 Feishu 仍写「已完成初步评估」，快照映射成
      // done/evaluate_node。12 秒轮询绝不能把卡片打回「AI初评完成」。
      const isSnapshotDowngrade = Boolean(
        prev?.status === "running" &&
        !isSnapshotTerminal &&
        nodeProgressRank(prev?.node) > nodeProgressRank(j.node) &&
        (j.status === "done" || j.status === "running")
      )
      const keepLocalProgress = isSnapshotDowngrade

      // 快照运行态文案：优先后端下发的 last_action_desc，缺省时按节点生成。
      // 本地乐观文案只在「投递在途」或「防降级」时优先；否则淘汰旧文案
      // （如「触发AI排雷规则淘汰」）会一直挂在已复活的岗位卡片上（2026-10-30 实测）。
      const snapshotActionDesc = j.last_action_desc || actionDescForNode(j.node, j.sub_status)
      const preferLocalDesc = keepLocalProgress || isDeliveringRunning

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
          : (keepLocalProgress ? "running" : (isOptimisticRunning ? "running" : (j.status || prev?.status))),
        node: isSnapshotTerminal
          ? j.node
          : (keepLocalProgress
              ? prev?.node
              : (isOptimisticRunning
                  ? ((j.node && j.node !== "ready_to_deliver" && j.node !== "error" && j.node !== "clean_rejected" && j.node !== "manual_review_node")
                      ? j.node
                      : ((prev?.node && prev.node !== "ready_to_deliver" && prev.node !== "error") ? prev.node : "delivery_node"))
                  : (j.node || prev?.node))),
        sub_status: isSnapshotTerminal
          ? j.sub_status
          : (keepLocalProgress
              ? prev?.sub_status
              : (isOptimisticRunning
                  // delivering 兜底仅限投递在途节点：scrape_node/greeting_node 等
                  // 裸 running 注入 delivering 会把评估/打招呼中的岗位误锁成「正在自动投递中」
                  ? (prev?.sub_status || j.sub_status ||
                     (j.node === "delivery_node" ? "delivering" : undefined))
                  : (j.sub_status || prev?.sub_status))),
        review_type: prev?.review_type || j.review_type,
        has_rewrite: j.has_rewrite !== undefined ? j.has_rewrite : prev?.has_rewrite,
        greeting_msg: j.greeting_msg || prev?.greeting_msg,
        reject_reason: prev?.reject_reason || j.reject_reason,
        reject_type: prev?.reject_type || j.reject_type,
        // 后端权威快照字段按 !==undefined 合并（审计 P2-18，与 has_rewrite 同口径）：
        // 旧写法 prev 真值恒胜出——打招呼送达状态恢复后，卡片「未送达」警示与补发按钮
        // 挂到刷新页面才消失
        delivery_materials: j.delivery_materials !== undefined ? j.delivery_materials : prev?.delivery_materials,
        failure_info: isSnapshotTerminal
          ? (isFailedTerminal ? (j.failure_info !== undefined ? j.failure_info : prev?.failure_info) : undefined)
          : (isOptimisticRunning || keepLocalProgress ? undefined : (j.failure_info !== undefined ? j.failure_info : prev?.failure_info)),
        deep_eval_done: prev?.deep_eval_done || j.deep_eval_done || undefined,
        is_current_run: j.is_current_run !== undefined ? j.is_current_run : (prev?.is_current_run ?? true),
        created_at: j.created_at || prev?.created_at,
        is_today: j.is_today !== undefined ? j.is_today : prev?.is_today,
        last_action_desc: isSnapshotTerminal
          ? (j.last_action_desc || prev?.last_action_desc)
          : (preferLocalDesc
              ? (prev?.last_action_desc || snapshotActionDesc)
              : (snapshotActionDesc || prev?.last_action_desc)),
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

        // LLM 阻塞事件：整体状态切到 blocked 并落地阻塞明细（含模型名/上游提示/修复依据）
        if (status === "blocked") {
          const detail: BlockedDetail = (data.blocked as BlockedDetail | undefined) || state.blockedDetail || {
            kind: "unknown",
            message: "AI 排雷持续失败，遗留岗位已保留在待AI初筛",
          }
          return {
            currentStage: state.currentStage,
            stageStatus: refined,
            status: "blocked" as PipelineStatus,
            blockedDetail: detail,
          }
        }
        // 阻塞恢复中（继续任务把 cleaning 置回 running）：保留 blockedDetail 供横幅转进行中态
        if (status === "running" && stageKey === "cleaning" && state.status === "blocked") {
          return {
            currentStage: stageKey,
            stageStatus: refined,
            status: "running" as PipelineStatus,
          }
        }

        return {
          // 只有 running 事件才能成为「当前阶段」：done 事件若也写 currentStage，
          // 已完成的飞书推送会带着紫色脉冲高亮，看起来像还在运行。
          currentStage: status === "running"
            ? stageKey
            : (stageKey === "done" || state.currentStage === stageKey ? null : state.currentStage),
          stageStatus: refined,
          status: stageKey === "done" && status === "done" ? "done" : state.status,
        }
      }

      case "progress": {
        // 抓取实时进度（2026-11-02 审计 P2-23）：4 平台 controller 只发 progress 事件
        //（{stage:"scraping", platform, total_inserted, target_jobs}），前端此前只听
        // scrape_progress（仅 skipped 字段），实时 N/M 永不生效、只能靠 12s 快照。
        // 映射到同一 scrapeProgress 存储；同时消费 cleaning_report 保持清洗计数实时
        if (data.stage === "scraping" && data.platform) {
          const prevP = state.scrapeProgress[data.platform as string]
          return {
            scrapeProgress: {
              ...state.scrapeProgress,
              [data.platform as string]: {
                ...prevP,
                current: Math.max(prevP?.current ?? 0, Number(data.total_inserted) || 0),
                total: Math.max(prevP?.total ?? 0, Number(data.target_jobs) || 0),
              },
            },
          }
        }
        return state
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
              // 重复跳过实况（跳过类事件只带 skipped；缺省字段经 Math.max 保留既有值）
              skipped: Math.max(prev?.skipped ?? 0, Number(data.skipped) || 0),
            },
          },
        }
      }

      case "phase_progress": {
        const phase = data.phase as string
        const incoming = {
          current: Number(data.current) || 0,
          total: Number(data.total) || 0,
        }
        // SSE 重连会回放 50 条历史：旧 phase 事件不得把进度条倒回更小值
        if (phase === "hard_clean") return { hardCleanProgress: mergeProgress(state.hardCleanProgress, incoming) }
        if (phase === "ai_scout") return { aiScoutProgress: mergeProgress(state.aiScoutProgress, incoming) }
        if (phase === "feishu_sync") return { feishuSyncProgress: mergeProgress(state.feishuSyncProgress, incoming) }
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

        // 抓取期流式清洗：清洗泵可能在 scrape 事件排队前后抢先推进卡片状态。
        // 迟到的 scrape 事件不得把已进入清洗/评估的卡片打回「待清洗」。
        const isScrapeDowngrade =
          data.status === "scraped" &&
          data.node === "scrape_node" &&
          prev.status !== undefined &&
          prev.status !== "scraped"

        // 迟到抓取事件命中已升级的 rec_ 卡：保留卡片与 key，绝不回退成 raw_ 卡
        if (isScrapeDowngrade && matchedKey && matchedKey !== jid) {
          return state
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
          // 运行态事件缺文案时按节点兜底（后端正常都会下发；旧后端/半截事件不能空着）
          last_action_desc: isScrapeDowngrade
            ? prev.last_action_desc
            : (data.last_action_desc
                || (data.status === "running" ? actionDescForNode(data.node, data.sub_status) : prev.last_action_desc)),
          last_action_time: data.last_action_time || prev.last_action_time,
          // 状态类字段用 !== undefined 合并：后端必须能通过事件清空/改写这些字段，
          // 否则放行后 node 残留 manual_review_node、重试后 failure_info 残留等状态卡死
          node: isScrapeDowngrade ? prev.node : (data.node !== undefined ? data.node : prev.node),
          status: isScrapeDowngrade ? prev.status : (data.status !== undefined ? data.status : prev.status),
          sub_status: isScrapeDowngrade ? prev.sub_status : (data.sub_status !== undefined ? data.sub_status : prev.sub_status),
          grade: data.grade !== undefined ? data.grade : prev.grade,
          score: typeof data.score === 'number' && !isNaN(data.score) ? data.score : prev.score,
          reject_reason: data.reject_reason !== undefined ? data.reject_reason : prev.reject_reason,
          reject_type: data.reject_type !== undefined ? data.reject_type : prev.reject_type,
          review_type: data.review_type !== undefined ? data.review_type : prev.review_type,
          has_rewrite: data.has_rewrite !== undefined ? Boolean(data.has_rewrite) : prev.has_rewrite,
          greeting_msg: data.greeting_msg || prev.greeting_msg,
          delivery_materials: data.delivery_materials !== undefined ? data.delivery_materials : prev.delivery_materials,
          failure_info: data.failure_info !== undefined ? data.failure_info : prev.failure_info,
          // 深评完成标记以服务端实时登记表为准（每个 job 事件都会带回该字段）。
          // 兼容旧后端：事件缺省时保留本地值，并识别 deep_eval_node done 事件。
          deep_eval_done: data.deep_eval_done !== undefined
            ? Boolean(data.deep_eval_done)
            : (prev.deep_eval_done || (data.node === "deep_eval_node" && data.status === "done") || undefined),
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

      case "platform_failure": {
        // 平台抓取失败：右下角弹窗数据源。用户手动关闭前常驻，绝不自动消失；
        // 同一轮多平台失败各自成卡（boss/51job/智联/猎聘/小红书通用协议）。
        const platform = (data.platform as string) || "unknown"
        const ts = Number(data.ts) || Date.now()
        // 去重：TaskChannel 断线重连会回放历史（同载荷二次投递），按 ts 精确去重——
        // 重放件静默吞掉；新一轮失败的全新 ts 正常弹出（不同轮次的相同原因不受影响）
        if (ts && state.platformFailures.some((f) => f.ts === ts && f.platform === platform)) {
          return state
        }
        const failure: PlatformFailure = {
          id: `${platform}_${ts}_${Math.random().toString(36).slice(2, 7)}`,
          platform,
          platform_name: (data.platform_name as string) || platform,
          reason: (data.reason as string) || "本轮抓取未成功（引擎未上报具体原因）",
          keyword: data.keyword as string | undefined,
          city: data.city as string | undefined,
          salary: data.salary as string | undefined,
          cursor_note: data.cursor_note as string | undefined,
          ts,
          time: new Date(ts).toLocaleTimeString("zh-CN", { hour12: false }),
        }
        return {
          // 上限 20 张：防异常风暴下用户长期不关闭导致无限增长；超出淘汰最早的卡
          platformFailures: [...state.platformFailures.slice(-19), failure],
          logs: [...state.logs.slice(-199), `🚨 [${failure.platform_name}] 抓取任务失败: ${failure.reason}`],
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
        // 分诊唯一实现在 classifyEndFrame（store 与 SSE toast 共用）
        const verdict = classifyEndFrame(data)
        if (verdict.kind === "blocked") {
          return {
            status: "blocked" as PipelineStatus,
            summary: data,
            blockedDetail: (data.summary?.blocked as BlockedDetail | undefined) || state.blockedDetail,
          }
        }
        if (verdict.kind === "aborted") {
          // 用户主动终止：中性就绪态（非「任务完成」也非异常），日志留终止说明
          return {
            status: "idle",
            summary: data,
            blockedDetail: null,
            logs: [...state.logs.slice(-199), `⏹️ ${verdict.message}`],
          }
        }
        if (verdict.kind === "expired" || verdict.kind === "no_resume") {
          return {
            status: "error",
            summary: data,
            blockedDetail: null,
            logs: [...state.logs.slice(-199), `❌ ${verdict.message}`],
          }
        }
        return {
          status: verdict.kind === "error" ? "error" : "done",
          summary: data,
          // 正常/异常收口都解除阻塞登记：横幅与「继续任务」入口随之撤下
          blockedDetail: null,
        }
      }

      default:
        return state
    }
  }),
}))
