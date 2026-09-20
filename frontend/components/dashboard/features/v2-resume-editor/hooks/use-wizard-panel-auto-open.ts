import { useEffect, useRef } from "react"
import type { WizardStep } from "./use-ai-wizard"

interface UseWizardPanelAutoOpenParams {
  wizardStep?: WizardStep
  /** 工作经历板块是否非空（实时读 store，空板块免疫初改面板自动打开） */
  hasWork: boolean
  /** 项目经历板块是否非空 */
  hasProjects: boolean
  /** 工作初改是否已完成（已完成板块不因板块内容翻转被重新自动打开） */
  initialDraftWorkDone: boolean
  /** 项目初改是否已完成 */
  initialDraftProjectDone: boolean
  syncQueue?: string[]
  setPruneOpen: (open: boolean) => void
  setCompressOpen: (open: boolean) => void
  setWorkInitialDraftOpen: (open: boolean) => void
  setProjectInitialDraftOpen: (open: boolean) => void
  setManualSyncOpen: React.Dispatch<React.SetStateAction<Record<string, boolean>>>
}

/**
 * 向导面板自动打开调度（自 editor-module-renderer 迁出）。
 *
 * 空板块免疫：step2 进入时若某板块为空，不自动打开对应初改面板——
 * 依赖数组含 hasWork/hasProjects，板块由空变非空时本 effect 自动重跑、恢复打开初改服务；
 * 由非空变空时不新开面板（已打开的交由面板自身错误态 + W-1 关闭兜底网收场）。
 */
export function useWizardPanelAutoOpen({
  wizardStep,
  hasWork,
  hasProjects,
  initialDraftWorkDone,
  initialDraftProjectDone,
  syncQueue,
  setPruneOpen,
  setCompressOpen,
  setWorkInitialDraftOpen,
  setProjectInitialDraftOpen,
  setManualSyncOpen,
}: UseWizardPanelAutoOpenParams) {
  const prevStepRef = useRef<string | undefined>(undefined)
  const prevHasWorkRef = useRef<boolean | undefined>(undefined)
  const prevHasProjectsRef = useRef<boolean | undefined>(undefined)
  useEffect(() => {
    const stepChanged = prevStepRef.current !== wizardStep;
    prevStepRef.current = wizardStep;
    if (wizardStep === 'step1') {
      // step1 行为保持与迁移前一致：仅在进入 step1 时双开，
      // 板块内容变化（如裁剪应用后清空）不重开面板
      if (stepChanged) {
        setPruneOpen(true);
        setCompressOpen(true);
      }
    } else if (wizardStep === 'step2') {
      // 打开触发 = 进入 step2（stepChanged）或该板块自身出现空→非空边沿。
      // 边沿检测避免兄弟板块内容变化重跑 effect 时，把用户手动关闭的
      // 未完成初改面板连带重开（agy/zcode review P2）。
      // 未 Done 守卫：已完成初改的板块任何情况下不得被自动重开。
      const workTrigger = stepChanged || (hasWork && prevHasWorkRef.current === false);
      const projectTrigger = stepChanged || (hasProjects && prevHasProjectsRef.current === false);
      if (hasWork && !initialDraftWorkDone && workTrigger) {
        setWorkInitialDraftOpen(true);
      }
      if (hasProjects && !initialDraftProjectDone && projectTrigger) {
        setProjectInitialDraftOpen(true);
      }
    } else if (wizardStep === 'step5' && syncQueue && syncQueue.length > 0) {
      setManualSyncOpen(prev => {
        const next = { ...prev };
        syncQueue.slice(0, 3).forEach(key => {
          next[key] = true;
        });
        return next;
      });
    }
    prevHasWorkRef.current = hasWork;
    prevHasProjectsRef.current = hasProjects;
  }, [wizardStep, hasWork, hasProjects, initialDraftWorkDone, initialDraftProjectDone, syncQueue, setPruneOpen, setCompressOpen, setWorkInitialDraftOpen, setProjectInitialDraftOpen, setManualSyncOpen]);
}
