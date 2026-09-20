/**
 * BOSS Tab 组件间共享上下文（拆分自 boss-tab.tsx 单组件作用域，类型自动推导零手写）。
 * useBossTabState 为状态中枢；各 section 组件经 useBossCtx 解构原闭包变量。
 */
"use client"

import { createContext, useContext } from "react"
import type { useBossTabState } from "./state"

export type BossCtx = ReturnType<typeof useBossTabState>

export const BossCtx = createContext<BossCtx | null>(null)

export function useBossCtx(): BossCtx {
  const ctx = useContext(BossCtx)
  if (!ctx) throw new Error("BossCtx missing provider: BossTab 主组件未挂 Provider")
  return ctx
}
