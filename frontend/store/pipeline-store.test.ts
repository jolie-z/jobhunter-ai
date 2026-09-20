import { describe, it, expect, beforeEach } from 'vitest'
import { usePipelineStore, PipelineJob } from './pipeline-store'
import { isJobFailed, isJobEvaluating, isJobWaitingReview } from '@/components/command-center/job-predicates'

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
})


