/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { PRIMARY, SectionCard, SectionHeader, FormRow, SimpleSelect, formatPeriod } from "../constants"
import { YearMonthPicker } from "../pickers"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"
import { cn } from "@/lib/utils"
import { ZHILIAN_EDUCATION } from "@/lib/zhilian-options"

import { useZhilianCtx } from "../context"

export function ZhilianEducation() {
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
    eduError,
    setEduError,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "education"
    const items = localData.education || []

    // 解析日期字符串为 {year, month}
    const parseDate = (fmt: string): { year: string; month: string } => {
      if (!fmt) return { year: "", month: "" }
      const parts = fmt.split("/")
      return { year: parts[0] || "", month: String(Number(parts[1] || "0")) }
    }

    // 初中及以下(9)/高中(7) 无二级详情表单
    const isSimpleEdu = (bg: string) => bg === "7" || bg === "9"
    // 本科(4)/硕士(3)/MBA(10)/博士(1) 显示学位证书
    const hasDegreeCert = (bg: string) => ["1", "3", "4", "10"].includes(bg)

    const handleStartEditEdu = (item: any, idx?: number) => {
      setEduError("")
      let start = parseDate(item.eduStartDateFormat || "")
      let end = parseDate(item.eduEndDateFormat || "")
      // 兜底：无格式字符串时从时间戳计算
      if (!start.year && item.eduStartDate) { const d = new Date(item.eduStartDate); start = { year: String(d.getFullYear()), month: String(d.getMonth() + 1) } }
      if (!end.year && item.eduEndDate) { const d = new Date(item.eduEndDate); end = { year: String(d.getFullYear()), month: String(d.getMonth() + 1) } }
      // API值转换：eduFullTime 'y'→'统招', 'n'→'非统招'; eduOverseaseExperience '2'→无, '1'/'y'→有
      const fullTimeVal = item.eduFullTime === "y" || item.eduFullTime === "统招" ? "统招" : (item.eduFullTime === "n" || item.eduFullTime === "非统招" ? "非统招" : "统招")
      const overseasVal = (item.eduOverseaseExperience === "1" || item.eduOverseaseExperience === "y") ? "y" : ""
      startEdit("education", {
        eduBackground: "12", eduBackgroundTranslation: "中专/中技",
        eduSchoolName: "", eduDepartment: "", eduMajorV: "",
        degreeCertificate: "1",
        ...item,
        eduFullTime: fullTimeVal,
        eduOverseaseExperience: overseasVal,
        _startYear: start.year,
        _startMonth: start.month,
        _endYear: end.year,
        _endMonth: end.month,
      }, idx)
    }

    const handleSaveEdu = async () => {
      const bg = editForm.eduBackground || ""
      if (!bg) { setEduError("请选择最高学历"); return }
      if (!isSimpleEdu(bg)) {
        if (!editForm.eduSchoolName?.trim()) { setEduError("请输入学校名称"); return }
        if (!editForm.eduMajorV?.trim()) { setEduError("请输入所学专业"); return }
        if (!editForm._startYear || !editForm._startMonth) { setEduError("请选择入学时间"); return }
        if (!editForm._endYear || !editForm._endMonth) { setEduError("请选择毕业时间"); return }
      }
      setEduError("")

      const found = ZHILIAN_EDUCATION.find(o => o.code === bg)
      const saveData: any = {
        ...editForm,
        eduBackgroundTranslation: found?.label || editForm.eduBackgroundTranslation || "",
        eduOverseaseExperience: editForm.eduOverseaseExperience ? "y" : "",
      }
      if (!isSimpleEdu(bg)) {
        const startDate = new Date(Number(editForm._startYear), Number(editForm._startMonth) - 1, 1).getTime()
        const endDate = new Date(Number(editForm._endYear), Number(editForm._endMonth) - 1, 1).getTime()
        saveData.eduStartDate = startDate
        saveData.eduEndDate = endDate
        saveData.eduStartDateFormat = `${editForm._startYear}/${String(editForm._startMonth).padStart(2, "0")}/01 00:00:00`
        saveData.eduEndDateFormat = `${editForm._endYear}/${String(editForm._endMonth).padStart(2, "0")}/01 00:00:00`
      } else {
        saveData.eduStartDate = 0
        saveData.eduEndDate = 0
        saveData.eduStartDateFormat = ""
        saveData.eduEndDateFormat = ""
        saveData.eduSchoolName = ""
        saveData.eduMajorV = ""
        saveData.eduDepartment = ""
      }
      delete saveData._startYear
      delete saveData._startMonth
      delete saveData._endYear
      delete saveData._endMonth

      if (editingIdx !== null) {
        await handleUpdateItem("education", editingIdx, saveData)
      } else {
        await handleAddItem("education", saveData)
      }
      cancelEdit()
    }

    const showDetail = isEditing && !isSimpleEdu(editForm.eduBackground || "")
    const showDegree = isEditing && hasDegreeCert(editForm.eduBackground || "")

    return (
      <SectionCard>
        <SectionHeader
          title="教育经历"
          changed={changedModuleKeys.has("education")}
          required
          onAdd={() => handleStartEditEdu({})}
        />
        {items.map((item, idx) => (
          <div key={idx} className="mb-3 pb-3 border-b border-gray-100 last:border-0 last:mb-0 last:pb-0">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-900">{item.eduSchoolName || item.eduBackgroundTranslation}</span>
                <Badge variant="outline" className="text-xs">{item.eduBackgroundTranslation}</Badge>
              </div>
              <div className="flex gap-2">
                <button className="text-xs cursor-pointer" style={{ color: PRIMARY }} onClick={() => handleStartEditEdu(item, idx)}>编辑</button>
                <button
                  className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  onClick={() => setDeleteTarget({
                    fieldName: "education",
                    index: idx,
                    title: `确认删除教育经历「${item.eduSchoolName || item.eduBackgroundTranslation || '教育经历'}」？`,
                    description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。"
                  })}
                >
                  删除
                </button>
              </div>
            </div>
            {(item.eduDepartment || item.eduMajorV) && (
              <div className="text-sm text-gray-600 mt-1">{[item.eduBackgroundTranslation, item.eduMajorV].filter(Boolean).join(" | ")}</div>
            )}
            {(item.eduStartDate || item.eduEndDate) ? (
              <div className="text-xs text-gray-400 mt-1">{formatPeriod(item.eduStartDate, item.eduEndDate)}</div>
            ) : null}
          </div>
        ))}
        {isEditing && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => { setEduError(""); cancelEdit() }} />
            <div className="relative bg-white rounded-xl shadow-2xl w-[560px] max-h-[85vh] flex flex-col">
              <div className="px-6 pt-5 pb-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-base font-medium text-gray-900">{editingIdx !== null ? "编辑教育经历" : "添加教育经历"}</h3>
                <button type="button" onClick={() => { setEduError(""); cancelEdit() }} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
              </div>
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                <div className="text-xs text-[#FF8800]">请填写国家承认的教育经历，非培训经历</div>
                {showDetail && (
                  <FormRow label="学校名称" required>
                    <Input value={editForm.eduSchoolName || ""} onChange={e => setEditForm((prev: any) => ({ ...prev, eduSchoolName: e.target.value }))} placeholder="请输入学校名称" />
                  </FormRow>
                )}
                <FormRow label="最高学历" required>
                  <SimpleSelect options={ZHILIAN_EDUCATION} value={editForm.eduBackground || ""} onChange={v => {
                    const f = ZHILIAN_EDUCATION.find(o => o.code === v)
                    setEditForm((prev: any) => ({ ...prev, eduBackground: v, eduBackgroundTranslation: f?.label || "" }))
                  }} />
                </FormRow>
                {showDetail && (
                  <>
                    <FormRow label="是否统招" required>
                      <div className="flex gap-2">
                        {[{ v: "统招", label: "统招" }, { v: "非统招", label: "非统招" }].map(opt => (
                          <button
                            key={opt.v}
                            type="button"
                            onClick={() => setEditForm((prev: any) => ({ ...prev, eduFullTime: opt.v }))}
                            className={cn(
                              "px-5 h-9 text-sm rounded-md border transition-colors relative",
                              editForm.eduFullTime === opt.v ? "text-white border-transparent" : "bg-white border-gray-300 text-gray-600 hover:border-gray-400"
                            )}
                            style={editForm.eduFullTime === opt.v ? { backgroundColor: PRIMARY } : {}}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </FormRow>
                    {showDegree && (
                      <FormRow label="学位证书" required>
                        <div className="flex gap-2">
                          {[{ v: "1", label: "有" }, { v: "0", label: "无" }].map(opt => (
                            <button
                              key={opt.v}
                              type="button"
                              onClick={() => setEditForm((prev: any) => ({ ...prev, degreeCertificate: opt.v }))}
                              className={cn(
                                "px-5 h-9 text-sm rounded-md border transition-colors",
                                editForm.degreeCertificate === opt.v ? "text-white border-transparent" : "bg-white border-gray-300 text-gray-600 hover:border-gray-400"
                              )}
                              style={editForm.degreeCertificate === opt.v ? { backgroundColor: PRIMARY } : {}}
                            >
                              {opt.label}
                            </button>
                          ))}
                        </div>
                      </FormRow>
                    )}
                    <FormRow label="所学专业" required>
                      <Input value={editForm.eduMajorV || ""} onChange={e => setEditForm((prev: any) => ({ ...prev, eduMajorV: e.target.value }))} placeholder="请输入专业名称" />
                    </FormRow>
                    <FormRow label="在校时间" required>
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
                            minYear={editForm._startYear || undefined}
                            minMonth={editForm._startMonth || undefined}
                          />
                        </div>
                      </div>
                    </FormRow>
                  </>
                )}
                <FormRow label="海外学习经历">
                  <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer h-9">
                    <input
                      type="checkbox"
                      checked={!!editForm.eduOverseaseExperience}
                      onChange={e => setEditForm((prev: any) => ({ ...prev, eduOverseaseExperience: e.target.checked ? "y" : "" }))}
                    />
                    海外学习经历
                  </label>
                </FormRow>
                <DynamicFieldSlot
                  data={editForm}
                  excludeKeys={[
                    "eduSchoolName", "newEduSchoolId", "eduBackground", "eduBackgroundTranslation", "eduMajorV",
                    "newEduMajorSmallType", "eduStartDateFormat", "eduEndDateFormat", "eduStartDate", "eduEndDate",
                    "_startYear", "_startMonth", "_endYear", "_endMonth", "_toPresent",
                    "eduFullTime", "eduOverseaseExperience", "degreeCertificate", "path", "id", "eduDepartment",
                    "academicCertificateNumber", "academicCertificateVerifyState", "eduCampusFullTime", "eduDegree",
                    "eduMajorSmallType", "eduMajorT", "newEduMajorT", "eduMinorName", "eduOverseaseExperienceYear",
                    "eduRank", "eduResearchArea", "eduSchoolCode", "eduSpecializedCourses",
                    "majorKgId", "schoolNameKgId", "schoolLogo", "schoolTag"
                  ]}
                  onChange={(k, v) => setEditForm((prev: any) => ({ ...prev, [k]: v }))}
                  title="教育经历 · 动态扩展字段"
                />
                {eduError && <div className="text-xs text-red-500">{eduError}</div>}
              </div>
              <div className="px-6 py-4 border-t border-gray-100 flex items-center gap-3">
                <button type="button" onClick={handleSaveEdu} className="px-5 py-2 text-sm text-white rounded-full" style={{ backgroundColor: PRIMARY }}>保存并更新</button>
                <button type="button" onClick={() => { setEduError(""); cancelEdit() }} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
              </div>
            </div>
          </div>
        )}
      </SectionCard>
    )
}
