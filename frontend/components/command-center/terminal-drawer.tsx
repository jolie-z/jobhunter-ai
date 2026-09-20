"use client"

import { useState, useEffect, useRef } from "react"
import {
  Terminal,
  ChevronUp,
  ChevronDown,
  ArrowDown,
  Trash2,
  Search,
  Maximize2,
  Minimize2,
  Copy,
  Check,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { usePipelineStore } from "@/store/pipeline-store"
import { API_BASE } from "@/lib/api"

interface LogLine {
  seq: number
  text: string
  time: string
}

function extractTimeOrNow(text: string): { time: string; cleanText: string } {
  // 匹配类似 "06:39:02" 或 "13:18:44" 开头的日志
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

export function TerminalDrawer() {
  const [isOpen, setIsOpen] = useState(false)
  const [isExpanded, setIsExpanded] = useState(false)
  const [lines, setLines] = useState<LogLine[]>([])
  const [search, setSearch] = useState("")
  const [autoScroll, setAutoScroll] = useState(true)
  const [copied, setCopied] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  const seqRef = useRef(0)
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const pipelineStatus = usePipelineStore((s) => s.status)
  const pendingRef = useRef<string[]>([])

  // 监听后端日志流
  useEffect(() => {
    if (!isOpen) return
    const es = new EventSource(`${API_BASE}/api/automation/console-stream`)
    // console-stream 每次（重）连接都会先回放最近快照再实时推送：
    // (re)open 时清空本地行并重置行号，以服务端快照为准，避免日志成倍叠加
    es.onopen = () => {
      seqRef.current = 0
      setLines([])
      pendingRef.current = []
    }
    es.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        if (d.line) {
          // 超长行截断：AI 白盒日志单行可达数十 KB，全量进 DOM 会卡死终端
          let text = String(d.line)
          if (text.length > 4000) {
            text = text.slice(0, 4000) + ` …(已截断 ${text.length - 4000} 字符)`
          }
          pendingRef.current.push(text)
        }
      } catch {}
    }
    // 批量渲染：初评/改写阶段的日志洪峰若逐行 setState 会触发渲染风暴导致终端「假死」
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
        return merged.slice(-999)
      })
    }, 300)
    return () => {
      es.close()
      clearInterval(flushTimer)
    }
  }, [isOpen])

  // 用户上滚查看历史时暂停自动滚动，回到底部附近自动恢复
  const handleScroll = () => {
    const el = boxRef.current
    if (!el) return
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(isAtBottom)
  }

  // 滚动到底部
  const scrollToBottom = () => {
    if (boxRef.current) {
      boxRef.current.scrollTo({
        top: boxRef.current.scrollHeight,
        behavior: "smooth",
      })
      setAutoScroll(true)
    }
  }

  // 自动滚动
  useEffect(() => {
    if (autoScroll && boxRef.current) {
      boxRef.current.scrollTop = boxRef.current.scrollHeight
    }
  }, [lines, autoScroll, isOpen])

  useEffect(() => {
    return () => {
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
    }
  }, [])

  const q = search.trim().toLowerCase()
  const filteredLines = q ? lines.filter((l) => l.text.toLowerCase().includes(q) || l.time.includes(q)) : lines

  const handleCopy = async () => {
    try {
      if (!navigator.clipboard?.writeText) return
      await navigator.clipboard.writeText(lines.map((l) => `[${l.time}] #${l.seq} ${l.text}`).join("\n"))
      setCopied(true)
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
      copiedTimer.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      // 非安全上下文（http 内网）无剪贴板权限时静默跳过
    }
  }

  return (
    <div
      className={cn(
        "fixed bottom-0 right-6 z-40 w-[580px] max-w-[calc(100vw-3rem)] rounded-t-2xl border border-border/80 bg-zinc-950 text-zinc-100 shadow-2xl transition-all duration-300",
        isOpen ? (isExpanded ? "h-[80vh]" : "h-[360px]") : "h-11"
      )}
    >
      {/* 终端顶栏 */}
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex h-11 items-center justify-between px-4 cursor-pointer select-none border-b border-zinc-800/80 bg-zinc-900/60 rounded-t-2xl hover:bg-zinc-900 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "h-2 w-2 rounded-full transition-all",
                pipelineStatus === "running" ? "bg-emerald-400 animate-pulse" : "bg-zinc-600"
              )}
            />
            <Terminal className="h-3.5 w-3.5 text-zinc-400" />
          </div>
          <span className="text-xs font-mono font-medium text-zinc-200">
            白盒日志终端
          </span>
          <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] font-mono text-zinc-400">
            {q ? `${filteredLines.length}/` : ""}
            {lines.length} 行
          </span>
        </div>

        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          {isOpen && (
            <>
              {/* 搜索框 */}
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-500" />
                <input
                  type="text"
                  placeholder="过滤日志…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="h-6 w-32 rounded bg-zinc-800/80 pl-6 pr-2 text-[10px] text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-600"
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

              {/* 全屏/窗口切换 */}
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="flex h-6 w-6 items-center justify-center rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
              >
                {isExpanded ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
              </button>
            </>
          )}

          <button
            onClick={() => setIsOpen(!isOpen)}
            className="flex h-6 w-6 items-center justify-center rounded text-zinc-400 hover:text-zinc-200"
          >
            {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* 终端内容区 */}
      {isOpen && (
        <div className="relative h-[calc(100%-2.75rem)] w-full">
          <div
            ref={boxRef}
            onScroll={handleScroll}
            className="h-full overflow-y-auto p-3 font-mono text-[11px] leading-relaxed text-zinc-300 select-text"
          >
            {filteredLines.length === 0 ? (
              <div className="flex h-full items-center justify-center text-zinc-600">
                等待后端控制台输出…（任意后端 print 或 logger 都会实时推送）
              </div>
            ) : (
              filteredLines.map((l) => {
                const line = l.text
                const isError = line.includes("❌") || line.includes("🚨") || line.includes("error") || line.includes("ERROR")
                const isSuccess = line.includes("✅") || line.includes("✓") || line.includes("成功")
                const isWarning = line.includes("⚠️") || line.includes("警告") || line.includes("WARNING")
                const isTrace = line.includes("👣 [Trace]")

                return (
                  <div
                    key={l.seq}
                    className={cn(
                      "py-0.5 whitespace-pre-wrap break-all transition-colors flex items-start",
                      isError
                        ? "text-rose-400 bg-rose-500/5 px-1 rounded"
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

          {/* 向下箭头：点击平滑直达底部 */}
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
      )}
    </div>
  )
}
