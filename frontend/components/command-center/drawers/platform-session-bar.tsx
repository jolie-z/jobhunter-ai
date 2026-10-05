"use client"

import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import {
  Globe,
  RefreshCw,
  PowerOff } from "lucide-react"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"

export interface PlatformSessionItem {
  platform: string
  display_name: string
  port: number
  state: string // healthy | degraded | offline | expired | unknown
  message: string
  is_alive: boolean
}

export interface PlatformSessionBarProps {
  onSessionsChange?: (sessions: PlatformSessionItem[]) => void
  className?: string
  gridClassName?: string
  excludePlatforms?: string[]
  allowedPlatforms?: string[]
}

// 唤起成功后的死亡观察窗口：窗口内"上轮存活→本轮掉线"判定为浏览器进程异常退出
// （2026-09-26 排查：Edge 曾多次 exec 后数分钟内静默退出，界面静默回落 offline 零反馈）
export const WAKE_DEATH_WATCH_MS = 120_000

// 会话快照的最小切面（死亡监视只关心这三个字段）
type WakeWatchSnapshot = Pick<PlatformSessionItem, "platform" | "display_name" | "is_alive">

// 观察窗口截止时刻（组件外定义：Date.now 属非纯调用，不进渲染作用域）
const wakeDeadline = () => Date.now() + WAKE_DEATH_WATCH_MS

/**
 * 唤起后死亡监视（纯函数）：对比前后两轮会话快照，
 * 在观察窗口内由存活翻转为掉线的平台即视为异常退出。
 * 不修改 watchUntil（触发后的去重删除由调用方完成）。
 */
export function findWakeDeaths(
  prev: WakeWatchSnapshot[],
  curr: WakeWatchSnapshot[],
  watchUntil: ReadonlyMap<string, number>,
  now: number,
): Array<Pick<PlatformSessionItem, "platform" | "display_name">> {
  const prevAlive = new Set(prev.filter((s) => s.is_alive).map((s) => s.platform))
  const deaths: Array<Pick<PlatformSessionItem, "platform" | "display_name">> = []
  for (const s of curr) {
    if (!s.is_alive && prevAlive.has(s.platform) && (watchUntil.get(s.platform) ?? 0) > now) {
      deaths.push({ platform: s.platform, display_name: s.display_name })
    }
  }
  return deaths
}

export function PlatformSessionBar({
  onSessionsChange,
  className,
  gridClassName,
  excludePlatforms,
  allowedPlatforms,
}: PlatformSessionBarProps = {}) {
  const [sessions, setSessions] = useState<PlatformSessionItem[]>([])
  const [loading, setLoading] = useState(false)
  const [launchingKey, setLaunchingKey] = useState<string | null>(null)
  const [closingAll, setClosingAll] = useState(false)
  // 唤起后延迟刷新会话的定时器（组件卸载时清理，防止 setState 泄漏）
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 死亡监视：平台 -> 观察窗口截止时间戳；prevSessionsRef 供"存活→掉线"翻转比对
  const wakeWatchRef = useRef<Map<string, number>>(new Map())
  const prevSessionsRef = useRef<PlatformSessionItem[]>([])
  const onSessionsChangeRef = useRef(onSessionsChange)

  useEffect(() => {
    onSessionsChangeRef.current = onSessionsChange
  }, [onSessionsChange])

  useEffect(() => {
    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current)
    }
  }, [])

  const displayedSessions = useMemo(() => {
    return sessions.filter((item) => {
      if (allowedPlatforms && !allowedPlatforms.includes(item.platform)) {
        return false
      }
      if (excludePlatforms && excludePlatforms.includes(item.platform)) {
        return false
      }
      return true
    })
  }, [sessions, allowedPlatforms, excludePlatforms])

  const fetchSessions = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/platform-sessions`)
      const data = await res.json()
      if (data.code === 0 && Array.isArray(data.data)) {
        const incoming = data.data as PlatformSessionItem[]
        // 死亡监视：观察窗口内"存活→掉线"即时告警，不再静默回落
        const deaths = findWakeDeaths(prevSessionsRef.current, incoming, wakeWatchRef.current, Date.now())
        for (const d of deaths) {
          wakeWatchRef.current.delete(d.platform)
          toast.error(
            `${d.display_name} 专用浏览器进程异常退出（已回落离线）。临终日志: backend/logs/edge_${d.platform}.log`,
            { duration: 8000 }
          )
        }
        prevSessionsRef.current = incoming
        setSessions(incoming)
        const filtered = data.data.filter((item: PlatformSessionItem) => {
          if (allowedPlatforms && !allowedPlatforms.includes(item.platform)) return false
          if (excludePlatforms && excludePlatforms.includes(item.platform)) return false
          return true
        })
        onSessionsChangeRef.current?.(filtered)
      }
    } catch {
      // 静默降级
    } finally {
      setLoading(false)
    }
  }, [allowedPlatforms, excludePlatforms])

  useEffect(() => {
    void (async () => {
      await fetchSessions()
    })()
    const timer = setInterval(fetchSessions, 15000) // 每 15 秒轻量轮询
    return () => clearInterval(timer)
  }, [fetchSessions])

  const handleLaunch = async (platKey: string, name: string) => {
    setLaunchingKey(platKey)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/platform-sessions/launch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: platKey }),
      })
      const data = await res.json()
      if (res.ok && data.code === 0) {
        toast.success(`已唤起 ${name} 专用浏览器，请完成扫码/登录`)
        // 登记死亡观察窗口：接下来 2 分钟内该平台掉线即告警
        wakeWatchRef.current.set(platKey, wakeDeadline())
        // 乐观登记存活：若 Edge 在 2s 首刷前就秒退，没经历过一次存活快照会漏报翻转
        prevSessionsRef.current = [
          ...prevSessionsRef.current.filter((s) => s.platform !== platKey),
          { platform: platKey, display_name: name, port: 0, state: "running", message: "", is_alive: true },
        ]
        if (refreshTimer.current) clearTimeout(refreshTimer.current)
        refreshTimer.current = setTimeout(fetchSessions, 2000)
      } else {
        toast.error(`唤起失败: ${data.detail || data.msg || "未知错误"}`)
      }
    } catch {
      toast.error("网络异常，无法唤起浏览器")
    } finally {
      setLaunchingKey(null)
    }
  }

  const handleCloseAll = async () => {
    if (!window.confirm("确定关闭所有平台的爬虫浏览器以释放内存吗？下次抓取将按需自动拉起。")) return
    setClosingAll(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/platform-sessions/close-all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
      const data = await res.json()
      if (res.ok && data.code === 0) {
        toast.success(`已安全关闭 ${data.data?.closed_count || 0} 个浏览器进程`)
        // 用户主动关闭：清空死亡观察，避免误报"异常退出"
        wakeWatchRef.current.clear()
        fetchSessions()
      } else {
        toast.error("关闭异常")
      }
    } catch {
      toast.error("网络异常")
    } finally {
      setClosingAll(false)
    }
  }

  return (
    <div className={cn("rounded-xl border border-border/80 bg-muted/20 p-3 space-y-2.5", className)}>
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <Globe className="h-4 w-4 text-violet-600 dark:text-violet-400 shrink-0" />
          <span className="text-xs font-semibold text-foreground">
            {displayedSessions.length > 0
              ? `${displayedSessions.length} 平台会话状态与生命周期`
              : (excludePlatforms?.includes("xiaohongshu") || excludePlatforms?.includes("xhs") || (allowedPlatforms && !allowedPlatforms.includes("xiaohongshu"))
                  ? "4 平台会话状态与生命周期"
                  : "5 平台会话状态与生命周期")}
          </span>
          <span className="text-[10px] text-muted-foreground hidden sm:inline">任务启动按需拉起 · 结束自动回收</span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={fetchSessions}
            disabled={loading}
            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50 cursor-pointer"
            title="刷新平台登录检测"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            刷新
          </button>

          <button
            type="button"
            onClick={handleCloseAll}
            disabled={closingAll}
            className="flex items-center gap-1 text-[11px] text-rose-600 dark:text-rose-400 hover:underline transition-colors disabled:opacity-50 font-medium cursor-pointer"
            title="关闭后台常驻浏览器释放内存"
          >
            <PowerOff className="h-3 w-3" />
            {closingAll ? "释放中…" : "关闭全部"}
          </button>
        </div>
      </div>

      <div className={cn("grid gap-2", gridClassName || (displayedSessions.length === 4 ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-2 sm:grid-cols-3 md:grid-cols-5"))}>
        {displayedSessions.map((item) => {
          const isHealthy = item.state === "healthy"
          const isAlive = item.is_alive
          // 后端 offline 时补读 profile cookie 有效期：离线 ≠ 登录丢失
          const cookieValidUntil = item.state === "offline"
            ? item.message.match(/登录 cookie 有效至 (\d{4}-\d{2}-\d{2})/)?.[1]
            : undefined
          const cookieExpired = item.state === "offline" && item.message.includes("cookie 已过期")
          const isLaunching = launchingKey === item.platform

          return (
            <div
              key={item.platform}
              className={cn(
                "flex flex-col justify-between rounded-lg border p-2 text-xs transition-all",
                isHealthy
                  ? "border-emerald-500/30 bg-emerald-500/[0.04]"
                  : cookieValidUntil
                  ? "border-sky-500/30 bg-sky-500/[0.03]"
                  : cookieExpired
                  ? "border-rose-500/30 bg-rose-500/[0.04]"
                  : isAlive
                  ? "border-sky-500/30 bg-sky-500/[0.03]"
                  : "border-border bg-card"
              )}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="font-semibold text-foreground truncate">{item.display_name}</span>
                <span className="font-mono text-[10px] text-muted-foreground">:{item.port}</span>
              </div>

              <div className="flex items-center justify-between gap-1 mt-2">
                <div className="flex items-center gap-1 min-w-0">
                  <span
                    className={cn(
                      "h-2 w-2 rounded-full shrink-0",
                      isHealthy
                        ? "bg-emerald-500 animate-pulse"
                        : cookieValidUntil || isAlive
                        ? "bg-sky-500"
                        : cookieExpired
                        ? "bg-rose-500"
                        : "bg-zinc-400"
                    )}
                  />
                  <span
                    className={cn(
                      "text-[10px] truncate",
                      isHealthy
                        ? "text-emerald-700 dark:text-emerald-300 font-medium"
                        : cookieValidUntil
                        ? "text-sky-700 dark:text-sky-300"
                        : cookieExpired
                        ? "text-rose-700 dark:text-rose-300 font-medium"
                        : isAlive
                        ? "text-sky-700 dark:text-sky-300"
                        : "text-muted-foreground"
                    )}
                    title={item.message}
                  >
                    {isHealthy
                      ? "已登录"
                      : isAlive
                      ? "已就绪"
                      : cookieValidUntil
                      ? `离线 · 登录有效至 ${cookieValidUntil.slice(5)}`
                      : cookieExpired
                      ? "离线 · 需重新登录"
                      : "未运行"}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={() => handleLaunch(item.platform, item.display_name)}
                  disabled={isLaunching}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-[10px] text-foreground hover:bg-muted font-medium transition-colors shrink-0 disabled:opacity-50"
                  title="唤起浏览器进行登录或操作"
                >
                  {isLaunching ? "唤起中…" : "唤起"}
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
