/**
 * Job51 Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { Job51YearMonthPicker } from "@/components/ui/51job-year-month-picker"
import { Job51IndustryPicker } from "@/components/ui/51job-industry-picker"
import { Job51FuntypePicker } from "@/components/ui/51job-funtype-picker"
import { JOB51_JOB_TERMS } from "@/lib/51job-options"
import { JOB51_COMPANY_TYPES } from "@/lib/51job-options"
import { JOB51_COMPANY_SIZES } from "@/lib/51job-options"
import { useJob51Ctx } from "../context"
import { SectionCard, SectionHeader } from "../constants"
import { JobFunctionWarningBar } from "../constants"
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


export function Job51WorkExperience() {
  const {
    saving,
    workExpEditing,
    setWorkExpEditing,
    workExpForm,
    setWorkExpForm,
    editingWorkExpIdx,
    setEditingWorkExpIdx,
    workFuntypePickerOpen,
    setWorkFuntypePickerOpen,
    workIndustryPickerOpen,
    setWorkIndustryPickerOpen,
    workSkillInput,
    setWorkSkillInput,
    report,
    setDeleteTarget,
    changedModuleKeys,
    handleAddItem,
    handleUpdateItem,
    getVal,
  } = useJob51Ctx()

    const items = getVal("works") || []

    const openAdd = () => {
      setEditingWorkExpIdx(null)
      setWorkExpForm({
        companyName: "", startTime: "", endTime: "",
        workFunction: "", workFunctionString: "",
        position: "",
        seekType: "0", workType: "0", workDescription: "",
        skills: [] as string[],
        workVocationalSkills: [] as any[],
        industry: "", industryName: "",
        workIndustry: "", workIndustryString: "",
        companySize: "", companyType: "",
        hideInfo: false,
      })
      setWorkSkillInput("")
      setWorkExpEditing(true)
    }

    const openEdit = (index: number) => {
      setEditingWorkExpIdx(index)
      const item = items[index]
      // 如果 endTimeString 为"至今"，表单 endTime 也设为"至今"
      const endTime = item.endTimeString === "至今" || item.endTime === "至今" ? "至今" : (item.endTime || "")
      const skills = (item.skills && item.skills.length > 0)
        ? item.skills
        : ((item.workVocationalSkills || []).map((s: any) => typeof s === "string" ? s : (s.skill || s.value || "")).filter(Boolean))
      const seekType = item.seekType || item.workType || "0"
      const ind = item.workIndustry || item.industry || ""
      const indName = item.workIndustryString || item.industryName || ""
      setWorkExpForm({
        ...item,
        endTime,
        skills,
        seekType,
        workType: seekType,
        industry: ind,
        workIndustry: ind,
        industryName: indName,
        workIndustryString: indName,
      })
      setWorkSkillInput("")
      setWorkExpEditing(true)
    }

    const handleCancel = () => {
      setWorkExpEditing(false)
      setWorkFuntypePickerOpen(false)
      setWorkIndustryPickerOpen(false)
    }

    const handleSave = async () => {
      const currentSkills = workExpForm.skills || []
      const ind = workExpForm.workIndustry || workExpForm.industry || ""
      const indName = workExpForm.workIndustryString || workExpForm.industryName || ""
      const payload = {
        ...workExpForm,
        position: workExpForm.position || workExpForm.workFunctionString || "专业人员",
        workType: workExpForm.seekType || workExpForm.workType || "0",
        seekType: workExpForm.seekType || workExpForm.workType || "0",
        industry: ind,
        workIndustry: ind,
        workIndustryNew: "",
        industryName: indName,
        workIndustryString: indName,
        skills: currentSkills,
        workVocationalSkills: currentSkills.map((s: string) => ({
          skill: s,
          value: s,
          isCustomize: true,
          skillCode: "",
          direction: "",
          directionCode: "",
        })),
      }
      let ok: boolean
      if (editingWorkExpIdx !== null) {
        ok = await handleUpdateItem("works", editingWorkExpIdx, payload)
      } else {
        ok = await handleAddItem("works", payload)
      }
      if (!ok) return
      setWorkExpEditing(false)
    }

    const addSkill = () => {
      const s = workSkillInput.trim()
      if (s && !(workExpForm.skills || []).includes(s)) {
        if ((workExpForm.skills || []).length >= 10) {
          alert("最多添加10个相关技能哦")
          return
        }
        setWorkExpForm({ ...workExpForm, skills: [...(workExpForm.skills || []), s] })
      }
      setWorkSkillInput("")
    }

    const removeSkill = (idx: number) => {
      setWorkExpForm({ ...workExpForm, skills: (workExpForm.skills || []).filter((_: string, i: number) => i !== idx) })
    }

    // ===== 编辑模式（内联展开） =====
    if (workExpEditing) {
      return (
        <SectionCard id="work-experience" changed={changedModuleKeys.has("works")}>
          <SectionHeader title="工作经历" changed={changedModuleKeys.has("works")} />

          <div className="space-y-5">
            {/* 公司名称 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>公司名称
              </label>
              <Input
                value={workExpForm.companyName || ""}
                onChange={(e) => setWorkExpForm({ ...workExpForm, companyName: e.target.value })}
                placeholder="请填写"
                className="h-[40px]"
              />
            </div>

            {/* 在职时间 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>在职时间
              </label>
              <div className="flex items-center gap-2">
                <Job51YearMonthPicker
                  value={workExpForm.startTime || ""}
                  onChange={(v) => setWorkExpForm({ ...workExpForm, startTime: v })}
                />
                <span className="text-gray-400 text-sm flex-shrink-0">至</span>
                {workExpForm.endTime === "至今" ? (
                  <div className="flex items-center gap-2 flex-1">
                    <span className="h-[40px] px-3 flex items-center text-sm text-[#FF6B00] bg-[#FFF3E8] rounded-md border border-[#FF6B00]/30">至今</span>
                  </div>
                ) : (
                  <Job51YearMonthPicker
                    value={workExpForm.endTime || ""}
                    onChange={(v) => setWorkExpForm({ ...workExpForm, endTime: v })}
                    placeholder="至今"
                    allowPresent
                  />
                )}
                <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer flex-shrink-0 select-none">
                  <input
                    type="checkbox"
                    checked={workExpForm.endTime === "至今"}
                    onChange={(e) => setWorkExpForm({ ...workExpForm, endTime: e.target.checked ? "至今" : "" })}
                    className="w-4 h-4 rounded border-gray-300 text-[#FF6B00] accent-[#FF6B00] cursor-pointer"
                  />
                  至今
                </label>
              </div>
            </div>

            {/* 职位 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>职位
              </label>
              <div
                onClick={() => setWorkFuntypePickerOpen(true)}
                className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 flex items-center text-sm cursor-pointer hover:border-[#FF6B00] transition-colors"
              >
                {workExpForm.position || workExpForm.workFunctionString ? (
                  <span className="text-gray-900">{workExpForm.position || workExpForm.workFunctionString}</span>
                ) : (
                  <span className="text-gray-400">请选择</span>
                )}
              </div>
            </div>

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
                    onClick={() => setWorkExpForm({ ...workExpForm, seekType: t.code })}
                    className={`px-5 py-1.5 rounded text-sm border transition-colors ${
                      workExpForm.seekType === t.code
                        ? "bg-[#FF6B00] text-white border-[#FF6B00]"
                        : "bg-white text-gray-600 border-gray-300 hover:border-[#FF6B00] hover:text-[#FF6B00]"
                    }`}
                  >
                    {t.value}
                  </button>
                ))}
              </div>
            </div>

            {/* 工作描述 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>工作描述
              </label>
              <Textarea
                value={workExpForm.workDescription || ""}
                onChange={(e) => setWorkExpForm({ ...workExpForm, workDescription: e.target.value.slice(0, 2000) })}
                rows={6}
                placeholder="描述这段时间工作期间你的主要工作，如：1.职责范围；2.工作任务；3.工作产出等"
                className="resize-none border-gray-300 focus:border-[#FF6B00]"
              />
              <div className="text-xs text-gray-400 text-right mt-1">
                {(workExpForm.workDescription || "").length}/2000
              </div>
            </div>

            {/* 相关技能（选填） */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm text-gray-700 font-medium">相关技能（选填）</label>
                <span className="text-xs text-gray-400">{(workExpForm.skills || []).length}/10</span>
              </div>
              <div>
                {/* 已添加的技能标签 */}
                {(workExpForm.skills || []).length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-2">
                    {(workExpForm.skills || []).map((skill: string, idx: number) => (
                      <span key={idx} className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-[#FFF3E8] border border-[#FF6B00]/30 rounded-md text-sm text-[#FF6B00] font-medium">
                        {skill}
                        <button type="button" onClick={() => removeSkill(idx)} className="text-[#FF6B00]/70 hover:text-red-500 text-xs font-bold leading-none">✕</button>
                      </span>
                    ))}
                  </div>
                )}
                <div className="flex gap-2">
                  <Input
                    value={workSkillInput}
                    onChange={(e) => setWorkSkillInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSkill() } }}
                    placeholder="输入技能关键词（如 Python、大模型、Prompt 等）"
                    className="h-[36px] flex-1"
                  />
                  <Button type="button" variant="outline" onClick={addSkill} className="text-[#FF6B00] border-[#FF6B00] hover:bg-[#FF6B00]/5 h-[36px]">
                    添加技能
                  </Button>
                </div>
              </div>
            </div>

            {/* 所属行业（选填） */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">所属行业（选填）</label>
              <div
                onClick={() => setWorkIndustryPickerOpen(true)}
                className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 flex items-center text-sm cursor-pointer hover:border-[#FF6B00] transition-colors"
              >
                {workExpForm.industryName || workExpForm.workIndustryString ? (
                  <span className="text-gray-900">{workExpForm.industryName || workExpForm.workIndustryString}</span>
                ) : (
                  <span className="text-gray-400">选择行业</span>
                )}
              </div>
            </div>

            {/* 公司性质与规模 */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm text-gray-700 mb-2 block">公司规模（选填）</label>
                <select
                  value={workExpForm.companySize || ""}
                  onChange={(e) => setWorkExpForm({ ...workExpForm, companySize: e.target.value })}
                  className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 text-sm focus:border-[#FF6B00] focus:outline-none"
                >
                  <option value="">请选择</option>
                  {JOB51_COMPANY_SIZES.map((s) => (
                    <option key={s.code} value={s.code}>{s.value}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm text-gray-700 mb-2 block">公司性质（选填）</label>
                <select
                  value={workExpForm.companyType || ""}
                  onChange={(e) => setWorkExpForm({ ...workExpForm, companyType: e.target.value })}
                  className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 text-sm focus:border-[#FF6B00] focus:outline-none"
                >
                  <option value="">请选择</option>
                  {JOB51_COMPANY_TYPES.map((t) => (
                    <option key={t.code} value={t.code}>{t.value}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* 对这家公司隐藏我的信息（仅新增时展示） */}
            {editingWorkExpIdx === null && (
              <div className="flex items-center justify-between pt-1">
                <div>
                  <div className="text-sm text-gray-800">对这家公司隐藏我的信息</div>
                  <div className="text-xs text-gray-400">该公司将无法搜索到您的简历</div>
                </div>
                <button
                  type="button"
                  onClick={() => setWorkExpForm({ ...workExpForm, hideInfo: !workExpForm.hideInfo })}
                  className={`relative w-11 h-6 rounded-full transition-colors ${workExpForm.hideInfo ? "bg-[#FF6B00]" : "bg-gray-300"}`}
                >
                  <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${workExpForm.hideInfo ? "left-[22px]" : "left-0.5"}`} />
                </button>
              </div>
            )}

            <DynamicFieldSlot
              data={workExpForm}
              excludeKeys={[
                "companyName", "industry", "industryName", "workIndustry", "workIndustryString", "workIndustryNew",
                "position", "workFunction", "workFunctionString", "startTime", "endTime",
                "isCurrent", "workDescription", "department", "companyType", "companySize",
                "companyNature", "companyNatureString", "companySizeString",
                "workType", "workTypeString", "salary", "salaryType", "salaryString", "hideInfo",
                "skills", "skill_tags", "workVocationalSkills", "workLabels", "path", "id", "subType"
              ]}
              onChange={(k, v) => setWorkExpForm((prev: any) => ({ ...prev, [k]: v }))}
              title="工作经历 · 动态扩展字段"
            />

            {/* 操作按钮 */}
            <div className="flex justify-end gap-3 pt-4 border-t border-gray-100">
              <Button type="button" variant="outline" onClick={handleCancel} className="border-gray-300 text-gray-600 min-w-[80px]">取消</Button>
              <Button type="button" onClick={handleSave} disabled={saving} className="bg-[#FF6B00] hover:bg-[#e55f00] text-white min-w-[80px]">
                {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : null}
                保存
              </Button>
            </div>
          </div>

          {/* 职位选择弹窗 */}
          <Job51FuntypePicker
            open={workFuntypePickerOpen}
            onClose={() => setWorkFuntypePickerOpen(false)}
            selectedCode={workExpForm.workFunction || ""}
            onConfirm={(code: any, name: any) => {
              setWorkExpForm({ ...workExpForm, workFunction: code, workFunctionString: name, position: workExpForm.position || name })
              setWorkFuntypePickerOpen(false)
            }}
          />

          {/* 行业选择弹窗 */}
          <Job51IndustryPicker
            open={workIndustryPickerOpen}
            onClose={() => setWorkIndustryPickerOpen(false)}
            selected={workExpForm.workIndustry || workExpForm.industry ? [workExpForm.workIndustry || workExpForm.industry] : []}
            onConfirm={(nodes: any) => {
              if (nodes.length > 0) {
                setWorkExpForm({
                  ...workExpForm,
                  industry: nodes[0].code,
                  workIndustry: nodes[0].code,
                  industryName: nodes[0].name,
                  workIndustryString: nodes[0].name,
                })
              } else {
                setWorkExpForm({
                  ...workExpForm,
                  industry: "",
                  workIndustry: "",
                  industryName: "",
                  workIndustryString: "",
                })
              }
              setWorkIndustryPickerOpen(false)
            }}
            maxSelect={1}
          />
        </SectionCard>
      )
    }

    // ===== 展示模式 =====
    return (
      <SectionCard id="work-experience" changed={changedModuleKeys.has("works")}>
        <SectionHeader title="工作经历" changed={changedModuleKeys.has("works")} />
        <JobFunctionWarningBar warnings={report?.warnings} />
        {items.length === 0 ? (
          <div className="text-sm text-gray-400">暂无工作经历</div>
        ) : (
          <div className="space-y-4">
            {items.map((item: any, index: number) => {
              const skillsList = (item.skills && item.skills.length > 0)
                ? item.skills
                : ((item.workVocationalSkills || []).map((s: any) => typeof s === "string" ? s : (s.skill || s.value || "")).filter(Boolean))
              const workType = item.seekType || item.workType || "0"
              const workTypeLabel = workType === "0" ? "全职" : workType === "1" ? "兼职" : workType === "2" ? "实习" : ""
              return (
                <div key={index} className="border-b border-gray-100 pb-4 last:border-0 last:pb-0 group">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium text-gray-900">{item.companyName || "未知公司"}</div>
                    <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => openEdit(index)} className="text-xs text-[#FF6B00] hover:text-[#e55f00] cursor-pointer">编辑</button>
                      <button onClick={() => setDeleteTarget({ fieldName: "works", index, title: `确认删除工作经历「${item.companyName || '工作经历'}」？`, description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。" })} className="text-xs text-red-400 hover:text-red-500 cursor-pointer">删除</button>
                    </div>
                  </div>
                  <div className="text-sm text-gray-600 mt-1">
                    {[
                      item.position || item.workFunctionString,
                      item.workIndustryString || item.industryName,
                      item.startTime ? `${item.startTime} - ${item.endTime || "至今"}` : null,
                      workTypeLabel,
                    ].filter(Boolean).join(" | ")}
                  </div>
                  {item.workDescription && (
                    <div className="text-sm text-gray-500 mt-2 whitespace-pre-wrap leading-relaxed line-clamp-4">
                      {item.workDescription}
                    </div>
                  )}
                  {skillsList.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2.5">
                      {skillsList.map((s: string, i: number) => (
                        <span key={i} className="px-2 py-0.5 bg-[#FFF3E8] border border-[#FF6B00]/20 rounded text-xs text-[#FF6B00] font-medium">{s}</span>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
        <button
          onClick={openAdd}
          className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          添加工作经历
        </button>
      </SectionCard>
    )
  }
