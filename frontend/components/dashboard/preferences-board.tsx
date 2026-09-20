"use client"

import React, { useState, useEffect } from 'react'
import { Heart, Trash2, Edit2, CheckCircle, AlertCircle, RefreshCw, Save, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { API_BASE } from '@/lib/api'
import { PreferenceThresholdCard, WeightsCard } from './preferences-board-cards'

type PreferenceType = '核心加分' | '职业愿景' | '自动化阈值'
type PreferenceStatus = '启用' | '停用'

type PreferenceRecord = {
  record_id?: string
  type: PreferenceType
  rule: string
  status: PreferenceStatus
}

export function PreferencesBoard() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [records, setRecords] = useState<PreferenceRecord[]>([])
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  
  // 权重状态
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [savingWeights, setSavingWeights] = useState(false)

  // 表单操作临时状态
  const [currentId, setCurrentId] = useState<string | undefined>(undefined)
  
  // 行内编辑状态
  const [editingRowId, setEditingRowId] = useState<string | null>(null)
  const [editingRowRule, setEditingRowRule] = useState('')
  const [formType, setFormType] = useState<PreferenceType>('核心加分')
  const [formRule, setFormRule] = useState('')
  const [formStatus, setFormStatus] = useState<PreferenceStatus>('启用')

  // 筛选器状态
  const [filterType, setFilterType] = useState<string>('all')

  const fetchPreferences = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/preferences`)
      const result = await res.json()
      if (result.status === 'success') {
        setRecords(result.data as PreferenceRecord[])
      } else {
        setToast({ type: 'error', msg: `读取失败: ${result.message}` })
      }
      
      const wRes = await fetch(`${API_BASE}/api/strategy/weights`)
      const wResult = await wRes.json()
      if (wResult.status === 'success') {
        setWeights(wResult.data)
      }
    } catch (e) {
      console.error(e)
      setToast({ type: 'error', msg: '❌ 网络交互异常或后端未启动' })
    } finally {
      setLoading(false)
      setTimeout(() => setToast(null), 5000)
    }
  }

  useEffect(() => {
    fetchPreferences()
  }, [])

  // 自动消散提示
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 3000)
    return () => clearTimeout(timer)
  }, [toast])

  // 提交新增或修改
  const handleSubmit = async () => {
    if (!formRule.trim()) return
    setSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          record_id: currentId,
          type: formType,
          rule: formRule.trim(),
          status: formStatus,
        }),
      })
      const data = await res.json()
      if (data.status === 'success') {
        setToast({ type: 'success', msg: '🎉 偏好规则新增成功！' })
        resetForm()
        fetchPreferences()
      } else {
        setToast({ type: 'error', msg: '❌ 同步失败: ' + data.message })
      }
    } catch (e) {
      setToast({ type: 'error', msg: '❌ 网络交互异常' })
    } finally {
      setSaving(false)
    }
  }

  // 删除规则
  const handleDelete = async (record_id: string) => {
    if (!confirm('确定要彻底移除这条偏好规则吗？')) return
    try {
      const res = await fetch(`${API_BASE}/api/strategy/preferences/${record_id}`, { method: 'DELETE' })
      const data = await res.json()
      if (data.status === 'success') {
        setToast({ type: 'success', msg: '🗑️ 偏好记录已成功移除！' })
        fetchPreferences()
      } else {
        setToast({ type: 'error', msg: '❌ 删除失败: ' + data.message })
      }
    } catch (e) {
      console.error(e)
      setToast({ type: 'error', msg: '❌ 网络交互异常' })
    }
  }

  const handleStatusToggle = async (item: PreferenceRecord) => {
    const newStatus = item.status === '启用' ? '停用' : '启用'
    
    // 🌟 乐观更新 (Optimistic UI)：先无延迟地更新前端界面状态
    setRecords((prev) => 
      prev.map(r => r.record_id === item.record_id ? { ...r, status: newStatus } : r)
    )

    try {
      const res = await fetch(`${API_BASE}/api/strategy/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          record_id: item.record_id,
          type: item.type,
          rule: item.rule,
          status: newStatus,
        }),
      })
      const data = await res.json()
      if (data.status === 'success') {
        // 后端同步成功，不需要再重新刷整个页面，保持乐观更新的丝滑
      } else {
        // 回滚乐观更新
        setRecords((prev) => 
          prev.map(r => r.record_id === item.record_id ? { ...r, status: item.status } : r)
        )
        setToast({ type: 'error', msg: '❌ 切换状态失败: ' + data.message })
      }
    } catch (e) {
      console.error(e)
      // 回滚乐观更新
      setRecords((prev) => 
        prev.map(r => r.record_id === item.record_id ? { ...r, status: item.status } : r)
      )
      setToast({ type: 'error', msg: '❌ 网络交互异常' })
    }
  }

  const handleInlineSave = async (item: PreferenceRecord) => {
    if (!editingRowRule.trim() || editingRowRule.trim() === item.rule) {
      setEditingRowId(null)
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/strategy/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          record_id: item.record_id,
          type: item.type,
          rule: editingRowRule.trim(),
          status: item.status,
        }),
      })
      const data = await res.json()
      if (data.status === 'success') {
        setToast({ type: 'success', msg: '🎉 偏好规则修改成功！' })
        setEditingRowId(null)
        fetchPreferences()
      } else {
        setToast({ type: 'error', msg: '❌ 修改失败: ' + data.message })
      }
    } catch (e) {
      setToast({ type: 'error', msg: '❌ 网络交互异常' })
    }
  }

  const resetForm = () => {
    setCurrentId(undefined)
    setFormRule('')
    setFormStatus('启用')
  }

  const saveWeights = async () => {
    setSavingWeights(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/weights`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ weights })
      })
      const result = await res.json()
      if (result.status === 'success') {
        setToast({ type: 'success', msg: '✅ 权重保存成功' })
      } else {
        setToast({ type: 'error', msg: result.message || '保存失败' })
      }
    } catch (e) {
      console.error(e)
      setToast({ type: 'error', msg: '保存失败，请检查后端服务' })
    } finally {
      setSavingWeights(false)
      setTimeout(() => setToast(null), 3000)
    }
  }

  // 计算过滤后的偏好规则
  const filteredRecords = records.filter((r) => r.type !== '自动化阈值' && (filterType === 'all' || r.type === filterType))

  // 自动化流转阈值变更（Q-M4-6 拆分：handler 留在主组件，卡片渲染下沉 preferences-board-cards）
  const handleThresholdChange = async (val: string) => {
    const existing = records.find(r => r.type === '自动化阈值')
    setSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          record_id: existing?.record_id,
          type: '自动化阈值',
          rule: val,
          status: '启用',
        }),
      })
      const data = await res.json()
      if (data.status === 'success') {
        setToast({ type: 'success', msg: '✅ 自动化阈值已更新！' })
        fetchPreferences()
      } else {
        setToast({ type: 'error', msg: '❌ 阈值更新失败' })
      }
    } catch (err) {
      setToast({ type: 'error', msg: '网络异常' })
    } finally {
      setSaving(false)
    }
  }

  // 根据偏好类型返回低饱和度柔和背景
  const getTypeStyles = (type: string) => {
    switch (type) {
      case '核心加分':
        return 'bg-emerald-50/70 text-emerald-700 border-emerald-100'
      case '职业愿景':
        return 'bg-sky-50/70 text-sky-700 border-sky-100'
      case '自动化阈值':
        return 'bg-purple-50/70 text-purple-700 border-purple-100'
      default:
        return 'bg-gray-50 text-gray-700 border-gray-100'
    }
  }

  if (loading)
    return (
      <div className="flex h-full items-center justify-center text-slate-500 gap-2 font-mono text-xs">
        <RefreshCw className="animate-spin h-4 w-4 text-rose-500" /> 正在加载求职偏好配置...
      </div>
    )

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto text-slate-800 bg-white min-h-full rounded-2xl border border-gray-100 shadow-sm overflow-y-auto">
      {/* 顶部标题 */}
      <div className="flex items-center justify-between border-b border-gray-100 pb-4">
        <div>
          <h2 className="text-base font-bold text-slate-950 flex items-center gap-2">
            <Heart className="h-4 w-4 text-rose-500 fill-rose-500" /> 求职偏好配置矩阵
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            偏好规则保存在本地数据库（backend SQLite），作为 AI 评估匹配时的核心加分项参考框架。
          </p>
        </div>
        <Button size="sm" onClick={fetchPreferences} variant="outline" className="rounded-xl h-8 text-xs gap-1.5">
          <RefreshCw className="h-3.5 w-3.5" /> 强刷同步
        </Button>
      </div>

      {/* 动态表单录入区 */}
      <div className="bg-slate-50/50 border border-slate-100 p-4 rounded-xl space-y-3">
        <span className="text-xs font-bold text-slate-700 block">
          ➕ 新增求职偏好
        </span>
        <div className="grid grid-cols-1 sm:grid-cols-6 gap-3 items-end text-xs">
          <div>
            <span className="text-[10px] text-slate-400">规则类别:</span>
            <select
              value={formType}
              onChange={(e) => setFormType(e.target.value as PreferenceType)}
              className="w-full bg-white border border-slate-200 p-1.5 rounded-lg mt-1 h-8 outline-none focus:border-rose-300"
            >
              <option value="核心加分">📈 核心加分 (加分权重技术)</option>
              <option value="职业愿景">🎯 职业愿景 (未来转型赛道)</option>
            </select>
          </div>
          <div className="sm:col-span-3">
            <span className="text-[10px] text-slate-400">具体规则正文描述:</span>
            <textarea 
              placeholder="如：拥有大模型项目经验 / 理想薪资 15K" 
              value={formRule} 
              onChange={(e)=>setFormRule(e.target.value)} 
              rows={2}
              className="w-full bg-white border border-slate-200 p-2 rounded-lg mt-1 outline-none focus:border-rose-300 text-xs resize-y min-h-[36px]" 
            />
          </div>
          <div>
            <span className="text-[10px] text-slate-400">决策状态:</span>
            <select
              value={formStatus}
              onChange={(e) => setFormStatus(e.target.value as PreferenceStatus)}
              className="w-full bg-white border border-slate-200 p-1.5 rounded-lg mt-1 h-8 outline-none"
            >
              <option value="启用">● 实时生效(启用)</option>
              <option value="停用">○ 暂缓下线(停用)</option>
            </select>
          </div>
          <div className="flex gap-1.5">
            <Button
              size="sm"
              onClick={handleSubmit}
              disabled={saving}
              className="bg-slate-900 text-white hover:bg-slate-800 rounded-lg h-8 px-3 text-[11px] font-medium flex-1"
            >
              <Save className="h-3 w-3 mr-1" /> 提交入库
            </Button>
          </div>
        </div>
      </div>

      {/* 核心展示主表格 */}
      <div className="rounded-xl border border-slate-100 bg-white overflow-hidden">
        <table className="w-full text-left text-xs border-collapse">
          <thead className="sticky top-0 z-10 bg-slate-50 border-b border-slate-100">
            <tr className="text-slate-400 font-semibold text-[11px]">
              <th className="p-3 w-32">
                <div className="flex items-center gap-1.5">
                  偏好类型
                  <select
                    value={filterType}
                    onChange={(e) => setFilterType(e.target.value)}
                    className="bg-white border border-slate-200 rounded px-1 py-0.5 text-[10px] font-normal text-slate-600 cursor-pointer outline-none"
                  >
                    <option value="all">全部</option>
                    <option value="核心加分">核心加分</option>
                    <option value="职业愿景">职业愿景</option>
                  </select>
                </div>
              </th>
              <th className="p-3">具体核心偏好描述</th>
              <th className="p-3 w-28 text-center">状态</th>
              <th className="p-3 w-24 text-center">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 font-sans text-slate-700">
            {filteredRecords.length === 0 ? (
              <tr>
                <td colSpan={4} className="p-8 text-center text-slate-400 font-mono">
                  暂无活跃规则记录
                </td>
              </tr>
            ) : (
              filteredRecords.map((item, idx) => (
                <tr key={item.record_id || idx} className="hover:bg-slate-50/50 transition-colors">
                  <td className="p-3">
                    <span
                      className={`px-2 py-0.5 rounded-md text-[10px] font-bold border ${getTypeStyles(item.type)}`}
                    >
                      {item.type}
                    </span>
                  </td>
                  <td className="p-3">
                    {editingRowId === item.record_id ? (
                      <textarea
                        value={editingRowRule}
                        onChange={(e) => setEditingRowRule(e.target.value)}
                        className="w-full bg-white border border-rose-300 p-2 rounded-lg outline-none text-xs resize-y min-h-[60px]"
                        autoFocus
                      />
                    ) : (
                      <span className="font-medium text-slate-900 leading-relaxed block">{item.rule}</span>
                    )}
                  </td>
                  <td className="p-3 text-center">
                    <div className="flex items-center justify-center gap-2">
                      <Switch 
                        checked={item.status === '启用'} 
                        onCheckedChange={() => handleStatusToggle(item)} 
                        className="data-[state=checked]:bg-emerald-500 data-[state=unchecked]:bg-slate-300"
                        disabled={editingRowId === item.record_id}
                      />
                      <span className={`text-[10px] font-mono font-medium w-6 text-left ${item.status === '启用' ? 'text-emerald-600' : 'text-slate-400'}`}>
                        {item.status}
                      </span>
                    </div>
                  </td>
                  <td className="p-3 text-center">
                    <div className="flex items-center justify-center gap-2">
                      {editingRowId === item.record_id ? (
                        <>
                          <button
                            onClick={() => handleInlineSave(item)}
                            className="text-emerald-600 hover:text-emerald-700 transition-colors p-1 bg-emerald-50 rounded-md"
                            title="保存修改"
                          >
                            <Save className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => setEditingRowId(null)}
                            className="text-slate-400 hover:text-slate-600 transition-colors p-1"
                            title="取消"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => {
                              setEditingRowId(item.record_id || null)
                              setEditingRowRule(item.rule)
                            }}
                            className="text-slate-400 hover:text-indigo-600 transition-colors p-1"
                            title="行内编辑"
                          >
                            <Edit2 className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => item.record_id && handleDelete(item.record_id)}
                            className="text-slate-400 hover:text-red-500 transition-colors p-1"
                            title="彻底移除"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* ---------------- 自动化流转阀门（卡片渲染下沉 preferences-board-cards） ---------------- */}
      <PreferenceThresholdCard
        records={records}
        saving={saving}
        onChangeThreshold={handleThresholdChange}
      />

      {/* ---------------- 权重配置区域（卡片渲染下沉 preferences-board-cards） ---------------- */}
      <WeightsCard
        weights={weights}
        savingWeights={savingWeights}
        onWeightChange={(key, value) => setWeights({ ...weights, [key]: value })}
        onSaveWeights={saveWeights}
      />

      {/* 底部浮动提示 */}
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl shadow-lg text-xs font-medium text-white font-mono ${
            toast.type === 'success' ? 'bg-emerald-600' : 'bg-rose-600'
          }`}
        >
          {toast.type === 'success' ? (
            <CheckCircle className="h-3.5 w-3.5" />
          ) : (
            <AlertCircle className="h-3.5 w-3.5" />
          )}{' '}
          {toast.msg}
        </div>
      )}
    </div>
  )
}
