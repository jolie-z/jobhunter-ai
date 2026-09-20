"use client"

import { useEffect, useRef, useState } from "react"
import { Terminal, X, Minimize2, Trash2, Loader2, CheckCircle2, AlertCircle, Play, Bug, StopCircle, Ban, Filter, Bot, Zap, Send, Layers } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useCrawlerTaskStore, CrawlerTask } from "@/store/crawler-task-store"
import { Progress } from "@/components/ui/progress"
import { MAIN_API_BASE } from "@/lib/platform-auth"
import { toast } from "sonner"

interface LiveTaskTerminalProps {
  title?: string
  onComplete?: () => void
  onMinimize?: () => void
  onClose?: () => void
  onSseMessage?: (data: unknown) => void
  showToolbar?: boolean
  showInternalHeader?: boolean
}

function PhaseProgressRow({
  title,
  progress,
  isTerminated,
  isError,
}: {
  title: string
  progress?: { current: number; total: number; passed?: number; rejected?: number }
  isTerminated?: boolean
  isError?: boolean
}) {
  const isDone = (progress?.total ?? 0) > 0 && progress?.current === progress?.total
  const percent = progress && (progress.total ?? 0) > 0 ? (progress.current / progress.total) * 100 : 0
  const hasBreakdown = isDone && progress?.passed !== undefined
  const isSync = title.includes("飞书")
  const isAi = title.includes("AI")
  const doneBadge = isSync ? "✅ 同步完成" : isAi ? "✅ 排雷完成" : "✅ 洗毕"
  const passLabel = isSync ? "成功" : isAi ? "放行" : "通过"
  const rejectLabel = isSync ? "失败" : "拦截"

  return (
    <div className="space-y-1.5 pr-2">
      <div className="flex justify-between items-center text-xs font-medium text-slate-600">
        <span className="flex items-center gap-1.5">
          {isDone ? (
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
          ) : isTerminated ? (
            <Ban className="w-3.5 h-3.5 text-slate-400" />
          ) : isError ? (
            <AlertCircle className="w-3.5 h-3.5 text-rose-500" />
          ) : (
            <Loader2 className={`w-3.5 h-3.5 ${progress ? 'animate-spin text-blue-500' : 'text-slate-300'}`} />
          )}
          {title}
        </span>
        <span>
          {!isDone && !isTerminated && !isError && (
            <span className="text-slate-500 font-medium">
              {progress ? `${progress.current}/${progress.total}` : "等待中..."}
            </span>
          )}
          {!isDone && (isTerminated || isError) && (
            <span className="text-slate-400 font-medium">
              {progress ? `${progress.current}/${progress.total} (${isTerminated ? '已终止' : '异常'})` : (isTerminated ? "已终止" : "异常")}
            </span>
          )}
          {isDone && !hasBreakdown && (
            <span className="text-emerald-600 font-semibold">
              {progress ? `${progress.current}/${progress.total} ` : ""}{doneBadge}
            </span>
          )}
          {isDone && hasBreakdown && (
            <span className="flex items-center gap-1.5 text-xs font-medium">
              <span className="text-emerald-600 font-semibold">{passLabel} {progress.passed}</span>
              {(progress.rejected ?? 0) > 0 ? (
                <span className="text-rose-600 font-semibold bg-rose-50 border border-rose-100 px-1.5 py-0.5 rounded text-[11px]">
                  {rejectLabel} {progress.rejected}
                </span>
              ) : (
                <span className="text-slate-400 font-normal">· 0 {rejectLabel}</span>
              )}
            </span>
          )}
        </span>
      </div>
      <Progress value={percent} className="h-1.5 bg-slate-100" />
    </div>
  )
}

// 🌐 Headless Component to manage SSE Connection per Task
function TaskSseConnection({ 
  task,
  onComplete,
  onSseMessage,
}: { 
  task: CrawlerTask
  onComplete?: () => void
  onSseMessage?: (data: unknown) => void
}) {
  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectFailuresRef = useRef<number>(0)

  // 🌟 将回调保存在 ref 中，避免父组件重渲染导致 SSE 频繁断开重建
  const onCompleteRef = useRef(onComplete)
  const onSseMessageRef = useRef(onSseMessage)

  useEffect(() => {
    onCompleteRef.current = onComplete
    onSseMessageRef.current = onSseMessage
  })

  useEffect(() => {
    // 避免在状态流转时重复断开与重连 SSE
    if (eventSourceRef.current) {
      return
    }

    if (task.status !== 'pending' && task.status !== 'running' && task.status !== 'cleaning') {
      return
    }

    // 跳过 localStorage 恢复的过期任务（1 小时前的 pending/running 不再尝试连接）
    if (Date.now() - task.startTime > 3600_000) {
      useCrawlerTaskStore.getState().updateTaskStatus(task.id, 'error', '任务已过期（重启后未完成）')
      return
    }

    const eventSource = new EventSource(
      `${MAIN_API_BASE}/tasks/logs?task_id=${task.id}`
    )
    eventSourceRef.current = eventSource

    const closeEventSource = () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }

    eventSource.onopen = () => {
      reconnectFailuresRef.current = 0
      console.log(`📡 [SSE] 连接已建立: ${task.id}`)
    }

    eventSource.onmessage = (event) => {
      try {
        reconnectFailuresRef.current = 0
        const data = JSON.parse(event.data)
        
        // 🌟 触发外部 SSE 监听回调
        onSseMessageRef.current?.(data)

        // 心跳包只保活，不落日志
        if (data.type === "heartbeat") {
          return
        }

        if (data.type === "error") {
          useCrawlerTaskStore.getState().updateTaskStatus(task.id, 'error', data.message || "任务异常退出")
          closeEventSource()
        } else if (data.type === "terminated") {
          useCrawlerTaskStore.getState().updateTaskStatus(task.id, 'terminated')
          closeEventSource()
        } else if (data.type === "progress") {
          // 🌟 兼容后端爬虫的标准字段名 total_inserted / target_jobs / current_page
          const currentVal = data.total_inserted !== undefined ? data.total_inserted : (data.current ?? 0)
          const targetVal = data.target_jobs !== undefined ? data.target_jobs : data.total
          const pageVal = data.current_page !== undefined ? data.current_page : data.page

          useCrawlerTaskStore.getState().updateTaskProgress(
            task.id, 
            parseInt(String(currentVal), 10) || 0,
            targetVal !== undefined ? parseInt(String(targetVal), 10) : undefined,
            pageVal !== undefined ? parseInt(String(pageVal), 10) : undefined
          )
        } else if (data.type === "phase_progress") {
          useCrawlerTaskStore.getState().updateTaskPhaseProgress(
            task.id, 
            data.phase, 
            data.current, 
            data.total, 
            data.passed, 
            data.rejected
          )
        } else if (data.type === "phase_change") {
          useCrawlerTaskStore.getState().updateTaskStatus(task.id, data.phase)
        } else if (data.type === "connected") {
          const currentTask = useCrawlerTaskStore.getState().tasks[task.id]
          if (currentTask?.status === 'pending') {
            useCrawlerTaskStore.getState().updateTaskStatus(task.id, 'running')
          }
        } else if (data.type === "end" || data.type === "completed" || data.type === "complete") {
          const currentTask = useCrawlerTaskStore.getState().tasks[task.id]
          // 仅当任务非终态（非 error / terminated / completed）时才更新为 completed，防止把错误任务刷绿
          if (currentTask && !['completed', 'terminated', 'error'].includes(currentTask.status)) {
            useCrawlerTaskStore.getState().updateTaskStatus(task.id, 'completed')
          }
          // 🌟 触发任务完成回调，刷新岗位列表等
          onCompleteRef.current?.()
          closeEventSource()
        }
      } catch (error) {
        console.error("❌ [SSE] 解析消息失败:", error)
      }
    }

    eventSource.onerror = () => {
      const currentTask = useCrawlerTaskStore.getState().tasks[task.id]
      if (!currentTask || ['completed', 'terminated', 'error'].includes(currentTask.status)) {
        closeEventSource()
        return
      }

      // 🌟 若连接处于 CLOSED 状态（如 404 或后端服务重启队列丢失，浏览器不再重连），立刻置 error 并关闭
      if (eventSource.readyState === EventSource.CLOSED) {
        console.warn(`🛑 [SSE] 服务端连接已关闭或任务已不存在 (${task.id})，标记为错误终止`)
        useCrawlerTaskStore.getState().updateTaskStatus(task.id, 'error', '任务连接已中断（服务端不存在或已重启）')
        closeEventSource()
        return
      }

      // 🌟 连续重试失败上限保护：防止后台进程宕机或断网时无休止重连达 1 小时卡住卡片
      reconnectFailuresRef.current += 1
      if (reconnectFailuresRef.current >= 8) {
        console.warn(`🛑 [SSE] 连续 8 次重连失败 (${task.id})，判定服务离线或网络断开`)
        useCrawlerTaskStore.getState().updateTaskStatus(task.id, 'error', '无法连接到任务通道（服务离线或重试超时）')
        closeEventSource()
        return
      }

      if (Date.now() - currentTask.startTime > 3600_000) {
        useCrawlerTaskStore.getState().updateTaskStatus(task.id, 'error', '任务已过期（重启后未完成）')
        closeEventSource()
        return
      }

      // pending/running/cleaning 阶段且处于 CONNECTING 时保留连接，让浏览器原生自动重连
      console.warn(`⚠️ [SSE] 连接暂时重试中 (${task.id}, 次数: ${reconnectFailuresRef.current}):`, eventSource.readyState)
    }

    return () => {
      if (eventSourceRef.current && eventSourceRef.current.readyState !== EventSource.CLOSED) {
        eventSourceRef.current.close()
      }
      eventSourceRef.current = null
    }
  }, [task.id])

  return null
}

export function LiveTaskTerminal({ 
  title = "任务流看板", 
  onMinimize,
  onClose,
  onComplete,
  onSseMessage,
  showToolbar = false,
  showInternalHeader = true
}: LiveTaskTerminalProps) {
  const { tasks, clearTasks, removeTask } = useCrawlerTaskStore()
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null)
  const taskList = Object.values(tasks).sort((a, b) => b.startTime - a.startTime)

  const handleCancelTask = async (taskId: string) => {
    if (cancellingTaskId === taskId) return
    setCancellingTaskId(taskId)
    toast.info("已发送终止指令，正在安全清理...")
    try {
      const res = await fetch(`${MAIN_API_BASE}/v1/crawlers/cancel/${taskId}`, { method: 'POST' })
      if (res.ok) {
        toast.success("终止指令已生效")
      } else {
        const data = await res.json().catch(() => ({}))
        toast.error(`终止请求失败: ${data.detail || "服务繁忙"}`)
      }
    } catch (e) {
      console.error("终止任务失败", e)
      toast.error("网络异常，无法连接到终止服务")
    } finally {
      setCancellingTaskId(null)
    }
  }

  const getPlatformIcon = (platform: string, taskId?: string) => {
    if (taskId?.startsWith('clean_hard_')) return <div className="w-8 h-8 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-100 flex items-center justify-center shrink-0 shadow-sm" title="纯硬规则初筛"><Filter className="w-4 h-4" /></div>
    if (taskId?.startsWith('clean_ai_')) return <div className="w-8 h-8 rounded-full bg-purple-50 text-purple-600 border border-purple-100 flex items-center justify-center shrink-0 shadow-sm" title="AI深度排雷"><Bot className="w-4 h-4" /></div>
    if (taskId?.startsWith('skip_ai_')) return <div className="w-8 h-8 rounded-full bg-amber-50 text-amber-600 border border-amber-100 flex items-center justify-center shrink-0 shadow-sm" title="免AI直推"><Zap className="w-4 h-4" /></div>
    if (taskId?.startsWith('sync_feishu_')) return <div className="w-8 h-8 rounded-full bg-sky-50 text-sky-600 border border-sky-100 flex items-center justify-center shrink-0 shadow-sm" title="推送飞书"><Send className="w-4 h-4" /></div>
    if (taskId?.startsWith('clean_global_')) return <div className="w-8 h-8 rounded-full bg-indigo-50 text-indigo-600 border border-indigo-100 flex items-center justify-center shrink-0 shadow-sm" title="全平台联合清洗"><Layers className="w-4 h-4" /></div>
    switch (platform) {
      case 'boss': return <div className="w-8 h-8 rounded-full bg-[#00c8c8] text-white flex items-center justify-center font-bold text-xs shrink-0">B</div>
      case 'liepin': return <div className="w-8 h-8 rounded-full bg-[#ff6b00] text-white flex items-center justify-center font-bold text-xs shrink-0">猎</div>
      case '51job': return <div className="w-8 h-8 rounded-full bg-[#ffeb00] text-[#ff6b00] flex items-center justify-center font-bold text-xs shrink-0">51</div>
      case 'xiaohongshu': return <div className="w-8 h-8 rounded-full bg-[#FF2442] text-white flex items-center justify-center font-bold text-[10px] shrink-0">RED</div>
      case 'zhilian': return <div className="w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center font-bold text-xs shrink-0">Z</div>
      default: return <Bug className="w-8 h-8 p-1.5 rounded-full bg-slate-100 text-slate-500 shrink-0" />
    }
  }

  const getTaskTitle = (task: CrawlerTask) => {
    if (task.id.startsWith('clean_hard_')) return '纯硬规则初筛'
    if (task.id.startsWith('clean_ai_')) return 'AI深度排雷'
    if (task.id.startsWith('skip_ai_')) return '免AI直推飞书'
    if (task.id.startsWith('sync_feishu_')) return '推送至飞书'
    const nameMap: Record<string, string> = { global: '全平台联合清洗', boss: 'BOSS直聘', liepin: '猎聘', zhilian: '智联招聘', xiaohongshu: '小红书', '51job': '前程无忧' }
    return nameMap[task.platform] || '求职任务'
  }

  const getStatusBadge = (task: CrawlerTask) => {
    const isCleaner = task.platform === 'global' || task.id.startsWith('clean_') || task.id.startsWith('skip_') || task.id.startsWith('sync_')
    switch (task.status) {
      case 'pending': return <span className="flex items-center text-xs font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full"><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 等待中</span>
      case 'running': return <span className="flex items-center text-xs font-medium text-blue-600 bg-blue-50 border border-blue-100 px-2 py-0.5 rounded-full"><span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse mr-1.5" /> {isCleaner ? '处理中' : '抓取中'}</span>
      case 'cleaning': return <span className="flex items-center text-xs font-medium text-purple-600 bg-purple-50 border border-purple-100 px-2 py-0.5 rounded-full"><CheckCircle2 className="w-3 h-3 mr-1 text-purple-500" /> {task.platform === 'global' ? '清洗中' : '爬虫✅ 清洗中'}<span className="w-1 h-1 rounded-full bg-purple-500 animate-pulse ml-1.5" /></span>
      case 'completed': return <span className="flex items-center text-xs font-medium text-emerald-600 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded-full"><CheckCircle2 className="w-3 h-3 mr-1" /> {task.platform === 'xiaohongshu' ? '爬虫✅ 清洗✅' : '已完成'}</span>
      case 'terminated': return <span className="flex items-center text-xs font-medium text-slate-500 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-full"><Ban className="w-3 h-3 mr-1" /> 已终止</span>
      case 'error': return <span className="flex items-center text-xs font-medium text-rose-600 bg-rose-50 border border-rose-100 px-2 py-0.5 rounded-full"><AlertCircle className="w-3 h-3 mr-1" /> 异常</span>
    }
  }

  return (
    <div className="h-full bg-slate-50 transition-all duration-300 flex flex-col overflow-hidden w-full">
      {/* 隐式挂载所有处于活跃周期的 SSE 监听器（已完成/异常/终止的历史记录不占用组件实例） */}
      {taskList
        .filter(task => ['pending', 'running', 'cleaning'].includes(task.status))
        .map(task => (
          <TaskSseConnection 
            key={task.id} 
            task={task} 
            onComplete={onComplete}
            onSseMessage={onSseMessage}
          />
        ))}

      {showInternalHeader && (
        <div className={`px-4 flex items-center border-b border-gray-100 bg-white shrink-0 ${showToolbar ? 'h-12 justify-between' : 'h-10'}`}>
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-gray-700" />
            <span className="text-sm font-medium text-gray-800">{title}</span>
            <span className="text-xs text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded-md ml-2">{taskList.length} 个任务</span>
          </div>
          {showToolbar && (
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-slate-500 hover:text-rose-600 hover:bg-rose-50" onClick={clearTasks} title="清空全部">
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
              {onMinimize && <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-slate-500 hover:bg-slate-100" onClick={onMinimize} title="最小化"><Minimize2 className="h-3.5 w-3.5" /></Button>}
              {onClose && <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-slate-500 hover:text-rose-600 hover:bg-rose-50" onClick={onClose} title="关闭"><X className="h-3.5 w-3.5" /></Button>}
            </div>
          )}
        </div>
      )}

      {/* Task Cards List */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 relative">
        
        {/* 如果有任务，在列表顶部显示一键清空按钮 */}
        {taskList.length > 0 && (
          <div className="flex justify-between items-center mb-2 pb-2 border-b border-slate-100">
            <span className="text-xs font-medium text-slate-500">当前任务记录 ({taskList.length})</span>
            <Button 
              variant="ghost" 
              size="sm" 
              className="h-6 px-2 text-xs text-slate-500 hover:text-rose-600 hover:bg-rose-50" 
              onClick={clearTasks}
            >
              <Trash2 className="h-3 w-3 mr-1" /> 清空全部
            </Button>
          </div>
        )}
        {taskList.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 space-y-3">
            <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center">
              <Play className="w-5 h-5 ml-1 text-slate-300" />
            </div>
            <p className="text-sm">当前无爬虫任务运行，请前往蜘蛛引擎启动</p>
          </div>
        ) : (
          taskList.map((task, index) => {
            const progressPercent = task.targetJobs > 0 ? Math.min(100, (task.totalInserted / task.targetJobs) * 100) : 0
            const isCleanHard = task.id.startsWith('clean_hard_')
            const isCleanAi = task.id.startsWith('clean_ai_')
            const isSkipAi = task.id.startsWith('skip_ai_')
            const isSyncFeishu = task.id.startsWith('sync_feishu_')
            const isGlobalJoint = task.platform === 'global' && !isCleanHard && !isCleanAi && !isSkipAi && !isSyncFeishu

            const showHardClean = isCleanHard || isGlobalJoint
            const showAiScout = isCleanAi || isGlobalJoint
            const showFeishuSync = isSyncFeishu || isSkipAi || isGlobalJoint
            
            return (
              <div key={task.id} className="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4 relative overflow-hidden group hover:shadow-md transition-shadow">
                
                {/* 顶部按钮区 */}
                <div className="absolute top-3 right-3 flex items-center gap-1 z-10">
                  <button 
                    onClick={() => removeTask(task.id)} 
                    className="text-slate-300 hover:text-rose-500 transition-colors p-1"
                    title="删除任务记录"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="flex items-start gap-4 pr-10">
                  <div className="flex flex-col items-center gap-2">
                    {getPlatformIcon(task.platform, task.id)}
                    {['pending', 'running', 'cleaning'].includes(task.status) && (
                      <button 
                        onClick={() => handleCancelTask(task.id)}
                        disabled={cancellingTaskId === task.id}
                        className={`flex items-center justify-center w-8 h-8 rounded-full text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all shadow-sm border border-transparent hover:border-rose-100 ${cancellingTaskId === task.id ? 'opacity-60 cursor-not-allowed' : ''}`}
                        title="强制终止任务"
                      >
                        {cancellingTaskId === task.id ? (
                          <Loader2 className="w-4 h-4 animate-spin text-rose-500" />
                        ) : (
                          <StopCircle className="w-4 h-4" />
                        )}
                      </button>
                    )}
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center mb-2 min-w-0">
                      <h4 className="font-semibold text-sm text-slate-800 truncate mr-2">
                        任务 {taskList.length - index}：{getTaskTitle(task)}
                      </h4>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {task.currentPage && ['running', 'cleaning'].includes(task.status) && (
                          <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded font-medium whitespace-nowrap">第 {task.currentPage} 页</span>
                        )}
                        <div className="whitespace-nowrap">
                          {getStatusBadge(task)}
                        </div>
                      </div>
                    </div>

                    <div className="space-y-1 mb-3">
                      <div className="text-xs text-slate-600 font-medium truncate">
                        {task.platform === 'xiaohongshu' ? `${task.keyword}` : `${task.city} · ${task.keyword}`} 
                        {task.platform !== 'xiaohongshu' && <span className="opacity-60 font-normal"> ({task.salary})</span>}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {new Date(task.startTime).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).replace(/\//g, '-')}
                      </div>
                    </div>

                    {task.platform === 'global' ? (
                      <div className="mt-4 space-y-3">
                        {showHardClean && (
                          <PhaseProgressRow title="硬性规则拦截" progress={task.hardCleanProgress} isTerminated={task.status === 'terminated'} isError={task.status === 'error'} />
                        )}
                        {showAiScout && (
                          <PhaseProgressRow title="AI初筛侦察" progress={task.aiScoutProgress} isTerminated={task.status === 'terminated'} isError={task.status === 'error'} />
                        )}
                        {showFeishuSync && (
                          <PhaseProgressRow title="推送飞书" progress={task.feishuSyncProgress} isTerminated={task.status === 'terminated'} isError={task.status === 'error'} />
                        )}
                      </div>
                    ) : (
                      <div className="space-y-1.5 pr-2">
                        <div className="flex justify-between items-center text-[10px] font-medium text-slate-400">
                          <span>进度</span>
                          <span>{Math.round(progressPercent)}%</span>
                        </div>
                        <Progress value={progressPercent} className="h-1.5 bg-slate-100" />
                      </div>
                    )}
                    
                    {task.errorMessage && (
                      <div className="mt-2 text-xs text-rose-500 bg-rose-50 px-2 py-1.5 rounded-md border border-rose-100 break-words">
                        {task.errorMessage}
                      </div>
                    )}
                  </div>

                  {/* 居中偏右的数字进度 */}
                  {task.platform !== 'global' && (
                    <div className="shrink-0 flex items-center self-center pl-2 ml-auto">
                      <span className="text-lg font-bold text-slate-700 whitespace-nowrap">
                        {task.totalInserted}
                        <span className="text-slate-400 text-sm font-medium mx-1">/</span>
                        <span className="text-slate-400 text-sm font-medium">{task.targetJobs}</span>
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
