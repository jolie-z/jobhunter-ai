/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { SectionCard, SectionHeader, InlineEditActions } from "../constants"
import { Textarea } from "@/components/ui/textarea"

import { useZhilianCtx } from "../context"

export function ZhilianSelfEval() {
  const {
    localData,
    editingSection,
    editForm,
    setEditForm,
    changedModuleKeys,
    saving,
    showToast,
    startEdit,
    cancelEdit,
    persistData,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "selfEval"
    const item = localData.selfEvaluation?.[0]
    const seLen = (editForm.selfEvaContent || "").length
    return (
      <SectionCard>
        <SectionHeader title="个人优势" changed={changedModuleKeys.has("self_evaluation")} onEdit={() => startEdit("selfEval", { selfEvaContent: item?.selfEvaContent || "" })} />
        {isEditing ? (
          <div>
            <Textarea
              value={editForm.selfEvaContent || ""}
              onChange={e => setEditForm({ ...editForm, selfEvaContent: e.target.value })}
              placeholder="请输入个人优势"
              rows={6}
            />
            <div className={`text-xs text-right mt-1 ${seLen > 500 ? "text-red-500 font-semibold" : "text-gray-400"}`}>
              {seLen > 500 ? `⚠️ 已超出 ${seLen - 500} 个字（上限 500 字，超限无法保存/回写）` : `${seLen}/500`}
            </div>
            <InlineEditActions
              onCancel={cancelEdit}
              saving={saving}
              onSave={async () => {
                if ((editForm.selfEvaContent || "").length > 500) {
                  showToast(`个人优势已超出上限 ${(editForm.selfEvaContent || "").length - 500} 字（当前 ${(editForm.selfEvaContent || "").length} / 500 字），请删减精简至 500 字以内后再保存`, "error")
                  return
                }
                const ok = await persistData({ ...localData, selfEvaluation: [{ ...item, selfEvaContent: editForm.selfEvaContent, selfEvaTitle: "自我介绍" }] })
                if (!ok) return
                cancelEdit()
              }}
            />
          </div>
        ) : (
          <div className="text-sm text-gray-700 whitespace-pre-wrap">{item?.selfEvaContent || "暂无"}</div>
        )}
      </SectionCard>
    )
}
