"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect } from "react"
import { X, Trash2, Bot, ShieldAlert, CheckCircle2, RefreshCw, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"

import { toast } from "sonner"


export function TrashBinWorkspace({ onClose }: { onClose: () => void }) {
  const [jobs, setJobs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [processingId, setProcessingId] = useState<string | null>(null)

  const fetchTrashBin = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/processor/trash-bin`)
      if (res.ok) {
        const data = await res.json()
        if (data.status === "success") {
          setJobs(data.data || [])
        }
      }
    } catch (e) {
      console.error("Failed to fetch trash bin", e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTrashBin()
  }, [])

  const handleUnreject = async (jobLink: string) => {
    setProcessingId(jobLink)
    try {
      const res = await fetch(`${API_BASE}/api/v1/processor/unreject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_link: jobLink })
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        setJobs(prev => prev.filter(j => j.job_link !== jobLink))
        toast.success("✅ 已成功放行并同步至飞书！")
        window.dispatchEvent(new CustomEvent("pipeline-stats-refresh", { detail: { action: "unreject" } }))
      } else {
        toast.error(`放行失败: ${data.message || data.detail || "服务繁忙"}`)
      }
    } catch (e) {
      toast.error("网络错误，放行失败")
    } finally {
      setProcessingId(null)
    }
  }

  const handleConfirmReject = async (jobLink: string) => {
    setProcessingId(jobLink)
    try {
      const res = await fetch(`${API_BASE}/api/v1/processor/confirm-reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_link: jobLink })
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        setJobs(prev => prev.filter(j => j.job_link !== jobLink))
        toast.success("已确认淘汰归档")
        window.dispatchEvent(new CustomEvent("pipeline-stats-refresh", { detail: { action: "confirm-reject" } }))
      } else {
        toast.error(`操作失败: ${data.message || data.detail || "服务繁忙"}`)
      }
    } catch (e) {
      toast.error("网络错误，操作失败")
    } finally {
      setProcessingId(null)
    }
  }

  const handleEmptyTrash = async () => {
    if (!window.confirm("确定要一键清空当前所有拦截记录吗？\n清空后将无法在此处找回这些岗位的记录。")) {
      return
    }
    
    try {
      const res = await fetch(`${API_BASE}/api/v1/processor/empty-trash`, { method: "POST" })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        setJobs([])
        toast.success("回收站已清空")
        window.dispatchEvent(new CustomEvent("pipeline-stats-refresh", { detail: { action: "empty-trash" } }))
      } else {
        toast.error(`清空失败: ${data.message || data.detail || "服务繁忙"}`)
      }
    } catch (e) {
      toast.error("网络错误，操作失败")
    }
  }

  return (
    <div className="absolute inset-0 z-40 bg-white flex flex-col shadow-2xl animate-in slide-in-from-bottom-8">
      {/* Header */}
      <div className="h-14 border-b border-slate-100 flex items-center justify-between px-6 shrink-0 bg-slate-50">
        <div className="flex items-center gap-3">
          <div className="size-8 rounded-lg bg-rose-100 flex items-center justify-center text-rose-600">
            <Trash2 size={18} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-slate-800">清洗拦截回收站</h2>
            <p className="text-xs text-slate-500">查看被清洗规则和 AI 侦察兵淘汰的岗位，发现误杀可一键放行。</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {jobs.length > 0 && (
            <Button variant="ghost" size="sm" onClick={handleEmptyTrash} className="h-8 text-xs gap-1 text-slate-500 hover:text-rose-600 hover:bg-rose-50 mr-2">
              <Trash2 size={14} /> 一键清空
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={fetchTrashBin} className="h-8 text-xs gap-1">
            <RefreshCw size={14} /> 刷新
          </Button>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-md transition-colors"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 bg-slate-50/50">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400">
            <Spinner className="size-6 mb-2" />
            <span className="text-sm">正在拉取回收站数据...</span>
          </div>
        ) : jobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400">
            <CheckCircle2 size={40} className="mb-3 text-emerald-400 opacity-50" />
            <span className="text-sm">回收站空空如也，全部岗位都已放行！</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 max-w-5xl mx-auto">
            {jobs.map((job, i) => {
              const isAi = job.process_status === 'ai清洗淘汰'
              return (
                <div key={i} className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex flex-col gap-3 transition-shadow hover:shadow-md">
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold flex items-center gap-1 ${isAi ? 'bg-purple-100 text-purple-700' : 'bg-orange-100 text-orange-700'}`}>
                          {isAi ? <Bot size={12} /> : <ShieldAlert size={12} />}
                          {isAi ? 'AI排雷' : '规则拦截'}
                        </span>
                        <h3 className="text-base font-bold text-slate-800">{job.job_title}</h3>
                        <span className="text-sm font-semibold text-rose-500">{job.salary}</span>
                      </div>
                      <p className="text-sm text-slate-600 font-medium">
                        {job.company_name} <span className="text-slate-300 mx-1">|</span> {job.city}
                      </p>
                    </div>
                    <div className="flex flex-col gap-2">
                      <Button 
                        size="sm" 
                        onClick={() => handleUnreject(job.job_link)}
                        disabled={processingId === job.job_link}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm h-8 px-3"
                      >
                        {processingId === job.job_link ? <Spinner className="size-4 mr-1 border-white" /> : <CheckCircle2 size={16} className="mr-1" />}
                        放行并推送
                      </Button>
                      <Button 
                        size="sm" 
                        variant="outline"
                        onClick={() => handleConfirmReject(job.job_link)}
                        disabled={processingId === job.job_link}
                        className="h-8 px-3 text-slate-500 hover:text-rose-600 hover:bg-rose-50 hover:border-rose-200"
                      >
                        <XCircle size={16} className="mr-1" />
                        确认淘汰
                      </Button>
                    </div>
                  </div>
                  
                  <div className="bg-rose-50 border border-rose-100 text-rose-800 text-xs px-3 py-2 rounded-md font-medium flex items-start gap-1.5">
                    <ShieldAlert size={14} className="mt-0.5 shrink-0" />
                    <span>死因: {job.reject_reason}</span>
                  </div>

                  <details className="group">
                    <summary className="text-xs text-blue-600 cursor-pointer font-medium hover:underline outline-none select-none">
                      展开 JD 全文查看是否误杀
                    </summary>
                    <div className="mt-2 bg-slate-50 rounded-lg p-3 text-xs text-slate-600 whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto custom-scrollbar border border-slate-100">
                      {job.jd_text}
                    </div>
                  </details>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
