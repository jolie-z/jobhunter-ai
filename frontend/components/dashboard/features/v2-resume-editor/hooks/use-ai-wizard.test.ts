import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useAiWizard } from './use-ai-wizard'
import { useResumeV2Store } from '@/hooks/use-resume-v2-store'

// Mock fetch for Step 3
global.fetch = vi.fn() as any;

describe('useAiWizard Full 6 Steps Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    
    const store = useResumeV2Store.getState()
    store.setResumeData({
      personalInfo: { name: 'Test User' } as any,
      summary: '',
      workExperience: [
        { title: 'Job 1', description: ['desc1'] } as any,
        { title: 'Job 2', description: ['desc2'] } as any
      ],
      education: [
        { school: 'School 1' } as any
      ],
      personalProjects: [
        { name: 'Proj 1', description: ['desc1'] } as any,
        { name: 'Proj 2', description: ['desc2'] } as any,
        { name: 'Proj 3', description: ['desc3'] } as any
      ],
      additional: { technicalSkills: ['skill 1'], languages: [], certificationsTraining: [] },
      moduleOrder: ["summary", "workExperience", "personalProjects", "education", "additional", "custom_1"],
      moduleTitles: {},
      customModules: {
        "custom_1": [{ title: 'Custom 1' } as any]
      }
    })
  })

  describe('Step 1: Prune and Compress', () => {
    it('should complete when both prune and compress are done, even with partial crop and recycle bin restore', () => {
      const { result } = renderHook(() => useAiWizard(null))

      act(() => { result.current.actions.handleStartWizard() })
      
      expect(result.current.state.wizardStep).toBe('step1')
      expect(result.current.state.wizardProgress.pruneDone).toBe(false)
      expect(result.current.state.wizardProgress.compressDone).toBe(false)

      act(() => {
        const store = useResumeV2Store.getState()
        store.archiveProject(1) 
        result.current.actions.handleWizardComplete('prune')
      })

      expect(result.current.state.wizardProgress.pruneDone).toBe(true)

      act(() => {
        const store = useResumeV2Store.getState()
        store.restoreProject(0) 
      })

      const stateAfterRestore = useResumeV2Store.getState()
      expect(stateAfterRestore.resumeData?.personalProjects.length).toBe(3)
      expect(result.current.state.wizardProgress.pruneDone).toBe(true)

      act(() => { result.current.actions.handleWizardComplete('compress') })

      expect(result.current.state.wizardProgress.compressDone).toBe(true)
      const isStep2LitUp = result.current.state.wizardProgress.pruneDone && result.current.state.wizardProgress.compressDone
      expect(isStep2LitUp).toBe(true)
    })

    it('Recycle bin restore logic should correctly map indexes after filtering', () => {
      act(() => {
        const store = useResumeV2Store.getState()
        store.archiveProject(2) // Proj 3
        store.archiveProject(0) // Proj 1
      })

      const archivedBefore = useResumeV2Store.getState().resumeData?.archivedProjects || []
      expect(archivedBefore.length).toBe(2)
      expect(archivedBefore[0].name).toBe('Proj 3')
      expect(archivedBefore[1].name).toBe('Proj 1')

      act(() => {
        const idsToRestore = ['0']
        const sortedIds = idsToRestore.map(id => parseInt(id)).sort((a, b) => b - a)
        const store = useResumeV2Store.getState()
        sortedIds.forEach(idx => store.restoreProject(idx))
      })

      const archivedAfter = useResumeV2Store.getState().resumeData?.archivedProjects || []
      expect(archivedAfter.length).toBe(1)
      expect(archivedAfter[0].name).toBe('Proj 1')

      const projectsAfter = useResumeV2Store.getState().resumeData?.personalProjects || []
      expect(projectsAfter.length).toBe(2)
      expect(projectsAfter[1].name).toBe('Proj 3') 
    })
  })

  describe('Step 2: Initial Draft Rewrite', () => {
    it('should complete when initialDraftProject and initialDraftWork are both done', () => {
      const { result } = renderHook(() => useAiWizard(null))
      
      act(() => { result.current.actions.handleStartWizard() })
      act(() => { result.current.actions.setWizardStep('step2') })
      
      expect(result.current.state.wizardProgress.initialDraftProjectDone).toBe(false)
      expect(result.current.state.wizardProgress.initialDraftWorkDone).toBe(false)

      act(() => { result.current.actions.handleWizardComplete('initial_draft_project') })
      expect(result.current.state.wizardProgress.initialDraftProjectDone).toBe(true)
      
      act(() => { result.current.actions.handleWizardComplete('initial_draft_work') })
      expect(result.current.state.wizardProgress.initialDraftWorkDone).toBe(true)
      
      const isStep3LitUp = result.current.state.wizardProgress.initialDraftProjectDone && result.current.state.wizardProgress.initialDraftWorkDone
      expect(isStep3LitUp).toBe(true)
    })
  })

  describe('Step 3: Grill (Deep AI Interview)', () => {
    it('should auto-open grill panel when entering step3', () => {
      const { result } = renderHook(() => useAiWizard(null))

      act(() => { result.current.actions.handleStartWizard() })
      expect(result.current.state.grillPanelOpen).toBe(false)

      act(() => { result.current.actions.setWizardStep('step3') })
      expect(result.current.state.grillPanelOpen).toBe(true)
    })

    it('should complete immediately if there are no suggestions or user skips', () => {
      const { result } = renderHook(() => useAiWizard(null))
      
      act(() => { result.current.actions.handleStartWizard() })
      act(() => { result.current.actions.setWizardStep('step3') })
      
      expect(result.current.state.wizardProgress.grillDone).toBe(false)
      
      act(() => { result.current.actions.handleStartGrillQueue([]) })
      
      expect(result.current.state.wizardProgress.grillDone).toBe(true)
    })

    it('should process grill items one by one and complete when queue is empty', () => {
      const { result } = renderHook(() => useAiWizard(null))

      act(() => { result.current.actions.handleStartWizard() })
      act(() => { result.current.actions.setWizardStep('step3') })

      act(() => { result.current.actions.handleStartGrillQueue(['project-1', 'work-0']) })

      expect(result.current.state.grillQueue).toEqual(['project-1', 'work-0'])
      expect(result.current.state.wizardProgress.grillDone).toBe(false)

      act(() => { result.current.actions.handleWizardComplete('grill_item_done', 'project-1') })
      expect(result.current.state.grillQueue).toEqual(['work-0'])
      expect(result.current.state.grillQueue[0]).toBe('work-0')
      expect(result.current.state.wizardProgress.grillDone).toBe(false)

      act(() => { result.current.actions.handleWizardComplete('grill_item_done', 'work-0') })
      expect(result.current.state.grillQueue).toEqual([])
      expect(result.current.state.wizardProgress.grillDone).toBe(true)
    })

    it('should close grillPanelOpen when grill queue starts so next item can auto-open', () => {
      const { result } = renderHook(() => useAiWizard(null))

      act(() => { result.current.actions.handleStartWizard() })
      act(() => { result.current.actions.setWizardStep('step3') })
      expect(result.current.state.grillPanelOpen).toBe(true)

      // User selects items and starts grill queue
      act(() => { result.current.actions.handleStartGrillQueue(['work-0', 'project-1']) })
      expect(result.current.state.grillPanelOpen).toBe(false)
      expect(result.current.state.grillQueue).toEqual(['work-0', 'project-1'])

      // After completing first item, queue updates for next item
      act(() => { result.current.actions.handleWizardComplete('grill_item_done', 'work-0') })
      expect(result.current.state.grillQueue[0]).toBe('project-1')
      expect(result.current.state.grillQueue.length).toBe(1)
    })
  })

  describe('Step 4: ATS Evaluation', () => {
    it('should auto-initialize atsQueue based on work and projects', () => {
      const { result } = renderHook(() => useAiWizard(null))
      
      act(() => { result.current.actions.handleStartWizard() })
      
      // Navigate to step 4 to trigger initialization
      act(() => { result.current.actions.setWizardStep('step4') })
      
      expect(result.current.state.atsQueue).toEqual([
        'work-0', 'work-1',
        'project-0', 'project-1', 'project-2'
      ])
      
      expect(result.current.state.wizardProgress.atsDone).toBe(false)
    })

    it('should process ats items and complete when queue is empty (including cancel)', () => {
      const { result } = renderHook(() => useAiWizard(null))
      
      act(() => { result.current.actions.handleStartWizard() })
      act(() => { result.current.actions.setWizardStep('step4') })
      
      // We have 5 items in atsQueue. Let's process/cancel them all.
      act(() => { result.current.actions.handleWizardComplete('ats_item_done', 'work-0') })
      act(() => { result.current.actions.handleWizardComplete('ats_item_done', 'work-1') })
      act(() => { result.current.actions.handleWizardComplete('ats_item_cancel', 'project-0') }) // cancel shouldn't mark step complete early, but removes it
      act(() => { result.current.actions.handleWizardComplete('ats_item_done', 'project-1') })
      
      expect(result.current.state.wizardProgress.atsDone).toBe(false)
      
      act(() => { result.current.actions.handleWizardComplete('ats_item_done', 'project-2') })
      expect(result.current.state.wizardProgress.atsDone).toBe(true)
    })

    it('should immediately complete if resume has no work or projects', () => {
      act(() => {
        const store = useResumeV2Store.getState()
        store.setResumeData({
          ...store.resumeData!,
          workExperience: [],
          personalProjects: []
        })
      })

      const { result } = renderHook(() => useAiWizard(null))
      
      act(() => { result.current.actions.handleStartWizard() })
      act(() => { result.current.actions.setWizardStep('step4') })
      
      expect(result.current.state.atsQueue).toEqual([])
      expect(result.current.state.wizardProgress.atsDone).toBe(true)
    })
  })

  describe('Step 5: Global Sync (Sync Queue)', () => {
    it('should auto-initialize syncQueue based on all enabled modules', () => {
      const { result } = renderHook(() => useAiWizard(null))
      
      act(() => { result.current.actions.handleStartWizard() })
      act(() => { result.current.actions.setWizardStep('step5') })
      
      // 产品设定：自定义模块（custom_ 前缀）不参与第五步联动更新
      expect(result.current.state.syncQueue).toEqual([
        'summary',
        'additional',
        'edu-0'
      ])
      
      expect(result.current.state.wizardProgress.syncDone).toBe(false)
    })

    it('should process sync items and complete when queue is empty', () => {
      const { result } = renderHook(() => useAiWizard(null))
      
      act(() => { result.current.actions.handleStartWizard() })
      act(() => { result.current.actions.setWizardStep('step5') })
      
      act(() => { result.current.actions.handleWizardComplete('sync_item_done', 'summary') })
      act(() => { result.current.actions.handleWizardComplete('sync_item_cancel', 'additional') })
      act(() => { result.current.actions.handleWizardComplete('sync_item_done', 'edu-0') })
      
      expect(result.current.state.wizardProgress.syncDone).toBe(true)
    })
  })

  describe('Step 6: Final Save', () => {
    it('should complete final save step', () => {
      const { result } = renderHook(() => useAiWizard(null))
      
      act(() => { result.current.actions.handleStartWizard() })
      act(() => { result.current.actions.setWizardStep('step6') })
      
      expect(result.current.state.wizardProgress.savedDone).toBe(false)
      
      act(() => { result.current.actions.handleWizardComplete('saved') })
      
      expect(result.current.state.wizardProgress.savedDone).toBe(true)
    })
  })
})
