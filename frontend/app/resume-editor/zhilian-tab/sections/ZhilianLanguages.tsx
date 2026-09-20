/**
 * Zhilian Tab 分区组件（机械搬迁自 zhilian-tab.tsx，行为零变化）
 */
"use client"

import { API_BASE } from "@/lib/api"
import { PRIMARY, SectionCard, SectionHeader, FormRow } from "../constants"
import { cn } from "@/lib/utils"
import { ZHILIAN_LANGUAGES, ZHILIAN_PROFICIENCY_LEVELS } from "@/lib/zhilian-options"

import { useZhilianCtx } from "../context"

export function ZhilianLanguages() {
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
    certOptions,
    setCertOptions,
    certLoading,
    setCertLoading,
    certPickerVisible,
    setCertPickerVisible,
    certPickerIdx,
    setCertPickerIdx,
    certActiveCategory,
    setCertActiveCategory,
  } = useZhilianCtx()
  if (!localData) return null
    const isEditing = editingSection === "language"
    const items = localData.language || []

    const fetchCertificates = async (langCode: number) => {
      setCertLoading(true)
      try {
        const res = await fetch(`${API_BASE}/api/resume-editor/zhilian/language-certificates/${langCode}`)
        const json = await res.json()
        if (json.success && json.data) {
          setCertOptions(json.data)
        } else {
          setCertOptions([])
        }
      } catch { setCertOptions([]) }
      setCertLoading(false)
    }

    const handleStartEditLanguage = (item: any, idx?: number) => {
      setLanguageError("")
      const langCode = item.langLanguageT
        ? (ZHILIAN_LANGUAGES.find(l => l.label === item.langLanguageT)?.code ?? 0)
        : 0
      const certs = (Array.isArray(item.langCertificatesFormat) ? item.langCertificatesFormat : []).map((c: any) => ({
        certificateId: c.certificateId || 0,
        certificateName: c.certificateName || "",
        certificateScore: c.certificateScore || "",
      }))
      startEdit("language", {
        langLanguageT: "", langLSProficiency: "", langRWProficiency: "",
        ...item,
        _langCode: langCode,
        _certs: certs.length > 0 ? certs : [],
      }, idx)
      if (langCode) fetchCertificates(langCode)
      else setCertOptions([])
    }

    const handleLanguageChange = (label: string) => {
      const lang = ZHILIAN_LANGUAGES.find(l => l.label === label)
      const code = lang?.code ?? 0
      setEditForm((prev: any) => ({ ...prev, langLanguageT: label, _langCode: code, _certs: [] }))
      if (code) fetchCertificates(code)
      else setCertOptions([])
    }

    const handleSaveLanguage = async () => {
      if (!editForm.langLanguageT) { setLanguageError("请选择语种"); return }
      if (!editForm.langLSProficiency) { setLanguageError("请选择听说能力"); return }
      if (!editForm.langRWProficiency) { setLanguageError("请选择读写能力"); return }
      setLanguageError("")

      const saveData: any = {
        langLanguageT: editForm.langLanguageT,
        langLSProficiency: editForm.langLSProficiency,
        langRWProficiency: editForm.langRWProficiency,
        langCertificatesFormat: (editForm._certs || []).filter((c: any) => c.certificateId),
      }

      if (editingIdx !== null) {
        await handleUpdateItem("language", editingIdx, saveData)
      } else {
        await handleAddItem("language", saveData)
      }
      cancelEdit()
    }

    const addCertSlot = () => {
      const certs = [...(editForm._certs || [])]
      if (certs.length >= 5) return
      certs.push({ certificateId: 0, certificateName: "", certificateScore: "" })
      setEditForm((prev: any) => ({ ...prev, _certs: certs }))
    }

    const removeCertSlot = (idx: number) => {
      const certs = (editForm._certs || []).filter((_: any, i: number) => i !== idx)
      setEditForm((prev: any) => ({ ...prev, _certs: certs }))
    }

    const openCertPicker = (idx: number) => {
      setCertPickerIdx(idx)
      setCertActiveCategory(0)
      setCertPickerVisible(true)
    }

    const selectCert = (cert: any) => {
      const certs = [...(editForm._certs || [])]
      if (certs[certPickerIdx]) {
        certs[certPickerIdx] = { ...certs[certPickerIdx], certificateId: cert.value, certificateName: cert.label }
      }
      setEditForm((prev: any) => ({ ...prev, _certs: certs }))
      setCertPickerVisible(false)
    }

    return (
      <SectionCard>
        <SectionHeader
          title="语言能力"
          changed={changedModuleKeys.has("language")}
          onAdd={() => handleStartEditLanguage({})}
        />
        {items.length === 0 && !isEditing && <div className="text-sm text-gray-400">暂无语言能力</div>}
        {items.map((item, idx) => (
          <div key={idx} className="mb-2 pb-2 border-b border-gray-100 last:border-0 last:mb-0 last:pb-0">
            <div className="flex items-center justify-between">
              <div className="text-sm text-gray-700">
                <span className="font-medium">{item.langLanguageT}</span>
                <span className="text-gray-500 ml-3">听说：{item.langLSProficiency}</span>
                <span className="text-gray-500 ml-3">读写：{item.langRWProficiency}</span>
                {Array.isArray(item.langCertificatesFormat) && item.langCertificatesFormat.map((c: any, ci: number) => (
                  <span key={ci} className="text-gray-400 ml-2 text-xs">{c.certificateName}{c.certificateScore ? `(${c.certificateScore})` : ""}</span>
                ))}
              </div>
              <div className="flex gap-2">
                <button className="text-xs cursor-pointer" style={{ color: PRIMARY }} onClick={() => handleStartEditLanguage(item, idx)}>编辑</button>
                <button
                  className="text-xs text-red-400 hover:text-red-500 cursor-pointer"
                  onClick={() => setDeleteTarget({
                    fieldName: "language",
                    index: idx,
                    title: `确认删除语言能力「${item.langLanguageT || '语言能力'}」？`,
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
            <div className="absolute inset-0 bg-black/40" onClick={() => { setLanguageError(""); setCertPickerVisible(false); cancelEdit() }} />
            <div className="relative bg-white rounded-xl shadow-2xl w-[560px] max-h-[85vh] flex flex-col">
              <div className="px-6 pt-5 pb-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-base font-medium text-gray-900">{editingIdx !== null ? "编辑语言能力" : "添加语言能力"}</h3>
                <button type="button" onClick={() => { setLanguageError(""); setCertPickerVisible(false); cancelEdit() }} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
              </div>
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                <FormRow label="语种" required>
                  <select
                    className="w-full h-9 px-3 text-sm border border-gray-300 rounded-md bg-white focus:outline-none"
                    value={editForm.langLanguageT || ""}
                    onChange={e => handleLanguageChange(e.target.value)}
                  >
                    <option value="">请选择</option>
                    {ZHILIAN_LANGUAGES.map(l => (
                      <option key={l.code} value={l.label}>{l.label}</option>
                    ))}
                  </select>
                </FormRow>
                <FormRow label="听说能力" required>
                  <select
                    className="w-full h-9 px-3 text-sm border border-gray-300 rounded-md bg-white focus:outline-none"
                    value={editForm.langLSProficiency || ""}
                    onChange={e => setEditForm((prev: any) => ({ ...prev, langLSProficiency: e.target.value }))}
                  >
                    <option value="">请选择</option>
                    {ZHILIAN_PROFICIENCY_LEVELS.map(lv => (
                      <option key={lv} value={lv}>{lv}</option>
                    ))}
                  </select>
                </FormRow>
                <FormRow label="读写能力" required>
                  <select
                    className="w-full h-9 px-3 text-sm border border-gray-300 rounded-md bg-white focus:outline-none"
                    value={editForm.langRWProficiency || ""}
                    onChange={e => setEditForm((prev: any) => ({ ...prev, langRWProficiency: e.target.value }))}
                  >
                    <option value="">请选择</option>
                    {ZHILIAN_PROFICIENCY_LEVELS.map(lv => (
                      <option key={lv} value={lv}>{lv}</option>
                    ))}
                  </select>
                </FormRow>
                {/* 获得证书 */}
                <div>
                  <div className="text-sm text-gray-700 mb-2">获得证书</div>
                  {(editForm._certs || []).map((cert: any, ci: number) => (
                    <div key={ci} className="flex items-center gap-2 mb-2">
                      <button
                        type="button"
                        onClick={() => openCertPicker(ci)}
                        className="flex-1 h-9 px-3 text-sm border border-gray-300 rounded-md bg-white text-left truncate focus:outline-none hover:border-gray-400"
                      >
                        {cert.certificateName || <span className="text-gray-400">请选择证书（选填）</span>}
                      </button>
                      <input
                        type="text"
                        className="w-[100px] h-9 px-2 text-sm border border-gray-300 rounded-md focus:outline-none"
                        placeholder="分数（选填）"
                        value={cert.certificateScore || ""}
                        maxLength={3}
                        onChange={e => {
                          const certs = [...(editForm._certs || [])]
                          certs[ci] = { ...certs[ci], certificateScore: e.target.value.slice(0, 3) }
                          setEditForm((prev: any) => ({ ...prev, _certs: certs }))
                        }}
                      />
                      <button type="button" onClick={() => removeCertSlot(ci)} className="text-xs text-red-400 hover:text-red-600 shrink-0">删除</button>
                    </div>
                  ))}
                  {(editForm._certs || []).length < 5 && (
                    <button type="button" onClick={addCertSlot} className="text-sm cursor-pointer" style={{ color: PRIMARY }}>+ 添加证书</button>
                  )}
                  {certLoading && <div className="text-xs text-gray-400 mt-1">加载证书列表中...</div>}
                </div>
                {languageError && <div className="text-xs text-red-500">{languageError}</div>}
              </div>
              <div className="px-6 py-4 border-t border-gray-100 flex items-center gap-3">
                <button type="button" onClick={handleSaveLanguage} className="px-5 py-2 text-sm text-white rounded-full" style={{ backgroundColor: PRIMARY }}>保存并更新</button>
                <button type="button" onClick={() => { setLanguageError(""); setCertPickerVisible(false); cancelEdit() }} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
              </div>
            </div>
            {/* 证书选择弹窗 */}
            {certPickerVisible && (
              <div className="fixed inset-0 z-[200] flex items-center justify-center">
                <div className="absolute inset-0 bg-black/30" onClick={() => setCertPickerVisible(false)} />
                <div className="relative bg-white rounded-xl shadow-2xl w-[600px] max-h-[500px] flex flex-col">
                  <div className="px-5 pt-4 pb-3 border-b border-gray-100 flex items-center justify-between">
                    <h4 className="text-sm font-medium text-gray-900">请选择证书</h4>
                    <button type="button" onClick={() => setCertPickerVisible(false)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
                  </div>
                  <div className="flex-1 flex overflow-hidden">
                    {/* 左侧分类 */}
                    <div className="w-[240px] border-r border-gray-100 overflow-y-auto py-2">
                      {certOptions.map((cat: any, ci: number) => (
                        <button
                          key={cat.value}
                          type="button"
                          onClick={() => setCertActiveCategory(ci)}
                          className={cn(
                            "w-full text-left px-4 py-2 text-sm transition-colors",
                            ci === certActiveCategory ? "bg-blue-50 text-blue-600 font-medium" : "text-gray-700 hover:bg-gray-50"
                          )}
                        >
                          {cat.label}
                        </button>
                      ))}
                    </div>
                    {/* 右侧具体证书 */}
                    <div className="flex-1 overflow-y-auto py-2">
                      {(certOptions[certActiveCategory]?.children || []).map((cert: any) => (
                        <button
                          key={cert.value}
                          type="button"
                          onClick={() => selectCert(cert)}
                          className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                        >
                          {cert.label}
                        </button>
                      ))}
                      {(!certOptions[certActiveCategory]?.children || certOptions[certActiveCategory].children.length === 0) && (
                        <div className="px-4 py-6 text-sm text-gray-400 text-center">暂无证书</div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </SectionCard>
    )
}
