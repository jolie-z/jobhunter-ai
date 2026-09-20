import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type CrawlerStatus = 'pending' | 'running' | 'cleaning' | 'completed' | 'error' | 'terminated'

export interface CrawlerTask {
  id: string; // The SSE task_id
  platform: 'liepin' | 'boss' | '51job' | 'xiaohongshu' | 'zhilian' | 'global';
  keyword: string;
  city: string;
  salary: string;
  status: CrawlerStatus;
  totalInserted: number;
  targetJobs: number;
  currentPage?: number;
  startTime: number;
  endTime?: number;
  errorMessage?: string;
  hardCleanProgress?: { current: number; total: number; passed?: number; rejected?: number };
  aiScoutProgress?: { current: number; total: number; passed?: number; rejected?: number };
  feishuSyncProgress?: { current: number; total: number; passed?: number; rejected?: number };
}

interface CrawlerTaskStore {
  tasks: Record<string, CrawlerTask>;
  
  // Actions
  addTask: (task: Omit<CrawlerTask, 'status' | 'totalInserted' | 'startTime'>) => void;
  updateTaskProgress: (id: string, totalInserted: number, targetJobs?: number, currentPage?: number) => void;
  updateTaskPhaseProgress: (id: string, phase: 'hard_clean' | 'ai_scout' | 'feishu_sync', current: number, total: number, passed?: number, rejected?: number) => void;
  updateTaskStatus: (id: string, status: CrawlerStatus, errorMessage?: string) => void;
  clearTasks: () => void;
  removeTask: (id: string) => void;
}

export const useCrawlerTaskStore = create<CrawlerTaskStore>()(
  persist(
    (set) => ({
      tasks: {},
      
      addTask: (taskParams) => set((state) => ({
        tasks: {
          ...state.tasks,
          [taskParams.id]: {
            ...taskParams,
            status: 'pending',
            totalInserted: 0,
            startTime: Date.now(),
          }
        }
      })),
      
      updateTaskProgress: (id, totalInserted, targetJobs, currentPage) => set((state) => {
        const task = state.tasks[id]
        if (!task) return state
        
        // 🌟 终态不可逆保护：terminated / error / completed / cleaning 状态严禁被滞后的 progress 事件翻回 running
        const isTerminalOrCleaning = ['cleaning', 'completed', 'terminated', 'error'].includes(task.status)
        const nextStatus = isTerminalOrCleaning ? task.status : 'running'

        return {
          tasks: {
            ...state.tasks,
            [id]: {
              ...task,
              totalInserted,
              ...(targetJobs !== undefined ? { targetJobs } : {}),
              ...(currentPage !== undefined ? { currentPage } : {}),
              status: nextStatus
            }
          }
        }
      }),

      updateTaskPhaseProgress: (id, phase, current, total, passed, rejected) => set((state) => {
        const task = state.tasks[id]
        if (!task) return state

        const phaseKey = phase === 'hard_clean' ? 'hardCleanProgress'
                       : phase === 'ai_scout' ? 'aiScoutProgress'
                       : 'feishuSyncProgress'

        // 🌟 终态不可逆保护：terminated / error / completed 状态严禁被滞后的阶段进度翻回 cleaning
        const isTerminal = ['completed', 'terminated', 'error'].includes(task.status)
        const nextStatus = isTerminal ? task.status : 'cleaning'

        return {
          tasks: {
            ...state.tasks,
            [id]: {
              ...task,
              [phaseKey]: { 
                current, 
                total,
                passed: passed !== undefined ? passed : task[phaseKey]?.passed,
                rejected: rejected !== undefined ? rejected : task[phaseKey]?.rejected,
              },
              status: nextStatus
            }
          }
        }
      }),
      
      updateTaskStatus: (id, status, errorMessage) => set((state) => {
        const task = state.tasks[id]
        if (!task) return state
        
        return {
          tasks: {
            ...state.tasks,
            [id]: {
              ...task,
              status,
              ...(status === 'completed' || status === 'error' || status === 'terminated' ? { endTime: Date.now() } : {}),
              ...(errorMessage ? { errorMessage } : {})
            }
          }
        }
      }),
      
      clearTasks: () => set({ tasks: {} }),
      
      removeTask: (id) => set((state) => {
        const newTasks = { ...state.tasks }
        delete newTasks[id]
        return { tasks: newTasks }
      }),
    }),
    {
      name: 'crawler-tasks-storage',
    }
  )
)
