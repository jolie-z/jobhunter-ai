/**
 * Liepin Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { SectionHeader } from "../constants"

import { useLiepinCtx } from "../context"
import { LiepinCitySelector } from "@/components/ui/liepin-city-selector"
import { LiepinJobSelector } from "@/components/ui/liepin-job-selector"
import { LiepinIndustrySelector } from "@/components/ui/liepin-industry-selector"
import { LiepinYearMonthPicker } from "@/components/ui/liepin-year-month-picker"
import { SectionCard, DialogActions, ReadOnlyNote } from "./shared"
import { ChangedBadge } from "../../agent-report-shared"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Loader2, ChevronDown, Plus, Edit, Trash2, Save, X, Upload, Sparkles, Lock } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { ReportWarnings, ReportUnfilled, ModuleChangeSummary, ModuleReportNotice } from "../../agent-report-shared"
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
import { YearMonthPicker } from "@/components/ui/year-month-picker"
import { ExpectationEditor } from "@/components/ui/expectation-editor"


export function LiepinWorkExperience() {
  const {
    saving,
    report,
    workExpDialogOpen,
    setWorkExpDialogOpen,
    workExpForm,
    setWorkExpForm,
    editingWorkExpIdx,
    setEditingWorkExpIdx,
    showOptional,
    setShowOptional,
    setDeleteTarget,
    itemChanged,
    handleAddItem,
    handleUpdateItem,
    getVal,
    getLabel,
  } = useLiepinCtx()

    const items = getVal("work_experience") || []

    const emptyWorkExp = (): any => ({
      company: "",
      industry: "",
      position: "",
      job_category: "",
      start_date: "",
      end_date: "",
      responsibilities: "",
      is_internship: false,
      hide_resume: false,
      department: "",
      report_to: "",
      team_size: "",
      salary_amount: "",
      salary_months: "",
      work_city: "",
    })

    const openAdd = () => {
      setEditingWorkExpIdx(null)
      setWorkExpForm(emptyWorkExp())
      setShowOptional(false)
      setWorkExpDialogOpen(true)
    }

    const openEdit = (index: number) => {
      const item = items[index]
      setEditingWorkExpIdx(index)
      const rawEnd = item.end_date || ""
      const normalizedEnd = (rawEnd === "至今" || rawEnd.startsWith("9999")) ? "至今" : rawEnd
      setWorkExpForm({
        ...emptyWorkExp(),
        ...item,
        end_date: normalizedEnd,
        // Data migration: description → responsibilities
        responsibilities: item.responsibilities || item.description || "",
      })
      // Auto-expand optional section if any optional field is filled
      const hasOptional = !!(
        item.is_internship ||
        item.hide_resume ||
        item.department ||
        item.report_to ||
        item.team_size ||
        item.salary_amount ||
        item.salary_months ||
        item.work_city
      )
      setShowOptional(hasOptional)
      setWorkExpDialogOpen(true)
    }

    const handleSave = async () => {
      if (editingWorkExpIdx !== null) {
        await handleUpdateItem("work_experience", editingWorkExpIdx, workExpForm)
      } else {
        await handleAddItem("work_experience", workExpForm)
      }
      setWorkExpDialogOpen(false)
    }

    return (
      <SectionCard moduleKey="work_experience">
        <SectionHeader title={getLabel("work_experience", "工作经历")} />
        <div className="space-y-4">
          {items.map((item: any, index: number) => {
            const resp = item.responsibilities || item.description || ""
            const industry = item.industry || ""
            const city = item.work_city || ""
            const isOngoing = item.end_date === "至今" || item.end_date?.startsWith("9999")
            return (
              <div key={index} className="border-b border-gray-100 pb-4 last:border-0 last:pb-0">
                {/* Row 1: company + dates/actions */}
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium text-gray-900 flex items-center gap-2">
                    {item.company || "未知公司"}
                    {itemChanged("work_experience", index) && <ChangedBadge />}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">
                      {item.start_date || ""} - {isOngoing ? "至今" : (item.end_date || "至今")}
                    </span>
                    <button onClick={() => openEdit(index)} className="text-xs text-[#FF6B00] hover:text-[#e55f00] cursor-pointer">编辑</button>
                    <button
                      onClick={() => {
                        const item = items[index]
                        const name = `${item?.company || "未知公司"}${item?.position ? ` · ${item.position}` : ""}`
                        setDeleteTarget({
                          fieldName: "work_experience",
                          index,
                          title: `确认删除工作经历「${name}」？`,
                          description: "删除后本地工作经历将移除该条目，保存快照或回写官网后生效。",
                        })
                      }}
                      className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                    >
                      删除
                    </button>
                  </div>
                </div>
                {/* Row 2: company·position */}
                {item.position && (
                  <div className="text-sm text-gray-600 mt-1">{item.company}·{item.position}</div>
                )}
                {/* Row 3: industry | city */}
                {(industry || city) && (
                  <div className="text-xs text-gray-500 mt-1">
                    {[industry, city].filter(Boolean).join(" | ")}
                  </div>
                )}
                {/* Row 4: responsibilities preview (2 lines truncated) */}
                {resp && (
                  <div className="text-sm text-gray-500 mt-2 whitespace-pre-wrap leading-relaxed line-clamp-2">
                    {resp}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <button
          onClick={openAdd}
          className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          添加工作经历
        </button>

        <Dialog open={workExpDialogOpen} onOpenChange={setWorkExpDialogOpen}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editingWorkExpIdx !== null ? "编辑工作经历" : "添加工作经历"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 max-h-[68vh] overflow-y-auto pr-1">
              {/* ── Section 1: Required fields ── */}

              {/* 公司名称 | 所属行业 */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">公司名称 <span className="text-red-500">*</span></label>
                  <Input
                    value={workExpForm.company || ""}
                    onChange={(e: any) => setWorkExpForm({ ...workExpForm, company: e.target.value })}
                    placeholder="请输入公司名称"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">所属行业</label>
                  <LiepinIndustrySelector
                    value={workExpForm.industry ? [workExpForm.industry] : []}
                    onChange={(v: any) => {
                      const newIndustry = v.length > 0 ? v[v.length - 1] : ""
                      setWorkExpForm({ ...workExpForm, industry: newIndustry })
                    }}
                  />
                </div>
              </div>

              {/* 职位名称 | 职位类别 */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">职位名称 <span className="text-red-500">*</span></label>
                  <Input
                    value={workExpForm.position || ""}
                    onChange={(e: any) => setWorkExpForm({ ...workExpForm, position: e.target.value })}
                    placeholder="请输入职位名称"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">职位类别</label>
                  <LiepinJobSelector
                    value={workExpForm.job_category || ""}
                    onChange={(v: any) => setWorkExpForm({ ...workExpForm, job_category: v })}
                  />
                </div>
              </div>

              {/* 开始时间 | 结束时间 (+ 至今 toggle) */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">开始时间</label>
                  <LiepinYearMonthPicker
                    value={workExpForm.start_date || ""}
                    onChange={(v: any) => setWorkExpForm({ ...workExpForm, start_date: v })}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">结束时间</label>
                  <div className="flex items-center gap-2">
                    <div className="flex-1">
                      <LiepinYearMonthPicker
                        value={(workExpForm.end_date === "至今" || workExpForm.end_date?.startsWith("9999")) ? "" : (workExpForm.end_date || "")}
                        onChange={(v: any) => setWorkExpForm({ ...workExpForm, end_date: v })}
                        placeholder={(workExpForm.end_date === "至今" || workExpForm.end_date?.startsWith("9999")) ? "至今" : "请选择"}
                        disabled={workExpForm.end_date === "至今" || workExpForm.end_date?.startsWith("9999")}
                      />
                    </div>
                    <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer select-none whitespace-nowrap">
                      <input
                        type="checkbox"
                        checked={workExpForm.end_date === "至今" || workExpForm.end_date?.startsWith("9999")}
                        onChange={(e: any) => setWorkExpForm({ ...workExpForm, end_date: e.target.checked ? "至今" : "" })}
                        className="accent-[#FF6B00]"
                      />
                      至今
                    </label>
                  </div>
                </div>
              </div>

              {/* 职责业绩 */}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">职责业绩</label>
                <div className="relative">
                  <Textarea
                    value={workExpForm.responsibilities || ""}
                    onChange={(e: any) => setWorkExpForm({ ...workExpForm, responsibilities: e.target.value.slice(0, 2000) })}
                    rows={5}
                    maxLength={2000}
                    placeholder="请描述主要工作内容和业绩"
                    className="resize-none pb-6"
                  />
                  <span className="absolute bottom-2 right-3 text-xs text-gray-400">
                    {(workExpForm.responsibilities || "").length} / 2000
                  </span>
                </div>
              </div>

              {/* ── Section 2: Optional fields ── */}
              <div>
                <button
                  type="button"
                  onClick={() => setShowOptional(!showOptional)}
                  className="flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
                >
                  <ChevronDown className={`w-4 h-4 transition-transform ${showOptional ? "rotate-180" : ""}`} />
                  {showOptional ? "收起选填信息" : "展开选填信息"}
                </button>
              </div>

              {showOptional && (
                <div className="space-y-4">
                  {/* 本段经历是实习经历 | 对该公司屏蔽我的简历 */}
                  <div className="flex items-center gap-6">
                    <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={!!workExpForm.is_internship}
                        onChange={(e: any) => setWorkExpForm({ ...workExpForm, is_internship: e.target.checked })}
                        className="accent-[#FF6B00]"
                      />
                      本段经历是实习经历
                    </label>
                    <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={!!workExpForm.hide_resume}
                        onChange={(e: any) => setWorkExpForm({ ...workExpForm, hide_resume: e.target.checked })}
                        className="accent-[#FF6B00]"
                      />
                      对该公司屏蔽我的简历
                    </label>
                  </div>

                  {/* 所属部门 | 汇报对象职位 */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-gray-500 mb-1 block">所属部门</label>
                      <Input
                        value={workExpForm.department || ""}
                        onChange={(e: any) => setWorkExpForm({ ...workExpForm, department: e.target.value })}
                        placeholder="请输入所属部门"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-500 mb-1 block">汇报对象职位</label>
                      <Input
                        value={workExpForm.report_to || ""}
                        onChange={(e: any) => setWorkExpForm({ ...workExpForm, report_to: e.target.value })}
                        placeholder="请输入汇报对象职位"
                      />
                    </div>
                  </div>

                  {/* 下属人数 | 工作地点 */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-gray-500 mb-1 block">下属人数</label>
                      <Input
                        value={workExpForm.team_size || ""}
                        onChange={(e: any) => setWorkExpForm({ ...workExpForm, team_size: e.target.value.replace(/\D/g, "") })}
                        placeholder="请输入下属人数"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-500 mb-1 block">工作地点</label>
                      <LiepinCitySelector
                        value={workExpForm.work_city || ""}
                        onChange={(v: any) => setWorkExpForm({ ...workExpForm, work_city: v })}
                      />
                    </div>
                  </div>

                  {/* 目前薪资: 月薪 × 月数 */}
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">目前薪资</label>
                    <div className="flex items-center gap-2">
                      <Input
                        value={workExpForm.salary_amount || ""}
                        onChange={(e: any) => setWorkExpForm({ ...workExpForm, salary_amount: e.target.value.replace(/\D/g, "") })}
                        placeholder="月薪"
                        className="flex-1"
                      />
                      <span className="text-sm text-gray-400 whitespace-nowrap">元 ×</span>
                      <Input
                        value={workExpForm.salary_months || ""}
                        onChange={(e: any) => setWorkExpForm({ ...workExpForm, salary_months: e.target.value.replace(/\D/g, "") })}
                        placeholder="月数"
                        className="w-24"
                      />
                      <span className="text-sm text-gray-400 whitespace-nowrap">个月</span>
                    </div>
                  </div>
                </div>
              )}

              <DynamicFieldSlot
                data={workExpForm}
                excludeKeys={[
                  // 与猎聘数据真实键约定对齐（collector/pusher/mapper/表单绑定均为
                  // company/position/job_category 体系）；旧列表写的 company_name/
                  // position_name/work_summary 等键在猎聘链路中不存在，导致模块
                  // 自有字段全部漏进「动态扩展字段」误报
                  "company", "industry", "position", "start_date", "end_date",
                  "job_category", "responsibilities", "is_internship", "hide_resume",
                  "department", "report_to", "team_size", "work_city",
                  "salary_amount", "salary_months", "path", "id", "subType"
                ]}
                onChange={(k: any, v) => setWorkExpForm((prev: any) => ({ ...prev, [k]: v }))}
                title="工作经历 · 动态扩展字段"
              />
            </div>
            <DialogActions onCancel={() => setWorkExpDialogOpen(false)} onConfirm={handleSave} saving={saving} />
          </DialogContent>
        </Dialog>
      </SectionCard>
    )
  }
