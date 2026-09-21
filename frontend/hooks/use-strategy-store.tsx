"use client"

import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { useResumeV2Store, createEmptyResume } from '@/hooks/use-resume-v2-store'
import { apiFetch } from '@/lib/api'
import { STRATEGY_SET_SECTION_EVENT } from '@/lib/strategy-events'
import { useResumeUpload, type ParseProgress } from '@/hooks/use-resume-upload'
import { ConfigGateDialog } from '@/components/dashboard/config-gate-dialog'

// Markdown 解析/序列化纯函数与简历模块类型：实现下沉 lib/resume-blocks.ts（Q-M4-6 拆分），此处 re-export 保持兼容
export { parseMarkdownToBlocks, serializeBlocksToMarkdown, DEFAULT_RESUME_MARKDOWN } from '@/lib/resume-blocks'
export type { ResumeModule, ResumeSubModule } from '@/lib/resume-blocks'
import { parseMarkdownToBlocks, serializeBlocksToMarkdown, DEFAULT_RESUME_MARKDOWN, genResumeBlockId, type ResumeModule, type ResumeSubModule } from '@/lib/resume-blocks'

export type SectionId = "system" | "feishu" | "resume" | "preferences"

export type StrategyItem = {
    record_id?: string;
    name: string;
    content: string;
    status: string;
    avatar_url?: string;
    structured_json?: any;
}

// ========== Context 定义 ==========
type StrategyContextType = {
    section: SectionId;
    setSection: (s: SectionId) => void;
    resumes: StrategyItem[];
    setResumes: React.Dispatch<React.SetStateAction<StrategyItem[]>>;
    loading: boolean;
    saving: boolean;
    editingItem: StrategyItem | null;
    setEditingItem: React.Dispatch<React.SetStateAction<StrategyItem | null>>;

    // 简历编辑器状态
    resumeBlocks: ResumeModule[];
    setResumeBlocks: React.Dispatch<React.SetStateAction<ResumeModule[]>>;
    showRawMarkdown: boolean;
    setShowRawMarkdown: React.Dispatch<React.SetStateAction<boolean>>;
    isParsing: boolean;
    fileInputRef: React.RefObject<HTMLInputElement | null>;
    parseError: { taskId: string; msg: string } | null;
    handleRetry: () => Promise<void>;
    /** SSE 真进度（阶段 + 流式字数），解析结束后复位为 null */
    parseProgress: ParseProgress | null;
    /** 主 LLM 未配置的上传闸门：非 null 时弹配置引导（缺失字段列表） */
    uploadGate: string[] | null;
    clearUploadGate: () => void;
    dismissParseError: () => void;
    updateBlock: (id: string, patch: Partial<ResumeModule>) => void;
    deleteBlock: (id: string) => void;
    addBlock: () => void;
    updateSubModule: (blockId: string, subId: string, patch: Partial<ResumeSubModule>) => void;
    deleteSubModule: (blockId: string, subId: string) => void;
    addSubModule: (blockId: string) => void;
    handleFileImport: (e: React.ChangeEvent<HTMLInputElement>) => Promise<void>;

    // 全局交互与数据获取
    toastMsg: string;
    showToast: (msg: string) => void;
    togglingResumeId: string | null;
    fetchConfig: (currentEditingId?: string) => Promise<void>;
    handleToggleResumeStatus: (e: React.MouseEvent, item: StrategyItem) => Promise<void>;
    handleCreateNew: () => void;
    handleDuplicate: (id: string) => void;
    handleSave: () => Promise<string | null>;
    /** 是否有未同步到飞书的修改（供切换简历前弹确认用） */
    hasUnsavedChanges: () => boolean;
    /** 手动标记有未保存修改（如改名） */
    markDirty: () => void;
    handleDelete: (e: React.MouseEvent, item: StrategyItem) => Promise<void>;
}

const StrategyContext = createContext<StrategyContextType | undefined>(undefined)

export function StrategyStoreProvider({ children }: { children: React.ReactNode }) {
    const [section, setSection] = useState<SectionId>("system")
    const [resumes, setResumes] = useState<StrategyItem[]>([])
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [editingItem, setEditingItem] = useState<StrategyItem | null>(null)
    const [toastMsg, setToastMsg] = useState('')

    const showToast = (msg: string) => {
        setToastMsg(msg)
        setTimeout(() => setToastMsg(''), 2800)
    }

    // 🌟 自动解析 URL 中的 section / tab 参数（如 /strategy?section=feishu 即刻进入飞书集成中心）
    // 另监听 strategy:set-section 自定义事件：新手引导等组件在页内免刷新直达指定板块
    useEffect(() => {
        const VALID_SECTIONS = ['feishu', 'resume', 'system', 'preferences']
        const updateSectionFromUrl = () => {
            if (typeof window !== 'undefined') {
                const params = new URLSearchParams(window.location.search)
                const s = params.get('section') || params.get('tab')
                if (s && (s === 'feishu' || s === 'resume' || s === 'system' || s === 'preferences')) {
                    setSection(s as SectionId)
                }
            }
        }
        const onSetSectionEvent = (e: Event) => {
            const s = (e as CustomEvent).detail
            if (typeof s === 'string' && VALID_SECTIONS.includes(s)) {
                setSection(s as SectionId)
            }
        }

        updateSectionFromUrl()
        window.addEventListener('popstate', updateSectionFromUrl)
        window.addEventListener(STRATEGY_SET_SECTION_EVENT, onSetSectionEvent)
        return () => {
            window.removeEventListener('popstate', updateSectionFromUrl)
            window.removeEventListener(STRATEGY_SET_SECTION_EVENT, onSetSectionEvent)
        }
    }, [])

    // ========== 简历编辑器状态 ==========
    const fileInputRef = useRef<HTMLInputElement>(null)
    const [isParsing, setIsParsing] = useState(false)
    const [resumeBlocks, setResumeBlocks] = useState<ResumeModule[]>([])
    const [showRawMarkdown, setShowRawMarkdown] = useState(false)
    const isSerializingRef = useRef(false)

    // 异步解析状态机
    // （structuredJsonCache 已退役：结构化数据的唯一真相源是 v2 store + editingItem.structured_json）
    const [parseError, setParseError] = useState<{ taskId: string; msg: string } | null>(null)
    // SSE 真进度（阶段 + 流式字数）
    const [parseProgress, setParseProgress] = useState<ParseProgress | null>(null)
    // 主 LLM 未配置的上传闸门
    const [uploadGate, setUploadGate] = useState<string[] | null>(null)

    // 🌟 V2 Data Binding
    // v2OwnerRef 记录当前画布数据归属的简历。切换简历时若目标没有结构化数据（新简历/老记录），
    // 必须把画布重置为空模板——否则 v2 store 里残留的是上一份简历的数据，
    // 保存时会把 A 简历的结构化数据写进 B 简历（跨简历串号）
    const v2OwnerRef = useRef<string>("")
    // 未保存修改追踪：isDirtyRef=true 表示当前简历有尚未同步到飞书的改动
    const isDirtyRef = useRef(false)
    // 加载/重置画布期间抑制 dirty 标记（加载不算修改）
    const suppressDirtyRef = useRef(false)
    // 恢复暂存现场时跳过一次画布重载（画布数据本身还活着，重载反而会覆盖掉未保存内容）
    const skipNextV2LoadRef = useRef(false)
    // 离开简历页时若有未保存修改，暂存现场，切回时恢复，防止切个页签就静默丢稿
    const draftStashRef = useRef<{ item: StrategyItem } | null>(null)
    // 保存进行中锁（防双击双写，比 state 更及时）
    const savingRef = useRef(false)

    // 画布任何变更（正文/经历/个人信息/头像）都视为有未保存修改
    useEffect(() => {
        const unsub = useResumeV2Store.subscribe((state, prev) => {
            if (suppressDirtyRef.current) return
            if (state.resumeData !== prev.resumeData) isDirtyRef.current = true
        })
        return unsub
    }, [])

    useEffect(() => {
        if (section !== 'resume' || !editingItem) return
        const ownerKey = editingItem.record_id || ""
        if (skipNextV2LoadRef.current) {
            skipNextV2LoadRef.current = false
            v2OwnerRef.current = ownerKey
            return
        }
        const json = editingItem.structured_json
        v2OwnerRef.current = ownerKey
        isDirtyRef.current = false
        suppressDirtyRef.current = true
        try {
            if (json && typeof json === 'object' && Object.keys(json).length > 0) {
                useResumeV2Store.getState().setResumeData(json)
            } else {
                useResumeV2Store.getState().setResumeData(createEmptyResume())
            }
        } finally {
            suppressDirtyRef.current = false
        }
    }, [editingItem?.structured_json, editingItem?.record_id, section])

    useEffect(() => {
        if (section !== 'resume' || !editingItem) return;
        if (isSerializingRef.current) {
            isSerializingRef.current = false;
            return;
        }
        const blocks = parseMarkdownToBlocks(editingItem.content);
        setResumeBlocks(blocks);
    }, [editingItem?.content, editingItem?.record_id, section])

    const syncBlocksToContent = useCallback((newBlocks: ResumeModule[]) => {
        isDirtyRef.current = true
        setResumeBlocks(newBlocks);
        if (editingItem) {
            isSerializingRef.current = true;
            const md = serializeBlocksToMarkdown(newBlocks);
            const updatedItem = { ...editingItem, content: md };
            setEditingItem(updatedItem);

            // 🌟 核心修复：把最新的 Markdown 源码内容，实时覆盖同步到全局的 resumes 状态中
            // 这样能确保无论是修改了一级标题还是细节，侧边栏、预览弹窗等拿到的都是绝对同一份 Truth Source
            setResumes(prev => prev.map(r => r.record_id === editingItem.record_id ? { ...r, content: md } : r));
        }
    }, [editingItem, setResumes])

    const updateBlock = useCallback((id: string, patch: Partial<ResumeModule>) => {
        syncBlocksToContent(resumeBlocks.map(b => b.id === id ? { ...b, ...patch } : b));
    }, [resumeBlocks, syncBlocksToContent])

    const deleteBlock = useCallback((id: string) => {
        syncBlocksToContent(resumeBlocks.filter(b => b.id !== id));
    }, [resumeBlocks, syncBlocksToContent])

    const addBlock = useCallback(() => {
        syncBlocksToContent([...resumeBlocks, { id: genResumeBlockId(), type: 'basic', title: '新模块', content: '' }]);
    }, [resumeBlocks, syncBlocksToContent])

    const updateSubModule = useCallback((blockId: string, subId: string, patch: Partial<ResumeSubModule>) => {
        syncBlocksToContent(resumeBlocks.map(b => {
            if (b.id !== blockId || !b.subModules) return b;
            return { ...b, subModules: b.subModules.map(s => s.id === subId ? { ...s, ...patch } : s) };
        }));
    }, [resumeBlocks, syncBlocksToContent])

    const deleteSubModule = useCallback((blockId: string, subId: string) => {
        syncBlocksToContent(resumeBlocks.map(b => {
            if (b.id !== blockId) return b;
            return { ...b, subModules: b.subModules?.filter(s => s.id !== subId) };
        }));
    }, [resumeBlocks, syncBlocksToContent])

    const addSubModule = useCallback((blockId: string) => {
        syncBlocksToContent(resumeBlocks.map(b => {
            if (b.id !== blockId) return b;
            const subs = b.subModules || [];
            return { ...b, subModules: [...subs, { id: genResumeBlockId(), title: '新经历', content: '' }] };
        }));
    }, [resumeBlocks, syncBlocksToContent])

    // ========== 简历导入解析（上传/SSE/重试下沉 use-resume-upload，Q-M4-6 拆分） ==========
    const { handleFileImport, connectSSE } = useResumeUpload({
        onParsed: (fullMarkdown, structuredJson) => {
            setEditingItem(prev => prev ? { ...prev, content: fullMarkdown, structured_json: structuredJson } : null)
            import('@/hooks/use-resume-v2-store').then(({ useResumeV2Store }) => {
                useResumeV2Store.getState().setResumeData(structuredJson)
            })
            setParseError(null)
            showToast('✅ 简历解析成功，已生成结构化数据')
        },
        onError: (msg, taskId) => {
            if (taskId) setParseError({ taskId, msg })
            showToast('❌ ' + msg)
        },
        onParsingChange: (parsing) => {
            setIsParsing(parsing)
            if (!parsing) setParseProgress(null)
        },
        onProgress: (p) => setParseProgress(p),
        onGateBlocked: (missing) => setUploadGate(missing),
        onUploadStart: () => {
            setParseError(null)
            setParseProgress(null)
        },
        fileInputRef,
    })

    const handleRetry = async () => {
        if (!parseError?.taskId) return
        setParseError(null)
        setParseProgress(null)
        setIsParsing(true)
        try {
            const res = await apiFetch(`/api/strategy/retry_upload/${parseError.taskId}`, { method: "POST" })
            const data = await res.json()
            if (!res.ok || data.status !== "processing") throw new Error(data.detail || "重试失败")
            connectSSE(parseError.taskId)
        } catch (err) {
            setIsParsing(false)
            showToast('❌ 重试失败: ' + (err instanceof Error ? err.message : String(err)))
        }
    }

    // ========== 全局数据与飞书同步 ==========
    const [togglingResumeId, setTogglingResumeId] = useState<string | null>(null)

    const sectionRef = useRef(section);
    useEffect(() => { sectionRef.current = section }, [section]);

    const fetchConfig = async (currentEditingId?: string) => {
        setLoading(true)
        try {
            const res = await apiFetch(`/api/strategy/config`)
            if (!res.ok) {
                console.warn(`fetchConfig 响应异常 HTTP ${res.status}`)
                showToast(`⚠️ 简历配置加载异常 (HTTP ${res.status})`)
                return
            }
            const data = await res.json()
            if (data.status === "success") {
                const mappedResumes = data.resumes.map((r: any) => ({
                    record_id: r.record_id,
                    name: r.version_name,
                    content: r.content,
                    status: r.status,
                    avatar_url: r.avatar_url,
                    structured_json: r.structured_json
                }))
                setResumes(mappedResumes)

                if (currentEditingId) {
                    const target = mappedResumes.find((i: any) => i.record_id === currentEditingId)
                    if (target) setEditingItem(prev => {
                        // 本地有未保存修改时保留本地稿（名称/内容/画布），只同步服务端状态类字段
                        // （如头像、生效状态），否则切换生效/上传头像后的刷新会把正在编辑的内容静默覆盖掉
                        if (prev && isDirtyRef.current && prev.record_id === target.record_id) {
                            return { ...target, name: prev.name, content: prev.content, structured_json: prev.structured_json }
                        }
                        return target
                    })
                } else {
                    setEditingItem(prev => {
                        const s = sectionRef.current;
                        if (!prev || (!prev.record_id && prev.name === '新建简历版本')) {
                            if (s === 'resume' && mappedResumes.length > 0) return mappedResumes[0];
                        }
                        return prev;
                    });
                }
            } else {
                showToast('⚠️ 简历配置加载失败：' + (data.detail || `HTTP ${res.status}`))
            }
        } catch (e) {
            console.warn('fetchConfig 连接提示 (非致命):', e)
            showToast('⚠️ 无法连接后端服务，正在使用离线草稿')
        }
        finally { setLoading(false) }
    }

    useEffect(() => { fetchConfig() }, [])

    // 监听 Section 切换：进入时优先恢复暂存的未保存现场，否则选中第一项；
    // 离开时若有未保存修改先暂存，防止切个页签就静默丢稿
    useEffect(() => {
        if (section === 'resume') {
            if (draftStashRef.current) {
                const stashed = draftStashRef.current
                draftStashRef.current = null
                skipNextV2LoadRef.current = true
                setEditingItem(stashed.item)
                return
            }
            setEditingItem(prev => {
                if (prev) return prev
                if (resumes.length > 0) return resumes[0]
                return { name: '新建简历版本', content: DEFAULT_RESUME_MARKDOWN, status: '停用' }
            })
        }
        else {
            if (isDirtyRef.current && editingItem) {
                draftStashRef.current = { item: editingItem }
            } else {
                draftStashRef.current = null
            }
            setEditingItem(null)
        }
    }, [section])

    const handleToggleResumeStatus = async (e: React.MouseEvent, item: StrategyItem) => {
        e.stopPropagation()
        if (!item.record_id || togglingResumeId) return
        setTogglingResumeId(item.record_id)
        try {
            const res = await apiFetch(`/api/strategy/activate_resume`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ record_id: item.record_id })
            })
            const data = await res.json()
            if (res.ok && data.status === 'success') { await fetchConfig(editingItem?.record_id); showToast('✅ 已切换生效底稿') }
            else alert('❌ 切换失败' + (data?.detail ? '：' + data.detail : ''))
        } catch { alert('❌ 切换失败：网络异常') }
        finally { setTogglingResumeId(null) }
    }

    const handleCreateNew = () => {
        if (isDirtyRef.current && !window.confirm('当前简历有未保存的修改，新建后将丢弃这些修改。确定继续吗？')) return
        setEditingItem({
            name: '新建简历版本',
            content: DEFAULT_RESUME_MARKDOWN,
            status: '停用'
        })
    }

    const handleDuplicate = (id: string) => {
        if (isDirtyRef.current && !window.confirm('当前有未保存的修改，复制后画布将切换到副本，未保存的修改会丢失。确定继续吗？')) return
        const itemIndex = resumes.findIndex(r => r.record_id === id)
        const itemToCopy = resumes[itemIndex]
        if (!itemToCopy) return

        const tempId = `temp_${Date.now()}`
        const duplicatedItem = {
            ...itemToCopy,
            name: `${itemToCopy.name} - 副本`,
            status: '停用',
            record_id: tempId
        }

        setResumes(prev => {
            const copy = [...prev]
            copy.splice(itemIndex + 1, 0, duplicatedItem)
            return copy
        })

        setEditingItem(duplicatedItem)
        showToast('已为您创建副本，请修改后点击右上角「保存并同步」')
    }

    const handleSave = async (): Promise<string | null> => {
        if (!editingItem || !editingItem.name.trim()) { alert("名称不能为空！"); return null }
        if (savingRef.current) return null
        savingRef.current = true
        setSaving(true)

        let payloadFields: any = {};
        if (section === 'resume') {
            const blocks = parseMarkdownToBlocks(editingItem.content);
            const personalInfoBlock = blocks.find(b => b.title === '个人信息');
            const otherBlocks = blocks.filter(b => b.title !== '个人信息');

            const personalInfoText = personalInfoBlock ? `# ${personalInfoBlock.title}\n\n${personalInfoBlock.content || ''}` : '';
            const otherContentText = serializeBlocksToMarkdown(otherBlocks);

            // 🌟 获取最新 V2 状态
            // 只有画布数据确实归属当前简历（v2OwnerRef 匹配）才采用 v2；
            // 否则回退到本记录自带的结构化数据，绝不把上一份简历残留的画布写进当前记录
            let latestJsonToSave = editingItem.structured_json || {};
            try {
                // 动态获取 V2 Store 中的当前状态，以防缓存过期
                const { useResumeV2Store } = await import('@/hooks/use-resume-v2-store');
                const v2Data = useResumeV2Store.getState().resumeData;
                const ownerKey = editingItem.record_id || "";
                if (v2Data && v2OwnerRef.current === ownerKey) {
                    latestJsonToSave = v2Data;
                }
            } catch (e) {
                console.error("无法拉取 V2 Store 状态", e);
            }

            payloadFields = {
                "简历版本": editingItem.name,
                "简历内容": otherContentText,
                "个人信息": personalInfoText,
                "当前状态": editingItem.status,
                "结构化数据": JSON.stringify(latestJsonToSave)
            };
        }

        const actualRecordId = editingItem.record_id?.startsWith('temp_') ? undefined : editingItem.record_id;
        const payload = {
            table_type: "resume", record_id: actualRecordId,
            fields: payloadFields
        }
        try {
            const res = await apiFetch(`/api/strategy/save`, {
                method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
            })
            const data = await res.json()
            if (data.status === "success") {
                showToast("✅ 保存飞书成功！")
                const newRecordId = data.record_id || editingItem.record_id || null
                isDirtyRef.current = false
                setEditingItem(prev => prev ? { ...prev, record_id: newRecordId } : null)
                fetchConfig(newRecordId)
                return newRecordId
            } else {
                alert("❌ 保存失败: " + (data.detail || `HTTP ${res.status}`))
                return null
            }
        } catch {
            alert("❌ 网络错误，保存失败，请检查后端服务后重试")
            return null
        }
        finally {
            savingRef.current = false
            setSaving(false)
        }
    }

    const handleDelete = async (e: React.MouseEvent, item: StrategyItem) => {
        e.stopPropagation(); if (!item.record_id) return
        if (!window.confirm(`确定要永久删除「${item.name || '未命名'}」吗？`)) return

        // 乐观更新
        setResumes(prev => prev.filter(r => r.record_id !== item.record_id))
        if (editingItem?.record_id === item.record_id) {
            const remaining = resumes.filter(r => r.record_id !== item.record_id);
            if (remaining.length > 0) setEditingItem(remaining[0]);
            else setEditingItem({ name: '新建简历版本', content: DEFAULT_RESUME_MARKDOWN, status: '停用' });
        }

        // temp_ 前缀 = 从未同步到飞书的本地副本（新建/克隆产生），直接本地删除即可，
        // 调云端 DELETE 必然 RecordIdNotFound 报「假失败」
        if (item.record_id.startsWith('temp_')) return

        try {
            const res = await apiFetch(`/api/strategy/delete`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ table_type: "resume", record_id: item.record_id })
            })
            const data = await res.json()
            if (!res.ok || data.status !== "success") {
                alert(`❌ 后台删除失败，数据将恢复`); fetchConfig()
            }
        } catch { alert(`❌ 网络请求异常`); fetchConfig() }
    }

    return (
        <StrategyContext.Provider value={{
            section, setSection, resumes, setResumes, loading, saving,
            editingItem, setEditingItem, resumeBlocks, setResumeBlocks, showRawMarkdown, setShowRawMarkdown,
            isParsing, fileInputRef, parseError, handleRetry, updateBlock, deleteBlock, addBlock, updateSubModule, deleteSubModule, addSubModule, handleFileImport,
            parseProgress, uploadGate,
            clearUploadGate: () => setUploadGate(null),
            dismissParseError: () => setParseError(null),
            toastMsg, showToast, togglingResumeId, fetchConfig, handleToggleResumeStatus, handleCreateNew, handleDuplicate, handleSave, handleDelete,
            hasUnsavedChanges: () => isDirtyRef.current,
            markDirty: () => { isDirtyRef.current = true }
        }}>
            {children}
            {/* 主 LLM 未配置的上传闸门：引导前往系统底层配置 */}
            <ConfigGateDialog
                open={uploadGate !== null}
                onClose={() => setUploadGate(null)}
                title="简历解析暂不可用"
                description="上传简历需要「大模型」做结构化解析，当前还未配置。前往 系统底层配置 → LLM 大模型，填好 API Key、Base URL 与推理模型后即可使用。"
                missing={uploadGate ?? []}
                onGoConfigure={() => { setUploadGate(null); setSection('system') }}
            />
        </StrategyContext.Provider>
    )
}

export function useStrategyStore() {
    const context = useContext(StrategyContext)
    if (context === undefined) throw new Error("useStrategyStore must be used within a StrategyStoreProvider")
    return context
}

export function useOptionalStrategyStore() {
    return useContext(StrategyContext)
}
