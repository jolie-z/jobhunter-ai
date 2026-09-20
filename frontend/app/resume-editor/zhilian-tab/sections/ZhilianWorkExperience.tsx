/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { PRIMARY, SectionCard, SectionHeader, FormRow, formatPeriod } from "../constants"
import { YearMonthPicker } from "../pickers"
import { JobCategoryCascader, IndustrySelect, SkillSelect, type SkillItem } from "../../zhilian-work-selectors"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"
import { ZHILIAN_WORK_JOB_TITLES } from "@/lib/zhilian-options"

import { useZhilianCtx } from "../context"

export function ZhilianWorkExperience() {
  const {
    localData,
    editingSection,
    editForm,
    setEditForm,
    editingIdx,
    changedModuleKeys,
    saving,
    startEdit,
    cancelEdit,
    handleAddItem,
    handleUpdateItem,
    setDeleteTarget,
    workExpError,
    setWorkExpError,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "workExp"
    const items = localData.workExperience || []

    // 解析日期字符串为 {year, month}
    const parseDate = (fmt: string): { year: string; month: string } => {
      if (!fmt) return { year: "", month: "" }
      const parts = fmt.split("/")
      return { year: parts[0] || "", month: String(Number(parts[1] || "0")) }
    }

    // 从时间戳兜底解析日期
    const dateFromTs = (ts: number): { year: string; month: string } => {
      if (!ts) return { year: "", month: "" }
      const d = new Date(ts)
      return { year: String(d.getFullYear()), month: String(d.getMonth() + 1) }
    }

    const handleStartEditWork = (item: any, idx?: number) => {
      setWorkExpError("")
      let start = parseDate(item.startDateFormat || "")
      let end = parseDate(item.endDateFormat || "")
      // 兜底：无格式字符串时从时间戳计算
      if (!start.year && item.startDate) start = dateFromTs(item.startDate)
      if (!end.year && item.endDate) end = dateFromTs(item.endDate)
      const toPresent = !item.endDate || item.endDate === 0
      // 解析技能标签（兼容对象数组、字符串数组、JSON 串及逗号分隔串，分配合法唯一 ID）
      let skillItems: SkillItem[] = []
      if (item.skillTagList && Array.isArray(item.skillTagList)) {
        skillItems = item.skillTagList.map((s: any, i: number) => {
          if (typeof s === "string") {
            return {
              id: 300000000 + Math.floor(Math.random() * 90000000) + i,
              name: s.trim(),
              isCustom: true,
              pathId: -1,
            }
          }
          const rawId = Number(s?.skillId || s?.id)
          const sid = rawId && !isNaN(rawId) ? rawId : (300000000 + Math.floor(Math.random() * 90000000) + i)
          return {
            id: sid,
            name: s?.name || s?.tagValue || "",
            isCustom: !!(s?.customize || s?.isCustom),
            pathId: Number(s?.skillParentId ?? s?.pathId ?? -1)
          }
        }).filter((s: SkillItem) => s.name)
      } else if (item.skills && Array.isArray(item.skills)) {
        skillItems = item.skills.map((s: any, i: number) => ({
          id: typeof s === "object" && Number(s?.id || s?.skillId) ? Number(s?.id || s?.skillId) : (300000000 + Math.floor(Math.random() * 90000000) + i),
          name: typeof s === "string" ? s.trim() : (s?.name || s?.skill || s?.value || ""),
          isCustom: true,
          pathId: -1,
        })).filter((s: SkillItem) => s.name)
      } else if (item.skillTags && Array.isArray(item.skillTags)) {
        skillItems = item.skillTags.map((s: any, i: number) => ({
          id: typeof s === "object" && Number(s?.intKey || s?.id) ? Number(s?.intKey || s?.id) : (300000000 + Math.floor(Math.random() * 90000000) + i),
          name: typeof s === "string" ? s.trim() : (s?.tagValue || s?.name || ""),
          isCustom: typeof s === "object" ? !s?.standard : true,
          pathId: Number(s?.pathId ?? -1),
        })).filter((s: SkillItem) => s.name)
      } else if (typeof item.skillTags === "string" && item.skillTags.trim().startsWith("[")) {
        try {
          const parsed = JSON.parse(item.skillTags)
          if (Array.isArray(parsed)) {
            skillItems = parsed.map((s: any, i: number) => {
              const rawId = Number(s?.intKey || s?.strKey || s?.id)
              const sid = rawId && !isNaN(rawId) ? rawId : (300000000 + Math.floor(Math.random() * 90000000) + i)
              return {
                id: sid,
                name: s?.tagValue || s?.name || "",
                isCustom: !s?.standard,
                pathId: Number(s?.pathId ?? -1)
              }
            }).filter((s: SkillItem) => s.name)
          }
        } catch {}
      } else if (typeof item.skillTagsTranslation === "string" && item.skillTagsTranslation.trim()) {
        skillItems = item.skillTagsTranslation.split(/[,，、;；]/).map((name: string, i: number) => ({
          id: 300000000 + Math.floor(Math.random() * 90000000) + i,
          name: name.trim(),
          isCustom: true,
          pathId: -1,
        })).filter((s: SkillItem) => s.name)
      }
      startEdit("workExp", {
        ...item,
        _startYear: start.year,
        _startMonth: start.month,
        _endYear: toPresent ? "" : end.year,
        _endMonth: toPresent ? "" : end.month,
        _toPresent: toPresent,
        _industrySelected: item.wnewIndustry ? [{ code: item.wnewIndustry, name: item.wnewIndustryTranslation || "" }] : [],
        _skillItems: skillItems,
      }, idx)
    }

    const handleSaveWork = async () => {
      if (!editForm.companyName?.trim()) { setWorkExpError("请输入公司名称"); return }
      if (!editForm.wnewIndustry) { setWorkExpError("请选择所属行业"); return }
      if (!editForm.wnewJobSubType) { setWorkExpError("请选择职位类别"); return }
      if (!editForm._startYear || !editForm._startMonth) { setWorkExpError("请选择入职时间"); return }
      if (!editForm._toPresent && (!editForm._endYear || !editForm._endMonth)) { setWorkExpError("请选择离职时间"); return }
      if (!editForm.workDesc?.trim()) { setWorkExpError("请输入工作描述"); return }
      if ((editForm.workDesc || "").length > 3000) {
        setWorkExpError(`工作描述已超出上限 ${(editForm.workDesc || "").length - 3000} 字（当前 ${(editForm.workDesc || "").length} / 3000 字），请删减精简至 3000 字以内后再保存`)
        return
      }
      setWorkExpError("")

      // 组装日期
      const startDate = new Date(Number(editForm._startYear), Number(editForm._startMonth) - 1, 1).getTime()
      const startDateFormat = `${editForm._startYear}/${String(editForm._startMonth).padStart(2, "0")}/01 00:00:00`
      const endDate = editForm._toPresent ? 0 : new Date(Number(editForm._endYear), Number(editForm._endMonth) - 1, 1).getTime()
      const endDateFormat = editForm._toPresent ? "" : `${editForm._endYear}/${String(editForm._endMonth).padStart(2, "0")}/01 00:00:00`

      const saveData = {
        ...editForm,
        startDate,
        startDateFormat,
        endDate,
        endDateFormat,
        jobTitle: editForm.jobTitle?.trim() || editForm.wnewJobSubTypeTranslation || "",
      }
      // 转换技能数据（全量对齐智联官网 Vuex/API 契约）
      const skillItems: SkillItem[] = editForm._skillItems || []
      saveData.skillTagList = skillItems.map(s => ({
        skillId: String(s.id),
        name: s.name,
        customize: !!s.isCustom,
        skillParentId: String(s.pathId ?? -1)
      }))
      saveData.skillTagsTranslation = skillItems.map(s => s.name).join(",")
      saveData.skillTagStandard = skillItems.filter(s => !s.isCustom).map(s => String(s.id)).join(",")
      saveData.skillTagCustomized = skillItems.filter(s => s.isCustom).map(s => s.name).join(",")
      saveData.preferenceQuestionAndAnswer = JSON.stringify(
        skillItems.map(s => ({ id: Number(s.id), pathId: Number(s.pathId ?? -1) }))
      )
      saveData.skillTags = JSON.stringify(
        skillItems.map(s => ({
          intKey: Number(s.id),
          standard: !s.isCustom,
          strKey: String(s.id),
          tagValue: s.name,
        }))
      )
      // 清理临时字段
      delete saveData._startYear
      delete saveData._startMonth
      delete saveData._endYear
      delete saveData._endMonth
      delete saveData._toPresent
      delete saveData._industrySelected
      delete saveData._skillItems

      if (editingIdx !== null) {
        await handleUpdateItem("workExperience", editingIdx, saveData)
      } else {
        await handleAddItem("workExperience", saveData)
      }
      cancelEdit()
    }

    return (
      <SectionCard>
        <SectionHeader
          title="工作／实习经历"
          changed={changedModuleKeys.has("work_experience")}
          required
          onAdd={() => handleStartEditWork({
            companyName: "", jobTitle: "", wnewIndustry: "", wnewIndustryTranslation: "",
            wnewJobSubType: "", wnewJobSubTypeTranslation: "",
            startDate: 0, endDate: 0, startDateFormat: "", endDateFormat: "",
            workDesc: "", salary: "", internshipWork: "2", skillTagsTranslation: "",
          })}
        />
        {items.map((item, idx) => (
          <div key={idx} className="mb-4 pb-4 border-b border-gray-100 last:border-0 last:mb-0 last:pb-0">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-900">{item.companyName}</span>
                {item.internshipWork === "1" && <span className="px-1.5 py-0.5 text-[10px] font-medium text-orange-600 bg-orange-50 border border-orange-200 rounded">实习</span>}
                <span className="text-xs text-gray-400">{formatPeriod(item.startDate, item.endDate)}</span>
              </div>
              <div className="flex gap-2">
                <button className="text-xs cursor-pointer" style={{ color: PRIMARY }} onClick={() => handleStartEditWork(item, idx)}>编辑</button>
                <button
                  className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  onClick={() => setDeleteTarget({
                    fieldName: "workExperience",
                    index: idx,
                    title: `确认删除工作经历「${item.companyName || item.jobTitle || '工作经历'}」？`,
                    description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。"
                  })}
                >
                  删除
                </button>
              </div>
            </div>
            <div className="text-sm font-medium text-gray-800 mt-1">{item.jobTitle || item.wnewJobSubTypeTranslation}</div>
            <div className="text-xs text-gray-500 mt-1">
              职位类别：{item.wnewJobSubTypeTranslation || item.jobTitle} | 所属行业：{item.wnewIndustryTranslation}
            </div>
            {item.skillTagsTranslation && (
              <div className="text-xs text-gray-500 mt-1">拥有技能：{item.skillTagsTranslation}</div>
            )}
            {item.workDesc && (
              <div className="text-sm text-gray-600 mt-2 whitespace-pre-wrap line-clamp-4">{item.workDesc}</div>
            )}
          </div>
        ))}
        {isEditing && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => { setWorkExpError(""); cancelEdit() }} />
            <div className="relative bg-white rounded-xl shadow-2xl w-[560px] max-h-[85vh] flex flex-col">
              <div className="px-6 pt-5 pb-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-base font-medium text-gray-900">{editingIdx !== null ? "编辑工作经历" : "添加工作经历"}</h3>
                <button type="button" onClick={() => { setWorkExpError(""); cancelEdit() }} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
              </div>
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                <FormRow label="公司名称" required>
                  <Input value={editForm.companyName || ""} onChange={e => setEditForm({ ...editForm, companyName: e.target.value })} placeholder="请输入公司名称" />
                </FormRow>
                <FormRow label="所属行业" required>
                  <IndustrySelect
                    showUnlimited={false}
                    maxSelect={1}
                    selected={editForm._industrySelected || []}
                    onChange={(items) => {
                      const sel = items.length > 0 ? items[items.length - 1] : null
                      setEditForm({
                        ...editForm,
                        _industrySelected: sel ? [sel] : [],
                        wnewIndustry: sel?.code || "",
                        wnewIndustryTranslation: sel?.name || "",
                      })
                    }}
                  />
                </FormRow>
                <FormRow label="职位类别" required>
                  <JobCategoryCascader
                    data={ZHILIAN_WORK_JOB_TITLES}
                    value={editForm.wnewJobSubType || ""}
                    onChange={(code, name) => setEditForm({
                      ...editForm,
                      wnewJobSubType: code,
                      wnewJobSubTypeTranslation: name,
                      jobTitle: editForm.jobTitle?.trim() ? editForm.jobTitle : name
                    })}
                  />
                </FormRow>
                <FormRow label="职位名称">
                  <Input
                    value={editForm.jobTitle || ""}
                    onChange={e => setEditForm({ ...editForm, jobTitle: e.target.value })}
                    placeholder="请输入自定义职位名称（如：独立 AI 应用开发者 / 全栈研发）"
                  />
                </FormRow>
                <FormRow label="拥有技能">
                  <SkillSelect
                    jobTypeId={editForm.wnewJobSubType || ""}
                    value={editForm._skillItems || []}
                    onChange={(items) => setEditForm({ ...editForm, _skillItems: items })}
                  />
                </FormRow>
                <FormRow label="在职时间" required>
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="w-[140px]">
                      <YearMonthPicker
                        year={editForm._startYear || ""}
                        month={editForm._startMonth || ""}
                        onYearChange={y => setEditForm((prev: any) => ({ ...prev, _startYear: y }))}
                        onMonthChange={m => setEditForm((prev: any) => ({ ...prev, _startMonth: m }))}
                      />
                    </div>
                    <span className="text-gray-400">-</span>
                    <div className="w-[140px]">
                      <YearMonthPicker
                        year={editForm._endYear || ""}
                        month={editForm._endMonth || ""}
                        onYearChange={y => setEditForm((prev: any) => ({ ...prev, _endYear: y }))}
                        onMonthChange={m => setEditForm((prev: any) => ({ ...prev, _endMonth: m }))}
                        disabled={!!editForm._toPresent}
                        minYear={editForm._startYear || undefined}
                        minMonth={editForm._startMonth || undefined}
                      />
                    </div>
                    <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!!editForm._toPresent}
                        onChange={e => setEditForm({ ...editForm, _toPresent: e.target.checked, _endYear: "", _endMonth: "" })}
                      />
                      至今
                    </label>
                  </div>
                </FormRow>
                <FormRow label="当前月薪">
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      inputMode="numeric"
                      className="flex-1 h-9 px-3 text-sm border border-gray-300 rounded-md focus:outline-none focus:border-[#2A7BFF]"
                      value={editForm.realSalary || ""}
                      onChange={e => {
                        const v = e.target.value.replace(/[^\d]/g, "")
                        setEditForm({ ...editForm, realSalary: v })
                      }}
                      placeholder="请输入当前薪资（选填）"
                    />
                    <span className="flex-shrink-0 h-9 px-3 flex items-center text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded-md">元</span>
                  </div>
                </FormRow>
                <FormRow label="工作描述" required>
                  <Textarea
                    value={editForm.workDesc || ""}
                    onChange={e => setEditForm({ ...editForm, workDesc: e.target.value })}
                    placeholder={"请输入工作内容：如：\n1. 主要负责绩效考评相关工作\n2. 完成招聘绩效考核获得优秀评级"}
                    rows={6}
                  />
                  <div className={`text-xs text-right mt-1 ${(editForm.workDesc || "").length > 3000 ? "text-red-500 font-semibold" : "text-gray-400"}`}>
                    {(editForm.workDesc || "").length > 3000
                      ? `⚠️ 已超出 ${(editForm.workDesc || "").length - 3000} 个字（上限 3000 字，超限无法保存/回写）`
                      : `还可输入 ${3000 - (editForm.workDesc || "").length} 个字`}
                  </div>
                </FormRow>
                <FormRow label="">
                  <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
                    <input type="checkbox" checked={editForm.internshipWork === "1"} onChange={e => setEditForm({ ...editForm, internshipWork: e.target.checked ? "1" : "2" })} />
                    本经历是实习经历
                  </label>
                </FormRow>
                <DynamicFieldSlot
                  data={editForm}
                  excludeKeys={[
                    "companyName", "jobTitle", "title", "wnewIndustry", "industrySerial", "industry", "newIndustry",
                    "wnewJobSubType", "jobTypeSerial", "jobSubType", "jobType", "newJobSubType", "newJobType", "jobTypeId",
                    "startDate", "endDate", "startDateFormat", "endDateFormat",
                    "_startYear", "_startMonth", "_endYear", "_endMonth", "_toPresent",
                    "realSalary", "salary", "salaryId", "salaryConfidentiality", "salaryTimes", "salaryTranslation",
                    "workDesc", "internshipWork", "workJobNature", "dailyWage", "durationInMonths", "index",
                    "skillTags", "skillTagList", "preferenceQuestionAndAnswer", "questionsAndAnswers", "workQuestionsAndAnswersList",
                    "skillTagStandard", "skillTagCustomized", "skillTagsTranslation",
                    "companyNature", "companyNatureTranslation", "companySize", "companySizeTranslation",
                    "companyId", "newCompanyId", "kgId", "isHiddenForB",
                    "workIsReferences", "workRefCompany", "workRefContact", "workRefName", "workRefPosition", "workRefRelation",
                    "workYear", "workdays", "path", "id", "department"
                  ]}
                  onChange={(k, v) => setEditForm((prev: any) => ({ ...prev, [k]: v }))}
                  title="工作经历 · 动态扩展字段"
                />
                {workExpError && <div className="text-xs text-red-500">{workExpError}</div>}
              </div>
              <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
                <button type="button" onClick={() => { setWorkExpError(""); cancelEdit() }} className="px-4 py-1.5 text-sm text-gray-600 hover:text-gray-800">取消</button>
                <button type="button" onClick={handleSaveWork} disabled={saving} className="px-5 py-1.5 text-sm text-white rounded-md disabled:opacity-50" style={{ backgroundColor: PRIMARY }}>
                  {saving ? "保存中..." : "保存并更新"}
                </button>
              </div>
            </div>
          </div>
        )}
      </SectionCard>
    )
}
