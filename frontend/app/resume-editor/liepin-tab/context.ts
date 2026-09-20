/**
 * Liepin Tab 组件间共享上下文（类型自动推导）
 */
"use client"

import { createContext, useContext } from "react"
import type { useLiepinTabState } from "./state"

export type LiepinCtx = ReturnType<typeof useLiepinTabState>

export const LiepinCtx = createContext<LiepinCtx | null>(null)

export function useLiepinCtx(): LiepinCtx {
  const ctx = useContext(LiepinCtx)
  if (!ctx) throw new Error("LiepinCtx missing provider")
  return ctx
}
