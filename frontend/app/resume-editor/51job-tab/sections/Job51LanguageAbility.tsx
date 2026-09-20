/**
 * Job51 Tab 分区组件（机械搬迁，行为零变化）
 */
"use client"

import { JOB51_LANGUAGES } from "@/lib/51job-options"
import { useJob51Ctx } from "../context"
import { SectionCard, SectionHeader, LANGUAGE_ABILITY_LEVELS } from "../constants"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Loader2, Plus, Edit, Trash2, Save, X, Upload, Sparkles, Lock } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { ReportWarnings, ReportUnfilled, ModuleChangeSummary, ModuleReportNotice } from "../../agent-report-shared"
import { DynamicFieldSlot } from "@/components/ui/dynamic-field-slot"


export function Job51LanguageAbility() {
  const {
    localData,
    setLocalData,
    saving,
    setSaving,
    toast,
    setToast,
    activeNav,
    setActiveNav,
    selfIntroEditing,
    setSelfIntroEditing,
    selfIntroValue,
    setSelfIntroValue,
    intentionEditing,
    setIntentionEditing,
    intentionForm,
    setIntentionForm,
    editingIntentionIdx,
    setEditingIntentionIdx,
    cityPickerOpen,
    setCityPickerOpen,
    funtypePickerOpen,
    setFuntypePickerOpen,
    industryPickerOpen,
    setIndustryPickerOpen,
    workExpEditing,
    setWorkExpEditing,
    workExpForm,
    setWorkExpForm,
    editingWorkExpIdx,
    setEditingWorkExpIdx,
    workFuntypePickerOpen,
    setWorkFuntypePickerOpen,
    workIndustryPickerOpen,
    setWorkIndustryPickerOpen,
    workSkillInput,
    setWorkSkillInput,
    projectEditing,
    setProjectEditing,
    projectForm,
    setProjectForm,
    editingProjectIdx,
    setEditingProjectIdx,
    educationEditing,
    setEducationEditing,
    educationForm,
    setEducationForm,
    editingEducationIdx,
    setEditingEducationIdx,
    majorPickerOpen,
    setMajorPickerOpen,
    educationErrors,
    setEducationErrors,
    languageEditing,
    setLanguageEditing,
    languageForm,
    setLanguageForm,
    editingLanguageIdx,
    setEditingLanguageIdx,
    langCertsData,
    setLangCertsData,
    langCertPickerOpen,
    setLangCertPickerOpen,
    skillEditing,
    setSkillEditing,
    skillForm,
    setSkillForm,
    editingSkillIdx,
    setEditingSkillIdx,
    skillPickerOpen,
    setSkillPickerOpen,
    skillErrors,
    setSkillErrors,
    certPickerOpen,
    setCertPickerOpen,
    selectedModules,
    setSelectedModules,
    writebackConfirm,
    setWritebackConfirm,
    writebacking,
    setWritebacking,
    writebackFeedback,
    setWritebackFeedback,
    showWritebackDetails,
    setShowWritebackDetails,
    savingSnapshot,
    setSavingSnapshot,
    snapshotFeedback,
    setSnapshotFeedback,
    report,
    setReport,
    reportLoading,
    setReportLoading,
    applyConfirmOpen,
    setApplyConfirmOpen,
    applying,
    setApplying,
    applyFeedback,
    setApplyFeedback,
    job51AgentDiagnosing,
    setJob51AgentDiagnosing,
    job51AgentReport,
    setJob51AgentReport,
    job51AgentModalOpen,
    setJob51AgentModalOpen,
    job51AgentApplying,
    setJob51AgentApplying,
    job51RollbackFeedback,
    setJob51RollbackFeedback,
    job51RollingBack,
    setJob51RollingBack,
    deleteTarget,
    setDeleteTarget,
    certNameMap,
    setCertNameMap,
    contentRef,
    changedModuleKeys,
    handleDispatchJob51HealerAgent,
    handleJob51AgentApplyHeal,
    handleRollbackJob51Snapshot,
    fetchReport,
    handleNavClick,
    getNowTime,
    handleSaveWritebackSource,
    selectedModuleKeys,
    handleApplyReport,
    handleWritebackModules,
    persistData,
    updateField,
    handleDeleteItem,
    confirmDelete,
    handleAddItem,
    handleUpdateItem,
    getVal,
    getLabel,
  } = useJob51Ctx()

    const items = getVal("language") || []

    const openAdd = () => {
      setEditingLanguageIdx(null)
      setLanguageForm({ skill: "", skillString: "", ability: "", abilityString: "", certifications: [] as string[] })
      setLanguageEditing(true)
    }

    const openEdit = (index: number) => {
      setEditingLanguageIdx(index)
      const item = items[index]
      const skillCode = item.skill || item.skillType || ""
      const foundLang = JOB51_LANGUAGES.find((l: any) => l.code === skillCode)
      const foundAbility = LANGUAGE_ABILITY_LEVELS.find((l: any) => l.code === String(item.ability))
      const rawCerts = item.certifications || (item.skillCertificationQueries ? item.skillCertificationQueries.map((c: any) => c.cert || c.code) : [])
      const certs = [...new Set((rawCerts || []).map((c: any) => typeof c === "string" ? c : (c.cert || c.code || "")).filter(Boolean))]
      setLanguageForm({
        ...item,
        skill: skillCode,
        skillType: skillCode,
        skillString: item.skillString || item.skillTypeString || item.skillName || foundLang?.value || "",
        skillName: item.skillName || item.skillString || foundLang?.value || "",
        skillTypeString: item.skillTypeString || item.skillString || foundLang?.value || "",
        ability: item.ability ? String(item.ability) : "",
        abilityString: item.abilityString || foundAbility?.label || "",
        certifications: certs,
      })
      setLanguageEditing(true)
    }

    const handleCancel = () => {
      setLanguageEditing(false)
    }

    const handleSave = async () => {
      const skillCode = languageForm.skill || languageForm.skillType || ""
      const foundLang = JOB51_LANGUAGES.find((l: any) => l.code === skillCode)
      const foundAbility = LANGUAGE_ABILITY_LEVELS.find((l: any) => l.code === String(languageForm.ability))
      const dedupedCerts = [...new Set((languageForm.certifications || []).map((c: any) => typeof c === "string" ? c : (c.cert || c.code || "")).filter(Boolean))]
      const toSave = {
        ...languageForm,
        skill: skillCode,
        skillType: skillCode,
        skillString: foundLang?.value || languageForm.skillString || "",
        skillName: foundLang?.value || languageForm.skillName || "",
        skillTypeString: foundLang?.value || languageForm.skillTypeString || "",
        ability: languageForm.ability ? String(languageForm.ability) : "",
        abilityString: foundAbility?.label || languageForm.abilityString || "",
        isEnglish: false,
        certifications: dedupedCerts,
      }
      let ok: boolean
      if (editingLanguageIdx !== null) {
        ok = await handleUpdateItem("language", editingLanguageIdx, toSave)
      } else {
        ok = await handleAddItem("language", toSave)
      }
      if (!ok) return
      setLanguageEditing(false)
    }

    const currentCerts = langCertsData[languageForm.skill]?.certs || []

    const toggleCert = (code: string) => {
      const certs: string[] = [...new Set<string>((languageForm.certifications || []).map((c: any) => typeof c === "string" ? c : (c.cert || c.code || "")).filter(Boolean))]
      if (certs.includes(code)) {
        setLanguageForm({ ...languageForm, certifications: certs.filter((c) => c !== code) })
      } else {
        setLanguageForm({ ...languageForm, certifications: [...certs, code] })
      }
    }

    // ===== 编辑模式（内联展开） =====
    if (languageEditing) {
      return (
        <SectionCard id="language-ability" changed={changedModuleKeys.has("language")}>
          <SectionHeader title="语言能力" changed={changedModuleKeys.has("language")} />

          <div className="space-y-5">
            {/* 语种 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>语种
              </label>
              <select
                value={languageForm.skill || ""}
                onChange={(e) => {
                  const found = JOB51_LANGUAGES.find((l: any) => l.code === e.target.value)
                  setLanguageForm({ ...languageForm, skill: e.target.value, skillString: found?.value || "", certifications: [] })
                }}
                className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
              >
                <option value="">请选择</option>
                {JOB51_LANGUAGES.map((o: any) => (
                  <option key={o.code} value={o.code}>{o.value}</option>
                ))}
              </select>
            </div>

            {/* 熟练程度 */}
            <div>
              <label className="text-sm text-gray-700 mb-2 block">
                <span className="text-red-500 mr-0.5">*</span>熟练程度
              </label>
              <select
                value={languageForm.ability || ""}
                onChange={(e) => {
                  const found = LANGUAGE_ABILITY_LEVELS.find((l: any) => l.code === e.target.value)
                  setLanguageForm({ ...languageForm, ability: e.target.value, abilityString: found?.label || "" })
                }}
                className="w-full h-[40px] rounded-md border border-gray-300 bg-white px-3 text-sm focus:outline-none focus:border-[#FF6B00]"
              >
                <option value="">请选择</option>
                {LANGUAGE_ABILITY_LEVELS.map((o: any) => (
                  <option key={o.code} value={o.code}>{o.label}</option>
                ))}
              </select>
            </div>

            {/* 证书（选填，跟随语种变化，弹窗选择） */}
            {currentCerts.length > 0 && (
              <div>
                <label className="text-sm text-gray-700 mb-2 block">证书（选填）</label>
                {/* 已选证书标签 */}
                {(languageForm.certifications || []).length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-2">
                    {[...new Set<string>((languageForm.certifications || []).map((c: any) => typeof c === "string" ? c : (c.cert || c.code || "")).filter(Boolean))].map((code: string, idx: number) => {
                      const cert = currentCerts.find((c) => c.code === code)
                      return (
                        <span key={`lang-cert-${code}-${idx}`} className="inline-flex items-center gap-1 px-2.5 py-1 bg-[#FFF3E8] text-[#FF6B00] rounded text-sm">
                          {cert?.value || code}
                          <button type="button" onClick={() => toggleCert(code)} className="ml-0.5 hover:text-[#cc5500] cursor-pointer">×</button>
                        </span>
                      )
                    })}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => setLangCertPickerOpen(true)}
                  className="px-3 py-1.5 rounded text-sm border border-gray-300 text-gray-600 hover:border-[#FF6B00] hover:text-[#FF6B00] transition-colors cursor-pointer"
                >
                  + 选择证书
                </button>
              </div>
            )}

            {/* 证书选择弹窗 */}
            <Dialog open={langCertPickerOpen} onOpenChange={setLangCertPickerOpen}>
              <DialogContent className="sm:max-w-md">
                <DialogHeader>
                  <DialogTitle>选择证书</DialogTitle>
                </DialogHeader>
                <div className="flex flex-wrap gap-2 max-h-[300px] overflow-y-auto py-2">
                  {currentCerts.map((cert) => {
                    const selected = (languageForm.certifications || []).includes(cert.code)
                    return (
                      <button
                        key={cert.code}
                        type="button"
                        onClick={() => toggleCert(cert.code)}
                        className={`px-3 py-1.5 rounded text-sm border transition-colors ${
                          selected
                            ? "bg-[#FF6B00] text-white border-[#FF6B00]"
                            : "bg-white text-gray-600 border-gray-300 hover:border-[#FF6B00] hover:text-[#FF6B00]"
                        }`}
                      >
                        {cert.value}
                      </button>
                    )
                  })}
                </div>
                <div className="flex justify-end pt-3 border-t border-gray-100">
                  <Button onClick={() => setLangCertPickerOpen(false)} className="bg-[#FF6B00] hover:bg-[#e55f00] text-white min-w-[80px]">
                    确定
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </div>

          {/* 底部按钮 */}
          <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-gray-100">
            <Button variant="outline" onClick={handleCancel} className="border-gray-300 text-gray-600 min-w-[80px]">
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving} className="bg-[#FF6B00] hover:bg-[#e55f00] text-white min-w-[80px]">
              {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : null}
              完成
            </Button>
          </div>
        </SectionCard>
      )
    }

    // ===== 展示模式 =====
    return (
      <SectionCard id="language-ability">
        <SectionHeader title="语言能力" changed={changedModuleKeys.has("language")} />
        <div className="space-y-3">
          {items.length > 0 ? items.map((item: any, index: number) => {
            const displayCerts = [...new Set<string>(((item.certifications || (item.skillCertificationQueries ? item.skillCertificationQueries.map((c: any) => c.cert || c.code) : [])) || []).map((c: any) => typeof c === "string" ? c : (c.cert || c.code || "")).filter(Boolean))]
            return (
              <div key={index} className="flex items-center justify-between border-b border-gray-100 pb-3 last:border-0 last:pb-0 group">
                <div className="text-sm text-gray-700">
                  <span className="font-medium">{item.skillString || item.skillTypeString || item.skillName || item.skill || "未知语言"}</span>
                  {item.abilityString && <span className="text-gray-500 ml-3">{item.abilityString}</span>}
                  {displayCerts.length > 0 && (
                    <span className="text-gray-500 ml-3">
                      证书：{displayCerts.map((code: string) => {
                        const cert = (langCertsData[item.skill || item.skillType]?.certs || []).find((c) => c.code === code)
                        return cert?.value || code
                      }).join("、")}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={() => openEdit(index)} className="text-xs text-[#FF6B00] hover:text-[#e55f00] cursor-pointer">编辑</button>
                  <button onClick={() => setDeleteTarget({ fieldName: "language", index, title: `确认删除语言能力「${item.skillTypeString || '语言能力'}」？`, description: "此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。" })} className="text-xs text-red-400 hover:text-red-500 cursor-pointer">删除</button>
                </div>
              </div>
            )
          }) : (
            <span className="text-sm text-gray-400">暂无语言能力</span>
          )}
        </div>
        <button
          onClick={openAdd}
          className="mt-3 flex items-center gap-1 text-sm text-[#FF6B00] hover:text-[#e55f00] cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          添加语言能力
        </button>
      </SectionCard>
    )
  }
