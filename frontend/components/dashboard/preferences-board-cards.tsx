"use client"

// 偏好大盘的两张独立卡片区（从 preferences-board.tsx 拆出，Q-M4-6 行数治理）
// ——自动化流转阀门 与 AI 专家评估权重配置

import { Save, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

type ThresholdRecord = { record_id?: string; type: string; rule: string; status: string }

export function PreferenceThresholdCard({
  records,
  saving,
  onChangeThreshold,
}: {
  records: ThresholdRecord[]
  saving: boolean
  onChangeThreshold: (val: string) => Promise<void>
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mt-8 mb-4">
      <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
        <div>
          <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
            <span className="text-xl">⚙️</span>
            自动化流转阀门
          </h2>
          <p className="text-xs text-slate-500 mt-1">控制达到什么评级的岗位，系统会自动进行深度评估并改写简历。</p>
        </div>
      </div>
      <div className="p-6">
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium text-slate-700">触发阈值设定：</span>
          <select
            value={records.find(r => r.type === '自动化阈值')?.rule || 'A'}
            onChange={(e) => onChangeThreshold(e.target.value)}
            disabled={saving}
            className="w-64 bg-white border border-slate-200 p-2 rounded-lg outline-none focus:border-rose-300 text-sm font-medium text-slate-700"
          >
            <option value="A">【仅 A级】极高匹配 (评分 &gt;= 90分)</option>
            <option value="B">【A级 和 B级】良好匹配及以上 (评分 &gt;= 70分)</option>
            <option value="C">【A、B、C级 均可】及格及以上 (评分 &gt;= 60分)</option>
          </select>
          <span className="text-xs text-slate-400">选择后实时生效落库</span>
        </div>
      </div>
    </div>
  )
}

export const WEIGHT_DIMENSIONS = [
  { key: 'role_match', label: '角色匹配' },
  { key: 'skills_align', label: '技能重合' },
  { key: 'seniority', label: '职级资历' },
  { key: 'interview_prob', label: '面试概率' },
  { key: 'compensation', label: '薪资契合' },
  { key: 'market_fit', label: '赛道前景' },
  { key: 'growth', label: '成长空间' },
  { key: 'company_stage', label: '公司阶段' }
]

export function WeightsCard({
  weights,
  savingWeights,
  onWeightChange,
  onSaveWeights,
}: {
  weights: Record<string, number>
  savingWeights: boolean
  onWeightChange: (key: string, value: number) => void
  onSaveWeights: () => void
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mt-8 mb-4">
      <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
        <div>
          <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
            <span className="text-xl">⚖️</span>
            AI 专家评估权重配置
          </h2>
          <p className="text-xs text-slate-500 mt-1">自定义 8 个评估维度的重要程度 (范围: 0.1 ~ 1.0，1.0为最高权重，0.1为最低权重)</p>
        </div>
        <Button onClick={onSaveWeights} disabled={savingWeights} className="bg-violet-600 hover:bg-violet-700 text-white shadow-sm h-8 text-xs rounded-lg px-4 transition-all">
          {savingWeights ? <RefreshCw className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Save className="w-3.5 h-3.5 mr-1.5" />}
          保存权重配置
        </Button>
      </div>

      <div className="p-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
          {WEIGHT_DIMENSIONS.map(dim => (
            <div key={dim.key} className="space-y-3">
              <div className="flex justify-between items-center">
                <label className="text-xs font-semibold text-slate-700">{dim.label}</label>
                <span className="text-xs font-mono text-violet-600 bg-violet-50 px-2 py-0.5 rounded border border-violet-100">
                  {(weights[dim.key] || 0.1).toFixed(1)}
                </span>
              </div>
              <input
                type="range"
                min="0.1"
                max="1.0"
                step="0.1"
                value={weights[dim.key] || 0.1}
                onChange={(e) => onWeightChange(dim.key, parseFloat(e.target.value))}
                className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-violet-600"
              />
            </div>
          ))}
        </div>

        <div className="bg-blue-50/50 border border-blue-100 rounded-lg p-4">
          <h4 className="text-xs font-bold text-blue-800 mb-2 flex items-center gap-1.5">
            <span className="text-base">💡</span> 最终评分规则揭秘
          </h4>
          <div className="text-[11px] text-blue-900/80 leading-relaxed space-y-1.5">
            <p>AI 将对每个维度给出 1~5 的原始得分。最终“匹配度百分比”计算公式为：</p>
            <div className="bg-white/60 p-2 rounded border border-blue-100 font-mono text-blue-700 my-2 text-center overflow-x-auto whitespace-nowrap">
              匹配度 = [ ∑ (各维度得分 × 各自权重) ] ÷ [ 满分5分 × ∑ 总权重 ] × 100%
            </div>
            <p>系统最终将根据该百分比推演综合评级：<span className="font-semibold">≥90% 为 A级，75%~89% 为 B级，60%~74% 为 C级</span>，以此类推。若某个环境维度未命中（如缺投资数据），AI 将给予保底的中性 3 分，不产生负向惩罚。</p>
          </div>
        </div>
      </div>
    </div>
  )
}
