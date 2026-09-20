export type WizardStep = 'idle' | 'step1' | 'step2' | 'step3' | 'step4' | 'step5' | 'step6'

export interface WizardProgress {
  pruneDone: boolean
  compressDone: boolean
  initialDraftProjectDone: boolean
  initialDraftWorkDone: boolean
  grillDone: boolean
  atsDone: boolean
  syncDone: boolean
  savedDone: boolean
}

export const DEFAULT_WIZARD_PROGRESS: WizardProgress = {
  pruneDone: false,
  compressDone: false,
  initialDraftProjectDone: false,
  initialDraftWorkDone: false,
  grillDone: false,
  atsDone: false,
  syncDone: false,
  savedDone: false,
}