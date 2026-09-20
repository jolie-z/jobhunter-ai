"use client"

import { useState } from "react"
import { ShieldAlert, Info } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface DeliverySecurityCardProps {
  deliveryTimeoutSec: number
  onChangeTimeout: (val: number) => void
  batchLimit: number
  onChangeBatchLimit: (val: number) => void
}

export function DeliverySecurityCard({
  deliveryTimeoutSec,
  onChangeTimeout,
  batchLimit,
  onChangeBatchLimit,
}: DeliverySecurityCardProps) {
  // 数字输入草稿值：null 表示跟随外部受控值，"" 表示用户已清空、等待重新输入（onBlur 再收敛）
  const [timeoutDraft, setTimeoutDraft] = useState<string | null>(null)
  const [batchDraft, setBatchDraft] = useState<string | null>(null)

  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3">
      {/* 顶栏标题与感叹号说明 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-amber-500/10 text-amber-600 dark:text-amber-400">
            <ShieldAlert className="h-3.5 w-3.5" />
          </div>
          <span className="text-xs font-semibold text-foreground tracking-tight">
            防封风控保护与超时看门狗熔断
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors cursor-help p-0.5 rounded-full hover:bg-muted"
              >
                <Info className="h-3.5 w-3.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
              【看门狗熔断】：单岗位若遇到弹窗验证码、网络卡死或浏览器未响应超过超时时间，看门狗将自动判定投递失败并跳过，防止整条流水线阻塞；【防封随机延时】：每个操作步骤自动注入 3~8 秒随机微波动，模拟人工真实行为。
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[11px] text-muted-foreground">
          单步自动注入 3~8s 随机操作延时
        </span>
      </div>

      {/* 两项设置行：改为 2 行全宽展示，单行完整不折行 */}
      <div className="space-y-2.5">
        {/* 单岗看门狗超时 */}
        <div className="flex items-center justify-between gap-2 rounded-xl border border-border/60 bg-background/60 p-3">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-foreground">
              🛡️ 单岗超时看门狗
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground hover:text-foreground">
                  <Info className="h-3.5 w-3.5 text-zinc-400" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                单岗位投递在浏览器中执行超过该秒数未完成时，强制熔断跳过并记录失败日志。
              </TooltipContent>
            </Tooltip>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <input
              type="number"
              min={15}
              max={180}
              step={5}
              value={timeoutDraft !== null ? timeoutDraft : deliveryTimeoutSec}
              onChange={(e) => {
                if (e.target.value === "") {
                  setTimeoutDraft("")
                } else {
                  setTimeoutDraft(null)
                  onChangeTimeout(Number(e.target.value))
                }
              }}
              onBlur={() => {
                if (timeoutDraft === "") {
                  // 清空失焦时回填默认值
                  onChangeTimeout(45)
                } else {
                  // 失焦时收敛到 [15, 180]
                  onChangeTimeout(Math.min(180, Math.max(15, deliveryTimeoutSec)))
                }
                setTimeoutDraft(null)
              }}
              className="h-8 w-20 rounded-lg border border-border bg-background px-2 text-center text-xs font-mono font-semibold text-foreground focus:border-amber-500 focus:outline-none"
            />
            <span className="text-xs text-muted-foreground">秒熔断跳过</span>
          </div>
        </div>

        {/* 单批次投递上限 */}
        <div className="flex items-center justify-between gap-2 rounded-xl border border-border/60 bg-background/60 p-3">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-foreground">
              📦 单批次投递上限
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground hover:text-foreground">
                  <Info className="h-3.5 w-3.5 text-zinc-400" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                控制单次任务执行的最大投递岗位数量，避免触发各大平台的单日投递配额上限。
              </TooltipContent>
            </Tooltip>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <input
              type="number"
              min={1}
              max={100}
              step={5}
              value={batchDraft !== null ? batchDraft : batchLimit}
              onChange={(e) => {
                if (e.target.value === "") {
                  setBatchDraft("")
                } else {
                  setBatchDraft(null)
                  onChangeBatchLimit(Number(e.target.value))
                }
              }}
              onBlur={() => {
                if (batchDraft === "") {
                  // 清空失焦时回填默认值
                  onChangeBatchLimit(20)
                } else {
                  // 失焦时收敛到 [1, 100]
                  onChangeBatchLimit(Math.min(100, Math.max(1, batchLimit)))
                }
                setBatchDraft(null)
              }}
              className="h-8 w-20 rounded-lg border border-border bg-background px-2 text-center text-xs font-mono font-semibold text-foreground focus:border-amber-500 focus:outline-none"
            />
            <span className="text-xs text-muted-foreground">岗/批次上限</span>
          </div>
        </div>
      </div>
    </div>
  )
}
