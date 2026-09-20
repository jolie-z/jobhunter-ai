/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { PRIMARY, SectionCard, SectionHeader, FormRow } from "../constants"
import { Input } from "@/components/ui/input"

import { useZhilianCtx } from "../context"

export function ZhilianCertificates() {
  const {
    localData,
    editingSection,
    editForm,
    setEditForm,
    editingIdx,
    trainingError,
    setTrainingError,
    changedModuleKeys,
    saving,
    startEdit,
    cancelEdit,
    handleAddItem,
    handleUpdateItem,
    setDeleteTarget,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "certificate"
    const items = localData.certificate || []

    const handleSaveCert = async () => {
      if (!editForm.certUserdefName?.trim()) { setTrainingError("请输入证书名称"); return }
      setTrainingError("")
      const saveData = { certUserdefName: editForm.certUserdefName }
      if (editingIdx !== null) {
        await handleUpdateItem("certificate", editingIdx, saveData)
      } else {
        await handleAddItem("certificate", saveData)
      }
      cancelEdit()
    }

    return (
      <SectionCard>
        <SectionHeader
          title="证书"
          changed={changedModuleKeys.has("certificates")}
          onAdd={() => { setTrainingError(""); startEdit("certificate", { certUserdefName: "" }) }}
        />
        {items.length === 0 && !isEditing && <div className="text-sm text-gray-400">暂无证书</div>}
        {items.map((item, idx) => (
          <div key={idx} className="mb-2 pb-2 border-b border-gray-100 last:border-0 last:mb-0 last:pb-0">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-900">{item.certUserdefName}</span>
              <div className="flex gap-2">
                <button className="text-xs cursor-pointer" style={{ color: PRIMARY }} onClick={() => { setTrainingError(""); startEdit("certificate", item, idx) }}>编辑</button>
                <button
                  className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  onClick={() => setDeleteTarget({
                    fieldName: "certificate",
                    index: idx,
                    title: `确认删除证书「${item.certUserdefName || '证书'}」？`,
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
            <div className="absolute inset-0 bg-black/40" onClick={() => { setTrainingError(""); cancelEdit() }} />
            <div className="relative bg-white rounded-xl shadow-2xl w-[560px] max-h-[85vh] flex flex-col">
              <div className="px-6 pt-5 pb-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-base font-medium text-gray-900">{editingIdx !== null ? "编辑证书" : "添加证书"}</h3>
                <button type="button" onClick={() => { setTrainingError(""); cancelEdit() }} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
              </div>
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                <FormRow label="证书名称" required>
                  <Input value={editForm.certUserdefName || ""} onChange={e => setEditForm((prev: any) => ({ ...prev, certUserdefName: e.target.value }))} placeholder="必填" />
                </FormRow>
                {trainingError && <div className="text-xs text-red-500">{trainingError}</div>}
              </div>
              <div className="px-6 py-4 border-t border-gray-100 flex items-center gap-3">
                <button type="button" onClick={handleSaveCert} className="px-5 py-2 text-sm text-white rounded-full" style={{ backgroundColor: PRIMARY }}>保存并更新</button>
                <button type="button" onClick={() => { setTrainingError(""); cancelEdit() }} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
              </div>
            </div>
          </div>
        )}
      </SectionCard>
    )
}
