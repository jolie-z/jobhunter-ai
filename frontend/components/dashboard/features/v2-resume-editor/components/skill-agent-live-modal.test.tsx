import { render, screen, act, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi, afterEach, beforeAll } from 'vitest'
import { SkillAgentLiveModal } from './skill-agent-live-modal'

// Skill Agent 实时作战推演看板（2026-10-09 报修回归锁）：
// 1. init / agent_error 事件此前无处理分支——官方剧本路径发的 init 直接被吞，看板「一动不动」；
// 2. onerror 读闭包旧 status（恒 connecting），完成前断流被静默吞掉；
// 3. 弹窗尺寸收敛（860×82vh → 600×58vh），不能回弹成满屏大窗。

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
  fail() {
    this.readyState = 2
    this.onerror?.(new Event('error'))
  }
  close() {
    this.closed = true
    this.readyState = 2
  }
}

function makeProps(overrides: Record<string, any> = {}) {
  return {
    open: true,
    onOpenChange: vi.fn(),
    taskId: 'skill_task_test123',
    jobTitle: '测试岗位',
    skillId: 'resume_rewrite',
    onComplete: vi.fn(),
    onOpenStudio: vi.fn(),
    ...overrides,
  }
}

describe('SkillAgentLiveModal 实时推演看板', () => {
  const originalES = global.EventSource

  beforeAll(() => {
    // jsdom 未实现 scrollIntoView（自动滚动日志区用）
    Element.prototype.scrollIntoView = vi.fn()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    FakeEventSource.instances = []
    ;(global as any).EventSource = FakeEventSource
  })

  afterEach(() => {
    ;(global as any).EventSource = originalES
  })

  it('弹窗尺寸收敛：宽 600px、高 58vh，不再是 860×82vh 满屏大窗', () => {
    render(<SkillAgentLiveModal {...makeProps()} />)
    const dialog = document.querySelector('[role="dialog"]') as HTMLElement
    expect(dialog).not.toBeNull()
    expect(dialog.className).toContain('max-w-[600px]')
    expect(dialog.className).toContain('h-[58vh]')
    expect(dialog.className).not.toContain('max-w-[860px]')
    expect(dialog.className).not.toContain('h-[82vh]')
  })

  it('init 事件渲染为日志行（官方剧本路径首事件不再被吞）', async () => {
    render(<SkillAgentLiveModal {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'init', message: '🚀 正在初始化 Skill 智能体改写任务...' })
    })
    expect(screen.getByText(/正在初始化 Skill 智能体改写任务/)).toBeTruthy()
  })

  it('agent_error 事件记为警告日志但不推翻终局状态（runner 单步异常可回退续跑）', async () => {
    render(<SkillAgentLiveModal {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'agent_error', message: '❌ 大模型调用异常，将回退标准 SOP' })
      es.emit({ type: 'complete', data: { parsed_json: {}, markdown: '# done', usage: {} } })
    })
    expect(screen.getByText(/大模型调用异常/)).toBeTruthy()
    expect(screen.getByText(/推演定稿完成/)).toBeTruthy()
  })

  it('完成前 SSE 断流 → 显式进入 error 态提示后台仍在执行，而非无声冻结', async () => {
    render(<SkillAgentLiveModal {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'agent_start', message: '智能体启动' })
    })
    await act(async () => {
      es.fail()
    })
    await waitFor(() => {
      // 日志行 + 底栏提示至少各出现一处
      expect(screen.getAllByText(/实时推演流连接中断/).length).toBeGreaterThanOrEqual(1)
    })
  })

  it('complete 之后断流 → 静默收尾，不误报错误', async () => {
    render(<SkillAgentLiveModal {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'complete', data: { parsed_json: {}, markdown: '# done', usage: {} } })
    })
    await act(async () => {
      es.fail()
    })
    expect(screen.queryByText(/实时推演流连接中断/)).toBeNull()
    expect(screen.getByText(/推演定稿完成/)).toBeTruthy()
  })

  it('后端已报 error 终局后断流 → 保留真实报错文案，不被「连接中断」假死提示覆盖', async () => {
    render(<SkillAgentLiveModal {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'error', detail: '飞书写回失败 502', message: '❌ 改写已完成，但写回失败' })
    })
    await act(async () => {
      es.fail()
    })
    // 真实报错（detail 优先展示）必须原样保留
    expect(screen.getAllByText(/飞书写回失败 502/).length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText(/实时推演流连接中断/)).toBeNull()
  })

  it('worker 归档汇总事件（无 filename）只记日志，不在产物托盘产生坏 chip', async () => {
    render(<SkillAgentLiveModal {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'artifact_saved', message: '💾 全套作战产物已归档（3 份）' })
    })
    expect(screen.getByText(/全套作战产物已归档/)).toBeTruthy()
    expect(screen.queryByText(/已落盘/)).toBeNull()
  })
})
