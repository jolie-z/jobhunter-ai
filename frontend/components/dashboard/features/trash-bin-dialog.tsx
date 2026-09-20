import { useState } from "react"
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Trash2, Building2, MapPin, DollarSign, Tag } from "lucide-react"
import { toast } from "sonner"
import { getMainApiBase } from "@/lib/platform-auth"

export interface RejectedJob {
  rowid: number
  platform: string
  job_title: string
  company_name: string
  city: string
  salary: string
  reject_reason: string
}

interface TrashBinDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function TrashBinDialog({ open, onOpenChange }: TrashBinDialogProps) {
  const [jobs, setJobs] = useState<RejectedJob[]>([])
  const [loading, setLoading] = useState(false)

  const fetchTrashJobs = async () => {
    setLoading(true)
    try {
      const apiBase = getMainApiBase()
      const res = await fetch(`${apiBase}/v1/processor/trash-bin`)
      if (res.ok) {
        const data = await res.json()
        setJobs(data.data || [])
      }
    } catch (e) {
      console.warn('[TrashBinDialog] 获取淘汰明细失败:', e)
      toast.error("获取淘汰岗位明细失败，请检查服务连接")
    } finally {
      setLoading(false)
    }
  }

  // 当弹窗打开时加载数据
  const handleOpenChange = (newOpen: boolean) => {
    if (newOpen) {
      void fetchTrashJobs()
    }
    onOpenChange(newOpen)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-[800px] w-[92vw] max-h-[82vh] flex flex-col p-6 border-zinc-200">
        <DialogTitle className="text-base font-semibold text-zinc-900 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Trash2 className="w-4 h-4 text-rose-500" />
            清洗淘汰岗位明细 (回收站)
          </div>
          <span className="text-xs text-zinc-500 font-normal">最近淘汰 200 条</span>
        </DialogTitle>
        <DialogDescription className="text-xs text-zinc-500 mt-1">
          以下岗位已被硬性规则或 AI 侦察排雷拦截淘汰，不会同步至飞书多维表格。
        </DialogDescription>

        <div className="flex-1 overflow-y-auto mt-4 space-y-2 pr-1 divide-y divide-zinc-100">
          {loading ? (
            <div className="py-16 text-center text-xs text-zinc-400">正在拉取淘汰明细...</div>
          ) : jobs.length === 0 ? (
            <div className="py-16 text-center text-xs text-zinc-400">暂无淘汰记录</div>
          ) : (
            jobs.map((job) => (
              <div key={job.rowid} className="pt-3 first:pt-0 flex items-start justify-between gap-3 text-xs">
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-zinc-100 text-[10px] font-medium text-zinc-600">
                      <Tag className="w-2.5 h-2.5 mr-1 text-zinc-400" />
                      {job.platform}
                    </span>
                    <h5 className="font-semibold text-zinc-900 truncate">{job.job_title}</h5>
                  </div>
                  <div className="text-zinc-500 flex items-center flex-wrap gap-x-2.5 gap-y-0.5 text-[11px]">
                    <span className="flex items-center gap-1">
                      <Building2 className="w-3 h-3 text-zinc-400" />
                      {job.company_name}
                    </span>
                    {job.city && (
                      <span className="flex items-center gap-0.5">
                        <MapPin className="w-2.5 h-2.5 text-zinc-400" />
                        {job.city}
                      </span>
                    )}
                    {job.salary && (
                      <span className="flex items-center gap-0.5 text-zinc-600 font-medium">
                        <DollarSign className="w-2.5 h-2.5 text-zinc-400" />
                        {job.salary}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <span className="inline-block px-2.5 py-1 rounded text-[11px] bg-rose-50 text-rose-700 border border-rose-100 font-medium">
                    {job.reject_reason || "不符合硬规则/AI初筛"}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
