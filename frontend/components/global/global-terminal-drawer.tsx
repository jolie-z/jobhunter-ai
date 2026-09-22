"use client"

import { useState, useEffect, useRef, useMemo, useCallback } from "react"
import {
  Terminal,
  ChevronDown,
  ArrowDown,
  Trash2,
  Search,
  Maximize2,
  Minimize2,
  Copy,
  Check,
  Activity,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { API_BASE } from "@/lib/api"
import { useGlobalTerminalStore } from "@/store/global-terminal-store"
import { usePipelineStore } from "@/store/pipeline-store"
import { usePathname } from "next/navigation"

interface LogLine {
  seq: number
  text: string
  time: string
}

function extractTimeOrNow(text: string): { time: string; cleanText: string } {
  const match = text.match(/^(\d{2}:\d{2}:\d{2})\s*(.*)$/)
  if (match) {
    return {
      time: match[1],
      cleanText: match[2] || text,
    }
  }
  const now = new Date()
  const timeStr = [
    String(now.getHours()).padStart(2, "0"),
    String(now.getMinutes()).padStart(2, "0"),
    String(now.getSeconds()).padStart(2, "0"),
  ].join(":")
  return { time: timeStr, cleanText: text }
}

export function GlobalTerminalDrawer() {
  const pathname = usePathname()

  // 🌟 打印路由 /print/* 完全杜绝控制台实例化与副作用，杜绝在无头浏览器和 iframe 中启动 EventSource 与轮询
  if (pathname?.startsWith("/print")) {
    return null
  }

  return <GlobalTerminalDrawerInner />
}

function GlobalTerminalDrawerInner() {
  const {
    isOpen,
    isExpanded,
    unreadErrors,
    toggleOpen,
    setOpen,
    toggleExpand,
    incrementErrors,
    clearErrors,
  } = useGlobalTerminalStore()

  const [lines, setLines] = useState<LogLine[]>([])
  const [search, setSearch] = useState("")
  const [autoScroll, setAutoScroll] = useState(true)
  const [copied, setCopied] = useState(false)
  const [lastActiveTime, setLastActiveTime] = useState<number>(Date.now())

  const boxRef = useRef<HTMLDivElement>(null)
  const seqRef = useRef(0)
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingRef = useRef<string[]>([])
  const pipelineStatus = usePipelineStore((s) => s.status)

  // 全局快捷键监听：Cmd + J 或 Ctrl + ` 呼出/收起
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const isTargetKey =
        ((e.metaKey || e.ctrlKey) && (e.key === "j" || e.key === "J")) ||
        (e.ctrlKey && e.key === "`")

      if (isTargetKey) {
        // 如果焦点在输入框中且只是普通输入，则不拦截，但带有 metaKey 时通常是快捷键
        e.preventDefault()
        toggleOpen()
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [toggleOpen])

  // 后端日志 SSE 按需连接：仅在终端展开或全链路任务运行时建立，空闲时主动断流。
  // 事件流长连接会常驻占用浏览器对同主机的 6 条并发连接名额，多标签页下曾把
  // 连接池占满，导致保存配置等短请求在浏览器内排队数十秒才发出（表现为保存转圈很久）。
  useEffect(() => {
    if (!isOpen && pipelineStatus !== "running") return
    const es = new EventSource(`${API_BASE}/api/automation/console-stream`)

    es.onopen = () => {
      seqRef.current = 0
      setLines([])
      pendingRef.current = []
    }

    es.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        if (d.line) {
          let text = String(d.line)
          if (text.length > 4000) {
            text = text.slice(0, 4000) + ` …(已截断 ${text.length - 4000} 字符)`
          }
          pendingRef.current.push(text)
          setLastActiveTime(Date.now())

          // 统计未读错误
          if (
            !isOpen &&
            (text.includes("❌") || text.includes("🚨") || text.toLowerCase().includes("error"))
          ) {
            incrementErrors()
          }
        }
      } catch {}
    }

    es.onerror = () => {
      // 避免频繁报错，EventSource 会自动重试
    }

    // 批量渲染定时器（300ms 批处理，避免高频日志冲垮主线程）
    const flushTimer = setInterval(() => {
      if (!pendingRef.current.length) return
      const incoming = pendingRef.current
      pendingRef.current = []

      setLines((prev) => {
        const merged = [...prev]
        for (const raw of incoming) {
          const { time, cleanText } = extractTimeOrNow(raw)
          merged.push({ seq: ++seqRef.current, text: cleanText, time })
        }
        return merged.slice(-800) // 限制最大 800 行内存驻留
      })
    }, 300)

    return () => {
      es.close()
      clearInterval(flushTimer)
    }
  }, [isOpen, pipelineStatus, incrementErrors])

  // 当终端打开时自动清除未读错误计数
  useEffect(() => {
    if (isOpen && unreadErrors > 0) {
      clearErrors()
    }
  }, [isOpen, unreadErrors, clearErrors])

  // 滚屏处理
  const handleScroll = () => {
    if (!boxRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = boxRef.current
    const atBottom = scrollHeight - scrollTop - clientHeight < 40
    setAutoScroll(atBottom)
  }

  const scrollToBottom = useCallback(() => {
    if (boxRef.current) {
      boxRef.current.scrollTo({
        top: boxRef.current.scrollHeight,
        behavior: "smooth",
      })
      setAutoScroll(true)
    }
  }, [])

  useEffect(() => {
    if (autoScroll && isOpen) {
      scrollToBottom()
    }
  }, [lines, autoScroll, isOpen, scrollToBottom])

  const handleCopy = () => {
    const text = lines.map((l) => `[${l.time}] ${l.text}`).join("\n")
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
      copiedTimer.current = setTimeout(() => setCopied(false), 2000)
    })
  }

  // 过滤后的日志
  const q = search.trim().toLowerCase()
  const filteredLines = useMemo(() => {
    if (!q) return lines
    return lines.filter((l) => l.text.toLowerCase().includes(q))
  }, [lines, q])

  // 活跃指示灯判定：近 5 秒内有日志进入或管道正在运行
  const isHeartbeatActive = pipelineStatus === "running" || Date.now() - lastActiveTime < 5000

  return (
    <>
      {/* 1. 浮动收起态：贴右边缘的竖排呼吸小签（右下角，窄边不挡内容） */}
      {!isOpen && (
        <button
          onClick={() => setOpen(true)}
          data-terminal-drawer="true"
          className={cn(
            "fixed bottom-4 right-0 z-40 print:hidden flex flex-col items-center gap-2 py-3 pl-1.5 pr-1 rounded-l-xl select-none",
            "bg-zinc-950/85 hover:bg-zinc-900/95 border border-r-0 border-zinc-800 shadow-xl shadow-black/25 backdrop-blur-md",
            "text-zinc-200 transition-all duration-200 hover:scale-[1.03] active:scale-[0.98] origin-bottom-right"
          )}
          title="点击展开白盒日志终端 (快捷键: ⌘J)"
        >
          {/* 呼吸状态灯 */}
          <span className="relative flex h-2 w-2">
            {isHeartbeatActive && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            )}
            <span
              className={cn(
                "relative inline-flex rounded-full h-2 w-2 transition-colors",
                unreadErrors > 0
                  ? "bg-rose-500"
                  : isHeartbeatActive
                  ? "bg-emerald-500"
                  : "bg-zinc-600"
              )}
            />
          </span>

          <Terminal className="h-3.5 w-3.5 text-zinc-400" />
          <span className="[writing-mode:vertical-rl] text-[11px] tracking-[0.18em] font-medium font-mono text-zinc-300">
            白盒控制台
          </span>

          {/* 计数徽标：红色=未读异常数，灰色=日志总行数，语义靠 title 消歧 */}
          <span
            title={unreadErrors > 0 ? `${unreadErrors} 条未读异常` : `${lines.length} 行日志`}
            className={cn(
              "rounded-full px-1.5 py-0.5 text-[10px] font-mono",
              unreadErrors > 0
                ? "bg-rose-500/20 border border-rose-500/40 text-rose-300"
                : "bg-zinc-800/80 text-zinc-400"
            )}
          >
            {unreadErrors > 0 ? unreadErrors : lines.length}
          </span>

          <kbd className="hidden sm:inline-block text-[9px] px-1 py-0.5 rounded bg-zinc-800/90 text-zinc-400 border border-zinc-700/50">
            ⌘J
          </kbd>
        </button>
      )}

      {/* 2. 展开态：停靠右边缘、贴地右下角的竖版控制台面板（只占右侧竖条，不横铺遮挡） */}
      {isOpen && (
        <div
          data-terminal-drawer="true"
          className={cn(
            "fixed bottom-0 right-0 z-50 print:hidden w-[400px] max-w-[calc(100vw-1rem)] rounded-l-2xl border border-r-0 border-zinc-800/90 bg-zinc-950/95 text-zinc-100 shadow-2xl backdrop-blur-xl transition-all duration-300 flex flex-col",
            isExpanded ? "h-[92vh]" : "h-[68vh]"
          )}
        >
          {/* 终端顶栏：竖版面板收窄后拆两行——第一行标题态、第二行过滤+操作 */}
          <div
            onClick={toggleOpen}
            className="cursor-pointer select-none border-b border-zinc-800/80 bg-zinc-900/60 rounded-tl-2xl hover:bg-zinc-900/90 transition-colors shrink-0"
          >
            <div className="flex h-11 items-center justify-between px-4">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "h-2 w-2 rounded-full transition-all",
                      isHeartbeatActive ? "bg-emerald-400 animate-pulse" : "bg-zinc-600"
                    )}
                  />
                  <Terminal className="h-3.5 w-3.5 text-zinc-400" />
                </div>
                <span className="text-xs font-mono font-medium text-zinc-200">白盒日志终端</span>
                <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] font-mono text-zinc-400">
                  {q ? `${filteredLines.length}/` : ""}
                  {lines.length} 行
                </span>
              </div>

              {isHeartbeatActive && (
                <span className="flex items-center gap-1 text-[10px] text-emerald-400/80 font-mono shrink-0">
                  <Activity className="h-3 w-3 animate-pulse" />
                  实时推流中
                </span>
              )}
            </div>

            <div
              className="flex items-center gap-1.5 px-3 pb-2.5"
              onClick={(e) => e.stopPropagation()}
            >
              {/* 搜索过滤框 */}
              <div className="relative flex-1 min-w-0">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-500" />
                <input
                  type="text"
                  placeholder="过滤日志…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="h-6 w-full rounded bg-zinc-800/80 pl-6 pr-2 text-[10px] text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-600"
                />
              </div>

              {/* 复制全部 */}
              <button
                onClick={handleCopy}
                className="flex h-6 w-6 items-center justify-center rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
                title="复制全部日志"
              >
                {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
              </button>

              {/* 清空日志 */}
              <button
                onClick={() => setLines([])}
                className="flex h-6 w-6 items-center justify-center rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
                title="清空日志"
              >
                <Trash2 className="h-3 w-3" />
              </button>

              {/* 全屏/半屏切换 */}
              <button
                onClick={toggleExpand}
                className="flex h-6 w-6 items-center justify-center rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
                title={isExpanded ? "还原半屏" : "最大化"}
              >
                {isExpanded ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
              </button>

              {/* 收起抽屉 */}
              <button
                onClick={toggleOpen}
                className="flex h-6 w-6 items-center justify-center rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
                title="收起控制台 (⌘J)"
              >
                <ChevronDown className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* 终端内容区 */}
          <div className="relative flex-1 min-h-0 w-full">
            <div
              ref={boxRef}
              onScroll={handleScroll}
              className="h-full overflow-y-auto p-3 font-mono text-[11px] leading-relaxed text-zinc-300 select-text"
            >
              {filteredLines.length === 0 ? (
                <div className="flex h-full items-center justify-center text-zinc-600">
                  等待后端控制台输出…（全站任意模块的 print 与 logger 均在此实时透出）
                </div>
              ) : (
                filteredLines.map((l) => {
                  const line = l.text
                  const isError =
                    line.includes("❌") ||
                    line.includes("🚨") ||
                    line.includes("error") ||
                    line.includes("ERROR")
                  const isSuccess =
                    line.includes("✅") || line.includes("✓") || line.includes("成功")
                  const isWarning =
                    line.includes("⚠️") || line.includes("警告") || line.includes("WARNING")
                  const isTrace = line.includes("👣 [Trace]")

                  return (
                    <div
                      key={l.seq}
                      className={cn(
                        "py-0.5 whitespace-pre-wrap break-all transition-colors flex items-start",
                        isError
                          ? "text-rose-400 bg-rose-500/10 px-1 rounded"
                          : isSuccess
                          ? "text-emerald-400"
                          : isWarning
                          ? "text-amber-400"
                          : isTrace
                          ? "text-violet-400 opacity-80"
                          : "text-zinc-300"
                      )}
                    >
                      <span className="text-zinc-600 select-none mr-1.5 text-[10px] shrink-0 font-mono">
                        {String(l.seq).padStart(3, " ")}
                      </span>
                      <span className="text-zinc-500 select-none mr-2 text-[10px] shrink-0 font-mono">
                        [{l.time}]
                      </span>
                      <span className="flex-1 min-w-0">{line}</span>
                    </div>
                  )
                })
              )}
            </div>

            {/* 回到底部悬浮按钮 */}
            {!autoScroll && lines.length > 0 && (
              <button
                onClick={scrollToBottom}
                className="absolute bottom-3 right-4 z-20 flex items-center gap-1 rounded-full bg-zinc-800/90 hover:bg-zinc-700 text-zinc-200 px-2.5 py-1 text-[10px] font-medium shadow-lg border border-zinc-700/80 backdrop-blur transition-all duration-200 hover:scale-105 active:scale-95 animate-in fade-in"
                title="回到底部"
              >
                <ArrowDown className="h-3 w-3 text-emerald-400 animate-bounce" />
                <span>回到底部</span>
              </button>
            )}
          </div>
        </div>
      )}
    </>
  )
}
