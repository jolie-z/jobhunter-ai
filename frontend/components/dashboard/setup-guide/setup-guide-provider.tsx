"use client"

// 新手引导全局 Provider：单实例挂 layout.tsx
// - 暴露 openGuide() 给 顶栏「新手引导」按钮 / 配置大盘左侧导航
// - 首次访问且配置未完成时自动弹出一次（localStorage 记账，不打扰第二次）

import { createContext, useCallback, useContext, useEffect, useState } from "react"
import { apiFetch } from "@/lib/api"
import { SETUP_GUIDE_FLAG_KEY, SetupGuideDialog } from "./setup-guide-dialog"

type SetupGuideContextType = {
  openGuide: () => void
  /** 首检发现配置未完成时为 true，供顶栏按钮显示提醒小点 */
  incomplete: boolean
}

const SetupGuideContext = createContext<SetupGuideContextType>({
  openGuide: () => {},
  incomplete: false,
})

export function useSetupGuide() {
  return useContext(SetupGuideContext)
}

export function SetupGuideProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const [incomplete, setIncomplete] = useState(false)

  const refreshIncomplete = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/settings/setup-status`)
      if (!res.ok) return
      const data = await res.json()
      if (data?.code === 0) setIncomplete(data.data?.complete === false)
    } catch {
      // 后端未启动时静默，不打扰用户
    }
  }, [])

  useEffect(() => {
    let notified = false
    try {
      notified = !!localStorage.getItem(SETUP_GUIDE_FLAG_KEY)
    } catch {}

    if (notified) {
      refreshIncomplete()
      return
    }

    // 首次访问：拉一次体检，未完成则自动弹出一次
    ;(async () => {
      try {
        const res = await apiFetch(`/api/settings/setup-status`)
        if (!res.ok) return
        const data = await res.json()
        if (data?.code !== 0) return
        const complete = data.data?.complete === true
        setIncomplete(!complete)
        try {
          localStorage.setItem(SETUP_GUIDE_FLAG_KEY, JSON.stringify({ notified: true, ts: Date.now() }))
        } catch {}
        if (!complete) setOpen(true)
      } catch {
        // 静默
      }
    })()
  }, [refreshIncomplete])

  const openGuide = useCallback(() => {
    setOpen(true)
    refreshIncomplete()
  }, [refreshIncomplete])

  // 引导弹窗内检测到配置已齐时，实时熄灭顶栏/侧栏入口的提醒点
  const markComplete = useCallback(() => setIncomplete(false), [])

  return (
    <SetupGuideContext.Provider value={{ openGuide, incomplete }}>
      {children}
      <SetupGuideDialog open={open} onClose={() => setOpen(false)} onComplete={markComplete} />
    </SetupGuideContext.Provider>
  )
}
