import { create } from "zustand"

interface GlobalTerminalState {
  isOpen: boolean
  isExpanded: boolean
  unreadErrors: number
  toggleOpen: () => void
  setOpen: (open: boolean) => void
  toggleExpand: () => void
  setExpanded: (expanded: boolean) => void
  incrementErrors: () => void
  clearErrors: () => void
}

export const useGlobalTerminalStore = create<GlobalTerminalState>((set) => ({
  isOpen: false,
  isExpanded: false,
  unreadErrors: 0,
  toggleOpen: () =>
    set((state) => ({
      isOpen: !state.isOpen,
      unreadErrors: !state.isOpen ? 0 : state.unreadErrors,
    })),
  setOpen: (open) =>
    set((state) => ({
      isOpen: open,
      unreadErrors: open ? 0 : state.unreadErrors,
    })),
  toggleExpand: () => set((state) => ({ isExpanded: !state.isExpanded })),
  setExpanded: (expanded) => set({ isExpanded: expanded }),
  incrementErrors: () => set((state) => ({ unreadErrors: state.unreadErrors + 1 })),
  clearErrors: () => set({ unreadErrors: 0 }),
}))
