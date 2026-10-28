import { render, screen, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import {
  SkillRewriteProgressDock,
  REWRITE_STAGES,
  AGENT_STAGES,
  GENERIC_AGENT_STAGES,
  deriveRewriteStage,
  deriveRewriteProgress,
  latestEngineFromLogs,
  latestResultKindFromLogs,
  stageIndexOfLog,
} from './skill-rewrite-progress-dock'
import { isSkillPack } from './use-resume-builder-actions'
import type { AgentLogItem } from '@/hooks/use-skill-agent-stream'

// 简历库官方剧本改写进度坞（2026-10-23）：此前走同步接口全程黑盒，
// 现为 useSkillAgentStream 的第三种皮肤——右下角 7 步轨道，只认结构化字段点亮。

// 同页解析卡的可见性来自 StrategyStore；进度坞用 Optional 取值，这里可控地模拟「解析卡在场」
let mockStrategy: { isParsing?: boolean; parseError?: string | null } | undefined
vi.mock('@/hooks/use-strategy-store', () => ({
  useOptionalStrategyStore: () => mockStrategy,
}))

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
  close() {
    this.readyState = 2
  }
}

const log = (partial: Partial<AgentLogItem> & { type: string }): AgentLogItem => ({
  id: 'x',
  timestamp: '00:00:00',
  message: '',
  ...partial,
})

describe('阶段推导（纯函数）：只认 type/step/tool/stage，不做文案匹配', () => {
  it('完整事件序列逐步推进到全部完成', () => {
    const seq: AgentLogItem[] = [
      log({ type: 'system' }),
      log({ type: 'thinking', stage: 'prepare' }),
      log({ type: 'agent_start' }),
      log({ type: 'step_start', step: 1 }),
      log({ type: 'thinking', message: '🧩 提示词装配完成' }), // 无 stage：不推进
      log({ type: 'step_start', step: 2 }),
      log({ type: 'thinking', message: '✅ 大模型响应完成' }), // 无 stage：不推进
      log({ type: 'tool_call', tool: 'truth_boundary_check' }),
      log({ type: 'thinking', stage: 'parse' }),
      log({ type: 'artifact_saved' }),
      log({ type: 'tool_call', tool: 'feishu_write' }),
      log({ type: 'complete' }),
    ]
    const expected = [0, 0, 0, 1, 1, 2, 2, 3, 4, 5, 6, REWRITE_STAGES.length]
    seq.forEach((_, i) => {
      expect(deriveRewriteStage(seq.slice(0, i + 1))).toBe(expected[i])
    })
  })

  it('无结构化标记的 thinking / 未知 tool 不推进，阶段只前进不后退', () => {
    expect(stageIndexOfLog(log({ type: 'thinking', message: '任意文案，哪怕写着 解析 写回' }))).toBe(-1)
    expect(stageIndexOfLog(log({ type: 'tool_call', tool: 'unknown_tool' }))).toBe(-1)
    // 先到 parse，再来一条 prepare：不得倒退
    expect(deriveRewriteStage([log({ type: 'thinking', stage: 'parse' }), log({ type: 'thinking', stage: 'prepare' })])).toBe(4)
  })
})

describe('engine 轨道纯函数（2026-10-25）', () => {
  it('最后一条带 engine 的日志优先', () => {
    expect(latestEngineFromLogs([
      log({ type: 'init', engine: 'official' }),
      log({ type: 'agent_start', engine: 'agent' }),
    ])).toBe('agent')
    expect(latestEngineFromLogs([log({ type: 'init', engine: 'agent' }), log({ type: 'step_start' })])).toBe('agent')
  })

  it('agent：agent_start 时底稿与技能包已装载，前两步完成', () => {
    const p = deriveRewriteProgress([
      log({ type: 'init', engine: 'agent' }),
      log({ type: 'agent_start', engine: 'agent' }),
    ], 'agent')
    expect(p.stage).toBe(2)
    expect(p.completed.has(0)).toBe(true)
    expect(p.completed.has(1)).toBe(true)
    expect(p.completed.has(2)).toBe(false)
  })

  it('agent：逐文件 artifact_saved 不推进；parse/archive/feishu 才推进', () => {
    const base = [
      log({ type: 'init', engine: 'agent' }),
      log({ type: 'agent_start', engine: 'agent' }),
      log({ type: 'step_start', step: 2 }),
    ]
    let p = deriveRewriteProgress(
      [...base, log({ type: 'artifact_saved', stage: 'agent_artifact', file: '01.md' })],
      'agent',
    )
    expect(p.stage).toBe(2)
    expect(p.completed.has(3)).toBe(false)

    p = deriveRewriteProgress(
      [...base, log({ type: 'artifact_saved', stage: 'agent_artifact' }), log({ type: 'thinking', stage: 'parse' })],
      'agent',
    )
    expect(p.stage).toBe(3)
    expect(p.completed.has(2)).toBe(true)

    p = deriveRewriteProgress(
      [...base, log({ type: 'thinking', stage: 'parse' }), log({ type: 'artifact_saved', stage: 'archive' })],
      'agent',
    )
    expect(p.stage).toBe(4)
    expect(p.completed.has(3)).toBe(true)

    p = deriveRewriteProgress(
      [
        ...base,
        log({ type: 'thinking', stage: 'parse' }),
        log({ type: 'artifact_saved', stage: 'archive' }),
        log({ type: 'tool_call', tool: 'feishu_write' }),
      ],
      'agent',
    )
    expect(p.stage).toBe(5)
    expect(p.completed.has(4)).toBe(true)
  })

  it('通用 skill：resultKind=markdown 使用 4 步轨道，archive 事件点亮归档', () => {
    const base = [
      log({ type: 'init', engine: 'agent', resultKind: 'markdown' }),
      log({ type: 'agent_start', engine: 'agent' }),
      log({ type: 'step_start', step: 2 }),
      log({ type: 'artifact_saved', stage: 'agent_artifact', file: '01.md' }),
    ]
    let p = deriveRewriteProgress(base, 'agent', 'markdown')
    expect(p.stage).toBe(2)
    expect(p.completed.has(3)).toBe(false)

    p = deriveRewriteProgress(
      [...base, log({ type: 'artifact_saved', stage: 'archive' })],
      'agent',
      'markdown',
    )
    expect(p.stage).toBe(3)
    expect(p.completed.has(2)).toBe(true)
    expect(latestResultKindFromLogs(base)).toBe('markdown')
  })

  it('official：逐文件 agent_artifact 不越级点亮归档', () => {
    const p = deriveRewriteProgress([
      log({ type: 'step_start', step: 1 }),
      log({ type: 'step_start', step: 2 }),
      log({ type: 'artifact_saved', stage: 'agent_artifact', file: '01.md' }),
    ], 'official')
    expect(p.stage).toBe(2)
    expect(p.completed.has(5)).toBe(false)
  })
})

function makeProps(overrides: Record<string, any> = {}) {
  return {
    taskId: 'skill_task_dock1',
    onComplete: vi.fn(),
    onError: vi.fn(),
    onDismiss: vi.fn(),
    ...overrides,
  }
}

describe('SkillRewriteProgressDock 右下角进度坞', () => {
  const originalES = global.EventSource

  beforeEach(() => {
    vi.clearAllMocks()
    FakeEventSource.instances = []
    mockStrategy = undefined
    ;(global as any).EventSource = FakeEventSource
  })
  afterEach(() => {
    ;(global as any).EventSource = originalES
  })

  it('taskId 为空不渲染', () => {
    const { container } = render(<SkillRewriteProgressDock {...makeProps({ taskId: null })} />)
    expect(container.firstChild).toBeNull()
  })

  it('运行中：7 步轨道全部可见，最新日志文案展示，无关闭按钮', async () => {
    render(<SkillRewriteProgressDock {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'thinking', stage: 'prepare', message: '📋 已读取底稿' })
      es.emit({ type: 'step_start', step: 2, message: '🧠 大模型单轮深度推演中' })
    })
    expect(screen.getByText('官方剧本改写进行中')).toBeTruthy()
    REWRITE_STAGES.forEach((s) => expect(screen.getByText(s.label)).toBeTruthy())
    expect(screen.getByText(/大模型单轮深度推演中/)).toBeTruthy()
    expect(screen.queryByLabelText('关闭进度面板')).toBeNull()
  })

  it('complete → 标题变完成态、onComplete 携带业务数据、不经 onError', async () => {
    const props = makeProps()
    render(<SkillRewriteProgressDock {...props} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'complete', data: { parsed_json: { summary: 'x' }, markdown: '# ok', usage: {} } })
    })
    expect(screen.getByText('改写完成，已写回底稿')).toBeTruthy()
    expect(props.onComplete).toHaveBeenCalledTimes(1)
    expect(props.onComplete.mock.calls[0][0].parsed_json.summary).toBe('x')
    expect(props.onError).not.toHaveBeenCalled()
    expect(screen.getByLabelText('关闭进度面板')).toBeTruthy()
  })

  it('error → 失败态展示后端原因（含写回保底闸拦截文案），onError 只报一次', async () => {
    const props = makeProps()
    render(<SkillRewriteProgressDock {...props} />)
    const es = FakeEventSource.instances[0]
    const detail = '改写结果丢失了原有模块（项目经历：原非空、改写后被清空），已拒绝写回并保留原简历数据'
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'step_start', step: 2 })
      es.emit({ type: 'error', detail, message: '❌ 改写产物完整性校验未通过' })
    })
    expect(screen.getByText('改写未完成')).toBeTruthy()
    expect(screen.getByText(detail)).toBeTruthy()
    expect(props.onError).toHaveBeenCalledTimes(1)
    expect(props.onError.mock.calls[0][0]).toContain('已拒绝写回')
    expect(props.onComplete).not.toHaveBeenCalled()
  })

  it('【R1-P1】同一页面连续两次任务（key=taskId 重挂）：第二次失败同样上报，不被首次的守卫吞掉', async () => {
    const props = makeProps({ taskId: 'task_1' })
    const { rerender } = render(<SkillRewriteProgressDock key="task_1" {...props} />)
    await act(async () => {
      FakeEventSource.instances[0].onopen?.()
      FakeEventSource.instances[0].emit({ type: 'error', detail: '第一次失败' })
    })
    expect(props.onError).toHaveBeenCalledTimes(1)

    // 第二次任务：父级按 key=taskId 重挂 → 全新 SSE 实例、全新守卫
    rerender(<SkillRewriteProgressDock key="task_2" {...props} taskId="task_2" />)
    expect(FakeEventSource.instances.length).toBe(2)
    await act(async () => {
      FakeEventSource.instances[1].onopen?.()
      FakeEventSource.instances[1].emit({ type: 'step_start', step: 1 })
    })
    // 新任务从轨道起点重新开始，不继承上一次的失败态
    expect(screen.getByText('官方剧本改写进行中')).toBeTruthy()
    await act(async () => {
      FakeEventSource.instances[1].emit({ type: 'error', detail: '第二次失败' })
    })
    expect(props.onError).toHaveBeenCalledTimes(2)
    expect(props.onError.mock.calls[1][0]).toContain('第二次失败')
  })

  it('【R1-P2】解析进度卡在场时上移让位，不与同槽位 fixed 卡片重叠', async () => {
    mockStrategy = { isParsing: true }
    const { container } = render(<SkillRewriteProgressDock {...makeProps()} />)
    const root = container.firstChild as HTMLElement
    expect(root.className).toContain('bottom-[17rem]')
    expect(root.className).not.toMatch(/\bbottom-6\b/)
  })

  it('无解析卡时停在默认右下角槽位', () => {
    const { container } = render(<SkillRewriteProgressDock {...makeProps()} />)
    const root = container.firstChild as HTMLElement
    expect(root.className).toMatch(/\bbottom-6\b/)
  })

  it('agent 任务：init 切换为 6 步技能包轨道，不出现官方安全阀步骤', async () => {
    render(<SkillRewriteProgressDock {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'init', engine: 'agent', message: '技能包启动' })
    })
    expect(screen.getByText('技能包改写进行中')).toBeTruthy()
    AGENT_STAGES.forEach((s) => expect(screen.getByText(s.label)).toBeTruthy())
    expect(screen.queryByText('萃取定稿 · 安全阀校验')).toBeNull()
  })

  it('partial complete：标题显示部分产物 N/11，onComplete 正常触发', async () => {
    const props = makeProps()
    render(<SkillRewriteProgressDock {...props} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'init', engine: 'agent' })
      es.emit({
        type: 'complete',
        message: '⚠️ 改写完成（部分产物 5/11），已写回简历库',
        data: {
          parsed_json: { summary: 'x' },
          markdown: '# ok',
          usage: {},
          partial: true,
          artifact_count: 5,
          expected_artifact_count: 11,
          engine: 'agent',
        },
      })
    })
    expect(screen.getByText('改写完成 · 部分产物 5/11')).toBeTruthy()
    expect(props.onComplete).toHaveBeenCalledTimes(1)
    expect(props.onError).not.toHaveBeenCalled()
  })

  it('agent 完整成功：标题区分「已写回简历库」', async () => {
    const props = makeProps()
    render(<SkillRewriteProgressDock {...props} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'init', engine: 'agent' })
      es.emit({
        type: 'complete',
        data: {
          parsed_json: {},
          markdown: '# ok',
          usage: {},
          partial: false,
          artifact_count: 11,
          expected_artifact_count: 11,
          engine: 'agent',
        },
      })
    })
    expect(screen.getByText('改写完成，已写回简历库')).toBeTruthy()
  })

  it('通用 skill：init 切换为 4 步轨道，不出现简历解析/写回阶段', async () => {
    render(<SkillRewriteProgressDock {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'init', engine: 'agent', result_kind: 'markdown', message: '通用技能启动' })
    })
    expect(screen.getByText('技能执行进行中')).toBeTruthy()
    GENERIC_AGENT_STAGES.forEach((s) => expect(screen.getByText(s.label)).toBeTruthy())
    expect(screen.queryByText('解析为结构化简历')).toBeNull()
    expect(screen.queryByText('写回简历库')).toBeNull()
  })

  it('通用 skill 完成：标题为“产物已归档”，onComplete 正常触发', async () => {
    const props = makeProps()
    render(<SkillRewriteProgressDock {...props} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'init', engine: 'agent', result_kind: 'markdown' })
      es.emit({
        type: 'complete',
        message: '🎉 技能执行完成，产物已归档到产物库',
        data: {
          parsed_json: {},
          markdown: '# cover letter',
          usage: {},
          partial: false,
          artifact_count: 2,
          expected_artifact_count: 2,
          engine: 'agent',
          result_kind: 'markdown',
          has_resume_output: false,
        },
      })
    })
    expect(screen.getByText('技能执行完成，产物已归档')).toBeTruthy()
    expect(props.onComplete).toHaveBeenCalledTimes(1)
    expect(props.onError).not.toHaveBeenCalled()
  })

  it('通用 skill 部分完成：显示 N/M（非简历）', async () => {
    const props = makeProps()
    render(<SkillRewriteProgressDock {...props} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'init', engine: 'agent', result_kind: 'markdown' })
      es.emit({
        type: 'complete',
        data: {
          parsed_json: {},
          markdown: '# cover letter',
          usage: {},
          partial: true,
          artifact_count: 2,
          expected_artifact_count: 3,
          engine: 'agent',
          result_kind: 'markdown',
          has_resume_output: false,
        },
      })
    })
    expect(screen.getByText('技能部分完成 · 2/3')).toBeTruthy()
  })

  it('isSkillPack 谓词：官方剧本不算技能包，其余算（口径与进度坞 skillLabel / 完成回调共用）', () => {
    expect(isSkillPack(null)).toBe(false)
    expect(isSkillPack(undefined)).toBe(false)
    expect(isSkillPack('resume_rewrite')).toBe(false)
    expect(isSkillPack('cold_call_master')).toBe(true)
  })
})
