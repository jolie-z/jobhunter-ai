import { describe, it, expect, beforeEach } from 'vitest'
import { usePipelineStore } from './pipeline-store'

describe('PipelineStore - platform_failure 右下角弹窗事件', () => {
  beforeEach(() => {
    usePipelineStore.getState().reset()
  })

  it('01. platform_failure 事件入列，字段完整；手动关闭后移除', () => {
    usePipelineStore.getState().handleEvent({
      type: 'platform_failure',
      platform: 'zhilian',
      platform_name: '智联招聘',
      reason: '薪资筛选失败中止（下拉选项未渲染，宁缺毋滥防越档岗位灌库）',
      keyword: '智能客服',
      city: '广州',
      salary: '15K-25K',
      cursor_note: '续抓起点已保留，下轮自动重试',
    })

    const failures = usePipelineStore.getState().platformFailures
    expect(failures).toHaveLength(1)
    expect(failures[0].platform).toBe('zhilian')
    expect(failures[0].platform_name).toBe('智联招聘')
    expect(failures[0].reason).toContain('薪资筛选失败中止')
    expect(failures[0].time).toBeTruthy()
    expect(failures[0].id).toBeTruthy()

    // 手动关闭：唯一关闭途径
    usePipelineStore.getState().dismissPlatformFailure(failures[0].id)
    expect(usePipelineStore.getState().platformFailures).toHaveLength(0)
  })

  it('02. 多平台失败各自成卡，关闭一张不影响其他', () => {
    usePipelineStore.getState().handleEvent({
      type: 'platform_failure', platform: 'zhilian', platform_name: '智联招聘', reason: 'r1',
    })
    usePipelineStore.getState().handleEvent({
      type: 'platform_failure', platform: 'boss', platform_name: 'BOSS直聘', reason: 'r2',
    })

    const failures = usePipelineStore.getState().platformFailures
    expect(failures).toHaveLength(2)
    expect(failures.map((f) => f.platform)).toEqual(['zhilian', 'boss'])

    usePipelineStore.getState().dismissPlatformFailure(failures[0].id)
    const rest = usePipelineStore.getState().platformFailures
    expect(rest).toHaveLength(1)
    expect(rest[0].platform).toBe('boss')
  })

  it('03. 新任务 startPipeline 清空历史失败弹窗', () => {
    usePipelineStore.getState().handleEvent({
      type: 'platform_failure', platform: '51job', platform_name: '前程无忧', reason: '页面加载失败',
    })
    expect(usePipelineStore.getState().platformFailures).toHaveLength(1)

    usePipelineStore.getState().startPipeline('pipeline_new_task')
    expect(usePipelineStore.getState().platformFailures).toHaveLength(0)
  })

  it('04. reason 缺省时给出兜底文案，不产生空白弹窗', () => {
    usePipelineStore.getState().handleEvent({
      type: 'platform_failure', platform: 'liepin',
    })
    const failures = usePipelineStore.getState().platformFailures
    expect(failures[0].reason).toContain('引擎未上报具体原因')
    expect(failures[0].platform_name).toBe('liepin')
  })

  it('05. 同 ts 的重放事件被去重（TaskChannel 断线重连回放免疫），新 ts 正常弹出', () => {
    const payload = {
      type: 'platform_failure', platform: 'zhilian', platform_name: '智联招聘',
      reason: '薪资筛选失败中止', ts: 1730000000000,
    }
    usePipelineStore.getState().handleEvent(payload)
    usePipelineStore.getState().handleEvent({ ...payload })  // 断线重连回放：同载荷二次投递
    expect(usePipelineStore.getState().platformFailures).toHaveLength(1)

    // 新一轮失败：全新 ts → 正常弹出（不同轮次的相同原因不受去重影响）
    usePipelineStore.getState().handleEvent({ ...payload, ts: 1730000060000 })
    expect(usePipelineStore.getState().platformFailures).toHaveLength(2)

    // 卡片时间取后端发射时刻，而非客户端接收时刻（重放件不串时间）
    expect(usePipelineStore.getState().platformFailures[0].ts).toBe(1730000000000)
  })
})
