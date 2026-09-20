/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { SectionCard, SectionHeader, FormRow, InlineEditActions, RadioGroup } from "../constants"
import { ZHILIAN_CAREER_STATUS_PROFESSIONAL, ZHILIAN_CAREER_STATUS_STUDENT } from "@/lib/zhilian-options"

import { useZhilianCtx } from "../context"

export function ZhilianJobStatus() {
  const {
    localData,
    editingSection,
    editForm,
    setEditForm,
    changedModuleKeys,
    saving,
    startEdit,
    cancelEdit,
    persistData,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "jobStatus"
    return (
      <SectionCard>
        <SectionHeader
          title="求职状态"
          changed={changedModuleKeys.has("job_status")}
          onEdit={() => startEdit("jobStatus", { jobStateCode: localData.jobStatus?.jobStateCode, jobState: localData.jobStatus?.jobState })}
        />
        {isEditing ? (
          <div>
            <FormRow label="求职状态" required>
              <RadioGroup
                options={
                  localData.profile?.currentIdentity === "1"
                    ? ZHILIAN_CAREER_STATUS_STUDENT
                    : ZHILIAN_CAREER_STATUS_PROFESSIONAL
                }
                value={editForm.jobStateCode}
                onChange={v => {
                  const opts = localData.profile?.currentIdentity === "1" ? ZHILIAN_CAREER_STATUS_STUDENT : ZHILIAN_CAREER_STATUS_PROFESSIONAL
                  const found = opts.find(o => o.code === v)
                  setEditForm({ ...editForm, jobStateCode: v, jobState: found?.label || "" })
                }}
              />
            </FormRow>
            <InlineEditActions
              onCancel={cancelEdit}
              saving={saving}
              onSave={async () => {
                const ok = await persistData({ ...localData, jobStatus: { jobState: editForm.jobState, jobStateCode: editForm.jobStateCode } })
                if (!ok) return
                cancelEdit()
              }}
            />
          </div>
        ) : (
          <div className="text-sm text-gray-700">{localData.jobStatus?.jobState || "未设置"}</div>
        )}
      </SectionCard>
    )
}
