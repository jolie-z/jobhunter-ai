/**
 * Job51 Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { Job51IndustryPicker } from "@/components/ui/51job-industry-picker"
import { Job51FuntypePicker } from "@/components/ui/51job-funtype-picker"
import { JOB51_JOB_TERMS } from "@/lib/51job-options"
import { Job51CityPicker } from "@/components/ui/51job-city-picker"
import { JOB51_SALARY_MONTHS } from "@/lib/51job-options"
import { JOB51_SALARY_RANGES } from "@/lib/51job-options"
import { useJob51Ctx } from "../context"
import { SectionCard, SectionHeader } from "../constants"
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
import { ReportWarnings, ReportUnfilled, ModuleChangeSummary, ModuleReportNotice } from "../../agent-report-shared"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"


export function Job51Intentions() {
  const {
    saving,
    intentionEditing,
    setIntentionEditing,
    intentionForm,
    setIntentionForm,
    editingIntentionIdx,
    setEditingIntentionIdx,
    cityPickerOpen,
    setCityPickerOpen,
    funtypePickerOpen,
    setFuntypePickerOpen,
    industryPickerOpen,
    setIndustryPickerOpen,
    setDeleteTarget,
    changedModuleKeys,
    handleAddItem,
    handleUpdateItem,
    getVal,
  } = useJob51Ctx()

    const items = getVal("intentions") || []

    // 薪资文本查找
    const salaryText = (val: string) => JOB51_SALARY_RANGES.find((r: any) => r.value === val)?.text || val
    // 薪资数值解析（用于 min < max 过滤）
    const salaryNum = (val: string) => {
      if (!val) return 0
      if (val.includes("-")) {
        const parts = val.split("-")
        return parseInt(parts[0] || "0", 10)
      }
      return parseInt(val, 10) || 0
    }

    const openAdd = () => {
      setEditingIntentionIdx(null)
      setIntentionForm({
        seekType: "0",
        expectArea: "",
        expectAreaNames: "",
        expectAreaString: "",
        expectFunction: "",
        expectFunctionName: "",
        expectFunctionString: "",
        minSalary: "",
        maxSalary: "",
        salaryMonth: 12,
        industry: "",
        industryNames: "",
        expectIndustry: "",
        expectIndustryString: "",
        preferenceValues: [] as string[],
      })
      setIntentionEditing(true)
    }

    const openEdit = (index: number) => {
      setEditingIntentionIdx(index)
      const it = items[index] || {}
      const ind = it.industry || it.expectIndustry || ""
      const indNames = it.industryNames || it.expectIndustryString || ""
      const area = it.expectArea || ""
      const areaNames = it.expectAreaNames || it.expectAreaString || ""
      const func = it.expectFunction || ""
      const funcName = it.expectFunctionName || it.expectFunctionString || ""
      setIntentionForm({
        ...it,
        industry: ind,
        industryNames: indNames,
        expectIndustry: ind,
        expectIndustryString: indNames,
        expectArea: area,
        expectAreaNames: areaNames,
        expectAreaString: areaNames,
        expectFunction: func,
        expectFunctionName: funcName,
        expectFunctionString: funcName,
      })
      setIntentionEditing(true)
    }

    const handleCancel = () => {
      setIntentionEditing(false)
      setCityPickerOpen(false)
      setFuntypePickerOpen(false)
      setIndustryPickerOpen(false)
    }

    const handleSave = async () => {
      const ind = intentionForm.industry || intentionForm.expectIndustry || ""
      const indNames = intentionForm.industryNames || intentionForm.expectIndustryString || ""
      const area = intentionForm.expectArea || ""
      const areaNames = intentionForm.expectAreaNames || intentionForm.expectAreaString || ""
      const func = intentionForm.expectFunction || ""
      const funcName = intentionForm.expectFunctionName || intentionForm.expectFunctionString || ""
      const cleanForm = {
        ...intentionForm,
        industry: ind,
        industryNames: indNames,
        expectIndustry: ind,
        expectIndustryString: indNames,
        expectArea: area,
        expectAreaNames: areaNames,
        expectAreaString: areaNames,
        expectFunction: func,
        expectFunctionName: funcName,
        expectFunctionString: funcName,
      }
      let ok: boolean
      if (editingIntentionIdx !== null) {
        ok = await handleUpdateItem("intentions", editingIntentionIdx, cleanForm)
      } else {
        ok = await handleAddItem("intentions", cleanForm)
      }
      if (!ok) return
      setIntentionEditing(false)
    }

    // 最高薪资选项：必须大于最低薪资
    const maxSalaryOptions = JOB51_SALARY_RANGES.filter(
      (r: any) => !intentionForm.minSalary || salaryNum(r.value) > salaryNum(intentionForm.minSalary)
    )

    // ===== 编辑模式（内联展开） =====
    if (intentionEditing) {
      return (
        <SectionCard id="intentions" changed={changedModuleKeys.has("intentions")}>
          <SectionHeader title="求职意向" changed={changedModuleKeys.has("intentions")} />

          <div className="space-y-5">
            {/* 工作类型 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>工作类型
              </label>
              <div className="flex gap-2">
                {JOB51_JOB_TERMS.map((t) => (
                  <button
                    key={t.code}
                    type="button"
                    onClick={() => setIntentionForm({ ...intentionForm, seekType: t.code })}
                    className={`px-5 py-1.5 rounded text-sm border transition-colors ${
                      intentionForm.seekType === t.code
                        ? "bg-[#FF6B00] text-white border-[#FF6B00]"
                        : "bg-white text-gray-600 border-gray-300 hover:border-[#FF6B00] hover:text-[#FF6B00]"
                    }`}
                  >
                    {t.value}
                  </button>
                ))}
              </div>
            </div>

            {/* 期望工作城市 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>期望工作城市
              </label>
              <div
                onClick={() => setCityPickerOpen(true)}
                className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 flex items-center text-sm cursor-pointer hover:border-[#FF6B00] transition-colors"
              >
                {intentionForm.expectAreaNames ? (
                  <span className="text-gray-900">{intentionForm.expectAreaNames}</span>
                ) : (
                  <span className="text-gray-400">请选择城市（最多3个）</span>
                )}
              </div>
            </div>

            {/* 期望职位 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>期望职位
              </label>
              <div
                onClick={() => setFuntypePickerOpen(true)}
                className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 flex items-center text-sm cursor-pointer hover:border-[#FF6B00] transition-colors"
              >
                {intentionForm.expectFunctionName ? (
                  <span className="text-gray-900">{intentionForm.expectFunctionName}</span>
                ) : (
                  <span className="text-gray-400">请选择职位</span>
                )}
              </div>
            </div>

            {/* 期望月薪 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>期望月薪
              </label>
              <div className="flex items-center gap-2">
                <select
                  value={intentionForm.minSalary || ""}
                  onChange={(e) => {
                    const v = e.target.value
                    // 如果最低薪资变了，且最高薪资 <= 最低，则清空最高
                    const next: any = { ...intentionForm, minSalary: v }
                    if (v && intentionForm.maxSalary && salaryNum(intentionForm.maxSalary) <= salaryNum(v)) {
                      next.maxSalary = ""
                    }
                    setIntentionForm(next)
                  }}
                  className="flex-1 h-[40px] rounded-md border border-gray-300 bg-white px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
                >
                  <option value="">最低薪资</option>
                  {JOB51_SALARY_RANGES.map((r: any) => (
                    <option key={r.id} value={r.value}>{r.text}</option>
                  ))}
                </select>
                <span className="text-gray-400 text-sm">—</span>
                <select
                  value={intentionForm.maxSalary || ""}
                  onChange={(e) => setIntentionForm({ ...intentionForm, maxSalary: e.target.value })}
                  disabled={!intentionForm.minSalary}
                  className="flex-1 h-[40px] rounded-md border border-gray-300 bg-white px-3 text-sm focus:outline-none focus:border-[#FF6B00] disabled:bg-gray-50 disabled:text-gray-300 disabled:cursor-not-allowed"
                >
                  <option value="">最高薪资</option>
                  {maxSalaryOptions.map((r: any) => (
                    <option key={r.id} value={r.value}>{r.text}</option>
                  ))}
                </select>
                <select
                  value={intentionForm.salaryMonth || 12}
                  onChange={(e) => setIntentionForm({ ...intentionForm, salaryMonth: Number(e.target.value) })}
                  className="w-[90px] h-[40px] rounded-md border border-gray-300 bg-white px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
                >
                  {JOB51_SALARY_MONTHS.map((m) => (
                    <option key={m.id} value={m.id}>{m.text}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* 期望行业（选填） */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">期望行业（选填）</label>
              <div
                onClick={() => setIndustryPickerOpen(true)}
                className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 flex items-center text-sm cursor-pointer hover:border-[#FF6B00] transition-colors"
              >
                {intentionForm.industryNames ? (
                  <span className="text-gray-900">{intentionForm.industryNames}</span>
                ) : (
                  <span className="text-gray-400">请选择行业（最多3个）</span>
                )}
              </div>
            </div>

            {/* 求职偏好（只读，数据来源官网） */}
            {(() => {
              const prefs = intentionForm.preferenceValues || []
              return (
                <div>
                  <label className="text-sm text-gray-700 mb-2 block">求职偏好（选填）</label>
                  {prefs.length > 0 ? (
                    <div className="flex flex-wrap gap-2 mb-2">
                      {prefs.map((pref: string, pIdx: number) => (
                        <span key={pIdx} className="inline-flex items-center px-2.5 py-1 bg-[#FFF3E8] text-[#FF6B00] rounded text-sm">
                          {pref}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="text-sm text-gray-400">暂无偏好数据</span>
                  )}
                  <p className="text-xs text-gray-400 mt-1">如需编辑，请前往51job官网修改</p>
                </div>
              )
            })()}
          </div>

          {/* 底部按钮 */}
          <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-gray-100">
            <Button variant="outline" onClick={handleCancel} className="border-gray-300 text-gray-600 min-w-[80px]">
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving} className="bg-[#FF6B00] hover:bg-[#e55f00] text-white min-w-[80px]">
              {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : null}
              完成
            </Button>
          </div>

          {/* 城市选择弹窗 */}
          <Job51CityPicker
            open={cityPickerOpen}
            onClose={() => setCityPickerOpen(false)}
            selected={intentionForm.expectArea ? intentionForm.expectArea.split(",").filter(Boolean) : []}
            onConfirm={(cities) => {
              setIntentionForm({
                ...intentionForm,
                expectArea: cities.map((c) => c.code).join(","),
                expectAreaNames: cities.map((c) => c.value).join("、"),
              })
              setCityPickerOpen(false)
            }}
            maxSelect={3}
          />

          {/* 职位选择弹窗 */}
          <Job51FuntypePicker
            open={funtypePickerOpen}
            onClose={() => setFuntypePickerOpen(false)}
            selectedCode={intentionForm.expectFunction || ""}
            onConfirm={(code: any, name: any) => {
              setIntentionForm({ ...intentionForm, expectFunction: code, expectFunctionName: name })
              setFuntypePickerOpen(false)
            }}
          />

          {/* 行业选择弹窗 */}
          <Job51IndustryPicker
            open={industryPickerOpen}
            onClose={() => setIndustryPickerOpen(false)}
            selected={(intentionForm.industry || intentionForm.expectIndustry) ? (intentionForm.industry || intentionForm.expectIndustry).split(",").filter(Boolean) : []}
            onConfirm={(nodes: any) => {
              const indCodes = nodes.map((n: any) => n.code).join(",")
              const indLabels = nodes.map((n: any) => n.name).join("、")
              setIntentionForm({
                ...intentionForm,
                industry: indCodes,
                industryNames: indLabels,
                expectIndustry: indCodes,
                expectIndustryString: indLabels,
              })
              setIndustryPickerOpen(false)
            }}
            maxSelect={3}
          />
        </SectionCard>
      )
    }

    // ===== 展示模式 =====
    return (
      <SectionCard id="intentions">
        <SectionHeader title="求职意向" changed={changedModuleKeys.has("intentions")} />
        {items.length === 0 ? (
          <div className="text-sm text-gray-400">暂无求职意向</div>
        ) : (
          <div className="space-y-4">
            {items.map((item: any, index: number) => (
              <div key={index} className="border-b border-gray-100 pb-4 last:border-0 last:pb-0 group">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium text-gray-900">
                    {item.expectFunctionName || "未设置职位"}
                  </div>
                  <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={() => openEdit(index)} className="text-xs text-[#FF6B00] hover:text-[#e55f00] cursor-pointer">编辑</button>
                    <button onClick={() => setDeleteTarget({ fieldName: "intentions", index, title: `确认删除求职意向「${item.expectFunctionName || item.expectFunctionString || '意向'}」？`, description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。" })} className="text-xs text-red-400 hover:text-red-500 cursor-pointer">删除</button>
                  </div>
                </div>
                <div className="text-sm text-gray-600 mt-1.5 space-y-0.5">
                  <div>
                    <span className="text-gray-400">工作类型：</span>
                    {item.seekType === "0" ? "全职" : item.seekType === "1" ? "兼职" : "实习"}
                  </div>
                  {(item.minSalary || item.maxSalary) && (
                    <div>
                      <span className="text-gray-400">期望月薪：</span>
                      {[salaryText(item.minSalary), salaryText(item.maxSalary)].filter(Boolean).join(" - ")}
                      {item.salaryMonth ? ` · ${item.salaryMonth}薪` : ""}
                    </div>
                  )}
                  {(item.expectAreaNames || item.expectArea) && (
                    <div>
                      <span className="text-gray-400">期望城市：</span>
                      {item.expectAreaNames || item.expectArea}
                    </div>
                  )}
                  {(item.industryNames || item.industry || item.expectIndustryString) && (
                    <div>
                      <span className="text-gray-400">期望行业：</span>
                      {item.industryNames || item.expectIndustryString || item.industry}
                    </div>
                  )}
                  {(item.preferenceValues || []).length > 0 && (
                    <div className="mt-1.5">
                      <span className="text-gray-400">求职偏好：</span>
                      <div className="inline-flex flex-wrap gap-1.5 mt-1">
                        {item.preferenceValues.map((pref: string, pIdx: number) => (
                          <span key={pIdx} className="px-2 py-0.5 bg-[#FFF3E8] text-[#FF6B00] text-xs rounded">{pref}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        {items.length < 3 && (
          <button
            onClick={openAdd}
            className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            添加求职意向
          </button>
        )}
      </SectionCard>
    )
  }
