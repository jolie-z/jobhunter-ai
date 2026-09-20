import { render, screen, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { WizardStatusPanel } from './wizard-status-panel'
import { useResumeV2Store } from '@/hooks/use-resume-v2-store'
import { DEFAULT_WIZARD_PROGRESS, type WizardProgress } from '../hooks/use-ai-wizard'

// 三态实时推导（W-2 空板块免疫）：step2 队列项 Done→已完成 / !Done且板块空→已跳过（板块为空）/ 否则处理中；
// 「进入第三步」门禁改为 (!hasProjects || Done) && (!hasWork || Done)

function makeProps(overrides: Record<string, any> = {}) {
  return {
    wizardStep: 'step2' as const,
    wizardProgress: { ...DEFAULT_WIZARD_PROGRESS } as WizardProgress,
    wizardHidden: false,
    setWizardStep: vi.fn(),
    setWizardProgress: vi.fn(),
    setWizardHidden: vi.fn(),
    grillPanelOpen: false,
    setGrillPanelOpen: vi.fn(),
    grillQueue: [] as string[],
    setGrillQueue: vi.fn(),
    atsQueue: [] as string[],
    syncQueue: [] as string[],
    grillSuggestions: [],
    isLoadingGrillSuggestions: false,
    handleStartGrillQueue: vi.fn(),
    handleSaveResume: vi.fn(),
    wizardStorageKey: 'wizard_test',
    saveWizardProgress: vi.fn(),
    grillSectionsList: [],
    sectionTitles: {} as Record<string, string>,
    handleLocate: vi.fn(),
    ...overrides,
  }
}

describe('WizardStatusPanel step2 空板块免疫三态推导', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('板块为空且未 Done → 显示「已跳过（板块为空）」，进入第三步门禁放行', () => {
    useResumeV2Store.getState().setResumeData({
      personalInfo: { name: 'T' } as any,
      workExperience: [],
      personalProjects: [],
      education: [],
      additional: { technicalSkills: [], languages: [], certificationsTraining: [] },
      moduleOrder: ["summary", "workExperience", "personalProjects", "education", "additional"],
      moduleTitles: {},
      customModules: {},
    } as any)

    render(<WizardStatusPanel {...makeProps()} />)

    expect(screen.getAllByText('已跳过（板块为空）').length).toBe(2)
    const gate = screen.getByRole('button', { name: /进入第三步/ }) as HTMLButtonElement
    expect(gate.disabled).toBe(false)
  })

  it('板块非空且未 Done → 显示「处理中」，门禁保持锁定', () => {
    useResumeV2Store.getState().setResumeData({
      personalInfo: { name: 'T' } as any,
      workExperience: [{ title: 'Job 1', description: ['d'] } as any],
      personalProjects: [{ name: 'Proj 1', description: ['d'] } as any],
      education: [],
      additional: { technicalSkills: [], languages: [], certificationsTraining: [] },
      moduleOrder: ["summary", "workExperience", "personalProjects", "education", "additional"],
      moduleTitles: {},
      customModules: {},
    } as any)

    render(<WizardStatusPanel {...makeProps()} />)

    expect(screen.getAllByText('处理中').length).toBe(2)
    const gate = screen.getByRole('button', { name: /进入第三步/ }) as HTMLButtonElement
    expect(gate.disabled).toBe(true)
  })

  it('板块非空且已 Done → 显示「已完成」，门禁放行', () => {
    useResumeV2Store.getState().setResumeData({
      personalInfo: { name: 'T' } as any,
      workExperience: [{ title: 'Job 1', description: ['d'] } as any],
      personalProjects: [{ name: 'Proj 1', description: ['d'] } as any],
      education: [],
      additional: { technicalSkills: [], languages: [], certificationsTraining: [] },
      moduleOrder: ["summary", "workExperience", "personalProjects", "education", "additional"],
      moduleTitles: {},
      customModules: {},
    } as any)

    render(<WizardStatusPanel {...makeProps({
      wizardProgress: { ...DEFAULT_WIZARD_PROGRESS, initialDraftWorkDone: true, initialDraftProjectDone: true },
    })} />)

    expect(screen.getAllByText('已完成').length).toBe(2)
    const gate = screen.getByRole('button', { name: /进入第三步/ }) as HTMLButtonElement
    expect(gate.disabled).toBe(false)
  })

  it('板块由空变非空 → 队列从「已跳过」实时翻回「处理中」，门禁自动重新锁上', () => {
    useResumeV2Store.getState().setResumeData({
      personalInfo: { name: 'T' } as any,
      workExperience: [],
      personalProjects: [],
      education: [],
      additional: { technicalSkills: [], languages: [], certificationsTraining: [] },
      moduleOrder: ["summary", "workExperience", "personalProjects", "education", "additional"],
      moduleTitles: {},
      customModules: {},
    } as any)

    const { rerender } = render(<WizardStatusPanel {...makeProps()} />)
    expect(screen.getAllByText('已跳过（板块为空）').length).toBe(2)
    expect((screen.getByRole('button', { name: /进入第三步/ }) as HTMLButtonElement).disabled).toBe(false)

    // 向导进行中板块重新有内容（如回收站恢复）：实时推导自动重新锁门
    act(() => {
      useResumeV2Store.getState().setResumeData({
        ...useResumeV2Store.getState().resumeData!,
        workExperience: [{ title: 'New Job', description: ['d'] } as any],
        personalProjects: [{ name: 'New Proj', description: ['d'] } as any],
      } as any)
    })
    rerender(<WizardStatusPanel {...makeProps()} />)

    expect(screen.queryByText('已跳过（板块为空）')).toBeNull()
    expect(screen.getAllByText('处理中').length).toBe(2)
    expect((screen.getByRole('button', { name: /进入第三步/ }) as HTMLButtonElement).disabled).toBe(true)
  })
})
