import { create } from "zustand"

interface TrashBinState {
  isOpen: boolean
  openTrashBin: () => void
  closeTrashBin: () => void
  toggleTrashBin: () => void
}

export const useTrashBinStore = create<TrashBinState>((set) => ({
  isOpen: false,
  openTrashBin: () => set({ isOpen: true }),
  closeTrashBin: () => set({ isOpen: false }),
  toggleTrashBin: () => set((state) => ({ isOpen: !state.isOpen })),
}))
