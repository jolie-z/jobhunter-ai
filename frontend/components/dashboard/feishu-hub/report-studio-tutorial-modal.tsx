import { Bell, Lightbulb } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

interface ReportStudioTutorialModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ReportStudioTutorialModal({
  open,
  onOpenChange,
}: ReportStudioTutorialModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto border-slate-200 bg-white">
        <DialogHeader>
          <DialogTitle className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <Bell className="size-5 text-sky-600" />
            飞书自动化战报调度与卡片解读说明
          </DialogTitle>
          <DialogDescription className="mt-1 text-xs leading-relaxed text-slate-500">
            系统通过内置的 APScheduler 定时任务引擎，在预设时间自动汇总流水数据，组装成高信息密度的交互式飞书卡片推送到绑定的求职群。
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 space-y-4">
          <div className="space-y-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">三大战报维度与推送节奏</h3>
            <div className="space-y-2.5">
              <div className="rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                <p className="text-xs font-semibold text-slate-900">1. 每日求职战报（建议 21:00）</p>
                <p className="mt-0.5 text-xs text-slate-500 leading-relaxed">
                  · <strong>今日流水</strong>：呈现今日雷达新抓取、AI 清洗放行数及今日实际投递数；<br />
                  · <strong>全局漏斗</strong>：对齐飞书当前累计投递、进入面试与斩获 Offer 总盘子；<br />
                  · <strong>Token 审计</strong>：清晰罗列今日调用大模型所消耗的算力与预估账单。
                </p>
              </div>

              <div className="rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                <p className="text-xs font-semibold text-slate-900">2. 周度复盘战报（建议周一 09:00）</p>
                <p className="mt-0.5 text-xs text-slate-500 leading-relaxed">
                  · <strong>渠道效能对比</strong>：展示 BOSS直聘、智联、猎聘、前程无忧等各平台的周抓取量排行；<br />
                  · <strong>转化演化</strong>：核算从全周抓取到累计投递与面试流转进展。
                </p>
              </div>

              <div className="rounded-xl border border-slate-200/70 bg-slate-50/50 p-3">
                <p className="text-xs font-semibold text-slate-900">3. 月度全景洞察（建议每月 1 日 09:00）</p>
                <p className="mt-0.5 text-xs text-slate-500 leading-relaxed">
                  · <strong>渠道 ROI</strong>：各招聘渠道投入产出比与通过率综合矩阵；<br />
                  · <strong>策略调优</strong>：辅助指导下月岗位关键词及投递方向。
                </p>
              </div>
            </div>
          </div>

          <div className="flex gap-2.5 rounded-xl border border-sky-200/80 bg-sky-50/80 p-3.5">
            <Lightbulb className="size-4 shrink-0 text-sky-600 mt-0.5" />
            <div className="text-xs text-sky-800 space-y-1">
              <p className="font-semibold">使用小贴士：</p>
              <p>1. 修改时间表后点击「保存时间表」，后端调度器会<strong>原地热重载</strong>，无需重启后端服务；</p>
              <p>2. 点击「立即推送当前到群」可在手机/电脑端即刻验收真实排版；</p>
              <p>3. 战报中所有指标均取自系统真实数据库，无任何虚假占位数据。</p>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
