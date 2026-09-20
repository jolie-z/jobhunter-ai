"use client"

import React, { useState, useEffect, useMemo } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  FileText, MessageSquare, Copy, Check, ExternalLink, Printer, SlidersHorizontal,
  Loader2, AlertCircle, ShieldCheck, Image as ImageIcon, Download,
} from "lucide-react"
import { API_BASE, apiFetch } from "@/lib/api"
import type { PipelineJob } from "@/store/pipeline-store"

let globalMassGreetingCache: string | null = null

interface JobMaterialPreviewModalProps {
  job: PipelineJob | null
  open: boolean
  onOpenChange: (open: boolean) => void
  initialTab?: "resume" | "greeting"
}

interface MaterialInfo {
  loading: boolean
  has_materials: boolean
  has_pdf: boolean
  has_image: boolean
  pdf_name: string
  image_name: string
  is_boss: boolean
  platform: string
  delivered_material: "image" | "pdf"
  greeting_msg?: string
  pdf_stream_url: string
  pdf_download_url: string
  image_stream_url: string
  image_download_url: string
}

export function JobMaterialPreviewModal({
  job, open, onOpenChange, initialTab = "resume",
}: JobMaterialPreviewModalProps) {
  const [activeTab, setActiveTab] = useState<"resume" | "greeting">(initialTab)
  const [greetingText, setGreetingText] = useState("")
  const [greetingType, setGreetingType] = useState<"custom" | "mass" | "none">("none")
  const [isLoadingGreeting, setIsLoadingGreeting] = useState(false)
  const [copied, setCopied] = useState(false)
  const [iframeLoading, setIframeLoading] = useState(true)
  const [materialView, setMaterialView] = useState<"image" | "pdf">("pdf")

  const [materialInfo, setMaterialInfo] = useState<MaterialInfo>({
    loading: false, has_materials: false, has_pdf: false, has_image: false,
    pdf_name: "", image_name: "", is_boss: false, platform: "", delivered_material: "pdf",
    greeting_msg: "",
    pdf_stream_url: "", pdf_download_url: "", image_stream_url: "", image_download_url: "",
  })

  useEffect(() => {
    if (open) { setActiveTab(initialTab); setIframeLoading(true) }
  }, [open, initialTab])

  const cleanRecordId = useMemo(() => {
    if (!job?.job_id || job.job_id.startsWith("raw_")) return ""
    const parts = job.job_id.split("-")
    return parts[parts.length - 1]
  }, [job])

  const isCustomJob = job?.grade === "A" || job?.grade === "B" || job?.review_type === "custom_tailored"
  const is51Job = useMemo(() => {
    const p = `${job?.platform || ""} ${materialInfo.platform || ""}`.toLowerCase()
    return p.includes("51job") || p.includes("前程无忧")
  }, [job?.platform, materialInfo.platform])

  // 🌟 直读飞书已归档真实 PDF / 长图物料（通过 stream 改写 Header 杜绝强制下载，实现所见即所得）
  useEffect(() => {
    if (!open || !cleanRecordId) {
      setMaterialInfo({
        loading: false, has_materials: false, has_pdf: false, has_image: false,
        pdf_name: "", image_name: "", is_boss: false, platform: "", delivered_material: "pdf",
        greeting_msg: "",
        pdf_stream_url: "", pdf_download_url: "", image_stream_url: "", image_download_url: "",
      })
      return
    }
    let isMounted = true
    setMaterialInfo((prev) => ({ ...prev, loading: true }))

    apiFetch(`/api/automation/job-material-urls?job_id=${encodeURIComponent(cleanRecordId)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((res) => {
        if (!isMounted) return
        const d = res?.data || {}
        const isBossJob = Boolean(d.is_boss || (job?.platform && (job.platform.toLowerCase().includes("boss") || job.platform.includes("直聘"))))
        const hasPdf = Boolean(d.has_pdf && d.pdf_stream_url)
        const hasImg = Boolean(d.has_image && d.image_stream_url)

        setMaterialInfo({
          loading: false,
          has_materials: Boolean(d.has_materials && (hasPdf || hasImg)),
          has_pdf: hasPdf,
          has_image: hasImg,
          pdf_name: d.pdf_name || "简历.pdf",
          image_name: d.image_name || "简历长图.jpg",
          is_boss: isBossJob,
          platform: d.platform || job?.platform || "",
          delivered_material: isBossJob ? "image" : "pdf",
          greeting_msg: d.greeting_msg || "",
          pdf_stream_url: d.pdf_stream_url || "",
          pdf_download_url: d.pdf_download_url || "",
          image_stream_url: d.image_stream_url || "",
          image_download_url: d.image_download_url || "",
        })
        if (isBossJob && hasImg) setMaterialView("image")
        else setMaterialView("pdf")
      })
      .catch((e) => {
        console.warn("读取飞书真实物料直链异常:", e)
        if (isMounted) setMaterialInfo((prev) => ({ ...prev, loading: false }))
      })
    return () => { isMounted = false }
  }, [open, cleanRecordId, job?.platform])

  // 极速获取打招呼语：优先使用 snapshot / 物料直链透传的话术(0ms 秒显)，未命中时异步拉取详情
  useEffect(() => {
    if (!open || !job) return
    let active = true
    setCopied(false)

    // 1. 优先使用已在看板快照或物料接口中透传的 greeting_msg (0ms 即时渲染)
    const directGreeting = (job.greeting_msg || materialInfo.greeting_msg || "").trim()
    if (directGreeting.length > 3) {
      setGreetingText(directGreeting)
      setGreetingType(isCustomJob ? "custom" : "mass")
      setIsLoadingGreeting(false)
      return
    }

    setIsLoadingGreeting(true)

    const loadMassGreeting = async (): Promise<string> => {
      if (globalMassGreetingCache) return globalMassGreetingCache
      try {
        const res = await apiFetch("/api/automation/config")
        const d = await res.json()
        const msg = (d?.data?.mass_apply_greeting || "").trim()
        if (msg) { globalMassGreetingCache = msg; return msg }
      } catch { /* ignore */ }
      return ""
    }

    const fetchGreeting = async () => {
      if (isCustomJob && cleanRecordId) {
        try {
          const ctrl = new AbortController()
          const timer = setTimeout(() => ctrl.abort(), 8000)
          const r = await apiFetch(`/api/jobs/${encodeURIComponent(cleanRecordId)}/detail`, { signal: ctrl.signal })
          clearTimeout(timer)
          if (r.ok) {
            const d = await r.json()
            const msg = (d?.data?.greeting_msg || "").trim()
            if (msg.length > 3 && active) {
              setGreetingText(msg); setGreetingType("custom"); setIsLoadingGreeting(false); return
            }
          }
        } catch (e) {
          console.warn("拉取精投专属打招呼语异常:", e)
        }
      }
      const mass = await loadMassGreeting()
      if (active) {
        setGreetingText(mass)
        setGreetingType(mass ? (isCustomJob ? "custom" : "mass") : "none")
        setIsLoadingGreeting(false)
      }
    }
    fetchGreeting()
    return () => { active = false }
  }, [open, job, cleanRecordId, isCustomJob, materialInfo.greeting_msg])

  if (!job) return null

  const printUrl = cleanRecordId ? `/print/resume?record_id=${encodeURIComponent(cleanRecordId)}&source=job&template=classic` : ""
  const customPanelUrl = `/?job_id=${encodeURIComponent(job.job_id)}`
  const activeStreamPath = materialView === "image" ? materialInfo.image_stream_url : materialInfo.pdf_stream_url
  const activeDownloadPath = materialView === "image" ? materialInfo.image_download_url : materialInfo.pdf_download_url
  const activeStreamUrl = activeStreamPath ? `${API_BASE}${activeStreamPath}` : ""
  const activeDownloadUrl = activeDownloadPath ? `${API_BASE}${activeDownloadPath}` : ""

  const handleCopyGreeting = async () => {
    if (!greetingText) return
    try { await navigator.clipboard.writeText(greetingText) }
    catch {
      const ta = document.createElement("textarea")
      ta.value = greetingText; document.body.appendChild(ta); ta.select()
      document.execCommand("copy"); document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[940px] h-[85vh] flex flex-col p-0 gap-0 overflow-hidden bg-background/95 backdrop-blur-md border border-border/80 shadow-2xl rounded-2xl">
        {/* 顶部 Header */}
        <DialogHeader className="p-4 sm:px-6 sm:py-3.5 border-b border-border/60 shrink-0 bg-muted/20">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pr-6">
            <DialogTitle className="text-base font-bold tracking-tight text-foreground flex items-center gap-2">
              <span>投递物料核验</span>
              <span className="text-xs px-2 py-0.5 rounded-full font-normal bg-primary/10 text-primary border border-primary/20">
                {job.company_name || "公司"} · {job.job_name || "岗位"}
              </span>
              {job.grade && (
                <span className="text-[11px] font-bold px-1.5 py-0.2 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                  {job.grade} 级
                </span>
              )}
            </DialogTitle>

            <div className="flex items-center p-1 bg-muted/60 rounded-lg border border-border/60 shrink-0">
              <button
                type="button"
                onClick={() => setActiveTab("resume")}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-md transition-all cursor-pointer ${
                  activeTab === "resume" ? "bg-background text-foreground shadow-xs font-semibold" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <FileText className="h-3.5 w-3.5 text-blue-500" />
                <span>投递简历</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("greeting")}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-md transition-all cursor-pointer ${
                  activeTab === "greeting" ? "bg-background text-foreground shadow-xs font-semibold" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <MessageSquare className="h-3.5 w-3.5 text-emerald-500" />
                <span>破冰欢迎语</span>
              </button>
            </div>
          </div>
        </DialogHeader>

        {/* Tab 1: 投递简历实体原件直读 */}
        {activeTab === "resume" && (
          <div className="flex-1 flex flex-col min-h-0 bg-zinc-100 dark:bg-zinc-950/60">
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 border-b border-border/60 bg-background/80 text-xs shrink-0">
              <div className="flex items-center gap-2">
                {materialInfo.loading ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                    <span>正在读取飞书物料库...</span>
                  </span>
                ) : materialInfo.has_materials ? (
                  materialInfo.is_boss ? (
                    <>
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30">
                        <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                        <span>BOSS 直聊原件</span>
                      </span>
                      <div className="flex items-center p-0.5 bg-muted rounded-md border border-border/60 ml-1">
                        {materialInfo.has_image && (
                          <button
                            type="button"
                            onClick={() => setMaterialView("image")}
                            className={`flex items-center gap-1 px-2.5 py-0.5 text-[11px] font-medium rounded transition-all cursor-pointer ${
                              materialView === "image" ? "bg-background text-foreground shadow-xs font-semibold" : "text-muted-foreground hover:text-foreground"
                            }`}
                          >
                            <ImageIcon className="h-3 w-3 text-amber-500" />
                            <span>微聊长图 (实际投递)</span>
                          </button>
                        )}
                        {materialInfo.has_pdf && (
                          <button
                            type="button"
                            onClick={() => setMaterialView("pdf")}
                            className={`flex items-center gap-1 px-2.5 py-0.5 text-[11px] font-medium rounded transition-all cursor-pointer ${
                              materialView === "pdf" ? "bg-background text-foreground shadow-xs font-semibold" : "text-muted-foreground hover:text-foreground"
                            }`}
                          >
                            <FileText className="h-3 w-3 text-blue-500" />
                            <span>PDF</span>
                          </button>
                        )}
                      </div>
                    </>
                  ) : (
                    /* 非 BOSS 平台（智联/51job/猎聘）仅保留单枚纯净的实际投递 PDF 标签，彻底消除重复 */
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-500/10 text-blue-700 dark:text-blue-300 border border-blue-500/30">
                      <FileText className="h-3.5 w-3.5 text-blue-500 shrink-0" />
                      <span>PDF 附件 (实际投递物料)</span>
                    </span>
                  )
                ) : (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/30">
                    <AlertCircle className="h-3 w-3 shrink-0" />
                    <span>实体附件未生成 · 实时排版预览</span>
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                <a
                  href={customPanelUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-all"
                >
                  <SlidersHorizontal className="h-3 w-3" />
                  <span>定制工作台</span>
                </a>

                {materialInfo.has_materials && activeStreamUrl ? (
                  <>
                    <a
                      href={activeDownloadUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-secondary text-secondary-foreground hover:bg-secondary/80 font-medium transition-all text-xs"
                      title="下载原件至本地"
                    >
                      <Download className="h-3 w-3" />
                      <span>下载原件</span>
                    </a>
                    <a
                      href={activeStreamUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 font-medium transition-all text-xs"
                      title="新标签直接预览原件（不触发下载）"
                    >
                      <ExternalLink className="h-3 w-3" />
                      <span>打开原件</span>
                    </a>
                  </>
                ) : printUrl ? (
                  <>
                    <button
                      type="button"
                      onClick={() => {
                        const iframe = document.getElementById("job-resume-iframe") as HTMLIFrameElement
                        if (iframe?.contentWindow) iframe.contentWindow.print()
                        else window.open(printUrl, "_blank")
                      }}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-secondary text-secondary-foreground hover:bg-secondary/80 font-medium transition-all cursor-pointer text-xs"
                    >
                      <Printer className="h-3 w-3" />
                      <span>打印/PDF</span>
                    </button>
                    <a
                      href={printUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 font-medium transition-all text-xs"
                    >
                      <ExternalLink className="h-3 w-3" />
                      <span>新标签打开</span>
                    </a>
                  </>
                ) : null}
              </div>
            </div>

            {/* BOSS 直聘专属投递规则提示条 */}
            {materialInfo.is_boss && materialInfo.has_materials && (
              <div className="px-4 py-1.5 bg-amber-500/10 border-b border-amber-500/20 text-[11px] text-amber-800 dark:text-amber-200 flex items-center justify-between shrink-0">
                <span className="flex items-center gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400 shrink-0" />
                  <span>💡 投递提示：BOSS直聘自动化投递将向 HR 微聊发送高清长图；如需使用 PDF 进行投递，可切换上方「PDF」并点击右上角「下载原件」自行发送。</span>
                </span>
              </div>
            )}

            {/* 物料内容展示区 */}
            <div className="flex-1 relative overflow-auto flex items-start justify-center p-4">
              {materialInfo.loading ? (
                <div className="my-auto flex flex-col items-center justify-center gap-2 text-muted-foreground">
                  <Loader2 className="h-6 w-6 animate-spin text-primary" />
                  <span className="text-xs">正在从飞书物料库读取原件...</span>
                </div>
              ) : materialInfo.has_materials ? (
                materialView === "image" && materialInfo.image_stream_url ? (
                  <div className="w-full max-w-[760px] flex justify-center py-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`${API_BASE}${materialInfo.image_stream_url}`}
                      alt={materialInfo.image_name || "投递长图原件"}
                      className="w-full rounded-md shadow-2xl border border-border/80 bg-white dark:bg-zinc-900"
                      loading="eager"
                    />
                  </div>
                ) : materialInfo.pdf_stream_url ? (
                  <iframe
                    src={`${API_BASE}${materialInfo.pdf_stream_url}`}
                    className="w-full max-w-[850px] h-full min-h-[600px] rounded-md shadow-xl border border-border/80 bg-white"
                    title="飞书 PDF 原件"
                  />
                ) : null
              ) : cleanRecordId ? (
                <div className="w-full h-full relative flex items-center justify-center">
                  {iframeLoading && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/60 backdrop-blur-xs z-10 gap-2">
                      <Loader2 className="h-6 w-6 text-primary animate-spin" />
                      <span className="text-xs text-muted-foreground">正在渲染排版...</span>
                    </div>
                  )}
                  <iframe
                    id="job-resume-iframe"
                    src={printUrl}
                    onLoad={() => setIframeLoading(false)}
                    className="w-full max-w-[800px] h-full rounded-md shadow-xl border border-border/80 bg-white dark:bg-zinc-900"
                    title="简历实时排版预览"
                  />
                </div>
              ) : (
                <div className="my-auto text-center p-8 max-w-sm space-y-2">
                  <AlertCircle className="h-8 w-8 text-amber-500 mx-auto opacity-80" />
                  <p className="text-sm font-medium text-foreground">尚未生成正式简历物料</p>
                  <p className="text-xs text-muted-foreground">该岗位推送到飞书并完成评估后即可在此核验真实投递物料。</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 2: 打招呼欢迎语视图 */}
        {activeTab === "greeting" && (
          <div className="flex-1 flex flex-col min-h-0 p-6 overflow-y-auto bg-muted/10">
            <div className="max-w-2xl mx-auto w-full space-y-4">
              {/* 51job 专属特性温馨提醒 */}
              {is51Job && (
                <div className="flex items-start gap-2.5 p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-200 text-xs">
                  <AlertCircle className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                  <div className="space-y-0.5">
                    <span className="font-semibold text-amber-800 dark:text-amber-200">51job (前程无忧) 平台特性提示</span>
                    <p className="text-[11px] text-amber-700/90 dark:text-amber-300/90 leading-relaxed">
                      由于 51job 网页端投递为纯简历附件直投机制、暂未开放微聊开场白接口，系统自动投递时不会发送打招呼语。您可在此一键复制专属话术，在手机 APP 端的聊天对话框中手动发送给 HR。
                    </p>
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between p-3 rounded-xl border border-border/70 bg-card">
                <div className="flex items-center gap-2">
                  <div className={`size-8 rounded-lg flex items-center justify-center shrink-0 ${
                    greetingType === "custom" ? "bg-amber-500/10 text-amber-600 dark:text-amber-400" : "bg-blue-500/10 text-blue-600 dark:text-blue-400"
                  }`}>
                    <MessageSquare className="size-4" />
                  </div>
                  <div>
                    <h4 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                      <span>{isLoadingGreeting ? "正在匹配打招呼语..." : is51Job ? "📱 51job 手机端沟通话术 (自动投递不发送，支持手动复制)" : greetingType === "custom" ? "🎯 岗位专属定制欢迎语" : "⚡ 通用海投打招呼语"}</span>
                      {!isLoadingGreeting && greetingType === "custom" && (
                        <span className="text-[10px] bg-amber-500/15 text-amber-700 dark:text-amber-300 px-1.5 py-0.2 rounded">针对 JD 提炼</span>
                      )}
                    </h4>
                    <p className="text-[11px] text-muted-foreground">
                      {isLoadingGreeting ? "正在读取微聊话术..." : is51Job
                        ? "51job 网页端无在线开场白功能，此话术已精调完毕，供您在手机 APP 与 HR 沟通时一键复制发送。"
                        : greetingType === "custom"
                        ? `已根据 ${job.company_name || "公司"} JD 提取关键能力信号，投递时自动触发。`
                        : "采用全局配置的通用海投打招呼语话术。"}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={handleCopyGreeting}
                  disabled={!greetingText || isLoadingGreeting}
                  className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer shrink-0 border ${
                    copied ? "bg-emerald-600 text-white border-emerald-600 shadow-xs" : "bg-background hover:bg-muted text-foreground border-border/80 shadow-xs"
                  }`}
                >
                  {copied ? (<><Check className="h-3.5 w-3.5" /><span>已复制</span></>) : (<><Copy className="h-3.5 w-3.5" /><span>复制话术</span></>)}
                </button>
              </div>

              <div className="rounded-xl border border-border/80 bg-card p-5 shadow-xs space-y-3">
                <div className="flex items-center justify-between text-xs text-muted-foreground border-b border-border/40 pb-2">
                  <span className="font-medium">微聊破冰预览 (HR 视角):</span>
                  <span>{greetingText.length} 字</span>
                </div>

                {isLoadingGreeting ? (
                  <div className="py-12 flex flex-col items-center justify-center gap-2 text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin text-primary" />
                    <span className="text-xs">正在拉取打招呼语...</span>
                  </div>
                ) : greetingText ? (
                  <div className="rounded-lg bg-muted/40 p-4 border border-border/40 text-sm leading-relaxed whitespace-pre-wrap font-normal text-foreground select-text">
                    {greetingText}
                  </div>
                ) : (
                  <div className="py-8 text-center space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">未配置打招呼语话术</p>
                  </div>
                )}

                <div className="pt-2 flex items-center justify-between text-xs">
                  <span className="text-[11px] text-muted-foreground">💡 微聊开场白需简明扼要，突出关键战绩</span>
                  <a href={customPanelUrl} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline flex items-center gap-0.5 text-xs font-medium">
                    <span>定制面板改写话术</span>
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
