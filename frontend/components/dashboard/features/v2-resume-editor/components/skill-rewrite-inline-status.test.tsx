import { render, screen, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi, afterEach, beforeAll } from 'vitest'
import { SkillRewriteInlineStatus } from './skill-rewrite-inline-status'

// 官方剧本/单文件技能的轻量行内状态条：与看板共用同一 SSE hook，
// 单轮引擎推演不弹「作战推演看板」，但必须保留最低限度进度反馈。

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

function makeProps(overrides: Record<string, any> = {}) {
  return {
    taskId: 'skill_task_inline1',
    skillLabel: '官方标准剧本',
    onComplete: vi.fn(),
    onError: vi.fn(),
    onDismiss: vi.fn(),
    ...overrides,
  }
}

describe('SkillRewriteInlineStatus 行内状态条', () => {
  const originalES = global.EventSource

  beforeAll(() => {
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

  it('阶段事件驱动文本更新，技能显示名与计时可见（不泄露原始 ID）', async () => {
    render(<SkillRewriteInlineStatus {...makeProps()} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'init', message: '🚀 正在初始化 Skill 智能体改写任务...' })
      es.emit({ type: 'thinking', message: '🧠 大模型单轮深度推演中（官方剧本模式）' })
    })
    expect(screen.getByText(/官方标准剧本 · 简历改写中/)).toBeTruthy()
    expect(screen.getByText(/大模型单轮深度推演中/)).toBeTruthy()
  })

  it('complete → 上抛业务数据（铺画布），不经 onError，无误报失败', async () => {
    const props = makeProps()
    render(<SkillRewriteInlineStatus {...props} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'complete', data: { parsed_json: { summary: 'x' }, markdown: '# ok', usage: {} } })
    })
    expect(props.onComplete).toHaveBeenCalledTimes(1)
    expect(props.onComplete.mock.calls[0][0].parsed_json.summary).toBe('x')
    expect(props.onError).not.toHaveBeenCalled()
    expect(screen.getByText('完成')).toBeTruthy()
  })

  it('终局后收起按钮隐藏（父级随后卸载状态条，杜绝「完成后收起被误报后台执行」）', async () => {
    const props = makeProps()
    render(<SkillRewriteInlineStatus {...props} />)
    const es = FakeEventSource.instances[0]
    expect(screen.getByTitle(/收起/)).toBeTruthy()
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'complete', data: { parsed_json: {}, markdown: '# ok', usage: {} } })
    })
    expect(screen.queryByTitle(/收起/)).toBeNull()
  })

  it('error → onError 携带真实报错，仅上报一次', async () => {
    const props = makeProps()
    render(<SkillRewriteInlineStatus {...props} />)
    const es = FakeEventSource.instances[0]
    await act(async () => {
      es.onopen?.()
      es.emit({ type: 'error', detail: '飞书写回失败 502', message: '❌ 写回失败' })
    })
    await act(async () => {
      es.emit({ type: 'error', detail: '重复错误', message: '❌ 重复' })
    })
    expect(props.onError).toHaveBeenCalledTimes(1)
    expect(props.onError.mock.calls[0][0]).toContain('飞书写回失败 502')
  })

  it('收起按钮 → onDismiss（SSE 停订，任务服务端继续）', async () => {
    const props = makeProps()
    render(<SkillRewriteInlineStatus {...props} />)
    act(() => {
      screen.getByTitle(/收起/).click()
    })
    expect(props.onDismiss).toHaveBeenCalledTimes(1)
  })
})
