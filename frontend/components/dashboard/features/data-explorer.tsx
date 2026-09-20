import { useState } from "react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { 
  Database, 
  RefreshCw, 
  Loader2,
  Play, 
  Settings2, 
  Send, 
  CheckCircle2, 
  Trash2, 
  ChevronDown,
  ChevronUp,
  Image as ImageIcon,
  ArrowDown,
  Sparkles,
  Bot
} from "lucide-react"

import { Dialog, DialogContent, DialogTrigger, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { RuleEngineBoard } from "@/components/dashboard/rule-engine-board"
import { useTrashBinStore } from "@/store/trash-bin-store"
import { useDataPipeline } from "./use-data-pipeline"

interface DataExplorerProps {
  onTaskStarted: () => void
}

export function DataExplorer({ onTaskStarted }: DataExplorerProps) {
  const [showXhsCard, setShowXhsCard] = useState(false)
  const openTrashBin = useTrashBinStore((state) => state.openTrashBin)

  const {
    stats,
    loading,
    isRefreshing,
    runningTask,
    isProcessing,
    cleanLimit,
    setCleanLimit,
    fetchStats,
    handleRunGlobal,
    handleSyncFeishu,
    handleRunXhs,
    handleRunHardFilter,
    handleRunAiScout,
    handleSkipAiSync,
  } = useDataPipeline({ onTaskStarted })

  return (
    <div className="flex-1 overflow-y-auto p-3.5 space-y-3 bg-zinc-50/50">
      {/* 顶部标题栏 */}
      <div className="flex items-center justify-between pb-2 border-b border-zinc-200/60 shrink-0">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900 flex items-center gap-1.5">
            <Database className="w-4 h-4 text-emerald-600" />
            数据流转管道大盘
          </h3>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            全平台岗位采集、初筛排雷到飞书同步
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-zinc-600 hover:text-emerald-700 hover:bg-emerald-50/50 transition-colors"
          onClick={() => void fetchStats(true)}
          disabled={isRefreshing}
          title="手动刷新各阶段最新水位指标"
        >
          {isRefreshing ? (
            <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin text-emerald-600" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5 mr-1 text-zinc-500" />
          )}
          <span>{isRefreshing ? "刷新中..." : "刷新"}</span>
        </Button>
      </div>

      {/* 🌊 核心流水大盘 (纵向流水拓扑) */}
      <Card className="p-3 border-zinc-200/80 bg-white shadow-xs space-y-2.5">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-zinc-700 tracking-wide">
            数据流转全景大盘
          </span>
          <span className="inline-flex items-center gap-1 text-[10px] text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            实时同步中
          </span>
        </div>

        {/* 纵向流水级联卡片 */}
        <div className="space-y-1.5">
          {/* Stage 1: 待清洗原始池 */}
          <div className="p-2.5 rounded-lg border border-blue-100 bg-blue-50/30 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="w-4 h-4 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-[10px] font-bold shrink-0">
                  1
                </span>
                <span className="text-xs font-semibold text-blue-950 truncate">待清洗原始池</span>
                <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 bg-blue-50 text-blue-600 border-blue-200 shrink-0">
                  刚抓取未洗
                </Badge>
              </div>
              <div className="flex items-baseline gap-1 shrink-0">
                <span className="text-lg font-bold text-blue-900">
                  {loading ? "..." : stats.raw_pending}
                </span>
                <span className="text-[10px] text-blue-600">个岗位</span>
              </div>
            </div>

            {/* 平台细分标签 */}
            <div className="flex flex-wrap items-center gap-1 pt-1.5 border-t border-blue-100/60 text-[10px]">
              {Object.keys(stats.global_breakdown).length > 0 ? (
                Object.entries(stats.global_breakdown).map(([platform, count]) => (
                  <span key={platform} className="px-1.5 py-0.5 rounded bg-white/80 border border-blue-100 text-zinc-600">
                    {platform}: <strong className="text-blue-900 font-semibold">{count}</strong>
                  </span>
                ))
              ) : (
                <span className="text-zinc-400">暂无新入库数据</span>
              )}
            </div>

            {/* Stage 1 内置原子控制按钮：仅保留纯硬筛选 (0 Token) */}
            {stats.raw_pending > 0 && (
              <div className="pt-1.5 border-t border-blue-100/60">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleRunHardFilter}
                  disabled={isProcessing}
                  className={`w-full h-6 px-2 text-[10px] font-medium flex items-center justify-center transition-colors ${
                    isProcessing
                      ? 'bg-zinc-100 border-zinc-200 text-zinc-400 cursor-not-allowed'
                      : 'bg-white hover:bg-blue-100/70 border-blue-300 text-blue-800'
                  }`}
                  title={isProcessing ? "已有清洗流水线任务正在执行，已自动锁定互斥防踩踏" : "仅执行本地硬规则过滤（城市/学历/年限/黑名单），毫秒级完成，0 Token 消耗"}
                >
                  <Sparkles className="w-3 h-3 mr-1 text-blue-600 shrink-0" />
                  <span>执行硬规则初筛 (0 Token 消耗)</span>
                </Button>
              </div>
            )}
          </div>

          {/* 连接箭头 1 */}
          <div className="flex items-center justify-center py-0.5 text-zinc-300">
            <ArrowDown className="w-3.5 h-3.5 animate-bounce duration-1000" />
          </div>

          {/* Stage 2: 待 AI 清洗池 (已完成硬清洗未执行AI清洗) */}
          <div className={`p-2.5 rounded-lg border space-y-2 transition-all ${stats.ai_pending > 0 ? 'border-purple-200 bg-purple-50/40 shadow-xs' : 'border-zinc-200/80 bg-zinc-50/40'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${stats.ai_pending > 0 ? 'bg-purple-100 text-purple-800' : 'bg-zinc-200/80 text-zinc-500'}`}>
                  2
                </span>
                <span className={`text-xs font-semibold truncate ${stats.ai_pending > 0 ? 'text-purple-950' : 'text-zinc-600'}`}>待 AI 清洗池</span>
                <Badge variant="outline" className={`text-[9px] px-1 py-0 h-4 shrink-0 ${stats.ai_pending > 0 ? 'bg-purple-50 text-purple-800 border-purple-200 font-medium' : 'text-zinc-400 border-zinc-200 bg-zinc-100/50'}`}>
                  硬规则已过
                </Badge>
              </div>
              <div className="flex items-baseline gap-1 shrink-0">
                <span className={`text-lg font-bold ${stats.ai_pending > 0 ? 'text-purple-900' : 'text-zinc-400'}`}>
                  {loading ? "..." : stats.ai_pending}
                </span>
                <span className="text-[10px] text-zinc-500">个岗位</span>
              </div>
            </div>

            <div className="flex items-center justify-between pt-1.5 border-t border-zinc-200/50 text-[10px]">
              <span className={`truncate ${stats.ai_pending > 0 ? 'text-purple-800/90 font-medium' : 'text-zinc-400'}`}>
                {stats.ai_pending > 0 ? "请选择流向策略" : "等待 Stage 1 数据流入"}
              </span>
              <div className="flex items-center gap-1 shrink-0">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleSkipAiSync}
                  disabled={stats.ai_pending === 0 || isProcessing}
                  className={`h-6 px-1.5 text-[10px] font-medium transition-all ${
                    stats.ai_pending > 0 && !isProcessing
                      ? 'bg-white hover:bg-zinc-100 border-zinc-300 text-zinc-700 shadow-xs'
                      : 'bg-zinc-100/60 border-zinc-200/70 text-zinc-400 cursor-not-allowed'
                  }`}
                  title={isProcessing ? "已有任务正在执行，已自动锁定互斥防踩踏" : (stats.ai_pending > 0 ? "跳过大模型排雷，将硬规则合格的岗位直接推送到飞书（省 Token）" : "当前暂无待 AI 清洗的岗位")}
                >
                  免AI直推飞书
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleRunAiScout}
                  disabled={stats.ai_pending === 0 || isProcessing}
                  className={`h-6 px-2 text-[10px] font-medium transition-all ${
                    stats.ai_pending > 0 && !isProcessing
                      ? 'bg-white hover:bg-purple-100/80 border-purple-300 text-purple-900 shadow-xs'
                      : 'bg-zinc-100/60 border-zinc-200/70 text-zinc-400 cursor-not-allowed'
                  }`}
                  title={isProcessing ? "已有任务正在执行，已自动锁定互斥防踩踏" : (stats.ai_pending > 0 ? "调用大模型对本批岗位做 JD 深度语义排雷" : "当前暂无待 AI 清洗的岗位")}
                >
                  <Bot className={`w-3 h-3 mr-1 ${stats.ai_pending > 0 && !isProcessing ? 'text-purple-700' : 'text-zinc-400'}`} />
                  启动 AI 排雷
                </Button>
              </div>
            </div>
          </div>

          {/* 连接箭头 2 */}
          <div className="flex items-center justify-center py-0.5 text-zinc-300">
            <ArrowDown className="w-3.5 h-3.5" />
          </div>

          {/* Stage 3: 待推送飞书池 */}
          <div className={`p-2.5 rounded-lg border space-y-1.5 transition-all ${stats.ready_to_sync > 0 ? 'border-amber-200 bg-amber-50/30' : 'border-zinc-200 bg-zinc-50/40'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="w-4 h-4 rounded-full bg-amber-100 text-amber-800 flex items-center justify-center text-[10px] font-bold shrink-0">
                  3
                </span>
                <span className="text-xs font-semibold text-amber-950 truncate">待推送飞书池</span>
                <Badge variant="outline" className={`text-[9px] px-1 py-0 h-4 shrink-0 ${stats.ready_to_sync > 0 ? 'bg-amber-50 text-amber-800 border-amber-200' : 'text-zinc-500 border-zinc-200'}`}>
                  已过AI清洗
                </Badge>
              </div>
              <div className="flex items-baseline gap-1 shrink-0">
                <span className={`text-lg font-bold ${stats.ready_to_sync > 0 ? 'text-amber-900' : 'text-zinc-600'}`}>
                  {loading ? "..." : stats.ready_to_sync}
                </span>
                <span className="text-[10px] text-zinc-500">个岗位</span>
              </div>
            </div>

            <div className="flex items-center justify-between pt-1.5 border-t border-amber-100/60 text-[10px]">
              <span className={`truncate ${stats.ready_to_sync > 0 ? 'text-zinc-500' : 'text-zinc-400'}`}>
                {stats.ready_to_sync > 0 ? "排雷合格，排队入库飞书" : "暂无待推送岗位"}
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={handleSyncFeishu}
                disabled={stats.ready_to_sync === 0 || isProcessing}
                className={`h-6 px-2 text-[10px] font-medium shrink-0 transition-all ${
                  stats.ready_to_sync > 0 && !isProcessing
                    ? 'bg-white border-amber-300 text-amber-900 hover:bg-amber-100/80 shadow-xs'
                    : 'bg-zinc-100/60 border-zinc-200/70 text-zinc-400 cursor-not-allowed'
                }`}
                title={isProcessing ? "已有任务正在执行，已自动锁定互斥防踩踏" : (stats.ready_to_sync > 0 ? "对滞留在待推送池的岗位一键补齐同步到飞书多维表格" : "当前暂无待推送岗位")}
              >
                <Send className={`w-3 h-3 mr-1 ${stats.ready_to_sync > 0 && !isProcessing ? 'text-amber-700' : 'text-zinc-400'}`} />
                补推飞书
              </Button>
            </div>
          </div>

          {/* 连接箭头 3 */}
          <div className="flex items-center justify-center py-0.5 text-zinc-300">
            <ArrowDown className="w-3.5 h-3.5" />
          </div>

          {/* Stage 4: 飞书多维表格 */}
          <div className="p-2.5 rounded-lg border border-emerald-100 bg-emerald-50/30 space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="w-4 h-4 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center text-[10px] font-bold shrink-0">
                  4
                </span>
                <span className="text-xs font-semibold text-emerald-950 truncate">飞书多维表格</span>
                <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 bg-emerald-50 text-emerald-800 border-emerald-200 shrink-0">
                  在线总表
                </Badge>
              </div>
              <div className="flex items-baseline gap-1 shrink-0">
                <span className="text-lg font-bold text-emerald-900">
                  {loading ? "..." : stats.synced_count}
                </span>
                <span className="text-[10px] text-emerald-700">个岗位</span>
              </div>
            </div>

            <div className="pt-1.5 border-t border-emerald-100/60 text-[10px] text-emerald-700 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3 text-emerald-600 shrink-0" />
              <span className="truncate">已入库协同并持续打分</span>
            </div>
          </div>
        </div>

        {/* 底部清洗拦截站分支 (与右上角拦截站完全对齐) */}
        <div className="p-2.5 rounded-lg bg-zinc-50 border border-zinc-200/80 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-6 h-6 rounded-md bg-rose-50 border border-rose-100 text-rose-600 flex items-center justify-center shrink-0">
              <Trash2 className="w-3.5 h-3.5" />
            </div>
            <div className="min-w-0 space-y-1">
              <div className="flex items-center gap-1.5">
                <span className="font-medium text-zinc-800 text-[11px]">清洗拦截站</span>
                <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 bg-rose-50 text-rose-600 border-rose-200 shrink-0 font-medium">
                  已拦截 {stats.rejected_count}
                </Badge>
              </div>
              <div className="flex items-center gap-1 text-[10px]">
                <span className="px-1.5 py-0.5 rounded bg-white/90 border border-rose-100 text-zinc-600 shadow-xs">
                  规则拦截: <strong className="text-rose-900 font-semibold">{stats.rejected_rule_count || 0}</strong>
                </span>
                <span className="px-1.5 py-0.5 rounded bg-white/90 border border-rose-100 text-zinc-600 shadow-xs">
                  AI排雷: <strong className="text-rose-900 font-semibold">{stats.rejected_ai_count || 0}</strong>
                </span>
              </div>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={openTrashBin}
            className="h-6 px-2 text-[11px] text-zinc-600 hover:text-zinc-900 shrink-0"
          >
            查看拦截明细
          </Button>
        </div>
      </Card>

      {/* ⚙️ 管道操作区 (Controls) */}
      <Card className="p-3 border-zinc-200/80 bg-white shadow-xs space-y-3">
        <span className="text-xs font-semibold text-zinc-700 tracking-wide">
          流水线操作指令
        </span>

        <div className="space-y-2.5">
          {/* 单轮清洗上限选择 */}
          <div className="space-y-1.5">
            <div className="flex items-center text-[11px] text-zinc-600">
              <span className="font-medium">单轮清洗上限:</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative flex items-center shrink-0">
                <span className="absolute left-2 text-[10px] font-medium text-zinc-400 select-none pointer-events-none">自定</span>
                <input 
                  type="number" 
                  value={cleanLimit}
                  onChange={(e) => setCleanLimit(e.target.value)}
                  className="w-20 h-8 pl-8 pr-5 outline-none border border-zinc-200 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 rounded-lg text-xs font-bold text-zinc-800 bg-white shadow-2xs [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none placeholder:text-zinc-300 placeholder:font-normal text-center"
                  min={1}
                  placeholder="数量"
                  title="自定义单轮执行数量（留空表示全量）"
                />
                <span className="absolute right-2 text-[10px] text-zinc-400 select-none pointer-events-none">条</span>
              </div>

              {/* 视觉分割线 */}
              <div className="h-4 w-px bg-zinc-200 shrink-0" />

              {/* 快捷档位预设 */}
              <div className="flex-1 grid grid-cols-4 gap-1">
                {["10", "20", "50", "全量"].map((opt) => {
                  const isSelected = opt === "全量" ? cleanLimit === "" : cleanLimit === opt
                  return (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => setCleanLimit(opt === "全量" ? "" : opt)}
                      className={`h-8 rounded-lg text-xs font-medium transition-all ${
                        isSelected 
                          ? 'bg-emerald-600 text-white shadow-xs font-semibold' 
                          : 'bg-zinc-100/90 hover:bg-zinc-200/80 text-zinc-600 border border-zinc-200/40'
                      }`}
                    >
                      {opt === "全量" ? "全量" : `${opt}条`}
                    </button>
                  )
                })}
              </div>
            </div>
          </div>

          {/* 启动清洗主按钮 (全宽) */}
          <Button
            onClick={handleRunGlobal}
            disabled={stats.raw_pending === 0 || isProcessing}
            className={`w-full h-9 text-xs font-medium shadow-xs transition-all ${
              stats.raw_pending > 0 && !isProcessing 
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white' 
                : 'bg-zinc-100 text-zinc-400 cursor-not-allowed'
            }`}
            title={isProcessing ? "清洗任务正在运行中，已自动锁定互斥防止踩踏" : "全自动串行流转：硬规则初筛 ➔ AI 深度排雷 ➔ 飞书同步入库"}
          >
            {isProcessing ? (
              <><RefreshCw className="w-3.5 h-3.5 mr-1.5 animate-spin text-emerald-600" /> 清洗流水线执行中（已互斥锁定）...</>
            ) : (
              <><Play className="w-3.5 h-3.5 mr-1.5" /> 启动联合清洗并同步 ({stats.raw_pending} 条)</>
            )}
          </Button>

          {/* 规则配置入口 (全宽) */}
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="w-full h-8 px-2 text-xs border-dashed border-zinc-300 text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900">
                <Settings2 className="w-3.5 h-3.5 mr-1.5 text-zinc-500" />
                配置全局清洗与 AI 侦察排雷规则
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-[1200px] w-[95vw] h-[85vh] p-0 border-none bg-transparent shadow-none [&>button]:hidden">
              <DialogTitle className="sr-only">清洗规则配置</DialogTitle>
              <DialogDescription className="sr-only">配置全局的数据清洗与拦截规则</DialogDescription>
              <RuleEngineBoard onSaveSuccess={() => fetchStats()} />
            </DialogContent>
          </Dialog>
        </div>
      </Card>

      {/* 📦 小红书轻量化折叠通道 */}
      <div className="border border-zinc-200/70 rounded-lg bg-white overflow-hidden text-xs">
        <button
          type="button"
          onClick={() => setShowXhsCard(!showXhsCard)}
          className="w-full p-2.5 flex items-center justify-between text-left hover:bg-zinc-50/80 transition-colors"
        >
          <div className="flex items-center gap-1.5 min-w-0">
            <ImageIcon className="w-3.5 h-3.5 text-red-500 shrink-0" />
            <span className="font-medium text-zinc-800 text-[11px] truncate">小红书多模态通道</span>
            <span className="text-[10px] text-zinc-400 truncate">（抓取后默认自洗）</span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${stats.xhs_pending > 0 ? 'bg-red-100 text-red-700' : 'bg-zinc-100 text-zinc-500'}`}>
              待洗: {stats.xhs_pending}
            </span>
            {showXhsCard ? <ChevronUp className="w-3.5 h-3.5 text-zinc-400" /> : <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />}
          </div>
        </button>

        {showXhsCard && (
          <div className="p-2.5 pt-1 border-t border-zinc-100 bg-zinc-50/50 space-y-2">
            <p className="text-[10px] text-zinc-500 leading-relaxed">
              专门针对小红书图文笔记的 OCR 识别与提取。爬虫结束后默认自动完成，若有中断积压可手动触发。
            </p>
            <Button
              size="sm"
              onClick={handleRunXhs}
              disabled={stats.xhs_pending === 0 || isProcessing}
              className={`w-full h-7 text-xs ${stats.xhs_pending > 0 && !isProcessing ? 'bg-red-500 hover:bg-red-600 text-white' : 'bg-zinc-200 text-zinc-400 cursor-not-allowed'}`}
              title={isProcessing ? "已有清洗任务正在运行中，已自动锁定互斥" : undefined}
            >
              {runningTask === 'xhs' ? (
                <><RefreshCw className="w-3 h-3 mr-1 animate-spin" /> 执行中...</>
              ) : (
                <><Play className="w-3 h-3 mr-1" /> 手动触发小红书多模态清洗</>
              )}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
