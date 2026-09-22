"use client"

import React, { useState, useEffect, useRef } from "react"
import { Textarea } from "@/components/ui/textarea"
import { API_BASE } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Bot, Send, Sparkles, CheckCircle2, XCircle, Mic, MicOff, Radio } from "lucide-react"
import { useDualChannelVoice } from "@/hooks/use-dual-channel-voice"

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

export interface Block {
  id: number
  original_content: string
  new_content: string
  is_modified: boolean
}

export interface ExperienceGrillerProps {
  originalExperience: string
  onAccept: (newContent: string) => void
  onCancel: () => void
  customJdContext?: string
  fullResumeContext?: string
}


export function ExperienceGriller({ originalExperience, onAccept, onCancel, customJdContext, fullResumeContext }: ExperienceGrillerProps) {
  const [mode, setMode] = useState<'grilling' | 'done'>('grilling')
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([])
  const [currentQuestion, setCurrentQuestion] = useState<{ text: string, options: string[] } | null>(null)
  const [inputValue, setInputValue] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [blocks, setBlocks] = useState<Block[]>([])
  const [acceptedBlockIds, setAcceptedBlockIds] = useState<Set<number>>(new Set())
  const [currentTurn, setCurrentTurn] = useState(1)

  const { isRecording, activeEngine, streamingText, toggleRecording, clearStreamingText, stopRecording } = useDualChannelVoice((finalText) => {
    setInputValue(prev => (prev ? `${prev} ${finalText}` : finalText).trim())
  })

  const [jdReportContext, setJdReportContext] = useState("")
  // SSE 真进度：阶段文案 / 已生成字数 / 已等待秒数（grill 输出为 JSON 协议，不逐字渲染，用字数做活跃感）
  const [streamStage, setStreamStage] = useState("")
  const [streamChars, setStreamChars] = useState(0)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const initRef = useRef(false)
  // 面板卸载时中断在飞的拷问请求；新一轮提问会自动中断上一轮
  const grillAbortRef = useRef<AbortController | null>(null)
  useEffect(() => () => grillAbortRef.current?.abort(), [])

  useEffect(() => {
    if (!isLoading) return
    setElapsedSeconds(0)
    const timer = setInterval(() => setElapsedSeconds(s => s + 1), 1000)
    return () => clearInterval(timer)
  }, [isLoading])

  useEffect(() => {
    if (!initRef.current) {
      initRef.current = true

      if (customJdContext !== undefined) {
        setJdReportContext(customJdContext)
        handleGrillRequest([], false, customJdContext)
      } else {
        fetch(`${API_BASE}/api/strategy/get_jd_report`)
          .then(res => res.json())
          .then(data => {
             if (data.status === "success" && data.data) {
               setJdReportContext(data.data)
               handleGrillRequest([], false, data.data)
             } else {
               handleGrillRequest([], false, "")
             }
          })
          .catch(() => handleGrillRequest([], false, ""))
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleGrillRequest = async (history: ChatMessage[], isForceFinish: boolean = false, contextStr: string = jdReportContext) => {
    setIsLoading(true)
    setStreamStage("正在连接面试官…")
    setStreamChars(0)
    grillAbortRef.current?.abort()
    const controller = new AbortController()
    grillAbortRef.current = controller
    try {
      const res = await fetch(`${API_BASE}/api/strategy/grill_experience_stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          original_experience: originalExperience,
          chat_history: history,
          current_turn: isForceFinish ? 4 : currentTurn,
          jd_report_context: contextStr,
          full_resume_context: fullResumeContext
        })
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      // 手写 SSE 帧解析（POST 无法用 EventSource）：sse_starlette 以 CRLF 分隔，按空行分帧兼容 LF/CRLF
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let finalData: { question: string, suggested_options: string[], is_finished: boolean, blocks: Block[] } | null = null
      let errMsg = ""
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split(/\r?\n\r?\n/)
        buffer = frames.pop() || ""
        for (const frame of frames) {
          let eventName = "message"
          let dataStr = ""
          for (const line of frame.split(/\r?\n/)) {
            const text = line.trim()
            if (text.startsWith("event:")) eventName = text.slice(6).trim()
            else if (text.startsWith("data:")) dataStr += text.slice(5).trim()
          }
          if (!dataStr) continue
          let payload: any
          try { payload = JSON.parse(dataStr) } catch { continue }
          if (eventName === "stage") setStreamStage(payload.message || "模型已响应，正在生成…")
          else if (eventName === "progress") setStreamChars(payload.chars || 0)
          else if (eventName === "final") finalData = payload
          else if (eventName === "error") errMsg = payload.message || "服务异常，请稍后重试"
        }
      }
      if (controller.signal.aborted) return
      if (finalData) {
        const { question, suggested_options, is_finished, blocks: responseBlocks } = finalData
        if (is_finished) {
          setMode('done')
          const finalBlocks: Block[] = responseBlocks || []
          setBlocks(finalBlocks)
          // 默认全选修改过的区块
          setAcceptedBlockIds(new Set(finalBlocks.filter(b => b.is_modified).map(b => b.id)))
        } else {
          setCurrentQuestion({ text: question, options: suggested_options || [] })
          setChatHistory(prev => [...prev, { role: "assistant", content: question }])
          setCurrentTurn(prev => prev + 1)
        }
      } else {
        alert("❌ 拷问请求失败: " + (errMsg || "连接中断或响应异常，请重试"))
      }
    } catch (err) {
      if (controller.signal.aborted) return
      alert("❌ 网络请求错误")
    } finally {
      if (!controller.signal.aborted) setIsLoading(false)
    }
  }

  const handleSend = () => {
    // If there's streaming text that hasn't been committed, we use it directly
    const combined = (inputValue + (streamingText ? (inputValue ? " " : "") + streamingText : "")).trim()
    if (!combined) return
    
    // Clear voice state explicitly to prevent trailing issues
    clearStreamingText()
    if (isRecording) {
      stopRecording()
    }
    
    const newHistory: ChatMessage[] = [...chatHistory, { role: "user", content: combined }]
    setChatHistory(newHistory)
    setInputValue("")
    setCurrentQuestion(null)
    handleGrillRequest(newHistory)
  }

  const handleExtractDetails = () => {
    // 捕获用户在文本框里输入的最后一段回答，以及可能的语音流缓冲
    const combinedInput = (inputValue + (streamingText ? (inputValue ? " " : "") + streamingText : "")).trim()
    clearStreamingText()
    if (isRecording) {
      stopRecording()
    }
    
    // 如果用户输入了回答，则将其与结束指令合并
    let finalContent = "我已经没有更多细节了，结束拷问，请帮我提取隐藏细节。"
    if (combinedInput) {
      finalContent = `${combinedInput}\n\n（以上是最后补充的细节。我现在已经没有更多细节了，请结束拷问，帮我提取隐藏细节。）`
    }

    const newHistory: ChatMessage[] = [...chatHistory, { role: "user", content: finalContent }]
    setChatHistory(newHistory)
    setInputValue("")
    setCurrentQuestion(null)
    handleGrillRequest(newHistory, true)
  }

  const handleAccept = () => {
    // 缝合所有区块，被采纳的用新内容，未被采纳的保持原内容
    const finalContent = blocks
      .map(b => acceptedBlockIds.has(b.id) ? b.new_content : b.original_content)
      .join("\n\n")
    onAccept(finalContent.trim())
  }

  const toggleBlockAcceptance = (id: number) => {
    const newSet = new Set(acceptedBlockIds)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    setAcceptedBlockIds(newSet)
  }

  return (
    <div className="mt-3 rounded-xl border border-orange-200 bg-orange-50/60 p-4 duration-200 animate-in fade-in slide-in-from-top-2">
      {chatHistory.length > 0 && mode === 'grilling' && (
        <div className="space-y-3 mb-4 max-h-60 overflow-y-auto pr-2">
          {chatHistory.map((msg, i) => {
             // 隐藏当前正在被回答的问题
             if (i === chatHistory.length - 1 && msg.role === 'assistant' && currentQuestion) return null; 
             return (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${msg.role === 'user' ? 'bg-orange-100 text-orange-900' : 'bg-white text-gray-700 border border-gray-200'}`}>
                  {msg.content}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {mode === 'grilling' && currentQuestion && (
        <div className="flex gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-orange-500 to-rose-500 text-white">
            <Bot className="h-5 w-5" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium leading-relaxed text-foreground mb-3">
              {currentQuestion.text}
            </p>
            
            {currentQuestion.options && currentQuestion.options.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {currentQuestion.options.map((opt, idx) => (
                  <button 
                    key={idx}
                    onClick={() => setInputValue(opt)}
                    className="text-xs bg-white border border-orange-200 text-orange-700 hover:bg-orange-100 px-3 py-1.5 rounded-full transition-colors text-left"
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}

            <div className="relative">
              <Textarea 
                value={inputValue + (streamingText ? (inputValue ? " " : "") + streamingText : "")}
                onChange={(e) => {
                  setInputValue(e.target.value)
                  clearStreamingText()
                }}
                placeholder={isRecording ? (activeEngine === "volc" ? "🎙️ 豆包大模型聆听中…" : "🎙️ 浏览器原生语音聆听中…") : "补充细节..."}
                className={`min-h-20 resize-y bg-white pr-10 ${isRecording ? 'border-orange-300 ring-2 ring-orange-100' : ''}`} 
                disabled={isLoading}
              />
              <button
                onClick={toggleRecording}
                disabled={isLoading}
                title={isRecording ? "停止录音" : "语音输入 (优先豆包大模型，自动降级)"}
                className={`absolute right-2 bottom-2 w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                  isRecording 
                    ? "bg-red-500 text-white shadow-md shadow-red-500/30 animate-pulse" 
                    : "bg-gray-100 text-gray-500 hover:text-gray-700 hover:bg-gray-200"
                }`}
              >
                {isRecording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
              </button>
            </div>
            
            {isRecording && (
              <div className="mt-2 flex items-center justify-end">
                <span className={`flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full ${
                  activeEngine === "volc"
                    ? "bg-indigo-500/10 text-indigo-600"
                    : "bg-amber-500/10 text-amber-600"
                }`}>
                  <Radio className="h-2.5 w-2.5" />
                  {activeEngine === "volc" ? "豆包流式 ASR" : "Edge 原生语音"}
                </span>
              </div>
            )}

            <div className={`flex flex-wrap gap-2 items-center justify-between ${isRecording ? 'mt-1' : 'mt-3'}`}>
              <div className="flex gap-2">
                <Button 
                  size="sm" 
                  onClick={handleSend}
                  disabled={isLoading || !inputValue.trim()}
                  className="bg-gradient-to-r from-orange-500 to-rose-500 text-white shadow-sm hover:from-orange-600 hover:to-rose-600"
                >
                  <Send className="mr-1.5 h-4 w-4" />
                  {isLoading ? '发送中...' : '发送'}
                </Button>
                <Button 
                  variant="outline" 
                  size="sm" 
                  onClick={handleExtractDetails}
                  disabled={isLoading}
                  className="bg-white border-orange-200 text-orange-600 hover:bg-orange-50 hover:text-orange-700"
                >
                  <Sparkles className="mr-1.5 h-4 w-4" />
                  📥 结束拷问，提取隐藏细节
                </Button>
              </div>
              <Button variant="ghost" size="sm" onClick={onCancel} className="text-gray-500 hover:text-gray-700">
                取消
              </Button>
            </div>
          </div>
        </div>
      )}

      {isLoading && !currentQuestion && mode === 'grilling' && (
        <div className="flex flex-col gap-1 text-sm text-orange-600 font-medium p-2">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 animate-bounce shrink-0" />
            <span className="flex-1">{streamStage || "面试官正在思考下一个问题..."}</span>
            <span className="text-xs font-normal text-orange-400">已等待 {elapsedSeconds}s</span>
            <button onClick={onCancel} className="text-xs font-normal text-gray-400 hover:text-gray-600 underline">
              取消
            </button>
          </div>
          {streamChars > 0 && (
            <div className="ml-6 text-xs font-normal text-orange-400">已生成 {streamChars} 字…</div>
          )}
        </div>
      )}

      {mode === 'done' && (
        <div className="bg-white rounded-xl border border-indigo-200 p-5 shadow-sm mt-3 animate-in fade-in slide-in-from-bottom-2">
          <div className="flex items-center gap-2 text-indigo-600 font-medium mb-4 pb-3 border-b border-indigo-100">
            <CheckCircle2 className="h-5 w-5" />
            <span>AI 挖掘与重写完成，请按区块挑选采纳：</span>
          </div>
          
          <div className="space-y-4 mb-6">
            {blocks.map((block) => (
              <div 
                key={block.id} 
                className={`relative rounded-lg border p-4 transition-all ${
                  !block.is_modified 
                    ? 'bg-gray-50 border-gray-200 opacity-80' 
                    : acceptedBlockIds.has(block.id)
                      ? 'bg-indigo-50/50 border-indigo-300 shadow-sm ring-1 ring-indigo-200'
                      : 'bg-white border-gray-200 hover:border-indigo-200'
                }`}
              >
                {!block.is_modified && (
                  <div className="absolute top-2 right-3 text-xs text-gray-400 font-medium bg-gray-100 px-2 py-0.5 rounded-full">
                    无需修改
                  </div>
                )}
                {block.is_modified && (
                  <div className="absolute top-3 right-3">
                    <label className="flex items-center gap-2 cursor-pointer text-sm font-medium">
                      <input 
                        type="checkbox" 
                        checked={acceptedBlockIds.has(block.id)}
                        onChange={() => toggleBlockAcceptance(block.id)}
                        className="w-4 h-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500 cursor-pointer"
                      />
                      <span className={acceptedBlockIds.has(block.id) ? "text-indigo-700" : "text-gray-500"}>
                        {acceptedBlockIds.has(block.id) ? '已采纳此修改' : '采纳此修改'}
                      </span>
                    </label>
                  </div>
                )}
                
                <div className="space-y-3 mt-1">
                  {block.is_modified && (
                    <div className="text-[13px] text-gray-500 line-through pr-24">
                      {block.original_content}
                    </div>
                  )}
                  <div className={`text-sm ${block.is_modified && acceptedBlockIds.has(block.id) ? 'text-indigo-900 font-medium' : 'text-gray-700'}`}>
                    <div className="whitespace-pre-wrap leading-relaxed">
                      {block.is_modified ? block.new_content : block.original_content}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between pt-4 border-t border-gray-100">
            <div className="text-sm text-gray-500">
              已选中 <span className="font-semibold text-indigo-600">{acceptedBlockIds.size}</span> 个优化区块
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={onCancel} className="text-gray-600">
                <XCircle className="mr-1.5 h-4 w-4" />
                放弃全部
              </Button>
              <Button 
                size="sm" 
                onClick={handleAccept}
                className="bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm"
              >
                <CheckCircle2 className="mr-1.5 h-4 w-4" />
                应用选中的修改
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
