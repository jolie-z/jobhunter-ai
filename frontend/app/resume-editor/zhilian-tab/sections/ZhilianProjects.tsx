/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { PRIMARY, SectionCard, SectionHeader, FormRow, formatPeriod } from "../constants"
import { YearMonthPicker } from "../pickers"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"

import { useZhilianCtx } from "../context"

export function ZhilianProjects() {
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
    projectError,
    setProjectError,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "project"
    const items = localData.project || []

    const parseDate = (fmt: string): { year: string; month: string } => {
      if (!fmt) return { year: "", month: "" }
      const parts = fmt.split("/")
      return { year: parts[0] || "", month: String(Number(parts[1] || "0")) }
    }

    const handleStartEditProject = (item: any, idx?: number) => {
      setProjectError("")
      let start = parseDate(item.proExpStartDateFormat || "")
      let end = parseDate(item.proExpEndDateFormat || "")
      // 兜底：无格式字符串时从时间戳计算
      if (!start.year && item.proExpStartDate) { const d = new Date(item.proExpStartDate); start = { year: String(d.getFullYear()), month: String(d.getMonth() + 1) } }
      if (!end.year && item.proExpEndDate) { const d = new Date(item.proExpEndDate); end = { year: String(d.getFullYear()), month: String(d.getMonth() + 1) } }
      const toPresent = !item.proExpEndDate || item.proExpEndDate === 0 || item.proExpIsCurrent === "true" || item.proExpIsCurrent === true
      startEdit("project", {
        proExpProjectName: "", proExpProjectDesc: "",
        proExpStartDate: 0, proExpEndDate: 0, proExpStartDateFormat: "", proExpEndDateFormat: "",
        ...item,
        _startYear: start.year,
        _startMonth: start.month,
        _endYear: toPresent ? "" : end.year,
        _endMonth: toPresent ? "" : end.month,
        _toPresent: toPresent,
      }, idx)
    }

    const handleSaveProject = async () => {
      if (!editForm.proExpProjectName?.trim()) { setProjectError("请输入项目名称"); return }
      if (!editForm._startYear || !editForm._startMonth) { setProjectError("请选择项目开始时间"); return }
      if (!editForm._toPresent && (!editForm._endYear || !editForm._endMonth)) { setProjectError("请选择项目结束时间"); return }
      if (!editForm.proExpProjectDesc?.trim()) { setProjectError("请输入项目描述"); return }
      if ((editForm.proExpProjectDesc || "").length > 2000) {
        setProjectError(`项目描述已超出上限 ${(editForm.proExpProjectDesc || "").length - 2000} 字（当前 ${(editForm.proExpProjectDesc || "").length} / 2000 字），请删减精简至 2000 字以内后再保存`)
        return
      }
      if ((editForm.proExpProjectDuty || "").length > 2000) {
        setProjectError(`项目职责已超出上限 ${(editForm.proExpProjectDuty || "").length - 2000} 字（当前 ${(editForm.proExpProjectDuty || "").length} / 2000 字），请删减精简至 2000 字以内后再保存`)
        return
      }
      setProjectError("")

      const toPresent = Boolean(editForm._toPresent)
      const startDate = new Date(Number(editForm._startYear), Number(editForm._startMonth) - 1, 1).getTime()
      const endDate = toPresent ? 0 : new Date(Number(editForm._endYear), Number(editForm._endMonth) - 1, 1).getTime()
      const saveData: any = {
        ...editForm,
        proExpStartDate: startDate,
        proExpEndDate: endDate,
        proExpStartDateFormat: `${editForm._startYear}/${String(editForm._startMonth).padStart(2, "0")}/01 00:00:00`,
        proExpEndDateFormat: toPresent ? "" : `${editForm._endYear}/${String(editForm._endMonth).padStart(2, "0")}/01 00:00:00`,
        proExpIsCurrent: toPresent ? "true" : "false",
      }
      delete saveData._startYear
      delete saveData._startMonth
      delete saveData._endYear
      delete saveData._endMonth
      delete saveData._toPresent

      if (editingIdx !== null) {
        await handleUpdateItem("project", editingIdx, saveData)
      } else {
        await handleAddItem("project", saveData)
      }
      cancelEdit()
    }

    const descLen = (editForm.proExpProjectDesc || "").length

    return (
      <SectionCard>
        <SectionHeader
          title="项目经历"
          changed={changedModuleKeys.has("projects")}
          onAdd={() => handleStartEditProject({})}
        />
        {items.map((item, idx) => (
          <div key={idx} className="mb-3 pb-3 border-b border-gray-100 last:border-0 last:mb-0 last:pb-0">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-900">{item.proExpProjectName}</span>
                <span className="text-xs text-gray-400">{formatPeriod(item.proExpStartDate, item.proExpEndDate, item.proExpIsCurrent)}</span>
              </div>
              <div className="flex gap-2">
                <button className="text-xs cursor-pointer" style={{ color: PRIMARY }} onClick={() => handleStartEditProject(item, idx)}>编辑</button>
                <button
                  className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  onClick={() => setDeleteTarget({
                    fieldName: "project",
                    index: idx,
                    title: `确认删除项目经历「${item.proExpProjectName || '项目经历'}」？`,
                    description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。"
                  })}
                >
                  删除
                </button>
              </div>
            </div>
            {item.proExpProjectDesc && <div className="text-sm text-gray-600 mt-1 whitespace-pre-wrap line-clamp-3">{item.proExpProjectDesc}</div>}
          </div>
        ))}
        {isEditing && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => { setProjectError(""); cancelEdit() }} />
            <div className="relative bg-white rounded-xl shadow-2xl w-[560px] max-h-[85vh] flex flex-col">
              <div className="px-6 pt-5 pb-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-base font-medium text-gray-900">{editingIdx !== null ? "编辑项目经历" : "添加项目经历"}</h3>
                <button type="button" onClick={() => { setProjectError(""); cancelEdit() }} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
              </div>
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                <FormRow label="项目名称" required>
                  <Input value={editForm.proExpProjectName || ""} onChange={e => setEditForm((prev: any) => ({ ...prev, proExpProjectName: e.target.value }))} placeholder="必填" />
                </FormRow>
                <FormRow label="项目时间" required>
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
                        onChange={e => setEditForm((prev: any) => ({ ...prev, _toPresent: e.target.checked, _endYear: "", _endMonth: "" }))}
                      />
                      至今
                    </label>
                  </div>
                </FormRow>
                <FormRow label="项目描述" required>
                  <div>
                    <Textarea
                      value={editForm.proExpProjectDesc || ""}
                      onChange={e => setEditForm((prev: any) => ({ ...prev, proExpProjectDesc: e.target.value }))}
                      placeholder="更完善的项目信息有助于HR快速找到你，为保护个人隐私，请不要填写手机号、QQ、微信等联系方式"
                      rows={5}
                    />
                    <div className="flex items-center justify-between mt-1">
                      <span className="text-xs text-gray-400">填写文字在100个字以上评定等级，少于不计算，内容越详细，等级越高</span>
                      <span className={`text-xs ${descLen > 2000 ? "text-red-500 font-semibold" : "text-gray-400"}`}>
                        {descLen > 2000
                          ? `⚠️ 已超出 ${descLen - 2000} 个字（上限 2000 字，超限无法保存/回写）`
                          : `还可输入 ${2000 - descLen} 个字`}
                      </span>
                    </div>
                  </div>
                </FormRow>
                <DynamicFieldSlot
                  data={editForm}
                  excludeKeys={[
                    "proExpProjectName", "proExpPosition", "proExpStartDate", "proExpEndDate",
                    "proExpStartDateFormat", "proExpEndDateFormat",
                    "_startYear", "_startMonth", "_endYear", "_endMonth", "_toPresent",
                    "proExpProjectDuty", "proExpProjectDesc", "affiliatedCompany",
                    "proExpDevTool", "proExpHardwareEnv", "proExpSoftwareEnv",
                    "proExpIsIt", "proExpIsCurrent", "path", "id"
                  ]}
                  onChange={(k, v) => setEditForm((prev: any) => ({ ...prev, [k]: v }))}
                  title="项目经历 · 动态扩展字段"
                />
                {projectError && <div className="text-xs text-red-500">{projectError}</div>}
              </div>
              <div className="px-6 py-4 border-t border-gray-100 flex items-center gap-3">
                <button type="button" onClick={handleSaveProject} className="px-5 py-2 text-sm text-white rounded-full" style={{ backgroundColor: PRIMARY }}>保存并更新</button>
                <button type="button" onClick={() => { setProjectError(""); cancelEdit() }} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
              </div>
            </div>
          </div>
        )}
      </SectionCard>
    )
}
