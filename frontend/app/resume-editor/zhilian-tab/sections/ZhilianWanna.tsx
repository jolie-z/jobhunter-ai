/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { PRIMARY, SectionCard, SectionHeader, FormRow, InlineEditActions, RadioGroup, SimpleSelect } from "../constants"
import { CityCascader } from "../pickers"
import { JobCategoryCascader, IndustrySelect } from "../../zhilian-work-selectors"
import { ZHILIAN_CITIES_FULL, ZHILIAN_EMPLOYMENT_TYPE, ZHILIAN_SALARY_MIN, ZHILIAN_SALARY_MAX } from "@/lib/zhilian-options"

import { useZhilianCtx } from "../context"

export function ZhilianWanna() {
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
    wannaError,
    setWannaError,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "wanna"
    const items = Array.isArray(localData.wanna) ? localData.wanna : (localData.wanna ? [localData.wanna] : [])

    // 根据城市code反查省份名
    const findProvinceByCityCode = (cityCode: string): string => {
      for (const prov of ZHILIAN_CITIES_FULL) {
        if (prov.cities.some(c => c.code === cityCode)) return prov.name
      }
      return ""
    }

    // 从已有item解析行业列表
    const parseIndustries = (item: any): { code: string; name: string }[] => {
      if (item.selectedIndustries && Array.isArray(item.selectedIndustries)) return item.selectedIndustries
      if (item.preferredIndustrySerialList && Array.isArray(item.preferredIndustrySerialList)) {
        // 智联API用 -99 表示"不限行业"，前端用 -1
        const hasUnlimited = item.preferredIndustrySerialList.some((s: any) => s.code === "-99")
        if (hasUnlimited) return [{ code: "-1", name: "不限" }]
        const names = (item.pnewPreferredIndustryTranslation || "").split(/[、,，]/)
        return item.preferredIndustrySerialList
          .map((s: any, i: number) => ({ code: s.code, name: names[i] || s.code }))
      }
      if (item.pnewPreferredIndustry === "-99") {
        return [{ code: "-1", name: "不限" }]
      }
      if (item.pnewPreferredIndustry) {
        return [{ code: item.pnewPreferredIndustry, name: item.pnewPreferredIndustryTranslation || "" }]
      }
      return []
    }

    const handleStartEditWanna = (item: any, idx?: number) => {
      setWannaError("")
      startEdit("wanna", {
        ...item,
        selectedIndustries: parseIndustries(item),
      }, idx)
    }

    const handleSaveWanna = async () => {
      // 必填校验
      if (!editForm.preferredJobNature) { setWannaError("请选择工作性质"); return }
      if (!editForm.pnewPreferredJobType) { setWannaError("请选择期望职位"); return }
      if (!editForm.selectedIndustries || editForm.selectedIndustries.length === 0) { setWannaError("请选择期望行业"); return }
      if (!editForm.preferredLocation) { setWannaError("请选择期望城市"); return }
      if (!editForm.preferredSalaryMin && editForm.preferredSalaryMin !== 0) { setWannaError("请选择最低薪资"); return }
      if (!editForm.preferredSalaryMax) { setWannaError("请选择最高薪资"); return }
      if (Number(editForm.preferredSalaryMax) <= Number(editForm.preferredSalaryMin)) { setWannaError("最高薪资必须大于最低薪资"); return }
      setWannaError("")

      // 组装保存数据
      const industries = editForm.selectedIndustries as { code: string; name: string }[]
      const salaryMinLabel = ZHILIAN_SALARY_MIN.find(o => o.code === String(editForm.preferredSalaryMin))?.label || ""
      const salaryMaxLabel = ZHILIAN_SALARY_MIN.find(o => o.code === String(editForm.preferredSalaryMax))?.label || ""
      const saveData = {
        ...editForm,
        pnewPreferredIndustry: industries.map(i => i.code).join(","),
        pnewPreferredIndustryTranslation: industries.map(i => i.name).join("、"),
        preferredIndustrySerialList: industries.map(i => ({ code: i.code, serial: "" })),
        preferredSalaryTranslation: `${salaryMinLabel}-${salaryMaxLabel}`,
        preferredSalary: `${editForm.preferredSalaryMin}${editForm.preferredSalaryMax}`,
      }
      delete saveData.selectedIndustries

      if (editingIdx !== null) {
        await handleUpdateItem("wanna", editingIdx, saveData)
      } else {
        await handleAddItem("wanna", saveData)
      }
      cancelEdit()
    }

    return (
      <SectionCard>
        <SectionHeader
          title="求职意向"
          changed={changedModuleKeys.has("wanna")}
          onAdd={items.length < 3 ? () => handleStartEditWanna({
            preferredJobNature: "2", preferredJobNatureTranslation: "全职",
            pnewPreferredJobType: "", pnewPreferredJobTypeTranslation: "",
            selectedIndustries: [],
            pnewPreferredIndustry: "", pnewPreferredIndustryTranslation: "",
            preferredLocation: "", preferredLocationTranslation: "",
            preferredCityDistrict: "", preferredCityDistrictTranslation: "",
            preferredSalaryMin: 0, preferredSalaryMax: 0,
          }) : undefined}
        />
        {items.map((item, idx) => (
          <div key={idx} className="mb-3 pb-3 border-b border-gray-100 last:border-0 last:mb-0 last:pb-0">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-gray-900">{item.pnewPreferredJobTypeTranslation || item.title || "未设置"}</div>
                <div className="text-xs text-gray-500 mt-1 flex flex-wrap gap-x-3">
                  <span>{item.preferredJobNatureTranslation}</span>
                  <span>{item.preferredLocationTranslation}{item.preferredCityDistrictTranslation && item.preferredCityDistrictTranslation !== item.preferredLocationTranslation ? `-${item.preferredCityDistrictTranslation}` : ""}</span>
                  <span>{item.pnewPreferredIndustryTranslation}</span>
                  {item.preferredSalaryTranslation && <span>{item.preferredSalaryTranslation}</span>}
                </div>
              </div>
              <div className="flex gap-2">
                <button className="text-xs cursor-pointer" style={{ color: PRIMARY }} onClick={() => handleStartEditWanna(item, idx)}>编辑</button>
                <button
                  className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  onClick={() => setDeleteTarget({
                    fieldName: "wanna",
                    index: idx,
                    title: `确认删除求职意向「${item.pnewPreferredJobTypeTranslation || item.title || '求职意向'}」？`,
                    description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。"
                  })}
                >
                  删除
                </button>
              </div>
            </div>
          </div>
        ))}
        {isEditing && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <FormRow label="工作性质" required>
              <RadioGroup options={ZHILIAN_EMPLOYMENT_TYPE} value={editForm.preferredJobNature} onChange={v => {
                const found = ZHILIAN_EMPLOYMENT_TYPE.find(o => o.code === v)
                setEditForm({ ...editForm, preferredJobNature: v, preferredJobNatureTranslation: found?.label || "" })
              }} />
            </FormRow>
            <FormRow label="期望职位" required>
              <JobCategoryCascader
                value={editForm.pnewPreferredJobType || ""}
                onChange={(code, name) => setEditForm({ ...editForm, pnewPreferredJobType: code, pnewPreferredJobTypeTranslation: name })}
              />
            </FormRow>
            <FormRow label="期望行业" required>
              <IndustrySelect
                selected={editForm.selectedIndustries || []}
                onChange={(items) => setEditForm({ ...editForm, selectedIndustries: items })}
              />
            </FormRow>
            <FormRow label="期望城市" required>
              <CityCascader
                province={editForm.preferredLocation ? findProvinceByCityCode(editForm.preferredLocation) : ""}
                city={editForm.preferredLocationTranslation || ""}
                district={editForm.preferredCityDistrictTranslation || ""}
                level={3}
                onChange={(prov, cityName, cityCode, distName, distCode) => {
                  setEditForm({
                    ...editForm,
                    preferredLocation: cityCode,
                    preferredLocationTranslation: cityName,
                    preferredCityDistrict: distCode || cityCode,
                    preferredCityDistrictTranslation: distName || cityName,
                  })
                }}
              />
            </FormRow>
            <FormRow label="薪资要求" required>
              <div className="flex items-center gap-2">
                <SimpleSelect options={ZHILIAN_SALARY_MIN} value={String(editForm.preferredSalaryMin || "")} onChange={v => setEditForm({ ...editForm, preferredSalaryMin: Number(v), preferredSalaryMax: 0 })} placeholder="最低薪资" />
                <span className="text-gray-400">-</span>
                <SimpleSelect options={ZHILIAN_SALARY_MAX[String(editForm.preferredSalaryMin || "0")] || []} value={String(editForm.preferredSalaryMax || "")} onChange={v => setEditForm({ ...editForm, preferredSalaryMax: Number(v) })} placeholder="最高薪资" />
              </div>
            </FormRow>
            {wannaError && <div className="text-xs text-red-500 mt-2">{wannaError}</div>}
            <InlineEditActions
              onCancel={() => { setWannaError(""); cancelEdit() }}
              saving={saving}
              onSave={handleSaveWanna}
            />
          </div>
        )}
      </SectionCard>
    )
}
