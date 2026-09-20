/**
 * BOSS直聘 Tab 主组件（模块五在线简历同步中心）。
 * 原 2967 行单组件经机械拆分：状态中枢 state.ts + Context 跨组件传递 + 分区组件渲染，行为零变化。
 */
"use client"

"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Loader2, Plus, Edit, Trash2, Save, X, Upload, Sparkles, Lock } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
// —— 映射报告共享组件（与猎聘 / 51job / 智联 Tab 同源）——
import { ReportWarnings, ReportUnfilled, ModuleChangeSummary, ModuleReportNotice, type PlatformReport } from "../agent-report-shared"
import { savePlatformData, fetchPlatformReport } from "../api-client"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"
import { JobTitleSelector } from "@/components/ui/job-title-selector"
import { IndustrySelector } from "@/components/ui/industry-selector"
import { CitySelector } from "@/components/ui/city-selector"
import { SalarySelector } from "@/components/ui/salary-selector"
import { OtherCitySelector } from "@/components/ui/other-city-selector"
import { DateRangePicker } from "@/components/ui/date-range-picker"
import { DegreeSelector } from "@/components/ui/degree-selector"
import { YearRangePicker } from "@/components/ui/year-range-picker"
import { CertificateSelector } from "@/components/ui/certificate-selector"
import { CountrySelector } from "@/components/ui/country-selector"
import { LanguageSelector } from "@/components/ui/language-selector"
import { ResumeCatalogue } from "@/components/ui/resume-catalogue"
import { YearMonthPicker } from "@/components/ui/year-month-picker"
import { ExpectationEditor } from "@/components/ui/expectation-editor"
import {
  countryRegions,
  durationOptions,
  COUNTRY_MAX_SELECT,
  LANGUAGE_MAX_SELECT,
} from "@/lib/overseas-options"



import { BossCtx, useBossCtx } from "./context"
import { useBossTabState } from "./state"
import { BOSS_MODULES } from "./constants"
import { BossAgentReport, BossTextField, BossExpectations, BossIndustry, BossWorkExperience, BossProjects, BossEducation, BossCertificates, BossOverseas, BossBaseInfo } from "./sections-loader"
import { BossWritebackPanel } from "./writeback-panel"
import { BossAgentModal } from "./agent-modal"

export function BossTab(props: import("./constants").BossTabProps) {
  const state = useBossTabState(props)
  const { displayData, visibleKeys, isEmpty, loading, toast } = state as any

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin" />
        <span className="ml-2">加载中...</span>
      </div>
    )
  }

  if (isEmpty) {
    return (
      <div className="text-center py-12 text-gray-500">
        <div className="text-4xl mb-4">📭</div>
        <div>暂无 BOSS直聘数据</div>
        <div className="text-sm mt-2">请先运行采集脚本</div>
        <Button onClick={state.onRefresh} className="mt-4 bg-[#00beab] hover:bg-[#00a89a] text-white">
          刷新数据
        </Button>
      </div>
    )
  }

  return (
    <BossCtx.Provider value={state}>
      {/* 左右布局（原 2574-2585） */}
    <div className="flex gap-6 items-start">
      {/* 左侧导航栏 - 简历目录 */}
      <div className="sticky top-6">
        <ResumeCatalogue visibleKeys={visibleKeys} />
      </div>

      {/* 右侧内容区 */}
      <div className="flex-1 space-y-4 min-w-0">
        {/* 0a. 主简历映射报告（顶部操作区「映射」生成；审核后应用到本地数据） */}
        {<BossAgentReport />}

        {/* 0b. 模块勾选回写栏 */}
        <BossWritebackPanel />

        {/* 空数据提示横幅（框架骨架仍保留在下方） */}
        {isEmpty && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-3 text-sm text-gray-500">
            <span>📭 暂无BOSS直聘数据，请先勾选平台并点击「采集数据」</span>
            <Button size="sm" variant="outline" onClick={state.onRefresh}>刷新数据</Button>
          </div>
        )}

        {/* 个人信息 - 统一卡片（照搬BOSS官网） */}
        <div id="section-baseInfo" className="scroll-mt-[260px]">
          {<BossBaseInfo />}
        </div>

        {/* 个人优势 */}
        <div id="section-selfEval" className="scroll-mt-[260px]">
          {displayData.personal_advantage && <BossTextField fieldName="personal_advantage" field={displayData.personal_advantage} />}
        </div>

        {/* 期望职位 + 期望行业 */}
        <div id="section-expectList" className="scroll-mt-[260px]">
          {displayData.expectations && <BossExpectations field={displayData.expectations} />}
          {displayData.industry && <BossIndustry field={displayData.industry} />}
        </div>

        {/* 工作经历 */}
        <div id="section-workExp" className="scroll-mt-[260px]">
          {displayData.work_experience && <BossWorkExperience field={displayData.work_experience} />}
        </div>

        {/* 项目经历 */}
        <div id="section-projectExpList" className="scroll-mt-[260px]">
          {displayData.projects && <BossProjects field={displayData.projects} />}
        </div>

        {/* 教育经历 */}
        <div id="section-educationExpList" className="scroll-mt-[260px]">
          {displayData.education && <BossEducation field={displayData.education} />}
        </div>

        {/* 资格证书 */}
        <div id="section-certificationList" className="scroll-mt-[260px]">
          {displayData.certificates && <BossCertificates field={displayData.certificates} />}
        </div>

        {/* 驻外选项 */}
        <div id="section-stayAbroad" className="scroll-mt-[260px]">
          {displayData.overseas && <BossOverseas field={displayData.overseas} />}
        </div>

      <BossAgentModal />
      </div>

      {/* 浮动提示 Toast */}
      {toast && (
        <div
          className={`fixed top-6 left-1/2 -translate-x-1/2 z-50 px-5 py-2.5 rounded-lg shadow-lg text-sm font-medium transition-all duration-300 ${
            toast.type === "success"
              ? "bg-green-500 text-white"
              : "bg-red-500 text-white"
          }`}
          style={{ animation: "fadeInDown 0.3s ease-out" }}
        >
          {toast.message}
        </div>
      )}
    </div>
    </BossCtx.Provider>
  )
}
