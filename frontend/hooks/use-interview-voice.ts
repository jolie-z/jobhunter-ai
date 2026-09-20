import { useState, useRef, useCallback, useEffect, useMemo } from "react"
import type { JobData } from "@/types/job"
import type { QuestionItem } from "./use-question-bank"
import { API_BASE, WS_BASE } from "@/lib/api"
import { toast } from "@/hooks/use-toast"
import { parseInterviewRecords, removeRecordFromMarkdown, type InterviewRecordItem } from "@/lib/interview-record-parser"

export function useInterviewVoice(
  activeJobId: string, 
  activeJob: JobData | undefined,
  intelData: any,
  activeDrillQuestion: QuestionItem | null,
  interviewMode: string,
  isCoachMode: boolean
) {
  // 🌟 独立管控面试记录的状态
  const [currentTranscript, setCurrentTranscript] = useState("")
  const [isRefreshingHistory, setIsRefreshingHistory] = useState(false)
  const [endDialogConfig, setEndDialogConfig] = useState<{show: boolean, transcript: string, role: string, style: string}>({show: false, transcript: "", role: "business", style: "coach"})
  const [isSavingRecord, setIsSavingRecord] = useState(false)
  const [interviewMinutes, setInterviewMinutes] = useState(0)

  // 面试模拟状态
  const [isInterviewing, setIsInterviewing] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [chatLog, setChatLog] = useState<{role: 'ai' | 'user', text: string}[]>([])

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const mediaRecorderRef = useRef<any>(null)
  const isAiPlayingRef = useRef(false)
  const isManualStopRef = useRef(false)
  
  const chatLogRef = useRef(chatLog)
  useEffect(() => { chatLogRef.current = chatLog }, [chatLog])

  // 🌟 面试时长提醒（纯函数解耦，避免在 setState updater 产生副作用导致 StrictMode 下双重弹窗）
  useEffect(() => {
    if (!isInterviewing) return
    if (interviewMinutes === 30) {
      toast({
        title: "⏳ 面试时间提示",
        description: "当前对战已进行 30 分钟，请把控答题节奏。",
      })
    } else if (interviewMinutes === 60) {
      toast({
        title: "🛑 达到时间上限",
        description: "面试已达 60 分钟建议上限，建议点击结束面试并生成评估报告。",
        variant: "destructive",
      })
    }
  }, [interviewMinutes, isInterviewing])

  // 🌟 现场面经流水账状态
  const [liveRecord, setLiveRecord] = useState("")
  const [isShredding, setIsShredding] = useState(false)
  const [shreddedQuestions, setShreddedQuestions] = useState<{question: string, answer: string}[]>([])
  const [isRecording, setIsRecording] = useState(false)
  const [isSavingLive, setIsSavingLive] = useState(false)
  const [saveLiveError, setSaveLiveError] = useState<string | null>(null)
  
  const recognitionRef = useRef<any>(null)
  const saveLiveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sttWsRef = useRef<WebSocket | null>(null)
  const sttAudioCtxRef = useRef<AudioContext | null>(null)
  const sttStreamRef = useRef<MediaStream | null>(null)
  const sttProcessorRef = useRef<ScriptProcessorNode | null>(null)
  const baseRecordRef = useRef("")
  // 🌟 删除记录防重入：in-flight 期间忽略再次删除，避免并发覆盖写互相回滚冲掉（R1 审查 P2-4）
  const deleteInFlightRef = useRef(false)

  // 🌟 记录当前已同步过数据的岗位：详情异步抵达会改变 activeJob 的引用身份，
  // 若无条件重置状态，会把用户正在输入的流水账/粉碎结果反复打回旧值
  const syncedJobIdRef = useRef<string | null>(null)
  const isUserEditingRef = useRef(false)

  // 包装外部 setLiveRecord，标记用户主动输入，防止后续异步请求覆盖
  const handleSetLiveRecord = useCallback((val: string | ((prev: string) => string)) => {
    isUserEditingRef.current = true
    setLiveRecord(val)
  }, [])

  // 同步 job 的 transcript 与流水账
  useEffect(() => {
    if (!activeJob) return

    const isJobSwitch = syncedJobIdRef.current !== activeJobId
    if (isJobSwitch) {
      syncedJobIdRef.current = activeJobId
      isUserEditingRef.current = false
      setSaveLiveError(null)
      setCurrentTranscript((activeJob as any).interviewTranscript || (activeJob as any).interview_transcript || "")
      setLiveRecord((activeJob as any)?.live_interview_record || "")
      // 🌟 仅在真正切换岗位时清空粉碎结果
      setShreddedQuestions([])
      if (isRecording) {
        recognitionRef.current?.stop()
        setIsRecording(false)
      }
    } else {
      // 🌟 同岗位详情异步抵达（如 useJobDetail 返回）：
      // 严禁覆盖用户正在输入的内容；只有当用户未编辑且本地为空时才平滑补齐
      if (!isUserEditingRef.current && !liveRecord) {
        const incoming = (activeJob as any)?.live_interview_record
        if (incoming) setLiveRecord(incoming)
      }
      if (!currentTranscript) {
        const incomingT = (activeJob as any).interviewTranscript || (activeJob as any).interview_transcript
        if (incomingT) setCurrentTranscript(incomingT)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeJobId, activeJob])

  const debouncedSaveLiveFields = useCallback((record: string) => {
    if (!activeJob) return
    if (saveLiveTimerRef.current) clearTimeout(saveLiveTimerRef.current)
    saveLiveTimerRef.current = setTimeout(async () => {
      setIsSavingLive(true)
      try {
        const res = await fetch(`${API_BASE}/api/save_live_fields`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: activeJob.id, live_record: record }),
        })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new Error(data?.detail || `保存失败 (HTTP ${res.status})`)
        }
        setSaveLiveError(null)
      } catch (e: any) {
        console.error("自动保存失败:", e)
        setSaveLiveError(e?.message || "自动保存失败，请检查网络或飞书配置")
      } finally {
        setIsSavingLive(false)
      }
    }, 2000)
  }, [activeJob])

  // 🌟 返回成功入库的题目数（0 = 失败或未提取到），方便调用方决定是否刷新题库
  const handleShredInterview = async (): Promise<number> => {
    if (!activeJob) return 0
    if (!liveRecord.trim()) {
      toast({
        title: "⚠️ 提示",
        description: "请先在文本框中粘贴或输入你的面试流水账。",
      })
      return 0
    }
    setIsShredding(true)
    setShreddedQuestions([])
    try {
      const res = await fetch(`${API_BASE}/api/jobs/shred_interview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: activeJob.id, record_text: liveRecord })
      })
      const data = await res.json()
      if (!res.ok || data.status !== "success") {
        throw new Error(data.detail || "未知错误")
      }
      setShreddedQuestions(data.questions || [])
      if (activeJob) (activeJob as any).live_interview_record = liveRecord
      toast({
        title: "✅ 提取并入库成功",
        description: `成功提取 ${data.inserted_count}/${data.extracted_count} 道真题，已存入专属面经库！`,
      })
      return (data.questions || []).length
    } catch (e: any) {
      toast({
        title: "❌ 粉碎失败",
        description: e?.message || String(e),
        variant: "destructive",
      })
      return 0
    } finally {
      setIsShredding(false)
    }
  }

  const toggleVoiceRecording = useCallback(async () => {
    if (isRecording) {
      if (sttWsRef.current) {
        sttWsRef.current.onclose = null
        sttWsRef.current.close()
        sttWsRef.current = null
      }
      if (sttProcessorRef.current) {
        sttProcessorRef.current.onaudioprocess = null
        sttProcessorRef.current.disconnect()
        sttProcessorRef.current = null
      }
      sttAudioCtxRef.current?.close().catch(() => {})
      sttAudioCtxRef.current = null
      sttStreamRef.current?.getTracks().forEach(t => t.stop())
      sttStreamRef.current = null
      recognitionRef.current?.stop()
      recognitionRef.current = null
      setIsRecording(false)
      return
    }

    setLiveRecord(prev => {
      baseRecordRef.current = prev
      return prev
    })

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      })
    } catch {
      toast({
        title: "❌ 权限受限",
        description: "无法获取麦克风权限，请在浏览器地址栏允许录音权限。",
        variant: "destructive",
      })
      return
    }
    sttStreamRef.current = stream
    setIsRecording(true)

    const audioCtx = new ((window as any).AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 }) as AudioContext
    sttAudioCtxRef.current = audioCtx
    const source = audioCtx.createMediaStreamSource(stream)
    const processor = audioCtx.createScriptProcessor(4096, 1, 1)
    sttProcessorRef.current = processor
    const gainNode = audioCtx.createGain()
    gainNode.gain.value = 0
    source.connect(processor)
    processor.connect(gainNode)
    gainNode.connect(audioCtx.destination)

    const startFallback = () => {
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
      if (!SR) {
        toast({
          title: "❌ 语音识别不可用",
          description: "后端 ASR 服务不可用，且当前浏览器环境不支持原生语音识别 API。",
          variant: "destructive",
        })
        setIsRecording(false)
        return
      }
      const rec = new SR()
      rec.lang = "zh-CN"
      rec.continuous = true
      rec.interimResults = false
      rec.onresult = (event: any) => {
        let finalText = ""
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) finalText += event.results[i][0].transcript
        }
        if (finalText) {
          setLiveRecord(prev => {
            const updated = prev + (prev && !prev.endsWith("\n") ? "\n" : "") + finalText
            debouncedSaveLiveFields(updated)
            return updated
          })
        }
      }
      rec.onerror = (event: any) => {
        recognitionRef.current = null
        setIsRecording(false)
        if (event.error === "network") {
          toast({
            title: "❌ 网络异常",
            description: "浏览器原生语音识别网络断开，请检查网络设置。",
            variant: "destructive",
          })
        }
      }
      rec.onend = () => {
        if (recognitionRef.current === rec) {
          try { rec.start() } catch {}
        }
      }
      recognitionRef.current = rec
      rec.start()
    }

    const ws = new WebSocket(`${WS_BASE}/ws/stt`)
    sttWsRef.current = ws
    let hasFallenBack = false

    processor.onaudioprocess = (e) => {
      if (ws.readyState !== WebSocket.OPEN) return
      const float32 = e.inputBuffer.getChannelData(0)
      const pcm16 = new Int16Array(float32.length)
      for (let i = 0; i < float32.length; i++) {
        const s = Math.max(-1, Math.min(1, float32[i]))
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
      }
      ws.send(pcm16.buffer)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === "fallback") {
          if (hasFallenBack) return
          hasFallenBack = true
          startFallback()
        } else if (data.type === "text" && data.text) {
          setLiveRecord(() => {
            const separator = baseRecordRef.current && !baseRecordRef.current.endsWith("\n") ? "\n" : ""
            const updated = baseRecordRef.current + separator + data.text
            debouncedSaveLiveFields(updated)
            return updated
          })
        }
      } catch { }
    }

    ws.onerror = () => {
      if (hasFallenBack) return
      hasFallenBack = true
      startFallback()
    }

    ws.onclose = (e) => {
      if (!e.wasClean && !hasFallenBack) {
        hasFallenBack = true
        startFallback()
      }
    }
  }, [isRecording, debouncedSaveLiveFields])

  const startInterview = async () => {
    if (!activeJob) return

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } 
      })
      
      setIsInterviewing(true)
      setChatLog([])
      // 🌟 新会话开始必须复位手动停止标记：否则上一场手动停止残留的 true
      // 会让本场异常断线时误判为手动操作，吞掉「语音连接已断开」提示
      isManualStopRef.current = false

      const ws = new WebSocket(`${WS_BASE}/ws/interview/${activeJob.id}`)
      wsRef.current = ws

      let isFallbackMode = false
      let fallbackRecognition: any = null

      ws.onopen = () => {
        isAiPlayingRef.current = true

        ws.send(JSON.stringify({
          type: "init",
          role: activeDrillQuestion ? "special_drill" : interviewMode,
          style: isCoachMode ? "coach" : "real",
          system_prompt: intelData?.system_prompt || "你是一位极其严厉的大厂面试官。",
          drill_question: activeDrillQuestion?.question || "",
          drill_answer: activeDrillQuestion?.golden_answer || "",
        }))

        if (activeDrillQuestion?.record_id) {
          fetch(`${API_BASE}/api/questions/${activeDrillQuestion.record_id}/increment`, {
            method: "POST",
          }).catch(() => {})
        }

        setInterviewMinutes(0)
        timerRef.current = setInterval(() => {
          setInterviewMinutes(prev => prev + 1)
        }, 60000)
      }
      
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        const unlockMic = (delay = 800) => {
          setTimeout(() => {
            if (isAiPlayingRef.current) isAiPlayingRef.current = false
          }, delay)
        }

        if (data.type === 'text') {
          setChatLog(prev => [...prev, { role: data.role, text: data.content }])
        } else if (data.type === 'user_text_replace') {
          setChatLog(prev => {
            const newLog = [...prev]
            const lastMsg = newLog[newLog.length - 1]
            if (lastMsg?.role === 'user') lastMsg.text = data.content
            else newLog.push({ role: 'user', text: data.content })
            return newLog
          })
        } else if (data.type === 'audio') {
          isAiPlayingRef.current = true
          const audio = new Audio("data:audio/mp3;base64," + data.audio_base64)
          ;(window as any).currentAiAudio = audio
          audio.onended = () => unlockMic(800)
          audio.play().catch(() => unlockMic(0))
          setTimeout(() => unlockMic(0), 15000) 
        } else if (data.type === 'native_tts') {
          isAiPlayingRef.current = true
          const utterance = new SpeechSynthesisUtterance(data.text)
          utterance.lang = 'zh-CN'
          utterance.rate = 1.05
          const voices = window.speechSynthesis.getVoices()
          const premiumVoice = voices.find(v => 
            v.name.includes('Xiaoxiao') || v.name.includes('Yunxi') || v.name.includes('Neural') || v.name.includes('Google')
          )
          if (premiumVoice) utterance.voice = premiumVoice
          utterance.onend = () => unlockMic(800)
          utterance.onerror = () => unlockMic(0)
          ;(window as any)._keepAliveUtterance = utterance
          window.speechSynthesis.speak(utterance)
          const expectedMs = Math.max(3000, data.text.length * 350)
          setTimeout(() => unlockMic(0), expectedMs + 2000)
        } else if (data.status === 'fallback') {
          if (isFallbackMode) return
          isFallbackMode = true
          const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
          if (!SpeechRecognition) return

          fallbackRecognition = new SpeechRecognition()
          fallbackRecognition.continuous = true
          fallbackRecognition.interimResults = false
          fallbackRecognition.lang = 'zh-CN'
          fallbackRecognition.onresult = (e: any) => {
            if (isAiPlayingRef.current) return
            for (let i = e.resultIndex; i < e.results.length; ++i) {
              if (e.results[i].isFinal) {
                const text = e.results[i][0].transcript
                if (ws.readyState === WebSocket.OPEN) {
                  ws.send(JSON.stringify({ type: "user_fallback_text", text: text }))
                }
              }
            }
          }
          fallbackRecognition.onend = () => {
            if (isFallbackMode && ws.readyState === WebSocket.OPEN) fallbackRecognition.start()
          }
          fallbackRecognition.start()
          if (mediaRecorderRef.current) (mediaRecorderRef as any).current.fallbackRecognition = fallbackRecognition
          else (mediaRecorderRef as any).current = { fallbackRecognition }
        }
      }

      ws.onerror = () => {
        toast({
          title: "❌ 语音连接异常",
          description: "与 AI 面试官服务建立连接失败，请检查网络或后端状态。",
          variant: "destructive",
        })
      }

      ws.onclose = (event) => {
        const isManual = isManualStopRef.current
        isManualStopRef.current = false
        stopInterview()
        if (!isManual && !event.wasClean) {
          toast({
            title: "⚠️ 语音连接已断开",
            description: "与 AI 面试官的服务连接异常中断，请检查服务后重新进入。",
            variant: "destructive",
          })
        }
      }

      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 })
      const source = audioContext.createMediaStreamSource(stream)
      const processor = audioContext.createScriptProcessor(4096, 1, 1)
      const gainNode = audioContext.createGain()
      gainNode.gain.value = 0

      source.connect(processor)
      processor.connect(gainNode)
      gainNode.connect(audioContext.destination)

      processor.onaudioprocess = (e) => {
        if (!isFallbackMode && ws.readyState === WebSocket.OPEN) {
          const float32Array = e.inputBuffer.getChannelData(0)
          let volume = 0
          for (let i = 0; i < float32Array.length; i++) volume += Math.abs(float32Array[i])
          const avgVolume = volume / float32Array.length

          if (isAiPlayingRef.current) {
             if (avgVolume > 0.05) {
                 const currentRef = mediaRecorderRef.current as any
                 if (!currentRef) return
                 currentRef.bargeInCounter = (currentRef.bargeInCounter || 0) + 1
                 if (currentRef.bargeInCounter > 2) {
                     isAiPlayingRef.current = false
                     currentRef.bargeInCounter = 0
                     if ((window as any).currentAiAudio) {
                       (window as any).currentAiAudio.pause()
                       (window as any).currentAiAudio.currentTime = 0
                     }
                     if (window.speechSynthesis) window.speechSynthesis.cancel()
                     ws.send(JSON.stringify({ action: "interrupt" }))
                 }
             } else {
                 if (mediaRecorderRef.current) (mediaRecorderRef.current as any).bargeInCounter = 0
             }
          }

          const pcm16 = new Int16Array(float32Array.length)
          if (isAiPlayingRef.current || isPaused) {
             ws.send(pcm16.buffer)
             return
          }
          for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]))
            pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
          }
          ws.send(pcm16.buffer)
        }
      }
      ;(mediaRecorderRef as any).current = { stream, audioContext, processor, gainNode, source }
    } catch (err) {
      toast({
        title: "❌ 权限受限",
        description: "无法获取麦克风权限，请检查系统与浏览器麦克风权限设置！",
        variant: "destructive",
      })
    }
  }

  const stopInterview = async () => {
    isManualStopRef.current = true
    setIsInterviewing(false)
    setIsPaused(false)
    if (timerRef.current) clearInterval(timerRef.current)
    setInterviewMinutes(0)
    if (window.speechSynthesis) window.speechSynthesis.cancel()
    
    if (mediaRecorderRef.current) {
      const { stream, audioContext, processor, gainNode, source, fallbackRecognition } = (mediaRecorderRef.current as any)
      if (fallbackRecognition) {
        fallbackRecognition.onend = null
        fallbackRecognition.stop()
      }
      if (processor) processor.onaudioprocess = null
      processor?.disconnect()
      gainNode?.disconnect()
      source?.disconnect()
      stream?.getTracks().forEach((track: MediaStreamTrack) => track.stop())
      audioContext?.close().catch(() => {})
      mediaRecorderRef.current = null
    }

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "stop" }))
      wsRef.current.close()
    }
    wsRef.current = null

    if (chatLogRef.current.length > 1) {
      const transcript = chatLogRef.current.map(m => `**${m.role === 'ai' ? '🗣️ 面试官' : '👤 我'}**: ${m.text}`).join('\n\n')
      setEndDialogConfig({ show: true, transcript, role: interviewMode, style: isCoachMode ? "coach" : "real" })
    }
  }

  const togglePause = () => {
    const newPaused = !isPaused
    setIsPaused(newPaused)
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "pause", state: newPaused }))
    }
  }

  const refreshHistory = async () => {
    if (!activeJobId) return
    setIsRefreshingHistory(true)
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${activeJobId}/transcript`)
      const data = await res.json()
      if (data.status === "success") setCurrentTranscript(data.transcript)
    } catch (e) {
    } finally {
      setIsRefreshingHistory(false)
    }
  }

  const handleSaveTranscript = async (generateReport: boolean) => {
    setIsSavingRecord(true)
    try {
      const res = await fetch(`${API_BASE}/api/save_transcript`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: activeJobId,
          transcript: endDialogConfig.transcript,
          generate_report: generateReport,
          jd_text: activeJob?.jdText || "",
          role: endDialogConfig.role,
          style: endDialogConfig.style
        })
      })
      const data = await res.json()
      // 🌟 Q-M8-1：后端写失败返回 {"status":"failed"}（无 new_record），必须显式校验，杜绝失败假成功
      if (!res.ok || data.status !== "success") {
        throw new Error(data?.detail || `归档失败 (HTTP ${res.status})`)
      }
      if (data.new_record) {
        setCurrentTranscript(data.new_record)
        if (activeJob) (activeJob as any).interview_transcript = data.new_record
      }
      toast({
        title: "✅ 归档成功",
        description: generateReport ? "面试复盘报告已生成并成功归档至飞书！" : "面试纪要已成功归档至飞书！",
      })
      setEndDialogConfig(prev => ({ ...prev, show: false, transcript: "" }))
      setChatLog([])
    } catch(e: any) {
      // 🌟 失败保持结束弹窗与文字稿，允许用户重试或改选「仅保存」
      toast({
        title: "❌ 保存失败",
        description: e?.message || "面试记录同步保存失败，请检查网络或后端状态。",
        variant: "destructive",
      })
    } finally {
      setIsSavingRecord(false)
    }
  }

  // 🌟 核心升级：将 Markdown 大文本自适应解析为强类型结构化记录列表
  const parsedRecords = useMemo<InterviewRecordItem[]>(() => {
    return parseInterviewRecords(currentTranscript)
  }, [currentTranscript])

  const handleDeleteRecord = async (targetIdOrBlock: string) => {
    if (deleteInFlightRef.current) return
    deleteInFlightRef.current = true
    // 🌟 外科手术式移除：只删目标块本身，块外零散文本（手动批注等）原样保留
    const prevTranscript = currentTranscript
    const newTranscript = removeRecordFromMarkdown(currentTranscript, targetIdOrBlock)
    setCurrentTranscript(newTranscript)
    if (activeJob) (activeJob as any).interview_transcript = newTranscript
    try {
      const res = await fetch(`${API_BASE}/api/save_transcript`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: activeJobId, transcript: newTranscript, is_overwrite: true })
      })
      const data = await res.json().catch(() => ({}))
      // 🌟 Q-M8-4：覆盖写失败必须回滚本地并明示，杜绝删除假成功
      if (!res.ok || data.status !== "success") {
        throw new Error(data?.detail || `删除同步失败 (HTTP ${res.status})`)
      }
      toast({
        title: "🗑️ 记录已删除",
        description: "该场面试练习记录已从飞书与本地同步移除。",
      })
    } catch(e: any) {
      setCurrentTranscript(prevTranscript)
      if (activeJob) (activeJob as any).interview_transcript = prevTranscript
      toast({
        title: "❌ 删除异常",
        description: e?.message || "网络错误，删除未能同步到云端，本地已回滚。",
        variant: "destructive",
      })
    } finally {
      deleteInFlightRef.current = false
    }
  }

  return {
    isInterviewing,
    isPaused,
    chatLog,
    setChatLog,
    interviewMinutes,
    currentTranscript,
    parsedRecords,
    isRefreshingHistory,
    endDialogConfig,
    setEndDialogConfig,
    isSavingRecord,
    liveRecord,
    setLiveRecord: handleSetLiveRecord,
    isShredding,
    shreddedQuestions,
    isRecording,
    isSavingLive,
    saveLiveError,
    toggleVoiceRecording,
    handleShredInterview,
    startInterview,
    stopInterview,
    togglePause,
    refreshHistory,
    handleSaveTranscript,
    handleDeleteRecord,
    debouncedSaveLiveFields
  }
}
