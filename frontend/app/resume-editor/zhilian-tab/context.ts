/**
 * Zhilian Tab 组件间共享上下文（类型自动推导）
 */
"use client"

import { createContext, useContext } from "react"
import type { useZhilianTabState } from "./state"

export type ZhilianCtx = ReturnType<typeof useZhilianTabState>

export const ZhilianCtx = createContext<ZhilianCtx | null>(null)

export function useZhilianCtx(): ZhilianCtx {
  const ctx = useContext(ZhilianCtx)
  if (!ctx) throw new Error("ZhilianCtx missing provider")
  return ctx
}
