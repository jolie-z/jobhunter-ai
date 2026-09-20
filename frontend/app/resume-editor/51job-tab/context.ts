/**
 * Job51 Tab 组件间共享上下文（类型自动推导）
 */
"use client"

import { createContext, useContext } from "react"
import type { useJob51TabState } from "./state"

export type Job51Ctx = ReturnType<typeof useJob51TabState>

export const Job51Ctx = createContext<Job51Ctx | null>(null)

export function useJob51Ctx(): Job51Ctx {
  const ctx = useContext(Job51Ctx)
  if (!ctx) throw new Error("Job51Ctx missing provider")
  return ctx
}
