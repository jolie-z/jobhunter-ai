import { useState } from "react"
import { Eye, Loader2, Code2, ChevronDown, ChevronUp, Lightbulb } from "lucide-react"
import { getWeekdayLabel, adaptChannelList } from "./report-studio-utils"

interface FeishuCardRendererProps {
  activeType: "daily" | "weekly" | "monthly"
  report: any
  card: any
  loading: boolean
}

function GlobalFunnelSection({
  feishu,
  rates,
}: {
  feishu: any
  rates?: { interview_rate?: number; offer_rate?: number }
}) {
  const cards = [
    { title: "累计已投递", val: `${feishu.total_delivered ?? 0} 个`, sub: rates ? "漏斗起点" : null, border: "border-slate-100 bg-white", text: "text-slate-800", tColor: "text-slate-500", badge: null, bColor: "" },
    { title: "推进面试轮次", val: `${feishu.total_interview ?? 0} 个`, sub: rates ? "投递➔面试转化" : null, border: "border-emerald-100 bg-emerald-50/30", text: "text-emerald-600", tColor: "text-emerald-700", badge: rates ? `${rates.interview_rate ?? 0}%` : null, bColor: "bg-emerald-100/80 text-emerald-800" },
    { title: "最终斩获 Offer", val: `${feishu.total_offer ?? 0} 个`, sub: rates ? "面试➔Offer转化" : null, border: "border-amber-100 bg-amber-50/30", text: "text-amber-600", tColor: "text-amber-700", badge: rates ? `${rates.offer_rate ?? 0}%` : null, bColor: "bg-amber-100/80 text-amber-800" },
  ]

  return (
    <div className="border-t border-slate-100 pt-3.5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-bold uppercase tracking-wider text-slate-600">
          {rates ? "📈 宏观转化漏斗与瓶颈诊断 (Macro Funnel)" : "📈 全局求职漏斗 (All-Time)"}
        </span>
        <span className="text-[11px] text-slate-400">
          {rates ? "投递 ➔ 面试 ➔ Offer 全程转化" : "系统历史总盘子"}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2.5">
        {cards.map((c) => (
          <div key={c.title} className={`rounded-lg border p-3 text-center ${c.border}`}>
            <div className="flex items-center justify-center gap-1">
              <span className={`text-[11px] font-medium ${c.tColor}`}>{c.title}</span>
              {c.badge && <span className={`text-[10px] font-mono px-1 rounded ${c.bColor}`}>{c.badge}</span>}
            </div>
            <p className={`mt-1 text-base font-bold ${c.text}`}>{c.val}</p>
            {c.sub && <span className="text-[10px] text-slate-400 block mt-0.5">{c.sub}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

export function FeishuCardRenderer({
  activeType,
  report,
  card,
  loading,
}: FeishuCardRendererProps) {
  const [showJson, setShowJson] = useState(false)

  const theme = {
    daily: { text: "text-sky-600", bar: "bg-sky-500", tipBg: "bg-amber-50/20", tipText: "text-amber-800", tipIcon: "text-amber-500", tipTitle: "明日建议与行动指引", tipDot: "text-amber-500" },
    weekly: { text: "text-emerald-600", bar: "bg-emerald-500", tipBg: "bg-emerald-50/25", tipText: "text-emerald-800", tipIcon: "text-emerald-600", tipTitle: "下周策略复盘与行动指引", tipDot: "text-emerald-600" },
    monthly: { text: "text-purple-600", bar: "bg-purple-500", tipBg: "bg-purple-50/25", tipText: "text-purple-800", tipIcon: "text-purple-600", tipTitle: "月度战略复盘与次月战术指引", tipDot: "text-purple-600" },
  }[activeType]
  const accentColor = theme.bar

  const feishu = report?.feishu || {}
  const crawl = report?.crawl || {}
  const tokens = report?.tokens || {}
  const suggestions: string[] = report?.suggestions || []

  // 今日放行数
  const totalCrawled = crawl.total ?? 0
  const rejectedCount = crawl.rejected ?? 0
  const passedCount = Math.max(0, totalCrawled - rejectedCount)
  const passRate = crawl.pass_rate ?? 100

  // 渠道统一效能数据适配 (日报/周报/月报)
  const channelList = adaptChannelList(activeType, report, crawl, totalCrawled)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
          <Eye className="size-3.5" />
          飞书群卡片实时渲染预览 (所见即所得)
        </span>
        <span className="text-[11px] text-slate-400 font-mono">
          {activeType === "daily"
            ? "日结收盘汇总"
            : activeType === "weekly"
            ? "周一全平台复盘"
            : "月度宏观全景与质量矩阵"}
        </span>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-16 text-center text-xs text-muted-foreground rounded-xl border border-slate-200 bg-white">
          <Loader2 className="size-6 animate-spin text-primary mb-2" />
          正在生成飞书交互式卡片实时预览...
        </div>
      ) : report && card ? (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xs">
          {/* 卡片顶端 Accent 饰条 */}
          <div className={`h-1.5 w-full ${accentColor}`} />

          {/* 卡片标题栏 */}
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5 bg-slate-50/50">
            <div className="flex items-center gap-2">
              <span className={`size-2.5 rounded-full ${accentColor}`} />
              <h3 className="text-sm font-bold text-slate-900">
                {activeType === "daily"
                  ? `📊 求职日报 · ${report.date} (${getWeekdayLabel(report.date)})`
                  : activeType === "weekly"
                  ? `📈 求职周报 · ${report.week_start} ~ ${report.week_end}`
                  : `🌐 求职月报 · ${report.month}`}
              </h3>
            </div>
            <span className="text-xs font-mono text-slate-500">
              {activeType === "daily" ? "今日战报" : activeType === "weekly" ? "周度复盘" : "月度全景"}
            </span>
          </div>

          {/* ══ 日报专属排版：今日流水动态 + 全局大盘 ══ */}
          {activeType === "daily" && (
            <div className="p-5 space-y-4">
              {/* 板块 1: 今日流水动态 */}
              <div>
                <div className="flex items-center justify-between mb-2.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-sky-700 bg-sky-50 px-2 py-0.5 rounded">
                    ⚡ 今日流水动态 (Today)
                  </span>
                  <span className="text-[11px] text-slate-400">今日单日增量数据</span>
                </div>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                  <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                    <span className="text-[11px] text-slate-500">今日新抓取</span>
                    <p className="mt-1 text-base font-bold text-slate-900">{totalCrawled} 条</p>
                  </div>
                  <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                    <span className="text-[11px] text-slate-500">AI 清洗放行</span>
                    <p className="mt-1 text-base font-bold text-slate-800">
                      {passedCount} 条 <span className="text-[10px] font-normal text-slate-400">({passRate}%)</span>
                    </p>
                  </div>
                  <div className="rounded-lg border border-sky-100 bg-sky-50/40 p-3">
                    <span className="text-[11px] text-sky-700 font-medium">今日实际投递</span>
                    <p className="mt-1 text-base font-bold text-sky-600">
                      {feishu.today_delivered ?? 0} 个
                    </p>
                  </div>
                  <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                    <span className="text-[11px] text-slate-500">待投递池存量</span>
                    <p className="mt-1 text-base font-bold text-slate-700">
                      {feishu.total_pending ?? 0} 个
                    </p>
                  </div>
                </div>
              </div>

              {/* 板块 2: 全局求职大盘漏斗 */}
              <GlobalFunnelSection feishu={feishu} />
            </div>
          )}

          {/* ══ 周报专属排版：周度战况 + 7天走势 + 全局大盘 ══ */}
          {activeType === "weekly" && (
            <div className="p-5 space-y-4">
              {/* 板块 1: 本周流转战报 */}
              <div>
                <div className="flex items-center justify-between mb-2.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">
                    ⚡ 本周流转战况 (Weekly Momentum)
                  </span>
                  <span className="text-[11px] text-slate-400">
                    {report.week_start} ~ {report.week_end}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                  <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                    <span className="text-[11px] text-slate-500">本周新抓取</span>
                    <div className="mt-1 flex items-baseline gap-1.5">
                      <span className="text-base font-bold text-slate-900">{totalCrawled} 条</span>
                      <span
                        className={`inline-flex items-center text-[10px] font-semibold px-1 py-0.5 rounded ${
                          (report.crawl_change_percent ?? 0) >= 0
                            ? "bg-emerald-50 text-emerald-700"
                            : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {(report.crawl_change_percent ?? 0) >= 0 ? "📈 +" : "📉 "}
                        {report.crawl_change_percent ?? 0}%
                      </span>
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                    <span className="text-[11px] text-slate-500">AI 清洗放行</span>
                    <p className="mt-1 text-base font-bold text-slate-800">
                      {passedCount} 条 <span className="text-[10px] font-normal text-slate-400">({passRate}%)</span>
                    </p>
                  </div>
                  <div className="rounded-lg border border-emerald-100 bg-emerald-50/40 p-3">
                    <span className="text-[11px] text-emerald-700 font-medium">本周实际投递</span>
                    <p className="mt-1 text-base font-bold text-emerald-600">
                      {feishu.week_delivered ?? 0} 个
                    </p>
                  </div>
                  <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                    <span className="text-[11px] text-slate-500">待投递池存量</span>
                    <p className="mt-1 text-base font-bold text-slate-700">
                      {feishu.total_pending ?? 0} 个
                    </p>
                  </div>
                </div>
              </div>

              {/* 板块 2: 周内 7 天推进节奏 */}
              {report.daily_breakdown && report.daily_breakdown.length > 0 && (
                <div className="border-t border-slate-100 pt-3.5">
                  <div className="flex items-center justify-between mb-2.5">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-slate-600">
                      📅 周内 7 天推进节奏 (Daily Cadence)
                    </span>
                    <span className="text-[11px] text-slate-400">周一至周日抓取走势</span>
                  </div>
                  <div className="grid grid-cols-7 gap-1.5">
                    {report.daily_breakdown.map((d: any) => {
                      const maxVal = Math.max(...report.daily_breakdown.map((x: any) => x.crawled), 1)
                      const heightPct = Math.max(12, Math.round((d.crawled / maxVal) * 100))
                      const isZero = d.crawled === 0
                      return (
                        <div
                          key={d.date}
                          className="flex flex-col items-center gap-1.5 rounded-lg border border-slate-100 bg-slate-50/50 p-2 text-center"
                        >
                          <span className="text-[10px] text-slate-400 font-mono">{d.date.slice(5)}</span>
                          <div className="flex h-10 w-full items-end justify-center">
                            <div
                              className={`w-4 rounded-t transition-all duration-300 ${
                                isZero ? "bg-slate-200" : "bg-emerald-500 shadow-xs"
                              }`}
                              style={{ height: `${heightPct}%` }}
                            />
                          </div>
                          <span
                            className={`text-[11px] font-bold font-mono ${
                              isZero ? "text-slate-400" : "text-emerald-700"
                            }`}
                          >
                            {d.crawled}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* 板块 3: 全局求职大盘漏斗 */}
              <GlobalFunnelSection feishu={feishu} />
            </div>
          )}

          {/* ══ 月报专属排版：本月流转效能 + 宏观转化漏斗与瓶颈诊断 ══ */}
          {activeType === "monthly" && (
            <div className="p-5 space-y-4">
              {/* 板块 1: 本月流转效能 */}
              <div>
                <div className="flex items-center justify-between mb-2.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-purple-700 bg-purple-50 px-2 py-0.5 rounded">
                    ⚡ 本月战果与流转效能 (Monthly Velocity)
                  </span>
                  <span className="text-[11px] text-slate-400">本月全盘流转增量</span>
                </div>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                  <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                    <span className="text-[11px] text-slate-500">本月新抓取</span>
                    <p className="mt-1 text-base font-bold text-slate-900">{totalCrawled} 条</p>
                  </div>
                  <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                    <span className="text-[11px] text-slate-500">AI 初筛放行</span>
                    <p className="mt-1 text-base font-bold text-slate-800">
                      {passedCount} 条 <span className="text-[10px] font-normal text-slate-400">({passRate}%)</span>
                    </p>
                  </div>
                  <div className="rounded-lg border border-purple-100 bg-purple-50/40 p-3">
                    <span className="text-[11px] text-purple-700 font-medium">本月实际投递</span>
                    <p className="mt-1 text-base font-bold text-purple-600">
                      {feishu.month_delivered ?? 0} 个
                    </p>
                  </div>
                  <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                    <span className="text-[11px] text-slate-500">待投递池存量</span>
                    <p className="mt-1 text-base font-bold text-slate-700">
                      {feishu.total_pending ?? 0} 个
                    </p>
                  </div>
                </div>
              </div>

              {/* 板块 2: 宏观转化漏斗与瓶颈诊断 */}
              <GlobalFunnelSection feishu={feishu} rates={report.funnel_rates} />
            </div>
          )}

          {/* 渠道分布 / 月度质量矩阵 (结构化效能矩阵表) */}
          <div className="border-t border-slate-100 px-5 py-4">
            <div className="flex items-center justify-between mb-2.5">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-600 flex items-center gap-1.5">
                <span>📡</span>
                <span>
                  {activeType === "monthly"
                    ? "各渠道月度质量与在库矩阵"
                    : activeType === "weekly"
                    ? "各渠道本周产出与在库总量"
                    : "各渠道今日产出与在库总量"}
                </span>
              </p>
              <span className="text-[10px] text-slate-400 font-mono">
                {activeType === "monthly"
                  ? "月度质量评级矩阵"
                  : activeType === "weekly"
                  ? "周度贡献效能矩阵"
                  : "今日贡献效能矩阵"}
              </span>
            </div>

            <div className="overflow-x-auto rounded-lg border border-slate-100 bg-slate-50/40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-200/70 text-slate-500 bg-slate-50/80 text-[11px]">
                    <th className="py-2.5 pl-3.5 text-left font-medium">招聘渠道</th>
                    <th className="py-2.5 px-2 text-right font-medium">
                      {activeType === "monthly" ? "本月抓取" : activeType === "weekly" ? "本周新增" : "今日新增"}
                    </th>
                    <th className="py-2.5 px-2 text-left font-medium w-36">
                      {activeType === "monthly" ? "AI初筛合格率" : activeType === "weekly" ? "周贡献占比" : "今日贡献占比"}
                    </th>
                    <th className="py-2.5 px-2 text-right font-medium">在库总存量</th>
                    <th className="py-2.5 pr-3.5 text-right font-medium">
                      {activeType === "monthly" ? "质量评级" : "活跃度"}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {channelList.length > 0 ? (
                    channelList.map((item: any) => {
                      const barBg = activeType === "monthly" ? (item.rate >= 80 ? "bg-purple-500" : "bg-amber-500") : theme.bar

                      return (
                        <tr key={item.name} className="hover:bg-slate-50/60 transition-colors">
                          <td className="py-2.5 pl-3.5 font-medium text-slate-800">{item.name}</td>
                          <td className="py-2.5 px-2 text-right font-mono">
                            {item.count > 0 ? (
                              <span className={`${theme.text} font-bold`}>+{item.count} 条</span>
                            ) : (
                              <span className="text-slate-400">0 条</span>
                            )}
                          </td>
                          <td className="py-2.5 px-2">
                            <div className="flex items-center gap-2">
                              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                                <div
                                  className={`h-full rounded-full transition-all duration-300 ${
                                    item.count > 0 || activeType === "monthly" ? barBg : "bg-transparent"
                                  }`}
                                  style={{ width: `${Math.min(100, item.rate)}%` }}
                                />
                              </div>
                              <span className="font-mono text-[11px] text-slate-500 w-11">{item.rateLabel}</span>
                            </div>
                          </td>
                          <td className="py-2.5 px-2 text-right font-mono text-slate-700">
                            {item.stock.toLocaleString()} 条
                          </td>
                          <td className="py-2.5 pr-3.5 text-right">
                            <span
                              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${item.status.bg}`}
                            >
                              <span className={`size-1.5 rounded-full ${item.status.dot}`} />
                              {item.status.text}
                            </span>
                          </td>
                        </tr>
                      )
                    })
                  ) : (
                    <tr>
                      <td colSpan={5} className="py-4 text-center text-xs text-slate-400">
                        暂无渠道数据
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* 建议与行动指引 */}
          {suggestions.length > 0 && (
            <div className={`border-t border-slate-100 px-5 py-3.5 ${theme.tipBg}`}>
              <p className={`mb-2 text-[11px] font-semibold uppercase tracking-wider flex items-center gap-1.5 ${theme.tipText}`}>
                <Lightbulb className={`size-3.5 ${theme.tipIcon}`} />
                {theme.tipTitle}
              </p>
              <div className="space-y-1">
                {suggestions.map((s, idx) => (
                  <p key={idx} className="text-xs text-slate-700 flex items-start gap-1.5 leading-relaxed">
                    <span className={`font-bold ${theme.tipDot}`}>•</span>
                    <span>{s}</span>
                  </p>
                ))}
              </div>
            </div>
          )}

          {/* 卡片底栏: 模型与 Token 消耗 */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 bg-slate-50/50 px-5 py-3 text-xs text-slate-500">
            <div className="flex items-center gap-4 font-mono">
              <span>Token: <strong className="text-slate-800">{tokens.tokens?.toLocaleString() ?? 0}</strong></span>
              <span>预估成本: <strong className="text-slate-800">¥{tokens.cost_cny?.toFixed(2) ?? "0.00"}</strong></span>
            </div>
            <span className="text-[11px]">JobHunter AI Copilot 真实数据驱动</span>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-xs text-slate-400 bg-white">
          暂无预览数据，系统产生真实岗位抓取或投递后自动组装。
        </div>
      )}

      {/* 飞书卡片 JSON 查看 */}
      {card && (
        <div>
          <button
            type="button"
            onClick={() => setShowJson(!showJson)}
            className="flex items-center gap-1.5 text-xs text-slate-400 transition-colors hover:text-slate-700"
          >
            <Code2 className="size-3.5" />
            <span>{showJson ? "收起飞书卡片 JSON 协议结构" : "展开查看飞书 Interactive Card JSON 原始结构"}</span>
            {showJson ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
          </button>
          {showJson && (
            <pre className="mt-2 max-h-64 overflow-x-auto rounded-xl border border-slate-200 bg-slate-900 text-slate-100 p-4 font-mono text-[11px] leading-relaxed">
              {JSON.stringify(card, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
