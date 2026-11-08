import { describe, it, expect, beforeEach } from 'vitest'
import { usePipelineStore, PipelineJob } from './pipeline-store'
import { isJobDelivering, isJobFailed, isJobEvaluating, isJobRejected, isJobWaitingReview } from '@/components/command-center/job-predicates'

describe('PipelineStore - mergeJobsSnapshot 状态穿透与防乒乓测试', () => {
  beforeEach(() => {
    usePipelineStore.getState().reset()
  })

  it('01. 投递失败权威终态能够穿透本地 running 状态，且完整保留 failure_info（消除假死在评估中 Bug）', () => {
    const store = usePipelineStore.getState()
    
    // 模拟本地正在流水线流转中（初评/改写/投递中），通过 SSE job 事件入库
    store.handleEvent({
      type: 'job',
      job_id: 'recv_51job_1',
      job_name: '企业架构研究岗',
      company_name: '深圳市南电云商',
      platform: '51job',
      status: 'running',
      node: 'delivery_node',
      sub_status: 'delivering',
      grade: 'C',
      score: 68,
    })

    // 此时岗位由于 status=running，应处于 evaluating
    const currentJob = usePipelineStore.getState().jobs['recv_51job_1']
    expect(currentJob).toBeDefined()
    expect(currentJob.status).toBe('running')
    expect(isJobEvaluating(currentJob)).toBe(true)
    expect(isJobFailed(currentJob)).toBe(false)

    // 模拟后端快照轮询下发真实投递失败台账数据
    const incomingSnapshot: PipelineJob[] = [
      {
        job_id: 'recv_51job_1',
        job_name: '企业架构研究岗',
        company_name: '深圳市南电云商',
        platform: '51job',
        status: 'error',
        node: 'error',
        grade: 'C',
        score: 68,
        failure_info: {
          step: '自动投递阶段',
          reason: '❌ 51job 投递引擎执行失败，请检查相关日志',
          suggestion: '建议检查对应平台登录态后重试。',
          can_retry: true,
        },
        last_action_desc: '尝试自动投递受阻',
      }
    ]

    usePipelineStore.getState().mergeJobsSnapshot(incomingSnapshot)

    const updatedJob = usePipelineStore.getState().jobs['recv_51job_1']
    // 核心断言：必须成功穿透为 error，绝不能被锁定在 running
    expect(updatedJob.status).toBe('error')
    expect(updatedJob.node).toBe('error')
    expect(updatedJob.failure_info).toBeDefined()
    expect(updatedJob.failure_info?.reason).toContain('51job 投递引擎执行失败')

    // 判定断言：必须正确进入【执行失败】，绝不能继续停留在【评估/改写/投递中】
    expect(isJobFailed(updatedJob)).toBe(true)
    expect(isJobEvaluating(updatedJob)).toBe(false)
  })

  it('02. 投递成功 (delivered) 终态能够穿透本地 running 状态，并清空 failure_info', () => {
    const store = usePipelineStore.getState()
    
    // 本地之前是 running
    store.handleEvent({
      type: 'job',
      job_id: 'recv_boss_1',
      job_name: 'AI产品经理',
      status: 'running',
      node: 'delivery_node',
      sub_status: 'delivering',
    })

    const incomingSnapshot: PipelineJob[] = [
      {
        job_id: 'recv_boss_1',
        job_name: 'AI产品经理',
        status: 'delivered',
        node: 'delivery_node',
        delivery_materials: { pdf: true, greeting: true },
      }
    ]

    usePipelineStore.getState().mergeJobsSnapshot(incomingSnapshot)

    const updatedJob = usePipelineStore.getState().jobs['recv_boss_1']
    expect(updatedJob.status).toBe('delivered')
    expect(updatedJob.failure_info).toBeUndefined()
    expect(isJobFailed(updatedJob)).toBe(false)
    expect(isJobEvaluating(updatedJob)).toBe(false)
  })

  it('03. 用户点击重试或立即投递后，快照若仍为旧的非终态（ready_to_deliver），本地乐观 running 保持防倒流', () => {
    const store = usePipelineStore.getState()
    
    // 岗位原本在快照里是 ready_to_deliver
    store.mergeJobsSnapshot([
      {
        job_id: 'recv_zhilian_1',
        job_name: '解决方案专家',
        status: 'ready_to_deliver',
        node: 'ready_to_deliver',
      }
    ])

    // 用户刚刚点击了立即投递，本地乐观更新写入 running
    store.updateJob('recv_zhilian_1', {
      status: 'running',
      node: 'delivery_node',
      sub_status: 'delivering',
    })

    expect(usePipelineStore.getState().jobs['recv_zhilian_1'].status).toBe('running')

    // 后端快照在短时间内轮询，飞书状态由于尚未完成投递仍返回旧的 ready_to_deliver
    const incomingSnapshot: PipelineJob[] = [
      {
        job_id: 'recv_zhilian_1',
        job_name: '解决方案专家',
        status: 'ready_to_deliver',
        node: 'ready_to_deliver',
      }
    ]

    usePipelineStore.getState().mergeJobsSnapshot(incomingSnapshot)

    const updatedJob = usePipelineStore.getState().jobs['recv_zhilian_1']
    // 核心断言：快照非终态时，本地乐观 running 作为守卫防倒流
    expect(updatedJob.status).toBe('running')
    expect(updatedJob.node).toBe('delivery_node')
  })

  it('04. 重试中再次失败时，最新的 error 与 failure_info 能够再次穿透并更新', () => {
    const store = usePipelineStore.getState()
    
    // 处于重试中的 running 态
    store.handleEvent({
      type: 'job',
      job_id: 'recv_retry_1',
      job_name: '需求售前工程师',
      status: 'running',
      node: 'delivery_node',
      sub_status: 'delivering',
    })

    // 重试彻底结束并再次失败
    const incomingSnapshot: PipelineJob[] = [
      {
        job_id: 'recv_retry_1',
        job_name: '需求售前工程师',
        status: 'error',
        node: 'error',
        failure_info: {
          step: '自动投递阶段',
          reason: '附件简历上传失败',
          can_retry: true,
        },
      }
    ]

    usePipelineStore.getState().mergeJobsSnapshot(incomingSnapshot)

    const updatedJob = usePipelineStore.getState().jobs['recv_retry_1']
    expect(updatedJob.status).toBe('error')
    expect(updatedJob.failure_info?.reason).toBe('附件简历上传失败')
    expect(isJobFailed(updatedJob)).toBe(true)
  })

  it('05. 连续多次快照轮询下，失败岗位状态持续锁定在 error，评级与分数完整保留不被冲刷', () => {
    const store = usePipelineStore.getState()

    // 初始通过快照进入 error
    store.mergeJobsSnapshot([
      {
        job_id: 'recv_test_5',
        job_name: '解决方案分析师（广州）',
        company_name: '国泰航空有限公司上海代表处',
        platform: '51job',
        grade: 'D',
        score: 52,
        status: 'error',
        node: 'error',
        failure_info: {
          step: '自动投递阶段',
          reason: '投递异常中断: Locator.click: Timeout 30000ms exceeded',
          can_retry: true,
        },
      }
    ])

    // 第 2 次、第 3 次轮询重复下发
    for (let round = 1; round <= 3; round++) {
      store.mergeJobsSnapshot([
        {
          job_id: 'recv_test_5',
          job_name: '解决方案分析师（广州）',
          company_name: '国泰航空有限公司上海代表处',
          platform: '51job',
          grade: 'D',
          score: 52,
          status: 'error',
          node: 'error',
          failure_info: {
            step: '自动投递阶段',
            reason: '投递异常中断: Locator.click: Timeout 30000ms exceeded',
            can_retry: true,
          },
        }
      ])

      const job = usePipelineStore.getState().jobs['recv_test_5']
      expect(job).toBeDefined()
      expect(job.status).toBe('error')
      expect(job.grade).toBe('D')
      expect(job.score).toBe(52)
      expect(isJobFailed(job)).toBe(true)
      expect(isJobEvaluating(job)).toBe(false)
    }
  })

  it('06. 初评中处于 running 状态的岗位，快照下发 waiting 权威状态时必须成功穿透，绝不被误锁在评估中（回归守卫）', () => {
    const store = usePipelineStore.getState()

    // 模拟全链路初评流转中收到 SSE running 事件
    store.handleEvent({
      type: 'job',
      job_id: 'recvvlcWHtVLxW',
      job_name: '产品经理',
      company_name: '上海仁联企业服务(集团)有限公司',
      platform: 'zhilian',
      status: 'running',
      node: 'evaluate_node',
      sub_status: 'ai_eval',
      grade: 'C',
      score: 71,
    })

    const initialJob = usePipelineStore.getState().jobs['recvvlcWHtVLxW']
    expect(initialJob).toBeDefined()
    expect(initialJob.status).toBe('running')
    expect(isJobEvaluating(initialJob)).toBe(true)
    expect(isJobWaitingReview(initialJob)).toBe(false)

    // 后端工作流进入 manual_review_node 断点，快照轮询下发 waiting
    store.mergeJobsSnapshot([
      {
        job_id: 'recvvlcWHtVLxW',
        job_name: '产品经理',
        company_name: '上海仁联企业服务(集团)有限公司',
        platform: 'zhilian',
        grade: 'C',
        status: 'waiting',
        node: 'manual_review_node',
        review_type: 'mass_apply',
      }
    ])

    const updatedJob = usePipelineStore.getState().jobs['recvvlcWHtVLxW']
    // 核心断言：必须穿透为 waiting 与 manual_review_node，且保留初评 71 分
    expect(updatedJob.status).toBe('waiting')
    expect(updatedJob.node).toBe('manual_review_node')
    expect(updatedJob.score).toBe(71)
    expect(updatedJob.grade).toBe('C')

    // 状态判定：必须正确进入【待审批】，离开【评估/改写/投递中】
    expect(isJobWaitingReview(updatedJob)).toBe(true)
    expect(isJobEvaluating(updatedJob)).toBe(false)
  })

  it('07. 召回待初评岗位（淘汰卡 prev + 裸 running/scrape_node 快照）两跳轮询均不得被注入 delivering（防误锁「正在自动投递中」）', () => {
    const store = usePipelineStore.getState()

    // 首跳前的看板存量：岗位今日被 AI 排雷淘汰
    store.mergeJobsSnapshot([
      {
        job_id: 'raw_3113',
        job_name: 'AI大客户经理（AI产品高校方向）',
        company_name: '广州无意识设计有限公司',
        platform: 'boss',
        status: 'rejected',
        node: 'clean_rejected',
        last_action_desc: '触发AI排雷规则淘汰',
      }
    ])

    // 用户从飞书战报召回 → 后端快照下发裸 running（无 sub_status）
    const recallSnapshot: PipelineJob[] = [
      {
        job_id: 'raw_3113',
        job_name: 'AI大客户经理（AI产品高校方向）',
        company_name: '广州无意识设计有限公司',
        platform: 'boss',
        status: 'running',
        node: 'scrape_node',
        last_action_desc: '入库待清洗',
      } as PipelineJob
    ]

    // 首跳轮询
    store.mergeJobsSnapshot(recallSnapshot)
    const firstHop = usePipelineStore.getState().jobs['raw_3113']
    expect(firstHop.status).toBe('running')
    expect(firstHop.sub_status).not.toBe('delivering')

    // 次跳轮询（12s 后，prev 已是 running 非终态）
    store.mergeJobsSnapshot(recallSnapshot)
    const secondHop = usePipelineStore.getState().jobs['raw_3113']
    expect(secondHop.status).toBe('running')
    expect(secondHop.node).toBe('scrape_node')
    // 核心断言：两跳均不得出现 delivering（否则卡片误锁「正在自动投递中」并出现「终止投递」按钮）
    expect(secondHop.sub_status).not.toBe('delivering')
  })

  it('08. 正向对照：真实投递在途卡片（delivery_node 裸 running 快照）两跳后仍保持 delivering 乐观锁定', () => {
    const store = usePipelineStore.getState()

    const deliveringSnapshot: PipelineJob[] = [
      {
        job_id: 'rec_delivery_1',
        job_name: '解决方案专家',
        platform: 'zhilian',
        status: 'running',
        node: 'delivery_node',
      } as PipelineJob
    ]

    store.mergeJobsSnapshot(deliveringSnapshot)
    store.mergeJobsSnapshot(deliveringSnapshot)

    const job = usePipelineStore.getState().jobs['rec_delivery_1']
    expect(job.status).toBe('running')
    // 核心断言：投递在途节点的 delivering 注入不被收紧误伤
    expect(job.sub_status).toBe('delivering')
  })

  it('09. 首次快照即为 running（无本地 prev）时，卡片文案必须按节点生成，不得注入「正在自动投递中…」', () => {
    const store = usePipelineStore.getState()

    // 复现 2026-10-30 21:05 实测：猎聘最后一条岗位入库即进入清洗，
    // 首跳快照 status=running（待AI初筛），此前没有 scrape 快照建立文案。
    store.mergeJobsSnapshot([
      {
        job_id: 'raw_3234',
        job_name: 'AI产品经理（招商、A2A方向）',
        company_name: '探迹科技',
        platform: 'liepin',
        status: 'running',
        node: 'scrape_node',
        sub_status: 'ai_eval_queued',
        last_action_desc: '清洗排雷处理中',
      } as PipelineJob,
    ])

    const job = usePipelineStore.getState().jobs['raw_3234']
    expect(job.status).toBe('running')
    expect(job.last_action_desc).toBe('清洗排雷处理中')
    expect(job.last_action_desc).not.toContain('自动投递')
    // 清洗中的岗位不得出现投递在途判定（否则卡片会渲染「终止投递」按钮）
    expect(isJobDelivering(job)).toBe(false)
  })

  it('10. 首跳快照缺 last_action_desc 时，按节点生成文案（evaluate_node ≠ 自动投递）', () => {
    const store = usePipelineStore.getState()

    store.mergeJobsSnapshot([
      {
        job_id: 'rec_eval_1',
        job_name: '数据产品经理',
        company_name: '探迹科技',
        platform: 'liepin',
        status: 'running',
        node: 'evaluate_node',
        sub_status: 'ai_eval',
      } as PipelineJob,
    ])

    const job = usePipelineStore.getState().jobs['rec_eval_1']
    expect(job.last_action_desc).toBe('AI初评进行中')
    expect(isJobDelivering(job)).toBe(false)
  })

  it('11. 淘汰放行岗位（乐观 running + 快照 running）必须刷新为初评文案，不得残留「触发AI排雷规则淘汰」', () => {
    const store = usePipelineStore.getState()

    // 1) 快照下发淘汰卡（last_action_desc 为 AI 排雷文案）
    store.mergeJobsSnapshot([
      {
        job_id: 'raw_3231',
        job_name: '产品专员（AI方向）',
        company_name: '多益网络有限公司',
        platform: 'zhilian',
        status: 'rejected',
        node: 'clean_rejected',
        reject_type: 'ai',
        last_action_desc: '触发AI排雷规则淘汰',
      } as PipelineJob,
    ])

    // 2) 用户在淘汰 Tab 点「放行」：乐观更新为 running。
    //    载荷必须与 rejected-job-card.handleUnreject 逐字段一致（改那里时同步改这里）
    store.updateJob('raw_3231', {
      status: 'running',
      node: 'evaluate_node',
      sub_status: 'ai_eval_queued',
      reject_reason: undefined,
      reject_type: undefined,
      failure_info: undefined,
      last_action_time: '2026-10-30 21:15:14',
      last_action_desc: '♻️ 已放行，等待AI重新初评',
    })

    // 3) 下一跳快照：后端已推送飞书并开始复评，卡片升级为 rec_ id
    store.mergeJobsSnapshot([
      {
        job_id: 'reczz28TdQEei20y',
        raw_job_id: 'raw_3231',
        job_name: '产品专员（AI方向）',
        company_name: '多益网络有限公司',
        platform: 'zhilian',
        status: 'running',
        node: 'evaluate_node',
        sub_status: 'ai_eval',
        last_action_desc: 'AI初评进行中',
      } as PipelineJob,
    ])

    const job = usePipelineStore.getState().jobs['reczz28TdQEei20y']
    expect(job).toBeDefined()
    expect(job.status).toBe('running')
    expect(job.last_action_desc).toBe('AI初评进行中')
    expect(job.last_action_desc).not.toContain('排雷')
    expect(isJobEvaluating(job)).toBe(true)
    // 卡片升级后 raw_ 旧卡必须被清掉，杜绝双卡并存/去重抖动
    expect(usePipelineStore.getState().jobs['raw_3231']).toBeUndefined()
  })

  it('12. 快照缺 last_action_desc 时，各运行节点的兜底文案必须与后端 NODE_ACTION_DESC 同值', () => {
    // 表驱动锁定前后端镜像（backend/app/automation/pipeline_broadcast.py NODE_ACTION_DESC）。
    // manual_review_node 后端只以 waiting 终态下发，不会走运行态兜底，故不在此表。
    const cases: Array<{ node: string; sub?: string; desc: string }> = [
      { node: 'clean_rule_node', sub: 'clean_rule_passed', desc: '硬规则通过，排队AI排雷' },
      { node: 'clean_ai_node', sub: undefined, desc: 'AI排雷评估中' },
      { node: 'clean_ai_node', sub: 'clean_ai_passed', desc: 'AI排雷通过，等待推送飞书' },
      { node: 'clean_ai_node', sub: 'clean_ai_preserved', desc: 'AI排雷未完成，保留待重试' },
      { node: 'feishu_sync', sub: undefined, desc: '正在推送飞书多维表格' },
      { node: 'feishu_sync', sub: 'feishu_synced', desc: '已推送飞书，等待评估' },
      { node: 'feishu_sync', sub: 'feishu_synced_existing', desc: '已存在于飞书，跳过重复推送' },
      { node: 'feishu_sync', sub: 'feishu_sync_failed', desc: '飞书推送失败，等待下轮重试' },
      { node: 'evaluate_node', sub: 'ai_eval', desc: 'AI初评进行中' },
      { node: 'evaluate_node', sub: 'ai_eval_queued', desc: 'AI初评排队中' },
      { node: 'deep_eval_node', sub: 'deep_eval', desc: '深度画像评估中' },
      { node: 'rewrite_node', sub: 'rewriting', desc: '定制简历改写中' },
      { node: 'greeting_node', sub: 'greeting', desc: '生成打招呼语中' },
      { node: 'quick_greeting_node', sub: 'greeting', desc: '生成打招呼语中' },
      { node: 'delivery_node', sub: undefined, desc: '正在自动投递中' },
      { node: 'scrape_node', sub: undefined, desc: '流水线运行中' },
    ]

    for (const c of cases) {
      usePipelineStore.getState().reset()
      const jid = `rec_${c.node}_${c.sub || 'x'}`
      usePipelineStore.getState().mergeJobsSnapshot([
        {
          job_id: jid,
          job_name: '兜底文案用例',
          status: 'running',
          node: c.node,
          sub_status: c.sub,
        } as PipelineJob,
      ])
      const job = usePipelineStore.getState().jobs[jid]
      expect(job.last_action_desc, `${c.node}/${c.sub || '-'}`).toBe(c.desc)
    }
  })

  it('13. 投递在途本地文案优先：裸 running/delivery_node 快照不得冲掉「正在自动重试投递中…」', () => {
    const store = usePipelineStore.getState()

    // 本地重试已把卡片置为投递在途（use-board-actions.handleRetryFailedJob 口径）
    store.handleEvent({
      type: 'job',
      job_id: 'rec_retry_1',
      job_name: '解决方案专家',
      status: 'running',
      node: 'delivery_node',
      sub_status: 'delivering',
      last_action_desc: '正在自动重试投递中…',
    })

    // 12 秒快照：飞书侧尚未落终态，只回一条裸 running/delivery_node
    store.mergeJobsSnapshot([
      {
        job_id: 'rec_retry_1',
        job_name: '解决方案专家',
        status: 'running',
        node: 'delivery_node',
      } as PipelineJob,
    ])

    const job = usePipelineStore.getState().jobs['rec_retry_1']
    expect(job.sub_status).toBe('delivering')
    // 核心断言：投递在途时本地文案优先，不被快照的泛化文案冲掉
    expect(job.last_action_desc).toBe('正在自动重试投递中…')
    expect(isJobDelivering(job)).toBe(true)
  })

  it('14. 清洗/飞书推送逐岗位 SSE 事件：卡片随事件实时翻转，不依赖 12 秒快照', () => {
    const store = usePipelineStore.getState()

    // 抓取卡已存在
    store.handleEvent({
      type: 'job',
      job_id: 'raw_3301',
      job_name: 'AIGC产品经理',
      company_name: '广信通信',
      platform: 'zhilian',
      status: 'scraped',
      node: 'scrape_node',
    })

    // Tier 1 通过
    store.handleEvent({
      type: 'job',
      job_id: 'raw_3301',
      node: 'clean_rule_node',
      status: 'running',
      sub_status: 'clean_rule_passed',
    })
    let job = usePipelineStore.getState().jobs['raw_3301']
    expect(job.last_action_desc).toBe('硬规则通过，排队AI排雷')
    expect(isJobEvaluating(job)).toBe(true)
    expect(isJobDelivering(job)).toBe(false)

    // Tier 2 开始
    store.handleEvent({
      type: 'job',
      job_id: 'raw_3301',
      node: 'clean_ai_node',
      status: 'running',
    })
    expect(usePipelineStore.getState().jobs['raw_3301'].last_action_desc).toBe('AI排雷评估中')

    // Tier 2 通过
    store.handleEvent({
      type: 'job',
      job_id: 'raw_3301',
      node: 'clean_ai_node',
      status: 'running',
      sub_status: 'clean_ai_passed',
    })
    expect(usePipelineStore.getState().jobs['raw_3301'].last_action_desc).toBe('AI排雷通过，等待推送飞书')

    // 飞书推送开始
    store.handleEvent({
      type: 'job',
      job_id: 'raw_3301',
      node: 'feishu_sync',
      status: 'running',
    })
    job = usePipelineStore.getState().jobs['raw_3301']
    expect(job.last_action_desc).toBe('正在推送飞书多维表格')
    expect(job.node).toBe('feishu_sync')

    // 飞书推送完成（终态事件显式带文案）
    store.handleEvent({
      type: 'job',
      job_id: 'raw_3301',
      node: 'feishu_sync',
      status: 'done',
      sub_status: 'feishu_synced',
      last_action_desc: '已推送飞书，等待评估',
    })
    job = usePipelineStore.getState().jobs['raw_3301']
    expect(job.status).toBe('done')
    expect(job.last_action_desc).toBe('已推送飞书，等待评估')

    // 淘汰事件立即进入淘汰 Tab
    store.handleEvent({
      type: 'job',
      job_id: 'raw_3302',
      job_name: '产品专员（AI方向）',
      company_name: '多益网络有限公司',
      platform: 'zhilian',
      node: 'clean_rejected',
      status: 'rejected',
      reject_type: 'ai',
      reject_reason: '触发 AI 侦察兵排雷: 触发绝不条件 [游戏]',
    })
    const rejected = usePipelineStore.getState().jobs['raw_3302']
    expect(rejected.status).toBe('rejected')
    expect(isJobRejected(rejected)).toBe(true)
  })

  it('15. 清洗节点已登记进度秩：快照把 clean_ai_node 打回 scrape_node 时不得降级文案', () => {
    const store = usePipelineStore.getState()

    store.handleEvent({
      type: 'job',
      job_id: 'raw_3401',
      job_name: 'AIGC产品经理',
      company_name: '广信通信',
      platform: 'zhilian',
      node: 'clean_ai_node',
      status: 'running',
      sub_status: 'clean_ai_passed',
    })

    // 12 秒快照对「待推送至飞书」行只会画成 scrape_node/running（清洗排雷处理中）
    store.mergeJobsSnapshot([
      {
        job_id: 'raw_3401',
        job_name: 'AIGC产品经理',
        company_name: '广信通信',
        platform: 'zhilian',
        status: 'running',
        node: 'scrape_node',
        sub_status: 'ai_eval_queued',
        last_action_desc: '清洗排雷处理中',
      } as PipelineJob,
    ])

    const job = usePipelineStore.getState().jobs['raw_3401']
    // 核心断言：本地更靠后的 clean_ai 态必须获胜，不能被快照倒回清洗态
    expect(job.node).toBe('clean_ai_node')
    expect(job.last_action_desc).toBe('AI排雷通过，等待推送飞书')
  })

  it('16. 迟到的 scrape 事件不得把已清洗卡片打回待清洗，也不得把 rec_ 卡降回 raw_', () => {
    const store = usePipelineStore.getState()

    // 流式清洗泵抢先推进：清洗事件先于该轮 scrape 事件到达
    store.handleEvent({
      type: 'job',
      job_id: 'raw_3301',
      job_name: 'AIGC产品经理',
      company_name: '广信通信',
      platform: 'zhilian',
      node: 'clean_ai_node',
      status: 'running',
    })
    expect(usePipelineStore.getState().jobs['raw_3301'].last_action_desc).toBe('AI排雷评估中')

    // 迟到的抓取事件（同 key）：状态/节点/文案都不得回退
    store.handleEvent({
      type: 'job',
      job_id: 'raw_3301',
      job_name: 'AIGC产品经理',
      company_name: '广信通信',
      platform: 'zhilian',
      node: 'scrape_node',
      status: 'scraped',
    })
    const job = usePipelineStore.getState().jobs['raw_3301']
    expect(job.status).toBe('running')
    expect(job.node).toBe('clean_ai_node')
    expect(job.last_action_desc).toBe('AI排雷评估中')

    // 卡片升级为 rec_ 后再来迟到抓取事件：key 不得降回 raw_，状态不得回退
    store.handleEvent({
      type: 'job',
      job_id: 'rec_upgraded_1',
      raw_job_id: 'raw_3301',
      job_name: 'AIGC产品经理',
      company_name: '广信通信',
      platform: 'zhilian',
      node: 'feishu_sync',
      status: 'done',
      sub_status: 'feishu_synced',
      last_action_desc: '已推送飞书，等待评估',
    })
    expect(usePipelineStore.getState().jobs['rec_upgraded_1']).toBeDefined()
    expect(usePipelineStore.getState().jobs['raw_3301']).toBeUndefined()

    store.handleEvent({
      type: 'job',
      job_id: 'raw_3301',
      job_name: 'AIGC产品经理',
      company_name: '广信通信',
      platform: 'zhilian',
      node: 'scrape_node',
      status: 'scraped',
    })
    expect(usePipelineStore.getState().jobs['rec_upgraded_1']).toBeDefined()
    expect(usePipelineStore.getState().jobs['raw_3301']).toBeUndefined()
    expect(usePipelineStore.getState().jobs['rec_upgraded_1'].status).toBe('done')
  })
})


describe('PipelineStore - scrape_progress 重复跳过实况（2026-10-29 细节优化）', () => {
  beforeEach(() => {
    usePipelineStore.getState().reset()
  })

  it('01. scrape_progress 带 skipped 时累计进 scrapeProgress，且缺省 current/total 不冲刷轮询进度', () => {
    const store = usePipelineStore.getState()

    // 先由轮询快照建立权威 current/total
    store.mergeScrapeSnapshot([{ key: 'boss', current: 5, total: 15 }])

    // SSE 跳过事件只带 skipped（转发层补 platform）
    store.handleEvent({ type: 'scrape_progress', platform: 'boss', skipped: 2 })

    const prog = usePipelineStore.getState().scrapeProgress['boss']
    expect(prog.skipped).toBe(2)
    // 核心断言：缺省 current/total 经 Math.max(prev, 0) 保留轮询值，不被 0 冲刷
    expect(prog.current).toBe(5)
    expect(prog.total).toBe(15)
  })

  it('02. skipped 只增不减：低值重放不回退', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({ type: 'scrape_progress', platform: 'zhilian', skipped: 12 })
    store.handleEvent({ type: 'scrape_progress', platform: 'zhilian', skipped: 3 })
    expect(usePipelineStore.getState().scrapeProgress['zhilian'].skipped).toBe(12)
  })

  it('03. 轮询快照合并不丢 skipped（run_snapshot 不携带该字段）', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({ type: 'scrape_progress', platform: 'liepin', skipped: 4 })
    store.mergeScrapeSnapshot([{ key: 'liepin', current: 6, total: 15 }])
    const prog = usePipelineStore.getState().scrapeProgress['liepin']
    expect(prog.skipped).toBe(4)
    expect(prog.current).toBe(6)
  })

  it('04. startPipeline 开新轮时 skipped 随 emptyState 整体复位，不残留上轮数据', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({ type: 'scrape_progress', platform: 'boss', skipped: 9 })
    expect(usePipelineStore.getState().scrapeProgress['boss'].skipped).toBe(9)

    store.startPipeline('pipeline_new_round')
    expect(usePipelineStore.getState().scrapeProgress['boss']).toBeUndefined()
  })

  it('05. phase_progress 重放旧值不回退（SSE 重连回放 50 条历史）', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({ type: 'phase_progress', phase: 'hard_clean', current: 5, total: 10 })
    store.handleEvent({ type: 'phase_progress', phase: 'hard_clean', current: 2, total: 10 })
    expect(usePipelineStore.getState().hardCleanProgress).toEqual({ current: 5, total: 10, skipped: undefined })
  })

  it('06. phase_progress 总数被重新规划时允许回退分母', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({ type: 'phase_progress', phase: 'feishu_sync', current: 8, total: 10 })
    store.handleEvent({ type: 'phase_progress', phase: 'feishu_sync', current: 2, total: 5 })
    expect(usePipelineStore.getState().feishuSyncProgress).toEqual({ current: 2, total: 5, skipped: undefined })
  })
})

describe('PipelineStore - 12 秒快照不得倒流实时岗位态（2026-10-30 修复）', () => {
  beforeEach(() => {
    usePipelineStore.getState().reset()
  })

  it('01. 本地 rewrite running 时，快照 done/evaluate_node 不得把卡片打回「AI初评完成」', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({
      type: 'job',
      job_id: 'rec_live_rewrite',
      job_name: '定制改写岗',
      status: 'running',
      node: 'rewrite_node',
      sub_status: 'rewriting',
      grade: 'A',
      score: 88,
    })

    store.mergeJobsSnapshot([
      {
        job_id: 'rec_live_rewrite',
        job_name: '定制改写岗',
        status: 'done',
        node: 'evaluate_node',
        sub_status: 'eval_done',
        grade: 'A',
        score: 88,
      } as PipelineJob,
    ])

    const job = usePipelineStore.getState().jobs['rec_live_rewrite']
    expect(job.status).toBe('running')
    expect(job.node).toBe('rewrite_node')
    expect(job.sub_status).toBe('rewriting')
    expect(isJobEvaluating(job)).toBe(true)
  })

  it('02. 快照 waiting 仍必须穿透本地 running（真实审批断点不能被防倒流守卫误伤）', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({
      type: 'job',
      job_id: 'rec_live_eval',
      job_name: '评估岗',
      status: 'running',
      node: 'evaluate_node',
      sub_status: 'ai_eval',
    })
    store.mergeJobsSnapshot([
      {
        job_id: 'rec_live_eval',
        job_name: '评估岗',
        status: 'waiting',
        node: 'manual_review_node',
      } as PipelineJob,
    ])
    const job = usePipelineStore.getState().jobs['rec_live_eval']
    expect(job.status).toBe('waiting')
    expect(isJobWaitingReview(job)).toBe(true)
  })

  it('03. deep_eval_done 跨 job 事件与快照轮询保留', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({
      type: 'job',
      job_id: 'rec_deep',
      job_name: '深评岗',
      status: 'running',
      node: 'deep_eval_node',
      sub_status: 'deep_eval',
    })
    store.handleEvent({
      type: 'job',
      job_id: 'rec_deep',
      job_name: '深评岗',
      status: 'running',
      node: 'deep_eval_node',
      sub_status: 'deep_eval',
      deep_eval_done: true,
    })
    expect(usePipelineStore.getState().jobs['rec_deep'].deep_eval_done).toBe(true)

    // 后续 rewrite running 事件没有携带该字段，仍应保留
    store.handleEvent({
      type: 'job',
      job_id: 'rec_deep',
      job_name: '深评岗',
      status: 'running',
      node: 'rewrite_node',
      sub_status: 'rewriting',
    })
    expect(usePipelineStore.getState().jobs['rec_deep'].deep_eval_done).toBe(true)

    // 12 秒快照同样不得抹掉
    store.mergeJobsSnapshot([
      {
        job_id: 'rec_deep',
        job_name: '深评岗',
        status: 'running',
        node: 'rewrite_node',
        sub_status: 'rewriting',
        deep_eval_done: true,
      } as PipelineJob,
    ])
    expect(usePipelineStore.getState().jobs['rec_deep'].deep_eval_done).toBe(true)
  })

  it('04. seedStageSnapshot 恢复阶段状态/清洗进度，且不清空已有岗位', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({ type: 'job', job_id: 'rec_keep', job_name: '保留岗', status: 'running', node: 'evaluate_node' })
    store.seedStageSnapshot({
      task_id: 'pipeline_1',
      stage_status: { scraping: 'done', cleaning: 'running' },
      phases: { hard_clean: { current: 3, total: 10 }, feishu_sync: { current: 2, total: 8 } },
      current_stage: 'cleaning',
    })
    const state = usePipelineStore.getState()
    expect(state.jobs['rec_keep']).toBeDefined()
    expect(state.stageStatus.scraping).toBe('done')
    expect(state.stageStatus.cleaning).toBe('running')
    expect(state.hardCleanProgress).toEqual({ current: 3, total: 10, skipped: undefined })
    expect(state.feishuSyncProgress).toEqual({ current: 2, total: 8, skipped: undefined })
    expect(state.currentStage).toBe('cleaning')
  })

  it('05. 同一任务的后续 stage 快照不再覆盖 SSE 已推进的状态', () => {
    const store = usePipelineStore.getState()
    store.seedStageSnapshot({
      task_id: 'pipeline_1',
      stage_status: { scraping: 'done', cleaning: 'done' },
      current_stage: null,
    })
    // SSE 已把 cleaning 推进到 done；12 秒轮询又拿到同一任务的旧 running 快照
    store.handleEvent({ type: 'stage', stage: 'cleaning', status: 'done' })
    store.seedStageSnapshot({
      task_id: 'pipeline_1',
      stage_status: { cleaning: 'running' },
      current_stage: 'cleaning',
    })
    const state = usePipelineStore.getState()
    expect(state.stageStatus.cleaning).toBe('done')
  })

  it('06. 新任务快照也不能把已 done 阶段倒回 running（单调守卫）', () => {
    const store = usePipelineStore.getState()
    store.seedStageSnapshot({
      task_id: 'pipeline_old',
      stage_status: { scraping: 'done' },
    })
    store.seedStageSnapshot({
      task_id: 'pipeline_new',
      stage_status: { scraping: 'running' },
      current_stage: 'scraping',
    })
    const state = usePipelineStore.getState()
    expect(state.stageStatus.scraping).toBe('done')
    // 不把已完成阶段设为当前运行阶段
    expect(state.currentStage).not.toBe('scraping')
  })

  it('07. greeting_node 裸 running 快照不得注入 delivering（避免误亮投递阶段/终止按钮）', () => {
    const store = usePipelineStore.getState()
    store.mergeJobsSnapshot([
      {
        job_id: 'rec_greet',
        job_name: '打招呼岗',
        status: 'running',
        node: 'greeting_node',
        grade: 'A',
      } as PipelineJob,
    ])
    const job = usePipelineStore.getState().jobs['rec_greet']
    expect(job.status).toBe('running')
    expect(job.node).toBe('greeting_node')
    expect(job.sub_status).not.toBe('delivering')
    expect(isJobDelivering(job)).toBe(false)
  })

  it('08. 已完成 stage 的 done 事件不得把 currentStage 留在该阶段（避免完成态被高亮成运行中）', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({ type: 'stage', stage: 'feishu_sync', status: 'running' })
    expect(usePipelineStore.getState().currentStage).toBe('feishu_sync')
    store.handleEvent({ type: 'stage', stage: 'feishu_sync', status: 'done' })
    expect(usePipelineStore.getState().currentStage).toBeNull()
    expect(usePipelineStore.getState().stageStatus.feishu_sync).toBe('done')
  })

  it('09. 自动化阈值不随新任务复位（避免深评/改写分母闪回 A/B）', () => {
    const store = usePipelineStore.getState()
    store.setAutoEvalThreshold('C')
    store.startPipeline('pipeline_new')
    expect(usePipelineStore.getState().autoEvalThreshold).toBe('C')
  })

  it('10. job 事件下发的 last_action_desc 会更新卡片运行文案', () => {
    const store = usePipelineStore.getState()
    store.handleEvent({
      type: 'job',
      job_id: 'rec_desc',
      job_name: '岗位',
      status: 'running',
      node: 'rewrite_node',
      sub_status: 'rewriting',
      last_action_desc: '定制简历改写中',
    })
    expect(usePipelineStore.getState().jobs['rec_desc'].last_action_desc).toBe('定制简历改写中')
  })
})

describe('PipelineStore - 任务级 LLM 阻塞态（2026-10-31 上游聚合网关 账号池全灭事故）', () => {
  const blockedPayload = {
    blocked: true,
    task_id: 'pipeline_blk_1',
    kind: 'server',
    model: 'global:deepseek-flash',
    message: '模型服务端异常（503）：503 no_healthy_account',
    gateway_hint: '503 no_healthy_account',
    failed_count: 6,
    first_seen: '2026-10-31 11:34:00',
  }

  beforeEach(() => {
    usePipelineStore.getState().reset()
  })

  it('01. stage(status=blocked) 事件把整体状态切到 blocked，并落地阻塞明细与阶段态', () => {
    usePipelineStore.getState().startPipeline('pipeline_blk_1')
    // 先推进到 cleaning running
    usePipelineStore.getState().handleEvent({ type: 'stage', stage: 'cleaning', status: 'running' })
    expect(usePipelineStore.getState().status).toBe('running')

    usePipelineStore.getState().handleEvent({
      type: 'stage', stage: 'cleaning', status: 'blocked', blocked: blockedPayload,
    })
    const state = usePipelineStore.getState()
    expect(state.status).toBe('blocked')
    expect(state.blockedDetail?.kind).toBe('server')
    expect(state.blockedDetail?.model).toBe('global:deepseek-flash')
    expect(state.blockedDetail?.failed_count).toBe(6)
    expect(state.stageStatus.cleaning).toBe('blocked')
    // 看板岗位不被清空（用户仍能看到每张卡片的保留提示）
    expect(Object.keys(state.jobs)).toHaveLength(0) // startPipeline 尚无岗位事件
  })

  it('02. end(summary.outcome=blocked) 置 blocked；正常 end 仍为 done 且解除阻塞（回归守卫）', () => {
    // 阻塞收口
    usePipelineStore.getState().handleEvent({
      type: 'end',
      summary: { outcome: 'blocked', blocked: blockedPayload, jobs: 6 },
    })
    let state = usePipelineStore.getState()
    expect(state.status).toBe('blocked')
    expect(state.blockedDetail?.task_id).toBe('pipeline_blk_1')
    expect(state.blockedDetail?.gateway_hint).toContain('no_healthy_account')

    // 正常收口：done 且清空阻塞明细
    usePipelineStore.getState().handleEvent({ type: 'end', summary: { jobs: 3 } })
    state = usePipelineStore.getState()
    expect(state.status).toBe('done')
    expect(state.blockedDetail).toBeNull()
  })

  it('03. 正常 done/running/error 历史行为不回归（blocked 未介入时）', () => {
    usePipelineStore.getState().startPipeline('pipeline_norm_1')
    usePipelineStore.getState().handleEvent({ type: 'stage', stage: 'cleaning', status: 'running' })
    expect(usePipelineStore.getState().status).toBe('running')
    usePipelineStore.getState().handleEvent({ type: 'stage', stage: 'cleaning', status: 'done' })
    usePipelineStore.getState().handleEvent({ type: 'end', summary: { jobs: 2 } })
    expect(usePipelineStore.getState().status).toBe('done')
    expect(usePipelineStore.getState().blockedDetail).toBeNull()

    usePipelineStore.getState().reset()
    usePipelineStore.getState().handleEvent({ type: 'error', message: '链路崩溃' })
    expect(usePipelineStore.getState().status).toBe('error')
  })

  it('04. stage(cleaning, running) 在阻塞态下转回 running（继续任务受理），blockedDetail 保留供横幅转进行中态', () => {
    usePipelineStore.getState().handleEvent({
      type: 'end', summary: { outcome: 'blocked', blocked: blockedPayload },
    })
    expect(usePipelineStore.getState().status).toBe('blocked')

    // 模拟继续任务：后端 resume worker 广播 cleaning running
    usePipelineStore.getState().resumePipeline()
    usePipelineStore.getState().handleEvent({ type: 'stage', stage: 'cleaning', status: 'running' })
    const state = usePipelineStore.getState()
    expect(state.status).toBe('running')
    // 横幅据 blockedDetail 非空渲染「继续任务进行中」进行时态
    expect(state.blockedDetail?.kind).toBe('server')
  })

  it('05. 刷新恢复：stage 快照携带 blocked 时，空闲状态种出 blocked 徽标（不依赖 SSE）', () => {
    // 模拟刷新后的初始态：idle、无任务
    usePipelineStore.getState().seedStageSnapshot({
      task_id: 'pipeline_blk_1',
      stage_status: { scraping: 'done', cleaning: 'blocked', feishu_sync: 'done', done: 'done' },
      current_stage: null,
      blocked: blockedPayload,
    })
    const state = usePipelineStore.getState()
    expect(state.status).toBe('blocked')
    expect(state.blockedDetail?.failed_count).toBe(6)
    expect(state.stageStatus.cleaning).toBe('blocked')
    // 已收口的 done 阶段不被阻塞快照打回
    expect(state.stageStatus.done).toBe('done')
  })

  it('06. 阻塞快照不得污染新一轮任务或已收口界面', () => {
    // 已 done：不回 blocked
    usePipelineStore.getState().handleEvent({ type: 'end', summary: { jobs: 1 } })
    usePipelineStore.getState().seedStageSnapshot({
      task_id: 'pipeline_blk_1',
      stage_status: { cleaning: 'blocked' },
      blocked: blockedPayload,
    })
    expect(usePipelineStore.getState().status).toBe('done')
    expect(usePipelineStore.getState().blockedDetail).toBeNull()

    // 新一轮运行中（不同 task_id）：旧任务阻塞不越权
    usePipelineStore.getState().reset()
    usePipelineStore.getState().startPipeline('pipeline_new_round')
    usePipelineStore.getState().seedStageSnapshot({
      task_id: 'pipeline_blk_1',
      stage_status: { cleaning: 'blocked' },
      blocked: blockedPayload,
    })
    const state = usePipelineStore.getState()
    expect(state.status).toBe('running')
    expect(state.blockedDetail).toBeNull()
    expect(state.stageStatus.cleaning).toBe('pending')
  })

  it('07. resumePipeline 保留看板岗位（只切状态不清现场）', () => {
    usePipelineStore.getState().handleEvent({
      type: 'end', summary: { outcome: 'blocked', blocked: blockedPayload },
    })
    usePipelineStore.getState().handleEvent({
      type: 'job', job_id: 'raw_9', job_name: '保留岗', node: 'clean_ai_node',
      status: 'running', sub_status: 'clean_ai_preserved',
    })
    expect(usePipelineStore.getState().jobs['raw_9']).toBeDefined()

    usePipelineStore.getState().resumePipeline()
    const state = usePipelineStore.getState()
    expect(state.status).toBe('running')
    expect(state.jobs['raw_9']).toBeDefined()
    expect(state.jobs['raw_9'].sub_status).toBe('clean_ai_preserved')
  })

  it('08. 同一任务后续无 blocked 的快照不再重复置位（stageSnapshotTaskId 幂等）', () => {
    usePipelineStore.getState().seedStageSnapshot({
      task_id: 'pipeline_blk_1',
      stage_status: { cleaning: 'blocked' },
      blocked: blockedPayload,
    })
    expect(usePipelineStore.getState().status).toBe('blocked')

    // 用户已点继续任务回到 running；12 秒轮询同任务旧快照不得再次打回 blocked
    usePipelineStore.getState().resumePipeline()
    usePipelineStore.getState().seedStageSnapshot({
      task_id: 'pipeline_blk_1',
      stage_status: { cleaning: 'blocked' },
      blocked: blockedPayload,
    })
    expect(usePipelineStore.getState().status).toBe('running')
  })

  it('09. 轮询解除通道：后端登记已清（快照无 blocked）时，12 秒轮询必须摘下卡死的横幅（2026-11-03 事故根治）', () => {
    // 事故现场复刻：阻塞横幅挂着，SSE 已被 blocked 态断开（blockedDetail 成为无清除入口的孤儿）
    usePipelineStore.getState().handleEvent({
      type: 'end', summary: { outcome: 'blocked', blocked: blockedPayload },
    })
    expect(usePipelineStore.getState().blockedDetail).not.toBeNull()

    // 后端已恢复（LLM 自愈/继续任务重洗成功/终止任务 → 登记表已清）：
    // dashboard-sync 快照不再携带 blocked，轮询是唯一存活通道，必须能解除阻塞
    usePipelineStore.getState().seedStageSnapshot({
      task_id: 'pipeline_blk_1',
      stage_status: { cleaning: 'done' },
      blocked: null,
    })
    let state = usePipelineStore.getState()
    expect(state.blockedDetail).toBeNull()
    expect(state.status).toBe('running') // blocked → running（进行时态语义），横幅整体卸下

    // blocked 态直摘分支：status 停在 blocked 时同样摘横幅并转 running
    usePipelineStore.getState().reset()
    usePipelineStore.getState().handleEvent({
      type: 'end', summary: { outcome: 'blocked', blocked: blockedPayload },
    })
    usePipelineStore.getState().seedStageSnapshot({
      task_id: 'pipeline_blk_1',
      stage_status: {},
      blocked: undefined,
    })
    state = usePipelineStore.getState()
    expect(state.blockedDetail).toBeNull()

    // 守卫：后端仍阻塞（快照携带 blocked）时不得误解除
    usePipelineStore.getState().reset()
    usePipelineStore.getState().handleEvent({
      type: 'end', summary: { outcome: 'blocked', blocked: blockedPayload },
    })
    usePipelineStore.getState().seedStageSnapshot({
      task_id: 'pipeline_blk_1',
      stage_status: { cleaning: 'blocked' },
      blocked: blockedPayload,
    })
    state = usePipelineStore.getState()
    expect(state.status).toBe('blocked')
    expect(state.blockedDetail).not.toBeNull()

    // 守卫：done/error 收口态不受解除分支影响（终态本就无横幅，不得被改写）
    usePipelineStore.getState().reset()
    usePipelineStore.getState().startPipeline('pipeline_x')
    usePipelineStore.getState().handleEvent({ type: 'end', summary: { jobs: 1 } })
    usePipelineStore.getState().seedStageSnapshot({
      task_id: 'pipeline_x',
      stage_status: {},
      blocked: null,
    })
    expect(usePipelineStore.getState().status).toBe('done')
  })
})
