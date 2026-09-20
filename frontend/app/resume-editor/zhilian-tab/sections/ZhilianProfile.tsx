/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { PRIMARY, SectionCard, SectionHeader, FormRow, InlineEditActions, RadioGroup, SimpleSelect } from "../constants"
import { YearMonthPicker, CityCascader } from "../pickers"
import { Input } from "@/components/ui/input"
import { ZHILIAN_GENDER, ZHILIAN_JOB_SEEKER_IDENTITY, ZHILIAN_POLITICAL_STATUS, ZHILIAN_CITIES_FULL } from "@/lib/zhilian-options"

import { useZhilianCtx } from "../context"

export function ZhilianProfile() {
  const {
    localData,
    editingSection,
    editForm,
    setEditForm,
    profileError,
    setProfileError,
    changedModuleKeys,
    saving,
    startEdit,
    cancelEdit,
    persistData,
  } = useZhilianCtx()
  if (!localData) return null
    const p = localData.profile
    if (!p) return null
    const isEditing = editingSection === "profile"

    const validateProfile = (): boolean => {
      if (!editForm.name?.trim()) { setProfileError("请填写姓名"); return false }
      if (!editForm.gender) { setProfileError("请选择性别"); return false }
      if (!editForm.currentIdentity) { setProfileError("请选择当前身份"); return false }
      if (!editForm.birthyear || !editForm.birthmonth) { setProfileError("请选择出生年月"); return false }
      setProfileError("")
      return true
    }

    return (
      <SectionCard>
        <SectionHeader title="个人信息" changed={changedModuleKeys.has("basic_info")} onEdit={() => startEdit("profile", { ...p })} />
        {isEditing ? (
          <div>
            <FormRow label="姓名" required>
              <div className="flex items-center gap-2">
                <Input value={editForm.name || ""} onChange={e => setEditForm({ ...editForm, name: e.target.value })} placeholder="请填写真实姓名" className="flex-1" />
                <span className="text-[11px] text-gray-400 shrink-0">官网限制每月可修改2次</span>
              </div>
            </FormRow>
            <FormRow label="性别" required>
              <RadioGroup options={ZHILIAN_GENDER} value={editForm.gender} onChange={v => setEditForm({ ...editForm, gender: v })} />
            </FormRow>
            <FormRow label="当前身份" required>
              <RadioGroup options={ZHILIAN_JOB_SEEKER_IDENTITY} value={editForm.currentIdentity} onChange={v => setEditForm({ ...editForm, currentIdentity: v })} />
            </FormRow>
            <FormRow label="出生年月" required>
              <YearMonthPicker
                year={editForm.birthyear || ""}
                month={editForm.birthmonth || ""}
                onYearChange={y => setEditForm({ ...editForm, birthyear: y })}
                onMonthChange={m => setEditForm({ ...editForm, birthmonth: m })}
              />
            </FormRow>
            <FormRow label="参加工作时间">
              <YearMonthPicker
                year={editForm.yearStartWorking || ""}
                month={editForm.monthStartWorking || ""}
                onYearChange={y => setEditForm({ ...editForm, yearStartWorking: y })}
                onMonthChange={m => setEditForm({ ...editForm, monthStartWorking: m })}
              />
            </FormRow>
            <FormRow label="户口所在地">
              <CityCascader
                level={2}
                province={editForm.hukouProvinceIdTranslation || ""}
                city={editForm.hukouCityIdTranslation || ""}
                onChange={(provName, cityName, cityCode) => {
                  const provData = ZHILIAN_CITIES_FULL.find(pp => pp.name === provName)
                  setEditForm({ ...editForm, hukouProvinceId: provData?.code || "", hukouProvinceIdTranslation: provName, hukouCityId: cityCode, hukouCityIdTranslation: cityName })
                }}
              />
            </FormRow>
            <FormRow label="现居住城市">
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  {editForm.isOverseas ? (
                    <div className="px-3 py-1.5 rounded border border-gray-200 bg-gray-50 text-sm text-gray-500 select-none">
                      国外（已勾选国外）
                    </div>
                  ) : (
                    <CityCascader
                      level={3}
                      province={editForm.currentProvinceTranslation || ""}
                      city={editForm.currentCityTranslation || ""}
                      district={editForm.currentCityDistrictIdTranslation || ""}
                      onChange={(provName, cityName, cityCode, distName, distCode) => {
                        const provData = ZHILIAN_CITIES_FULL.find(pp => pp.name === provName)
                        setEditForm({
                          ...editForm,
                          currentProvince: provData?.code || "",
                          currentProvinceTranslation: provName,
                          currentCity: cityCode,
                          currentCityTranslation: cityName,
                          currentCityDistrictId: distCode || "",
                          currentCityDistrictIdTranslation: distName || "",
                          isOverseas: false,
                          foreign: false,
                        })
                      }}
                    />
                  )}
                </div>
                <label className="flex items-center gap-1.5 text-sm text-gray-600 shrink-0 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editForm.isOverseas === true || editForm.isOverseas === "1"}
                    onChange={e => {
                      const isChk = e.target.checked
                      if (isChk) {
                        setEditForm({
                          ...editForm,
                          isOverseas: true,
                          foreign: true,
                          currentProvince: "480",
                          currentProvinceTranslation: "国外",
                          currentCity: "480",
                          currentCityTranslation: "国外",
                          currentCityDistrictId: "0",
                          currentCityDistrictIdTranslation: "",
                        })
                      } else {
                        setEditForm({
                          ...editForm,
                          isOverseas: false,
                          foreign: false,
                          currentProvince: "",
                          currentProvinceTranslation: "",
                          currentCity: "",
                          currentCityTranslation: "",
                          currentCityDistrictId: "",
                          currentCityDistrictIdTranslation: "",
                        })
                      }
                    }}
                    className="w-4 h-4 rounded border-gray-300"
                  />
                  国外
                </label>
              </div>
            </FormRow>
            <FormRow label="政治面貌">
              <SimpleSelect options={ZHILIAN_POLITICAL_STATUS} value={editForm.politicalAffiliation || ""} onChange={v => {
                const found = ZHILIAN_POLITICAL_STATUS.find(o => o.code === v)
                setEditForm({ ...editForm, politicalAffiliation: v, politicalAffiliationTranslation: found?.label || "" })
              }} placeholder="请选择政治面貌，用于投递简历（选填）" />
            </FormRow>
            <FormRow label="联系方式">
              <div className="text-sm text-gray-500 pt-2">
                {(p.mobile || "").replace(/^\d+\|/, "") || "已绑定"}
                <span className="text-xs ml-2" style={{ color: PRIMARY }}>前往官网修改</span>
              </div>
            </FormRow>
            <FormRow label="电子邮箱">
              <div className="text-sm text-gray-500 pt-2">
                {p.email || "已绑定"}
                <span className="text-xs ml-2" style={{ color: PRIMARY }}>前往官网修改</span>
              </div>
            </FormRow>
            {profileError && <div className="text-sm text-red-500 mb-2 pl-27">{profileError}</div>}
            <InlineEditActions
              onCancel={cancelEdit}
              saving={saving}
              onSave={async () => {
                if (!validateProfile()) return
                const ok = await persistData({ ...localData, profile: editForm })
                if (!ok) return
                cancelEdit()
              }}
            />
          </div>
        ) : (
          <div className="space-y-2 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <div><span className="text-gray-500">姓名：</span>{p.name}</div>
              <div><span className="text-gray-500">性别：</span>{p.genderTranslation || (p.gender === "1" ? "男" : "女")}</div>
              <div><span className="text-gray-500">当前身份：</span>{p.currentIdentityTranslation}</div>
              <div><span className="text-gray-500">出生年月：</span>{p.birthyear}-{String(p.birthmonth).padStart(2, "0")}</div>
              <div><span className="text-gray-500">参加工作时间：</span>{p.yearStartWorking ? `${p.yearStartWorking}-${String(p.monthStartWorking).padStart(2, "0")}` : "未填写"}</div>
              <div><span className="text-gray-500">户口所在地：</span>{[p.hukouProvinceIdTranslation, p.hukouCityIdTranslation].filter(Boolean).join("-") || "未填写"}</div>
              <div>
                <span className="text-gray-500">现居住城市：</span>
                {p.isOverseas || p.foreign || p.currentProvince === "480" || p.currentCity === "480"
                  ? "国外"
                  : [p.currentProvinceTranslation, p.currentCityTranslation, p.currentCityDistrictIdTranslation].filter(Boolean).join("-") || "未填写"}
              </div>
              <div><span className="text-gray-500">政治面貌：</span>{p.politicalAffiliationTranslation || "未填写"}</div>
            </div>
            <div className="pt-2 border-t border-gray-100 grid grid-cols-2 gap-2 text-gray-500">
              <div>联系方式：{(p.mobile || "").replace(/^\d+\|/, "")} <span className="text-xs" style={{ color: PRIMARY }}>前往官网修改</span></div>
              <div>电子邮箱：{p.email} <span className="text-xs" style={{ color: PRIMARY }}>前往官网修改</span></div>
            </div>
          </div>
        )}
      </SectionCard>
    )
}
