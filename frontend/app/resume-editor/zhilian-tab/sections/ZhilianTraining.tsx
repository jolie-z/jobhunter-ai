/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { PRIMARY, SectionCard, SectionHeader, FormRow, formatPeriod } from "../constants"
import { YearMonthPicker } from "../pickers"
import { Input } from "@/components/ui/input"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"

import { useZhilianCtx } from "../context"

export function ZhilianTraining() {
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
    trainingError,
    setTrainingError,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "training"
    const items = localData.training || []

    const parseDate = (fmt: string): { year: string; month: string } => {
      if (!fmt) return { year: "", month: "" }
      const parts = fmt.split("/")
      return { year: parts[0] || "", month: String(Number(parts[1] || "0")) }
    }

    const handleStartEditTraining = (item: any, idx?: number) => {
      setTrainingError("")
      const start = parseDate(item.trainStartDateFormat || "")
      const end = parseDate(item.trainEndDateFormat || "")
      const toPresent = !item.trainEndDate || item.trainEndDate === 0
      startEdit("training", {
        trainName: "", trainCourse: "",
        trainStartDate: 0, trainEndDate: 0, trainStartDateFormat: "", trainEndDateFormat: "",
        ...item,
        _startYear: start.year,
        _startMonth: start.month,
        _endYear: toPresent ? "" : end.year,
        _endMonth: toPresent ? "" : end.month,
        _toPresent: toPresent,
      }, idx)
    }

    const handleSaveTraining = async () => {
      if (!editForm._startYear || !editForm._startMonth) { setTrainingError("请选择培训开始时间"); return }
      if (!editForm._toPresent && (!editForm._endYear || !editForm._endMonth)) { setTrainingError("请选择培训结束时间"); return }
      if (!editForm.trainName?.trim()) { setTrainingError("请输入培训机构"); return }
      if (!editForm.trainCourse?.trim()) { setTrainingError("请输入培训课程"); return }
      setTrainingError("")

      const startDate = new Date(Number(editForm._startYear), Number(editForm._startMonth) - 1, 1).getTime()
      const endDate = editForm._toPresent ? 0 : new Date(Number(editForm._endYear), Number(editForm._endMonth) - 1, 1).getTime()
      const agency = editForm.trainAgency || editForm.trainName || ""
      const course = editForm.trainCourse || editForm.trainCertName || ""
      const saveData: any = {
        ...editForm,
        trainAgency: agency,
        trainName: agency,
        trainCourse: course,
        trainStartDate: startDate,
        trainEndDate: endDate,
        trainStartDateFormat: `${editForm._startYear}/${String(editForm._startMonth).padStart(2, "0")}/01 00:00:00`,
        trainEndDateFormat: editForm._toPresent ? "" : `${editForm._endYear}/${String(editForm._endMonth).padStart(2, "0")}/01 00:00:00`,
      }
      delete saveData._startYear
      delete saveData._startMonth
      delete saveData._endYear
      delete saveData._endMonth
      delete saveData._toPresent

      if (editingIdx !== null) {
        await handleUpdateItem("training", editingIdx, saveData)
      } else {
        await handleAddItem("training", saveData)
      }
      cancelEdit()
    }

    return (
      <SectionCard>
        <SectionHeader
          title="培训经历"
          changed={changedModuleKeys.has("training")}
          onAdd={() => handleStartEditTraining({})}
        />
        {items.length === 0 && !isEditing && <div className="text-sm text-gray-400">暂无培训经历</div>}
        {items.map((item, idx) => (
          <div key={idx} className="mb-3 pb-3 border-b border-gray-100 last:border-0 last:mb-0 last:pb-0">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-900">{item.trainName || `培训 ${idx + 1}`}</span>
                <span className="text-xs text-gray-400">{formatPeriod(item.trainStartDate || 0, item.trainEndDate || 0)}</span>
              </div>
              <div className="flex gap-2">
                <button className="text-xs cursor-pointer" style={{ color: PRIMARY }} onClick={() => handleStartEditTraining(item, idx)}>编辑</button>
                <button
                  className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  onClick={() => setDeleteTarget({
                    fieldName: "training",
                    index: idx,
                    title: `确认删除培训经历「${item.trainName || item.trainCourse || '培训经历'}」？`,
                    description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。"
                  })}
                >
                  删除
                </button>
              </div>
            </div>
            {item.trainCourse && <div className="text-sm text-gray-600 mt-1">{item.trainCourse}</div>}
          </div>
        ))}
        {isEditing && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => { setTrainingError(""); cancelEdit() }} />
            <div className="relative bg-white rounded-xl shadow-2xl w-[560px] max-h-[85vh] flex flex-col">
              <div className="px-6 pt-5 pb-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-base font-medium text-gray-900">{editingIdx !== null ? "编辑培训经历" : "添加培训经历"}</h3>
                <button type="button" onClick={() => { setTrainingError(""); cancelEdit() }} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
              </div>
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                <FormRow label="培训时间" required>
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
                <FormRow label="培训机构" required>
                  <Input value={editForm.trainName || ""} onChange={e => setEditForm((prev: any) => ({ ...prev, trainName: e.target.value }))} placeholder="必填" />
                </FormRow>
                <FormRow label="培训课程" required>
                  <Input value={editForm.trainCourse || ""} onChange={e => setEditForm((prev: any) => ({ ...prev, trainCourse: e.target.value }))} placeholder="必填" />
                </FormRow>
                <DynamicFieldSlot
                  data={editForm}
                  excludeKeys={[
                    "trainName", "trainAgency", "trainCourse", "trainStartDate", "trainEndDate",
                    "trainStartDateFormat", "trainEndDateFormat",
                    "_startYear", "_startMonth", "_endYear", "_endMonth", "_toPresent",
                    "trainDesc", "trainCertificate", "trainAddress", "path", "id"
                  ]}
                  onChange={(k, v) => setEditForm((prev: any) => ({ ...prev, [k]: v }))}
                  title="培训经历 · 动态扩展字段"
                />
                {trainingError && <div className="text-xs text-red-500">{trainingError}</div>}
              </div>
              <div className="px-6 py-4 border-t border-gray-100 flex items-center gap-3">
                <button type="button" onClick={handleSaveTraining} className="px-5 py-2 text-sm text-white rounded-full" style={{ backgroundColor: PRIMARY }}>保存并更新</button>
                <button type="button" onClick={() => { setTrainingError(""); cancelEdit() }} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
              </div>
            </div>
          </div>
        )}
      </SectionCard>
    )
}
