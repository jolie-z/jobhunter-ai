import { useState, useRef, useCallback } from "react"
import { WS_BASE } from "@/lib/api"

export type VoiceEngine = "volc" | "native" | null

// ── PCM helpers ────────────────────────────────────────────────────────────
function float32ToPcm16(float32: Float32Array, srcRate: number, dstRate = 16000): ArrayBuffer {
  const ratio = srcRate / dstRate
  const outLen = Math.round(float32.length / ratio)
  const out = new Int16Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const s = Math.max(-1, Math.min(1, float32[Math.round(i * ratio)] ?? 0))
    out[i] = s < 0 ? s * 32768 : s * 32767
  }
  return out.buffer
}

export function useDualChannelVoice(onTextComplete?: (text: string) => void) {
  const [isRecording, setIsRecording] = useState(false)
  const [activeEngine, setActiveEngine] = useState<VoiceEngine>(null)
  const [streamingText, setStreamingText] = useState("")

  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nativeRecRef = useRef<any>(null)
  const streamingTextRef = useRef("")
  // 录音会话代际：每次开新连接递增。ws.close() 是异步握手，旧连接缓冲中的迟到
  // onmessage（上一轮全量转写）会在新会话里污染 streamingTextRef——除了解绑处理器，
  // 再用代际号把每条消息绑死在它自己的会话上，双保险。
  const sessionGenRef = useRef(0)
  // 消息/回调是否来自已废弃的旧会话
  const isStale = (gen: number) => gen !== sessionGenRef.current

  const stopAllRecording = useCallback(() => {
    sessionGenRef.current += 1
    const ws = wsRef.current
    if (ws) {
      // close() 是异步的，先摘掉回调，防止关闭握手期间迟到的识别消息写回状态
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
      try { ws.close() } catch { /* ignore */ }
    }
    wsRef.current = null
    try { processorRef.current?.disconnect() } catch { /* ignore */ }
    try { audioCtxRef.current?.close() } catch { /* ignore */ }
    try { streamRef.current?.getTracks().forEach((t) => t.stop()) } catch { /* ignore */ }
    processorRef.current = null
    audioCtxRef.current = null
    streamRef.current = null

    const nativeRec = nativeRecRef.current
    if (nativeRec) {
      nativeRec.onresult = null
      nativeRec.onend = null
      nativeRec.onerror = null
      try { nativeRec.stop() } catch { /* ignore */ }
    }
    nativeRecRef.current = null

    const pending = streamingTextRef.current.trim()
    if (pending && onTextComplete) {
      onTextComplete(pending)
    }

    streamingTextRef.current = ""
    setStreamingText("")
    setActiveEngine(null)
    setIsRecording(false)
  }, [onTextComplete])

  const startNativeRecognition = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechAPI = typeof window !== "undefined"
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ? ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)
      : null
    if (!SpeechAPI) { setIsRecording(false); return }

    const gen = ++sessionGenRef.current
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new SpeechAPI()
    rec.lang = "zh-CN"
    rec.continuous = true
    rec.interimResults = true

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (e: any) => {
      if (isStale(gen)) return
      let fullTranscript = ""
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      for (const res of Array.from<any>(e.results)) {
        fullTranscript += res[0].transcript
      }
      streamingTextRef.current = fullTranscript
      setStreamingText(fullTranscript)
    }

    rec.onend = () => { if (!isStale(gen)) stopAllRecording() }
    rec.onerror = () => { if (!isStale(gen)) stopAllRecording() }

    nativeRecRef.current = rec
    rec.start()
    setActiveEngine("native")
    setIsRecording(true)
  }, [stopAllRecording])

  const startVolcEngine = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
    streamRef.current = stream

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const AudioCtxCtor = (window.AudioContext || (window as any).webkitAudioContext) as typeof AudioContext
    const ctx = new AudioCtxCtor()
    audioCtxRef.current = ctx

    const gen = ++sessionGenRef.current
    const ws = new WebSocket(`${WS_BASE}/api/ws/asr`)
    wsRef.current = ws

    const fallbackToNative = () => {
      if (isStale(gen)) return
      try { ws.close() } catch { /* ignore */ }
      try { processorRef.current?.disconnect() } catch { /* ignore */ }
      try { ctx.close() } catch { /* ignore */ }
      try { stream.getTracks().forEach((t) => t.stop()) } catch { /* ignore */ }
      wsRef.current = null
      processorRef.current = null
      audioCtxRef.current = null
      streamRef.current = null
      streamingTextRef.current = ""
      setStreamingText("")
      startNativeRecognition()
    }

    ws.onmessage = (e) => {
      if (isStale(gen)) return
      try {
        const data = JSON.parse(e.data)
        if (data.status === "fallback" || data.status === "error") {
          fallbackToNative()
          return
        }
        if (data.status === "success" && data.text) {
          streamingTextRef.current = data.text
          setStreamingText(data.text)
        }
      } catch { /* ignore */ }
    }

    ws.onerror = () => fallbackToNative()

    ws.onopen = () => {
      if (isStale(gen)) { try { ws.close() } catch { /* ignore */ } return }
      const source = ctx.createMediaStreamSource(stream)
      const processor = ctx.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      processor.onaudioprocess = (ev) => {
        if (ws.readyState !== WebSocket.OPEN) return
        const pcm = float32ToPcm16(ev.inputBuffer.getChannelData(0), ctx.sampleRate)
        ws.send(pcm)
      }

      source.connect(processor)
      processor.connect(ctx.destination)

      setActiveEngine("volc")
      setIsRecording(true)
    }

    ws.onclose = (e) => {
      if (isStale(gen)) return
      // 只有当前引擎仍然是 volc 时，才在异常断开时重置状态。
      // 防止 fallbackToNative 触发的 ws.close() 产生竞态，把兜底的 native 状态给强行关掉。
      if (!e.wasClean) {
        setActiveEngine((prev) => {
          if (prev === "volc") {
            setStreamingText("")
            setIsRecording(false)
            return null
          }
          return prev
        })
      }
    }
  }, [startNativeRecognition])

  const toggleRecording = useCallback(async () => {
    if (isRecording) {
      stopAllRecording()
      return
    }
    try {
      await startVolcEngine()
    } catch {
      try { streamRef.current?.getTracks().forEach((t) => t.stop()) } catch { /* ignore */ }
      streamRef.current = null
      startNativeRecognition()
    }
  }, [isRecording, startVolcEngine, startNativeRecognition, stopAllRecording])

  const clearStreamingText = useCallback(() => {
    streamingTextRef.current = ""
    setStreamingText("")
  }, [])

  return {
    isRecording,
    activeEngine,
    streamingText,
    toggleRecording,
    stopRecording: stopAllRecording,
    clearStreamingText,
  }
}
