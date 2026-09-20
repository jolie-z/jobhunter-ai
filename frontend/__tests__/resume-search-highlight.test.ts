import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { useEditorSearchHighlight } from "../components/dashboard/features/v2-resume-editor/hooks/use-editor-search-highlight"

describe("useEditorSearchHighlight", () => {
  let mockHighlightsMap: Map<string, any>

  beforeEach(() => {
    // 1. Mock CSS.highlights API in jsdom
    mockHighlightsMap = new Map()
    const mockCSS = {
      highlights: {
        set: vi.fn((key: string, highlight: any) => {
          mockHighlightsMap.set(key, highlight)
        }),
        delete: vi.fn((key: string) => {
          mockHighlightsMap.delete(key)
        }),
        get: vi.fn((key: string) => mockHighlightsMap.get(key)),
        has: vi.fn((key: string) => mockHighlightsMap.has(key)),
      },
    }

    // 2. Mock window.Highlight constructor (W3C 标准中 Highlight 继承自 Set<Range>)
    class MockHighlight extends Set<Range> {
      constructor(...ranges: Range[]) {
        super(ranges)
      }
      get ranges(): Range[] {
        return Array.from(this)
      }
    }

    ;(globalThis as any).CSS = mockCSS
    ;(globalThis as any).Highlight = MockHighlight
    ;(window as any).CSS = mockCSS
    ;(window as any).Highlight = MockHighlight

    // 3. Clear DOM
    document.body.innerHTML = ""
  })

  afterEach(() => {
    document.body.innerHTML = ""
    vi.restoreAllMocks()
  })

  it("当画布容器缺失时安全早退并不抛出异常", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})

    const { result } = renderHook(() =>
      useEditorSearchHighlight({
        findText: "项目",
        currentMatchIndex: 0,
        canvasSelector: '[data-resume-canvas="true"]',
      })
    )

    expect(result.current.matches).toHaveLength(0)
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("未找到画布容器: [data-resume-canvas=\"true\"]")
    )
  })

  it("当画布容器存在时，能准确识别 DOM 文本节点中的匹配项并注册 CSS.highlights", () => {
    // 构造模拟真实简历画布
    const canvas = document.createElement("div")
    canvas.setAttribute("data-resume-canvas", "true")
    canvas.innerHTML = `
      <div class="work-block">
        <p>负责设计并主导了电商中台<strong>核心项目</strong>二期落地。</p>
        <p>该项目显著降低了跨仓库存周转耗时。</p>
      </div>
    `
    document.body.appendChild(canvas)

    const { result } = renderHook(() =>
      useEditorSearchHighlight({
        findText: "项目",
        currentMatchIndex: 0,
      })
    )

    // 总共两处“项目”
    expect(result.current.matches).toHaveLength(2)
    expect(result.current.matches[0].type).toBe("text")
    expect(result.current.matches[1].type).toBe("text")

    // 验证 CSS.highlights 注册了 search-results 与 search-result-active
    expect((CSS as any).highlights.set).toHaveBeenCalledWith(
      "search-results",
      expect.anything()
    )
    expect((CSS as any).highlights.set).toHaveBeenCalledWith(
      "search-result-active",
      expect.anything()
    )
  })

  it("同一文本节点内部出现多次命中时，charIndex 保持精确的 range.startOffset 严格单调递增", () => {
    const canvas = document.createElement("div")
    canvas.setAttribute("data-resume-canvas", "true")
    canvas.innerHTML = `
      <p>主导项目A架构设计，并在项目B中负责性能调优。</p>
    `
    document.body.appendChild(canvas)

    const { result } = renderHook(() =>
      useEditorSearchHighlight({
        findText: "项目",
        currentMatchIndex: 0,
      })
    )

    expect(result.current.matches).toHaveLength(2)
    const [first, second] = result.current.matches

    // 验证 charIndex 非 0，且按文档位置严格先后排序
    expect(first.charIndex).toBe(2)   // "主导项目A..." -> 索引 2
    expect(second.charIndex).toBe(12) // "...并在项目B..." -> 索引 12
    expect(second.charIndex).toBeGreaterThan(first.charIndex)
  })

  it("支持扫描 input 与 textarea 表单控件并正确分类（涵盖 text/email/tel 等类型）", () => {
    const canvas = document.createElement("div")
    canvas.setAttribute("data-resume-canvas", "true")
    canvas.innerHTML = `
      <div>
        <input type="text" value="电商项目主管" />
        <input type="email" value="project_lead@company.com" />
        <textarea>负责大型项目需求分析与原型设计</textarea>
      </div>
    `
    document.body.appendChild(canvas)

    const { result } = renderHook(() =>
      useEditorSearchHighlight({
        findText: "project",
        currentMatchIndex: 0,
      })
    )

    expect(result.current.matches).toHaveLength(1)
    expect(result.current.matches[0].type).toBe("input")
    expect(result.current.matches[0].text.toLowerCase()).toContain("project")
  })

  it("查找文本清空时自动注销高亮并清空匹配集", () => {
    const canvas = document.createElement("div")
    canvas.setAttribute("data-resume-canvas", "true")
    canvas.innerHTML = `<p>项目管理与推进</p>`
    document.body.appendChild(canvas)

    const { result, rerender } = renderHook(
      ({ text }) =>
        useEditorSearchHighlight({
          findText: text,
          currentMatchIndex: 0,
        }),
      { initialProps: { text: "项目" } }
    )

    expect(result.current.matches).toHaveLength(1)

    // 清空查找词
    rerender({ text: "" })

    expect(result.current.matches).toHaveLength(0)
    expect((CSS as any).highlights.delete).toHaveBeenCalledWith("search-results")
    expect((CSS as any).highlights.delete).toHaveBeenCalledWith("search-result-active")
  })

  it("查找文本由有命中变为完全无命中的文本时，同样彻底注销高亮并清空匹配集", () => {
    const canvas = document.createElement("div")
    canvas.setAttribute("data-resume-canvas", "true")
    canvas.innerHTML = `<p>项目管理与推进</p>`
    document.body.appendChild(canvas)

    const { result, rerender } = renderHook(
      ({ text }) =>
        useEditorSearchHighlight({
          findText: text,
          currentMatchIndex: 0,
        }),
      { initialProps: { text: "项目" } }
    )

    expect(result.current.matches).toHaveLength(1)

    // 变更为完全不匹配的词汇
    rerender({ text: "未命中的未知字符串xyz" })

    expect(result.current.matches).toHaveLength(0)
    expect((CSS as any).highlights.delete).toHaveBeenCalledWith("search-results")
    expect((CSS as any).highlights.delete).toHaveBeenCalledWith("search-result-active")
  })
})
