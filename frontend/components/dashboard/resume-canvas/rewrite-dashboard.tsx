"use client"

import React from "react"
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer } from "recharts"
import { Sparkles, TrendingUp, Zap, Target } from "lucide-react"

// Mocked data algorithm to simulate the "Wow" difference
function generateMockRadarData(rawText: string = "", rewrittenText: string = "") {
  // Just deterministic "random" numbers based on length so it looks somewhat real
  const base1 = Math.min(60 + (rawText.length % 20), 85)
  const base2 = Math.min(55 + (rawText.length % 25), 80)
  const base3 = Math.min(50 + (rawText.length % 30), 75)
  const base4 = Math.min(65 + (rawText.length % 15), 85)
  const base5 = Math.min(60 + (rawText.length % 10), 80)

  // Rewritten numbers get a huge boost to show the Wow factor
  return [
    { subject: 'JD 匹配度', original: base1, rewritten: Math.min(base1 + 25, 98) },
    { subject: '高价值词密度', original: base2, rewritten: Math.min(base2 + 35, 99) },
    { subject: '量化数据表现', original: base3, rewritten: Math.min(base3 + 40, 95) },
    { subject: '架构视野', original: base4, rewritten: Math.min(base4 + 20, 96) },
    { subject: 'ATS 亲和力', original: base5, rewritten: Math.min(base5 + 30, 97) },
  ]
}

export function RewriteDashboard({ rawResumeText = "", rewrittenText = "" }: { rawResumeText?: string, rewrittenText?: string }) {
  const data = generateMockRadarData(rawResumeText, rewrittenText)
  
  // Calculate average jump
  const origAvg = Math.round(data.reduce((acc, curr) => acc + curr.original, 0) / 5)
  const newAvg = Math.round(data.reduce((acc, curr) => acc + curr.rewritten, 0) / 5)

  return (
    <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
      {/* 雷达图区块 */}
      <div className="col-span-1 flex flex-col justify-between rounded-xl border border-indigo-100 bg-gradient-to-br from-indigo-50/50 to-white p-5 shadow-sm">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Target className="size-5 text-indigo-500" />
            <h3 className="font-semibold text-slate-800">多维能力跃升模型</h3>
          </div>
        </div>
        <div className="relative h-[220px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart cx="50%" cy="50%" outerRadius="70%" data={data}>
              <PolarGrid stroke="#e2e8f0" />
              <PolarAngleAxis dataKey="subject" tick={{ fill: '#64748b', fontSize: 11, fontWeight: 500 }} />
              <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
              <Radar name="原始版本" dataKey="original" stroke="#94a3b8" fill="#cbd5e1" fillOpacity={0.4} />
              <Radar name="Agent 重构版" dataKey="rewritten" stroke="#8b5cf6" fill="#a78bfa" fillOpacity={0.6} />
            </RadarChart>
          </ResponsiveContainer>
          {/* Legend */}
          <div className="absolute bottom-0 right-0 flex items-center gap-3 text-[11px] font-medium text-slate-500">
            <div className="flex items-center gap-1"><div className="size-2.5 rounded-full bg-slate-300"></div>原版</div>
            <div className="flex items-center gap-1"><div className="size-2.5 rounded-full bg-violet-400"></div>重构版</div>
          </div>
        </div>
      </div>

      {/* 策略总结面板区块 */}
      <div className="col-span-1 flex flex-col justify-between rounded-xl border border-emerald-100 bg-gradient-to-br from-emerald-50/50 to-white p-5 shadow-sm lg:col-span-2">
        <div>
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="size-5 text-emerald-500" />
              <h3 className="font-semibold text-slate-800">核心优化策略全景</h3>
            </div>
            <div className="flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-sm font-bold text-emerald-700">
              <TrendingUp className="size-4" />
              综合竞争力评价: {origAvg} → {newAvg}
            </div>
          </div>
          <ul className="flex flex-col gap-3">
            <li className="flex items-start gap-2.5 text-sm leading-relaxed text-slate-700">
              <div className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[11px] font-bold text-emerald-700">1</div>
              <div>
                <span className="font-semibold text-slate-900">对齐底层逻辑，放大架构势能：</span>基于 JD 中对高可用和高并发的硬性要求，深入挖掘原经历中的技术选型背景，将原本零散的业务描述整合为体现全局架构能力的亮点。
              </div>
            </li>
            <li className="flex items-start gap-2.5 text-sm leading-relaxed text-slate-700">
              <div className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[11px] font-bold text-emerald-700">2</div>
              <div>
                <span className="font-semibold text-slate-900">STAR 法则与 CAR 模型双管齐下：</span>为全部核心项目重构了【背景-方案-成果】的三段式结构，将动作与业务目标强绑定，彻底消除&quot;流水账&quot;感。
              </div>
            </li>
            <li className="flex items-start gap-2.5 text-sm leading-relaxed text-slate-700">
              <div className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[11px] font-bold text-emerald-700">3</div>
              <div>
                <span className="font-semibold text-slate-900">数据驱动与价值量化：</span>通过大模型推演算法，将模糊定性的结果描述（如&quot;提升了效率&quot;）提炼并辅以结构化展现，强化落地成果的视觉冲击力。
              </div>
            </li>
            <li className="flex items-start gap-2.5 text-sm leading-relaxed text-slate-700">
              <div className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[11px] font-bold text-emerald-700">4</div>
              <div>
                <span className="font-semibold text-slate-900">ATS (自动追踪系统) 微创注入：</span>在不改变原意的前提下，将缺乏的高权重行业黑话及技术栈无缝融合至正文，大幅提高被机器初筛命中的概率。
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>
  )
}
