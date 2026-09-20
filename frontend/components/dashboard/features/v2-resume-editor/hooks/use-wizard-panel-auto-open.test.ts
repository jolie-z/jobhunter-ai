import { renderHook } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { useWizardPanelAutoOpen } from './use-wizard-panel-auto-open'
import type { WizardStep } from './use-ai-wizard'

function makeProps(overrides: Record<string, any> = {}) {
  return {
    wizardStep: undefined as WizardStep | undefined,
    hasWork: true,
    hasProjects: true,
    initialDraftWorkDone: false,
    initialDraftProjectDone: false,
    syncQueue: [] as string[],
    setPruneOpen: vi.fn(),
    setCompressOpen: vi.fn(),
    setWorkInitialDraftOpen: vi.fn(),
    setProjectInitialDraftOpen: vi.fn(),
    setManualSyncOpen: vi.fn(),
    ...overrides,
  }
}

describe('useWizardPanelAutoOpen', () => {
  it('进入 step1 时自动打开裁剪/折叠面板（迁移回归）', () => {
    const props = makeProps({ wizardStep: 'step1' })
    renderHook(() => useWizardPanelAutoOpen(props))
    expect(props.setPruneOpen).toHaveBeenCalledWith(true)
    expect(props.setCompressOpen).toHaveBeenCalledWith(true)
  })

  it('step1 期间板块内容变化不重开面板（裁剪应用后板块清空时保持关闭，与迁移前行为一致）', () => {
    const initial = makeProps({ wizardStep: 'step1', hasWork: true, hasProjects: true })
    const { rerender } = renderHook((p: any) => useWizardPanelAutoOpen(p), { initialProps: initial })
    expect(initial.setPruneOpen).toHaveBeenCalledTimes(1)

    rerender({ ...initial, hasProjects: false })
    expect(initial.setPruneOpen).toHaveBeenCalledTimes(1)
    expect(initial.setCompressOpen).toHaveBeenCalledTimes(1)
  })

  it('step2 板块非空时自动打开对应初改面板（迁移回归）', () => {
    const props = makeProps({ wizardStep: 'step2', hasWork: true, hasProjects: true })
    renderHook(() => useWizardPanelAutoOpen(props))
    expect(props.setWorkInitialDraftOpen).toHaveBeenCalledWith(true)
    expect(props.setProjectInitialDraftOpen).toHaveBeenCalledWith(true)
  })

  it('step2 空板块不自动打开初改面板（空板块免疫：工作空/项目非空的半空场景）', () => {
    const props = makeProps({ wizardStep: 'step2', hasWork: false, hasProjects: true })
    renderHook(() => useWizardPanelAutoOpen(props))
    expect(props.setWorkInitialDraftOpen).not.toHaveBeenCalled()
    expect(props.setProjectInitialDraftOpen).toHaveBeenCalledWith(true)
  })

  it('step2 双空板块时两侧面板都不打开', () => {
    const props = makeProps({ wizardStep: 'step2', hasWork: false, hasProjects: false })
    renderHook(() => useWizardPanelAutoOpen(props))
    expect(props.setWorkInitialDraftOpen).not.toHaveBeenCalled()
    expect(props.setProjectInitialDraftOpen).not.toHaveBeenCalled()
  })

  it('step2 期间板块由空变非空时自动恢复打开（双向自愈，无 sticky skip 状态）', () => {
    const initial = makeProps({ wizardStep: 'step2', hasWork: false, hasProjects: false })
    const { rerender } = renderHook((p: any) => useWizardPanelAutoOpen(p), { initialProps: initial })
    expect(initial.setWorkInitialDraftOpen).not.toHaveBeenCalled()
    expect(initial.setProjectInitialDraftOpen).not.toHaveBeenCalled()

    rerender({ ...initial, hasWork: true, hasProjects: true })
    expect(initial.setWorkInitialDraftOpen).toHaveBeenCalledWith(true)
    expect(initial.setProjectInitialDraftOpen).toHaveBeenCalledWith(true)
  })

  it('step2 已完成初改（Done）的板块，进入时不再自动打开其面板', () => {
    const props = makeProps({ wizardStep: 'step2', hasWork: true, hasProjects: true, initialDraftWorkDone: true })
    renderHook(() => useWizardPanelAutoOpen(props))
    expect(props.setWorkInitialDraftOpen).not.toHaveBeenCalled()
    expect(props.setProjectInitialDraftOpen).toHaveBeenCalledWith(true)
  })

  it('step2 期间另一板块内容翻转时，已 Done 板块的面板不被连带重开（agy-review P1 修复回归）', () => {
    const initial = makeProps({ wizardStep: 'step2', hasWork: true, hasProjects: false, initialDraftWorkDone: true })
    const { rerender } = renderHook((p: any) => useWizardPanelAutoOpen(p), { initialProps: initial })
    expect(initial.setWorkInitialDraftOpen).not.toHaveBeenCalled()

    // 项目板块由空变非空（如回收站恢复）：effect 重跑，但工作侧已 Done，不得重开
    rerender({ ...initial, hasProjects: true })
    expect(initial.setWorkInitialDraftOpen).not.toHaveBeenCalled()
    expect(initial.setProjectInitialDraftOpen).toHaveBeenCalledWith(true)
  })

  it('step2 初改完成（Done 翻转）本身不触发面板重开', () => {
    const initial = makeProps({ wizardStep: 'step2', hasWork: true, hasProjects: true })
    const { rerender } = renderHook((p: any) => useWizardPanelAutoOpen(p), { initialProps: initial })
    expect(initial.setWorkInitialDraftOpen).toHaveBeenCalledTimes(1)

    rerender({ ...initial, initialDraftWorkDone: true })
    expect(initial.setWorkInitialDraftOpen).toHaveBeenCalledTimes(1)
  })

  it('step2 期间板块内容不变时 effect 重跑（如 syncQueue 变化），手动关闭的未完成板块不被连带重开（边沿化）', () => {
    const initial = makeProps({ wizardStep: 'step2', hasWork: true, hasProjects: true })
    const { rerender } = renderHook((p: any) => useWizardPanelAutoOpen(p), { initialProps: initial })
    expect(initial.setWorkInitialDraftOpen).toHaveBeenCalledTimes(1)

    // 用户手动关闭后（setter 状态在父层，此处只验证 effect 重跑不重复触发），无关依赖变化导致重跑
    rerender({ ...initial, syncQueue: ['summary'] })
    expect(initial.setWorkInitialDraftOpen).toHaveBeenCalledTimes(1)
    expect(initial.setProjectInitialDraftOpen).toHaveBeenCalledTimes(1)
  })

  it('step5 队列非空时打开前 3 个联动面板（迁移回归）', () => {
    const props = makeProps({ wizardStep: 'step5', syncQueue: ['summary', 'additional', 'edu-0', 'edu-1'] })
    renderHook(() => useWizardPanelAutoOpen(props))
    expect(props.setManualSyncOpen).toHaveBeenCalledTimes(1)
    const updater = props.setManualSyncOpen.mock.calls[0][0]
    expect(updater({})).toEqual({ summary: true, additional: true, 'edu-0': true })
  })

  it('step5 队列为空时不打开任何联动面板', () => {
    const props = makeProps({ wizardStep: 'step5', syncQueue: [] })
    renderHook(() => useWizardPanelAutoOpen(props))
    expect(props.setManualSyncOpen).not.toHaveBeenCalled()
  })

  it('非向导步骤不触发任何面板打开', () => {
    const props = makeProps({ wizardStep: 'step3' })
    renderHook(() => useWizardPanelAutoOpen(props))
    expect(props.setPruneOpen).not.toHaveBeenCalled()
    expect(props.setCompressOpen).not.toHaveBeenCalled()
    expect(props.setWorkInitialDraftOpen).not.toHaveBeenCalled()
    expect(props.setProjectInitialDraftOpen).not.toHaveBeenCalled()
    expect(props.setManualSyncOpen).not.toHaveBeenCalled()
  })
})
