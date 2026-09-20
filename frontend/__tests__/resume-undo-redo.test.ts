import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { useResumeUndoRedo } from "../components/dashboard/features/v2-resume-editor/hooks/use-resume-undo-redo"
import { useResumeV2Store, createEmptyResume } from "@/hooks/use-resume-v2-store"
import type { ResumeDataV2 } from "@/types/resume"

describe("useResumeUndoRedo 撤销与重做历史栈管理（Excel 标准规范对齐）", () => {
  let initialResume: ResumeDataV2

  beforeEach(() => {
    vi.useFakeTimers()
    initialResume = createEmptyResume()
    initialResume.personalInfo.name = "张三初始"
    initialResume.summary = "初始个人总结"
    useResumeV2Store.getState().setResumeData(initialResume)
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    useResumeV2Store.getState().setResumeData(null)
  })

  describe("Excel 默认就绪态与物理交互门禁 (mode: auto)", () => {
    it("1. 初始状态下 canUndo 与 canRedo 均为 false (双灰)", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(false)
    })

    it("2. 核心缺陷治愈：后台异步补水（如拉取母本头像）绝不提前虚亮撤销按钮", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      // 模拟后台异步网络请求返回，静默注入母本头像
      act(() => {
        useResumeV2Store.getState().updatePersonalInfo({ avatar_url: "https://feishu.cn/avatar.png" })
      })

      // 验证：无物理交互事件发生，即使 store 变化，撤销按钮依然保持置灰！
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(false)

      // 前进 500ms（防抖周期），依然不压栈、不虚亮
      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(false)
    })

    it("3. 用户发生真实打字输入 (DOM input 事件) 后，即刻点亮撤销按钮", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      // 模拟用户在真实 input 输入框中按键打字
      act(() => {
        window.dispatchEvent(new Event("input"))
        useResumeV2Store.getState().updatePersonalInfo({ name: "张三修改" })
      })

      // 物理门禁捕获后，立即识别为有效修改并点亮撤销
      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(false)

      // 执行撤销，回退到初始状态
      act(() => {
        result.current.undo()
      })

      // 严格对齐 Excel：回滚至最初状态后，撤销变灰，重做点亮！
      expect(useResumeV2Store.getState().resumeData?.personalInfo.name).toBe("张三初始")
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)

      // 执行重做，恢复修改
      act(() => {
        result.current.redo()
      })
      expect(useResumeV2Store.getState().resumeData?.personalInfo.name).toBe("张三修改")
      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(false)
    })

    it("3b. 用户发生点击类交互 (DOM click / pointerdown) 触发修改后，即刻点亮撤销按钮", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      // 模拟用户点击删除或添加卡片按钮
      act(() => {
        window.dispatchEvent(new MouseEvent("click", { bubbles: true }))
        useResumeV2Store.getState().updateSummary("点击操作修改总结")
      })

      // 物理点击门禁生效，点亮撤销
      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(false)

      act(() => {
        result.current.undo()
      })
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("初始个人总结")
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)
    })

    it("3c. 组合时序严格验证：后台注入 avatar -> 用户打字 -> undo，精准回滚打字且安全保留 avatar", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      // 1. 后台异步静默注入头像
      act(() => {
        useResumeV2Store.getState().updatePersonalInfo({ avatar_url: "https://feishu.cn/avatar.png" })
      })
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(false)

      // 2. 用户打字修改姓名
      act(() => {
        window.dispatchEvent(new Event("input"))
        useResumeV2Store.getState().updatePersonalInfo({ name: "张三打字中" })
      })
      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(false)

      // 3. 点击撤销
      act(() => {
        result.current.undo()
      })

      // 严格断言：姓名精准回退到初始状态，且头像完整安全保留！
      expect(useResumeV2Store.getState().resumeData?.personalInfo.name).toBe("张三初始")
      expect(useResumeV2Store.getState().resumeData?.personalInfo.avatar_url).toBe("https://feishu.cn/avatar.png")
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)

      // 4. 防抖延迟到期断言：挂起的防抖已被彻底清理，绝不会再次无故压栈！
      act(() => {
        vi.advanceTimersByTime(600)
      })
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)
    })

    it("3d. 撤销回退状态下用户发起新物理输入，重做栈立即清空并变灰 (Excel 规范)", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      // 用户打字并防抖落栈
      act(() => {
        window.dispatchEvent(new Event("input"))
        useResumeV2Store.getState().updatePersonalInfo({ name: "第一次修改" })
      })
      act(() => {
        vi.advanceTimersByTime(500)
      })
      expect(result.current.canUndo).toBe(true)

      // 撤销回退
      act(() => {
        result.current.undo()
      })
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)

      // 在撤销态键入新内容（产生新分支）
      act(() => {
        window.dispatchEvent(new Event("input"))
        useResumeV2Store.getState().updatePersonalInfo({ name: "新分支打字" })
      })

      // 严格对齐 Excel：重做栈立即被抹除，重做按钮变灰！
      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(false)
    })

    it("3e. 重做至最新状态后，重做按钮恢复置灰 (Excel 规范)", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      act(() => {
        window.dispatchEvent(new Event("input"))
        useResumeV2Store.getState().updateSummary("修改总结")
      })
      act(() => {
        vi.advanceTimersByTime(500)
      })

      // 撤销
      act(() => {
        result.current.undo()
      })
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)

      // 重做到底
      act(() => {
        result.current.redo()
      })

      // 恢复修改状态，重做耗尽置灰，撤销点亮
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("修改总结")
      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(false)
    })

    it("3f. 净零编辑（打字后删回原样），防抖到期自动回退置灰 (Excel 规范)", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      // 1. 用户物理输入打字
      act(() => {
        window.dispatchEvent(new Event("input"))
        useResumeV2Store.getState().updatePersonalInfo({ name: "张三初始_修改" })
      })
      // 正在打字期间：即刻点亮撤销
      expect(result.current.canUndo).toBe(true)

      // 2. 在防抖期内删回原样（净零编辑）
      act(() => {
        window.dispatchEvent(new Event("input"))
        useResumeV2Store.getState().updatePersonalInfo({ name: "张三初始" })
      })

      // 3. 推进防抖计时器到期
      act(() => {
        vi.advanceTimersByTime(500)
      })

      // 4. 关键验证：由于内容与基准完全一致（净零），不产生历史，防抖结算后撤销按钮必须立刻自动回灰！
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(false)
    })

    it("3g. 离散动作 (takeSnapshot + 物理点击) 在防抖期内撤销，必须彻底回退到底且撤销置灰", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      act(() => {
        result.current.takeSnapshot()
        window.dispatchEvent(new Event("click"))
        useResumeV2Store.getState().updateSummary("离散替换后的总结")
      })
      expect(result.current.canUndo).toBe(true)

      // 在防抖期内执行撤销
      act(() => {
        result.current.undo()
      })

      // 严格断言：立即回滚到初始基准，且历史栈冗余节点彻底弹出，撤销变灰，重做点亮
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("初始个人总结")
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)
    })

    it("3h. 等值空触发守卫：内容深度相等时绝不视为新分支，绝不摧毁重做栈", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      // 先完成一次正常修改并撤销，建立可重做状态
      act(() => {
        window.dispatchEvent(new Event("input"))
        useResumeV2Store.getState().updateSummary("修改后内容")
      })
      act(() => {
        vi.advanceTimersByTime(500)
      })
      act(() => {
        result.current.undo()
      })
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)

      // 模拟外部空触发（写入与当前基准一模一样的对象）
      act(() => {
        window.dispatchEvent(new Event("click"))
        const currentData = useResumeV2Store.getState().resumeData
        useResumeV2Store.getState().setResumeData(JSON.parse(JSON.stringify(currentData)))
      })

      // 验证：等值早退成功生效，未被误判为新编辑，重做栈完好保留！
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)
    })

    it("3i. redo 判空前置保护：无重做历史时调用 redo 绝不误杀用户正在打字的防抖", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "auto" })
      )

      // 用户正在输入
      act(() => {
        window.dispatchEvent(new Event("input"))
        useResumeV2Store.getState().updateSummary("正在打字中")
      })
      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(false)

      // 误触发了重做快捷键
      act(() => {
        result.current.redo()
      })

      // 验证：打字状态与 pending 未被破坏，推进防抖后成功固化
      expect(result.current.canUndo).toBe(true)
      act(() => {
        vi.advanceTimersByTime(500)
      })
      expect(result.current.canUndo).toBe(true)
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("正在打字中")
    })
  })

  describe("核心历史栈流转与边界对齐 (mode: always-record)", () => {
    it("4. 数据变更后即刻点亮 canUndo，且 undo 能精确回滚至初始状态，redo 能恢复", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "always-record" })
      )

      // 模拟用户修改了总结
      act(() => {
        useResumeV2Store.getState().updateSummary("修改后的个人总结")
      })

      // 修改产生后已即刻具备撤销能力，无需被动苦等防抖
      expect(result.current.canUndo).toBe(true)

      // 前进 500ms，防抖到期正式固化基准
      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(false)
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("修改后的个人总结")

      // 执行撤销
      act(() => {
        result.current.undo()
      })

      // 回退到初始状态
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("初始个人总结")
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)

      // 执行重做
      act(() => {
        result.current.redo()
      })

      // 重新恢复到修改后的状态
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("修改后的个人总结")
      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(false)
    })

    it("5. 核心边界突破：首次修改在防抖期内按 undo 能立即撤销并进入 future", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "always-record" })
      )

      // 首次打字修改姓名
      act(() => {
        useResumeV2Store.getState().updatePersonalInfo({ name: "张三打字中" })
      })

      // 仅过了 100ms（防抖远未到期），用户立即点击撤销
      act(() => {
        vi.advanceTimersByTime(100)
        result.current.undo()
      })

      // 验证立即回退回初始姓名，且可重做
      expect(useResumeV2Store.getState().resumeData?.personalInfo.name).toBe("张三初始")
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)

      // 点击重做，能准确找回打字中的姓名
      act(() => {
        result.current.redo()
      })
      expect(useResumeV2Store.getState().resumeData?.personalInfo.name).toBe("张三打字中")
    })

    it("6. 跳步防丢版本测试：S0 -> S1(到期) -> S2(防抖期内撤销)，精准回退至 S1", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "always-record" })
      )

      // S0 -> S1 并到期确认
      act(() => {
        useResumeV2Store.getState().updateSummary("版本S1")
      })
      act(() => {
        vi.advanceTimersByTime(500)
      })
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("版本S1")

      // S1 -> S2，在防抖期内点击撤销
      act(() => {
        useResumeV2Store.getState().updateSummary("版本S2未到期")
      })
      act(() => {
        vi.advanceTimersByTime(200)
        result.current.undo()
      })

      // 严密断言：必须精确回退到 S1，绝不能跳步丢失 S1 直接退回 S0
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("版本S1")
      expect(result.current.canUndo).toBe(true)
      expect(result.current.canRedo).toBe(true)

      // 再次撤销，回退到 S0
      act(() => {
        result.current.undo()
      })
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("初始个人总结")
    })

    it("7. 离散动作 takeSnapshot 能立即沉淀历史节点", () => {
      const { result } = renderHook(() =>
        useResumeUndoRedo({ resumeKey: "job-1", debounceMs: 500, mode: "always-record" })
      )

      // 离散操作：模拟查找替换
      act(() => {
        result.current.takeSnapshot()
        useResumeV2Store.getState().updateSummary("全部替换后的新总结")
      })

      // 无需等待 500ms 防抖，已即刻具备撤销能力
      expect(result.current.canUndo).toBe(true)

      act(() => {
        result.current.undo()
      })
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("初始个人总结")
      // 关键断言：回滚到底后撤销必须置灰，重做必须点亮（绝无幻影历史残留）
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(true)
    })

    it("8. 切换 resumeKey 时显式清空历史栈，杜绝跨简历污染", () => {
      const { result, rerender } = renderHook(
        ({ key }) => useResumeUndoRedo({ resumeKey: key, debounceMs: 500, mode: "always-record" }),
        { initialProps: { key: "resume-A" } }
      )

      // 在简历 A 中产生历史
      act(() => {
        useResumeV2Store.getState().updateSummary("简历A修改")
      })
      act(() => {
        vi.advanceTimersByTime(500)
      })
      expect(result.current.canUndo).toBe(true)

      // 切换到简历 B（同步场景）
      const resumeB = createEmptyResume()
      resumeB.summary = "简历B初始总结"
      useResumeV2Store.getState().setResumeData(resumeB)

      rerender({ key: "resume-B" })

      // 历史栈必须彻底重置清空
      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(false)
    })

    it("9. 突破异步加载边界：先切换 resumeKey，再异步载入简历数据，绝不误入编辑栈", () => {
      const { result, rerender } = renderHook(
        ({ key }) => useResumeUndoRedo({ resumeKey: key, debounceMs: 500, mode: "always-record" }),
        { initialProps: { key: "resume-old" } }
      )

      // 产生历史
      act(() => {
        useResumeV2Store.getState().updateSummary("旧简历修改")
        vi.advanceTimersByTime(500)
      })
      expect(result.current.canUndo).toBe(true)

      // 1. 切换到新简历 key（此时 store 还是旧数据）
      rerender({ key: "resume-new" })
      expect(result.current.canUndo).toBe(false)

      // 2. 模拟网络请求延迟后异步将新简历装入 store
      act(() => {
        vi.advanceTimersByTime(200)
        const asyncNewResume = createEmptyResume()
        asyncNewResume.personalInfo.name = "李四异步新简历"
        useResumeV2Store.getState().setResumeData(asyncNewResume)
      })

      // 3. 经过防抖期，新简历必须被作为基准，绝不能误判为用户编辑而入栈
      act(() => {
        vi.advanceTimersByTime(600)
      })

      expect(result.current.canUndo).toBe(false)
      expect(result.current.canRedo).toBe(false)
      expect(useResumeV2Store.getState().resumeData?.personalInfo.name).toBe("李四异步新简历")

      // 4. 用户在新简历上继续编辑，撤销重做机制继续发挥作用
      act(() => {
        useResumeV2Store.getState().updateSummary("新简历二次修改")
      })
      expect(result.current.canUndo).toBe(true)

      act(() => {
        vi.advanceTimersByTime(500)
        result.current.undo()
      })
      expect(useResumeV2Store.getState().resumeData?.summary).toBe("")
      expect(result.current.canRedo).toBe(true)
    })
  })
})
