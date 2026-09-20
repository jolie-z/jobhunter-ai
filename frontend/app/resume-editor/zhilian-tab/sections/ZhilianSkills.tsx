/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { PRIMARY, SectionCard, SectionHeader, FormRow, RadioGroup } from "../constants"
import { Input } from "@/components/ui/input"
import { ZHILIAN_PROFICIENCY_LEVELS } from "@/lib/zhilian-options"

import { useZhilianCtx } from "../context"

export function ZhilianSkills() {
  const {
    localData,
    editingSection,
    editForm,
    setEditForm,
    editingIdx,
    languageError,
    setLanguageError,
    changedModuleKeys,
    saving,
    startEdit,
    cancelEdit,
    handleAddItem,
    handleUpdateItem,
    setDeleteTarget,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "skills"
    const items = localData.professionalSkills || []

    const handleSaveSkill = async () => {
      if (!editForm.proskillName?.trim()) { setLanguageError("请输入技能名称"); return }
      setLanguageError("")
      const saveData = {
        proskillName: editForm.proskillName,
        proskillLevel: editForm.proskillLevel || "一般",
        proskillUseTime: (editForm.proskillUseTime || "").replace(/[^0-9]/g, ""),
      }
      if (editingIdx !== null) {
        await handleUpdateItem("professionalSkills", editingIdx, saveData)
      } else {
        await handleAddItem("professionalSkills", saveData)
      }
      cancelEdit()
    }

    return (
      <SectionCard>
        <SectionHeader
          title="专业技能"
          changed={changedModuleKeys.has("skill_tags")}
          onAdd={() => { setLanguageError(""); startEdit("skills", { proskillName: "", proskillLevel: "一般", proskillUseTime: "" }) }}
        />
        {items.length === 0 && !isEditing && <div className="text-sm text-gray-400">暂无专业技能</div>}
        {items.filter(it => it.proskillName && String(it.proskillName).trim() !== "").map((item, idx) => (
          <div key={idx} className="mb-2 pb-2 border-b border-gray-100 last:border-0 last:mb-0 last:pb-0">
            <div className="flex items-center justify-between">
              <div className="text-sm text-gray-700">
                <span className="font-medium">{item.proskillName}</span>
                <span className="text-gray-500 ml-3">{item.proskillLevel}</span>
                {item.proskillUseTime && <span className="text-gray-400 ml-2 text-xs">使用{String(item.proskillUseTime).replace(/[^0-9]/g, "")}个月</span>}
              </div>
              <div className="flex gap-2">
                <button className="text-xs cursor-pointer" style={{ color: PRIMARY }} onClick={() => { setLanguageError(""); startEdit("skills", item, idx) }}>编辑</button>
                <button
                  className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  onClick={() => setDeleteTarget({
                    fieldName: "professionalSkills",
                    index: idx,
                    title: `确认删除专业技能「${item.proskillName || '专业技能'}」？`,
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
          <div className="fixed inset-0 z-[100] flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => { setLanguageError(""); cancelEdit() }} />
            <div className="relative bg-white rounded-xl shadow-2xl w-[560px] max-h-[85vh] flex flex-col">
              <div className="px-6 pt-5 pb-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-base font-medium text-gray-900">{editingIdx !== null ? "编辑专业技能" : "添加专业技能"}</h3>
                <button type="button" onClick={() => { setLanguageError(""); cancelEdit() }} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
              </div>
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                <FormRow label="技能名称" required>
                  <Input value={editForm.proskillName || ""} onChange={e => setEditForm((prev: any) => ({ ...prev, proskillName: e.target.value }))} placeholder="必填" />
                </FormRow>
                <FormRow label="使用时长">
                  <div className="flex items-center gap-2">
                    <Input
                      className="w-24"
                      value={editForm.proskillUseTime || ""}
                      onChange={e => setEditForm((prev: any) => ({ ...prev, proskillUseTime: e.target.value.replace(/[^0-9]/g, "") }))}
                      placeholder=""
                    />
                    <span className="text-sm text-gray-500">月</span>
                  </div>
                </FormRow>
                <FormRow label="掌握程度" required>
                  <RadioGroup options={ZHILIAN_PROFICIENCY_LEVELS} value={editForm.proskillLevel || "一般"} onChange={v => setEditForm((prev: any) => ({ ...prev, proskillLevel: v }))} />
                </FormRow>
                {languageError && <div className="text-xs text-red-500">{languageError}</div>}
              </div>
              <div className="px-6 py-4 border-t border-gray-100 flex items-center gap-3">
                <button type="button" onClick={handleSaveSkill} className="px-5 py-2 text-sm text-white rounded-full" style={{ backgroundColor: PRIMARY }}>保存并更新</button>
                <button type="button" onClick={() => { setLanguageError(""); cancelEdit() }} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
              </div>
            </div>
          </div>
        )}
      </SectionCard>
    )
}
