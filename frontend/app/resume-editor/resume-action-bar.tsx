"use client"

import { useState, useEffect } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import Link from "next/link"
import {
  Loader2, RefreshCw, Download, Upload, Trash2, Sparkles, Cloud, CheckSquare, Square,
  ArrowLeft, Layers, ShieldCheck
} from "lucide-react"
import type { ResumeOption } from "./agent-report-shared"
import { MasterPreviewButton } from "./master-preview"

export const PLATFORM_NAMES: Record<string, string> = {
  boss: "BOSS直聘",
  liepin: "猎聘",
  "51job": "前程无忧",
  zhilian: "智联招聘",
}

export const PLATFORM_COLORS: Record<string, string> = {
  boss: "#00beab",
  liepin: "#FE9241",
  "51job": "#FF6000",
  zhilian: "#2A7BFF",
}

export interface MappingModuleItem {
  id: string
  label: string
  platforms?: { name: string; color: string; bg: string }[]
}

export const MAPPING_MODULE_ITEMS: MappingModuleItem[] = [
  { id: "basic_info", label: "基本信息" },
  { id: "personal_advantage", label: "个人优势" },
  { id: "expectations", label: "求职期望" },
  { id: "work_experience", label: "工作经历" },
  { id: "projects", label: "项目经历" },
  { id: "education", label: "教育经历" },
  {
    id: "skills",
    label: "专业技能",
    platforms: [
      { name: "智联", color: "#2A7BFF", bg: "#EFF6FF" },
      { name: "51job", color: "#FF6000", bg: "#FFF7ED" },
      { name: "BOSS", color: "#00beab", bg: "#F0FDFA" },
    ],
  },
  {
    id: "certificates",
    label: "证书与语言",
    platforms: [
      { name: "猎聘", color: "#FE9241", bg: "#FFF7ED" },
      { name: "智联", color: "#2A7BFF", bg: "#EFF6FF" },
      { name: "51job", color: "#FF6000", bg: "#FFF7ED" },
      { name: "BOSS", color: "#00beab", bg: "#F0FDFA" },
    ],
  },
  {
    id: "trainings",
    label: "培训经历",
    platforms: [
      { name: "智联", color: "#2A7BFF", bg: "#EFF6FF" },
    ],
  },
  {
    id: "overseas",
    label: "驻外偏好",
    platforms: [
      { name: "BOSS", color: "#00beab", bg: "#F0FDFA" },
    ],
  },
]

export const DEFAULT_SELECTED_MODULES = [
  "basic_info", "personal_advantage", "expectations",
  "work_experience", "projects", "education",
  "skills", "certificates", "trainings", "overseas"
]

interface ResumeActionBarProps {
  apiBase: string
  platformStatus: Record<string, { port: number; online: boolean; logged_in: boolean }>
  statusRefreshing: boolean
  launchingPlatform: string | null
  loginPlatform: string | null
  selectedPlatforms: Record<string, boolean>
  setSelectedPlatforms: React.Dispatch<React.SetStateAction<{ boss: boolean; liepin: boolean; "51job": boolean; zhilian: boolean }>>
  onCheckStatus: (showToastFeedback?: boolean) => Promise<void>
  onLaunchBrowser: (platform: string) => Promise<void>
  onGotoLogin: (platform: string) => Promise<void>
  onDeepVerify?: () => Promise<void>
  deepVerifying?: boolean
  onCollect: () => Promise<void>
  onSyncBack: () => Promise<void>
  onRefreshData: () => Promise<void>
  onClearData: () => Promise<void>
  collecting: string | null
  syncing: string | null
  showToast: (message: string, type?: "success" | "error" | "info") => void
  onReportGenerated: () => void
}

export function ResumeActionBar({
  apiBase,
  platformStatus,
  statusRefreshing,
  launchingPlatform,
  loginPlatform,
  selectedPlatforms,
  setSelectedPlatforms,
  onCheckStatus,
  onLaunchBrowser,
  onGotoLogin,
  onDeepVerify,
  deepVerifying,
  onCollect,
  onSyncBack,
  onRefreshData,
  onClearData,
  collecting,
  syncing,
  showToast,
  onReportGenerated,
}: ResumeActionBarProps) {
  const [agentResumes, setAgentResumes] = useState<ResumeOption[]>([])
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null)
  const [resumesLoading, setResumesLoading] = useState(false)
  const [selectedModules, setSelectedModules] = useState<string[]>(DEFAULT_SELECTED_MODULES)
  const [mapping, setMapping] = useState(false)

  // 获取飞书主简历列表
  const fetchResumes = async () => {
    setResumesLoading(true)
    try {
      const res = await fetch(`${apiBase}/api/agent-map/resumes`)
      const result = await res.json()
      if (result.success) {
        setAgentResumes(result.resumes || [])
        if (!selectedRecordId) {
          const active = result.resumes?.find((r: ResumeOption) => r.status === "启用中" || r.status === "已启用")
          if (active) setSelectedRecordId(active.record_id)
        }
      } else {
        showToast(result.message || "飞书简历列表获取失败，主简历来源将仅支持「默认（启用中）」", "error")
      }
    } catch (e: any) {
      showToast("主简历列表加载失败: " + (e?.message || e), "error")
    } finally {
      setResumesLoading(false)
    }
  }

  useEffect(() => {
    fetchResumes()
  }, [])

  const currentResume = agentResumes.find(r => r.record_id === selectedRecordId)

  // 模块快捷选择
  const handleSelectAllModules = () => {
    setSelectedModules(MAPPING_MODULE_ITEMS.map(m => m.id))
  }

  const handleSelectExperienceOnly = () => {
    setSelectedModules(["work_experience", "projects"])
  }

  const handleInvertModules = () => {
    setSelectedModules(prev =>
      MAPPING_MODULE_ITEMS.filter(m => !prev.includes(m.id)).map(m => m.id)
    )
  }

  const toggleModule = (id: string) => {
    setSelectedModules(prev =>
      prev.includes(id) ? prev.filter(m => m !== id) : [...prev, id]
    )
  }

  // 触发生成映射报告
  const handleGenerateMapping = async () => {
    const platforms = Object.entries(selectedPlatforms).filter(([, v]) => v).map(([k]) => k)
    if (platforms.length === 0) {
      showToast("请至少选择一个目标平台", "error")
      return
    }
    if (selectedModules.length === 0) {
      showToast("请至少选择一个映射模块", "error")
      return
    }

    setMapping(true)
    try {
      const res = await fetch(`${apiBase}/api/agent-map/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platforms,
          record_id: selectedRecordId,
          selected_modules: selectedModules,
        }),
      })
      const result = await res.json()
      // 无论整体成败，只要本次执行过就通知各 Tab 刷新报告（部分失败时成功平台的报告也要可见）
      onReportGenerated()
      const reports = (result.reports || {}) as Record<string, any>
      if (result.success) {
        const names = platforms.map(p => PLATFORM_NAMES[p] || p).join("、")
        showToast(`已成功为【${names}】生成映射报告，请在对应平台 Tab 查阅并确认！`, "success")
      } else {
        const failed = platforms
          .filter((p) => reports[p] && reports[p].success === false)
          .map((p) => `${PLATFORM_NAMES[p] || p}生成映射失败：${String(reports[p].message || "失败").slice(0, 80)}`)
        const okCount = platforms.length - failed.length
        if (failed.length > 0) {
          const tail = okCount > 0 ? `；其余${okCount}个平台已生成` : ""
          showToast(failed.join("；") + tail, "error")
        } else {
          showToast(result.message || "映射生成失败", "error")
        }
      }
    } catch (e: any) {
      showToast("映射请求网络异常: " + (e?.message || e), "error")
    } finally {
      setMapping(false)
    }
  }

  return (
    <Card className="mb-4 shadow-sm border border-gray-200/80 bg-white">
      <CardContent className="pt-3.5 pb-3.5 space-y-3.5">
        {/* 顶部标题与返回主页导航行 */}
        <div className="flex items-center justify-between pb-2.5 border-b border-gray-100/90">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100/80 transition-all duration-150 active:scale-[0.98] border border-gray-200 shadow-2xs"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>返回主页</span>
            </Link>
            <div className="h-3.5 w-px bg-gray-200" />
            <div className="flex items-center gap-2">
              <div className="w-5 h-5 rounded-md bg-indigo-50 text-indigo-600 flex items-center justify-center">
                <Layers className="w-3.5 h-3.5" />
              </div>
              <h2 className="text-sm font-bold text-gray-900 tracking-tight">
                在线简历多平台同步中心
              </h2>
              <Badge variant="outline" className="text-[10px] bg-indigo-50/60 text-indigo-700 border-indigo-200/80 font-normal px-1.5 py-0">
                4 平台同步
              </Badge>
            </div>
          </div>
          <div className="text-[11px] text-gray-400 hidden sm:block">
            飞书主简历 → 4 平台智能映射与官网自动化回写
          </div>
        </div>

        {/* 第一行：登录状态 */}
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-gray-500 shrink-0 w-16">登录状态</span>
          <div className="flex items-center gap-2 flex-1 flex-wrap">
            {(["boss", "liepin", "51job", "zhilian"] as const).map((p) => {
              const status = platformStatus[p]
              const online = status?.online ?? false
              const loggedIn = status?.logged_in ?? false
              const dotColor = !online ? "bg-gray-300" : loggedIn ? "bg-emerald-500" : "bg-amber-400"
              const label = !online ? "未启动" : loggedIn ? "已登录" : "未登录"
              const labelColor = !online ? "text-gray-400" : loggedIn ? "text-emerald-600 font-medium" : "text-amber-600 font-medium"

              return (
                <div key={p} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-gray-100 bg-gray-50/70 text-xs">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${dotColor}`} />
                  <span className="text-gray-700 font-medium">{PLATFORM_NAMES[p]}</span>
                  <span className={`text-[11px] ${labelColor}`}>{label}</span>
                  {!online && (
                    <button
                      className="text-[11px] text-blue-600 hover:underline inline-flex items-center gap-0.5 ml-1 disabled:opacity-50"
                      disabled={launchingPlatform === p}
                      onClick={() => onLaunchBrowser(p)}
                    >
                      {launchingPlatform === p && <Loader2 className="w-2.5 h-2.5 animate-spin" />}
                      启动
                    </button>
                  )}
                  {online && !loggedIn && (
                    <button
                      className="text-[11px] text-blue-600 hover:underline inline-flex items-center gap-0.5 ml-1 disabled:opacity-50"
                      disabled={loginPlatform === p}
                      onClick={() => onGotoLogin(p)}
                    >
                      {loginPlatform === p && <Loader2 className="w-2.5 h-2.5 animate-spin" />}
                      去登录
                    </button>
                  )}
                </div>
              )
            })}
          </div>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs shrink-0 text-gray-600 hover:text-gray-900 border-gray-200"
            onClick={() => onCheckStatus(true)}
            disabled={statusRefreshing}
          >
            {statusRefreshing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1" />}
            全部刷新
          </Button>
          {onDeepVerify && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs shrink-0 text-gray-600 hover:text-gray-900 border-gray-200"
              onClick={onDeepVerify}
              disabled={deepVerifying || statusRefreshing}
              title="逐平台打开官网首页做 DOM 级登录判定（权威但较慢，约 10 秒，会短暂占用平台浏览器）"
            >
              {deepVerifying ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <ShieldCheck className="w-3 h-3 mr-1" />}
              深度校验
            </Button>
          )}
        </div>

        {/* 第二行：目标平台与批量操作 */}
        <div className="flex items-center gap-3 flex-wrap border-t border-gray-100 pt-3">
          <span className="text-xs font-semibold text-gray-500 shrink-0 w-16">目标平台</span>
          <div className="flex items-center gap-3">
            {(["boss", "liepin", "51job", "zhilian"] as const).map((p) => {
              return (
                <label
                  key={p}
                  className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs cursor-pointer select-none transition-colors duration-150 ${
                    selectedPlatforms[p] ? "bg-gray-100/80 text-gray-900 font-medium" : "text-gray-500 hover:bg-gray-50"
                  }`}
                >
                  <Checkbox
                    checked={selectedPlatforms[p]}
                    onCheckedChange={(v) => setSelectedPlatforms(prev => ({ ...prev, [p]: !!v }))}
                    className="w-3.5 h-3.5 rounded"
                  />
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: PLATFORM_COLORS[p] }} />
                  <span>{PLATFORM_NAMES[p]}</span>
                </label>
              )
            })}
          </div>
          <div className="flex items-center gap-1.5 ml-auto">
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onCollect} disabled={collecting === "all"}>
              {collecting === "all" ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Download className="w-3 h-3 mr-1" />}
              {collecting === "all" ? "采集中（按平台顺序执行）..." : "采集数据"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={onSyncBack}
              disabled={syncing === "all"}
              title="覆盖写入官网在线简历；使用已保存的回写快照（未保存则用本地数据），按平台顺序执行"
            >
              {syncing === "all" ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Upload className="w-3 h-3 mr-1" />}
              {syncing === "all" ? "回写中（按平台顺序）..." : "回写数据"}
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onRefreshData}>
              <RefreshCw className="w-3 h-3 mr-1" />
              刷新数据
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700" onClick={onClearData}>
              <Trash2 className="w-3 h-3 mr-1" />
              清空数据
            </Button>
            <MasterPreviewButton />
          </div>
        </div>

        {/* 第三行：主简历选择与映射模块调度 */}
        <div className="border-t border-gray-100 pt-3 space-y-2.5">
          {/* 主简历来源选择 */}
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-xs font-semibold text-gray-500 shrink-0 w-16">主简历来源</span>
            <div className="flex items-center gap-2">
              <select
                value={selectedRecordId ?? ""}
                onChange={e => setSelectedRecordId(e.target.value || null)}
                className="px-2.5 py-1 rounded-lg border border-gray-200 bg-white text-xs font-medium text-gray-800 shadow-sm focus:outline-none focus:ring-1 focus:ring-indigo-500 min-w-[220px]"
                aria-label="选择主简历来源"
              >
                {agentResumes.length === 0 ? (
                  <option value="">默认（飞书启用中的主简历）</option>
                ) : (
                  agentResumes.map(r => (
                    <option key={r.record_id} value={r.record_id}>
                      {r.name} {r.status ? `(${r.status})` : ""}
                    </option>
                  ))
                )}
              </select>

              <Badge variant="outline" className="text-[11px] bg-blue-50 text-blue-700 border-blue-200 flex items-center gap-1 font-normal py-0.5">
                <Cloud className="w-3 h-3" />
                飞书云端简历
              </Badge>

              {currentResume && (
                <span className="text-xs text-gray-400">
                  {currentResume.char_count} 字符
                </span>
              )}

              <button
                type="button"
                onClick={fetchResumes}
                disabled={resumesLoading}
                className="text-gray-400 hover:text-gray-600 p-1 transition-colors"
                title="刷新主简历列表"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${resumesLoading ? "animate-spin text-indigo-600" : ""}`} />
              </button>
            </div>

            {/* 生成映射报告 主行动点 */}
            <div className="ml-auto flex items-center gap-2">
              <Button
                size="sm"
                onClick={handleGenerateMapping}
                disabled={mapping}
                className="h-8 px-4 text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition-all duration-200 active:scale-[0.98] flex items-center gap-1.5"
              >
                {mapping ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5 text-amber-300" />}
                {mapping ? "AI 智能映射中..." : "生成映射报告"}
              </Button>
            </div>
          </div>

          {/* 映射模块筛选栏（带快捷操作与专属平台彩色标签） */}
          <div className="flex items-start gap-3 flex-wrap">
            <span className="text-xs font-semibold text-gray-500 shrink-0 w-16 pt-1">映射模块</span>
            <div className="flex-1 flex flex-wrap items-center gap-2">
              {/* 快捷预设按钮组 */}
              <div className="flex items-center gap-1 bg-gray-100/80 p-0.5 rounded-lg mr-1.5">
                <button
                  type="button"
                  onClick={handleSelectAllModules}
                  className="px-2 py-0.5 text-[11px] text-gray-600 hover:text-gray-900 rounded font-medium hover:bg-white transition-all"
                >
                  全选
                </button>
                <button
                  type="button"
                  onClick={handleSelectExperienceOnly}
                  className="px-2 py-0.5 text-[11px] text-gray-600 hover:text-gray-900 rounded font-medium hover:bg-white transition-all"
                >
                  仅经历模块
                </button>
                <button
                  type="button"
                  onClick={handleInvertModules}
                  className="px-2 py-0.5 text-[11px] text-gray-600 hover:text-gray-900 rounded font-medium hover:bg-white transition-all"
                >
                  反选
                </button>
              </div>

              {/* 模块选择 Chips */}
              {MAPPING_MODULE_ITEMS.map((mod) => {
                const checked = selectedModules.includes(mod.id)
                return (
                  <label
                    key={mod.id}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs cursor-pointer select-none transition-all duration-150 ${
                      checked
                        ? "bg-indigo-50/60 border-indigo-200 text-indigo-950 font-medium shadow-xs"
                        : "bg-gray-50/60 border-gray-200/60 text-gray-500 hover:bg-gray-100"
                    }`}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggleModule(mod.id)}
                      className="w-3.5 h-3.5 rounded border-gray-300 data-[state=checked]:bg-indigo-600 data-[state=checked]:border-indigo-600"
                    />
                    <span>{mod.label}</span>

                    {/* 专属平台标签 */}
                    {mod.platforms && mod.platforms.length > 0 && (
                      <div className="flex items-center gap-0.5 ml-0.5">
                        {mod.platforms.map((p) => (
                          <span
                            key={p.name}
                            className="inline-block px-1 py-0.2 rounded text-[9px] leading-tight font-medium border"
                            style={{
                              backgroundColor: p.bg,
                              color: p.color,
                              borderColor: `${p.color}33`,
                            }}
                          >
                            {p.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </label>
                )
              })}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
