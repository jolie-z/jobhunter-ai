import { create } from "zustand"

/**
 * 岗位列表筛选/分页状态（全局模块级 store）。
 *
 * 为什么放 store：岗位列表进「定制面板」时 JobListView 会卸载，
 * 组件内 useState 的筛选条件随之丢失，返回后回到零筛选状态。
 * 状态提升到模块级 store 后，视图切换不再丢筛选，且列表与详情共享同一份状态。
 *
 * 约定：任何筛选条件变化都会把页码重置回第 1 页（setXxx 内部统一处理）。
 */

export const PAGE_SIZE_OPTIONS = [20, 50, 100] as const

const DEFAULT_FILTERS = {
  searchQuery: "",
  sortMode: "按时间", // "按时间" (默认) 或 "按评级"
  statusFilter: "全部",
  scoreFilter: "全部",
  eduFilter: "全部",
  expFilter: "全部",
  scaleFilter: "全部",
  platformFilter: "全部",
}

interface JobFilterState {
  searchQuery: string
  sortMode: string
  statusFilter: string
  scoreFilter: string
  eduFilter: string
  expFilter: string
  scaleFilter: string
  platformFilter: string
  pageSize: number
  currentPage: number

  setSearchQuery: (v: string) => void
  setSortMode: (v: string) => void
  setStatusFilter: (v: string) => void
  setScoreFilter: (v: string) => void
  setEduFilter: (v: string) => void
  setExpFilter: (v: string) => void
  setScaleFilter: (v: string) => void
  setPlatformFilter: (v: string) => void
  setPageSize: (v: number) => void
  setCurrentPage: (v: number) => void
  resetAll: () => void
}

export const useJobFilterStore = create<JobFilterState>((set) => ({
  ...DEFAULT_FILTERS,
  pageSize: 20,
  currentPage: 1,

  // 所有筛选 setter 统一重置页码，避免"筛完落在不存在的页"
  setSearchQuery: (v) => set({ searchQuery: v, currentPage: 1 }),
  setSortMode: (v) => set({ sortMode: v, currentPage: 1 }),
  setStatusFilter: (v) => set({ statusFilter: v, currentPage: 1 }),
  setScoreFilter: (v) => set({ scoreFilter: v, currentPage: 1 }),
  setEduFilter: (v) => set({ eduFilter: v, currentPage: 1 }),
  setExpFilter: (v) => set({ expFilter: v, currentPage: 1 }),
  setScaleFilter: (v) => set({ scaleFilter: v, currentPage: 1 }),
  setPlatformFilter: (v) => set({ platformFilter: v, currentPage: 1 }),
  setPageSize: (v) => set({ pageSize: v, currentPage: 1 }),
  setCurrentPage: (v) => set({ currentPage: v }),
  resetAll: () => set({ ...DEFAULT_FILTERS, currentPage: 1 }),
}))
