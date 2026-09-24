"use client"

import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { RefreshCw, Save, FileWarning } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useResumeV2Store, createEmptyResume } from '@/hooks/use-resume-v2-store'
import { apiFetch } from '@/lib/api'
import { STRATEGY_SET_SECTION_EVENT } from '@/lib/strategy-events'
import { useResumeUpload, type ParseProgress } from '@/hooks/use-resume-upload'
import { ConfigGateDialog } from '@/components/dashboard/config-gate-dialog'
import {
    RESUME_DRAFT_DEBOUNCE_MS,
    RESUME_DRAFT_LOCAL_KEY,
    createDraftScheduler,
    clearResumeDraft,
    readResumeDraft,
    writeResumeDraft,
} from '@/lib/resume-draft'
import {
    isTempResumeId,
    makeTempResumeId,
    mergeLocalResumes,
    purgeExpiredResumeRegistry,
    removeLocalResume,
    upsertLocalResume,
} from '@/lib/resume-draft-registry'

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

// ========== 本机草稿与未保存简历登记（2026-09-23 七项修复#4 + 刷新丢稿根治立项）==========
// 草稿槽/防抖排期器/登记表/过期清理的实现均已下沉 lib/resume-draft.ts 与
// lib/resume-draft-registry.ts（实现下沉收敛 store 体积，并供组件级测试直接驱动），此处仅接线：
//   写入 = 画布变更防抖排期（subscribe）+ 登记表同步；恢复 = load effect 本机稿优先；
//   清除 = 保存转正 / 记录删除；列表 = fetchConfig 合并本地未保存项（见 mergeLocalResumes）。
const resumeDraftScheduler = createDraftScheduler(writeResumeDraft, RESUME_DRAFT_DEBOUNCE_MS)

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
    /** 未保存修改拦截：有脏改动时弹「保存修改 / 放弃修改」双选框（保存=先保存再继续，放弃=丢弃继续，取消=中止）。
     *  无脏改动时直接放行。resolve 值 = 用户是否选择继续（true）。 */
    confirmUnsavedGuard: (scene: 'create' | 'duplicate' | 'switch') => Promise<boolean>;
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
                const VALID_SECTIONS = ['feishu', 'resume', 'system'] // 'preferences' 已退役：深链归一回落 system
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

    // ========== 未保存修改拦截弹窗（保存/放弃/取消三选，window.confirm 退役）==========
    // 用户口径：确认键默认语义应是「保存」，而非「丢弃」——故弹窗主按钮=保存修改（右）、
    // 次按钮=放弃修改（左），另留 ESC/关闭=取消不动。resolve(true)=继续后续动作。
    type UnsavedGuardScene = 'create' | 'duplicate' | 'switch'
    const [unsavedGuard, setUnsavedGuard] = useState<{ scene: UnsavedGuardScene; resolve: (ok: boolean) => void } | null>(null)
    const [guardSaving, setGuardSaving] = useState(false)
    const confirmUnsavedGuard = useCallback(async (scene: UnsavedGuardScene): Promise<boolean> => {
        if (!isDirtyRef.current) return true // 无脏改动直接放行
        return new Promise<boolean>((resolve) => {
            // 理论上不会并发（按钮点击后弹窗模态），防御性兜底：后到者先取消前者
            setUnsavedGuard(prev => { prev?.resolve(false); return { scene, resolve } })
        })
    }, [])
    const resolveGuard = useCallback(async (choice: 'save' | 'discard' | 'cancel') => {
        const current = unsavedGuard
        if (!current) return
        if (choice === 'cancel') {
            setUnsavedGuard(null)
            current.resolve(false)
            return
        }
        if (choice === 'save') {
            setGuardSaving(true)
            try {
                const savedId = await handleSave()
                if (!savedId) { setGuardSaving(false); return } // 保存失败（已有 alert），留在弹窗让用户重选
                // handleSave 成功路径自身已置 isDirtyRef=false、内部 await fetchConfig()
                // （内含 resumesRef 同步刷新），保存后的最新列表在此处已可读
            } finally {
                setGuardSaving(false)
            }
        }
        if (choice === 'discard') {
            // 放弃 = 丢弃当前未保存修改（内容仍在本机草稿槽，切回时可恢复），脏标记必须同步
            // 复位，否则 hasUnsavedChanges/confirmUnsavedGuard 永远拦截，用户陷入弹窗死循环
            isDirtyRef.current = false
        }
        setUnsavedGuard(null)
        current.resolve(true)
        // handleSave 为稳定引用（每渲染重建但内部仅依赖 ref/state），此处不列入依赖防弹窗期间重挂
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [unsavedGuard])
    // editingItem 的 ref 镜像（草稿写入守卫用；sectionRef 复用下方既有声明）
    const editingItemRef = useRef<StrategyItem | null>(editingItem)
    useEffect(() => { editingItemRef.current = editingItem }, [editingItem])
    // resumes 的 ref 镜像：异步回调（拦截弹窗保存后继续）里读最新列表用，防闭包快照陈旧
    const resumesRef = useRef<StrategyItem[]>(resumes)
    useEffect(() => { resumesRef.current = resumes }, [resumes])
    // 进程启动时原子清理过期草稿槽与登记表（含已删除简历的残留槽位、非 temp_ 垃圾行）
    useEffect(() => { purgeExpiredResumeRegistry() }, [])
    // 关页/卸载时把所有待写草稿立即落盘（pagehide 不触发 React unmount，需单独监听）
    useEffect(() => {
        const onPageHide = () => resumeDraftScheduler.flushAll()
        window.addEventListener("pagehide", onPageHide)
        return () => {
            window.removeEventListener("pagehide", onPageHide)
            resumeDraftScheduler.flushAll()
        }
    }, [])

    // 画布任何变更（正文/经历/个人信息/头像）都视为有未保存修改
    useEffect(() => {
        const unsub = useResumeV2Store.subscribe((state, prev) => {
            if (suppressDirtyRef.current) return
            if (state.resumeData !== prev.resumeData) {
                // dirty 语义与全仓保持一致（无条件置位，不得收窄）；
                // 草稿写入另设守卫：仅简历库上下文且归属明确时落本机
                isDirtyRef.current = true
                if (sectionRef.current !== 'resume' || !editingItemRef.current) return
                const draftOwner = v2OwnerRef.current
                // 空归属（异常兜底）与历史 local-draft 固定槽位一律不落草稿
                if (!draftOwner || draftOwner === RESUME_DRAFT_LOCAL_KEY) return
                // id 与 name 在同一语句快照，登记表与草稿槽同步归属（防切库窗口串写）
                const draftName = editingItemRef.current?.name || ""
                // owner 与数据快照在排期时绑定，触发时零可变引用——切换/保存互不干扰
                // （草稿定时器串写问题已改 per-owner 排期器根治）
                resumeDraftScheduler.schedule(draftOwner, state.resumeData)
                // 空名窗口（editingItem 尚未带 name）跳过登记但草稿排期照旧——
                // name 是未保存项刷新后唯一可辨识信息，不允许被空串覆写
                if (draftName) upsertLocalResume(draftOwner, draftName)
            }
        })
        return unsub
    }, [])

    useEffect(() => {
        if (section !== 'resume' || !editingItem) return
        // ownerKey 口径必须与 handleSave 的归属校验一致（record_id || ""）；
        // 新建记录由 handleCreateNew 发放 temp_ 前缀 id（草稿槽独立且保存链路已识别 temp_ 为新建）
        const ownerKey = editingItem.record_id || ""
        if (skipNextV2LoadRef.current) {
            // 恢复暂存现场（draftStash）：画布数据本身就是该 owner 的未保存内容，
            // store 数据与新 owner 天然同源，无需重载（agy double-check R2 H2）
            skipNextV2LoadRef.current = false
            v2OwnerRef.current = ownerKey
            return
        }
        // isDirty 守卫（七项修复#4 防御加固）：画布有未保存修改且归属未变时，
        // 外部引发的 structured_json 引用变化不得覆盖画布（防被动丢稿）
        if (isDirtyRef.current && v2OwnerRef.current === ownerKey) return

        const json = editingItem.structured_json
        isDirtyRef.current = false
        suppressDirtyRef.current = true
        try {
            // 本机草稿优先（仅限已同步到飞书的记录；新建未同步记录不读写固定槽位，
            // 防多张未保存新简历互相串写——R2 审查 H8）。草稿存在 = 上次在本机有未保存
            // 的修改（保存成功即清草稿）。草稿与云端数据一致时静默采用；不一致时恢复
            // 草稿并明示「点保存将以本机稿为准」的覆盖语义。
            const draft = editingItem.record_id ? readResumeDraft(ownerKey) : null
            let restoredDraft = false
            if (draft?.structured && Object.keys(draft.structured).length > 0) {
                const cloudJson = json && typeof json === 'object' ? JSON.stringify(json) : ""
                if (cloudJson && JSON.stringify(draft.structured) === cloudJson) {
                    useResumeV2Store.getState().setResumeData(draft.structured)
                } else {
                    useResumeV2Store.getState().setResumeData(draft.structured)
                    restoredDraft = true
                    const mins = Math.max(1, Math.round((Date.now() - draft.savedAt) / 60000))
                    showToast(`已恢复本机未保存草稿（${mins >= 60 ? `${Math.round(mins / 60)} 小时` : `${mins} 分钟`}前修改，仅存本机）。点「保存并同步」将以本机稿为准`)
                }
            } else if (json && typeof json === 'object' && Object.keys(json).length > 0) {
                useResumeV2Store.getState().setResumeData(json)
            } else {
                useResumeV2Store.getState().setResumeData(createEmptyResume())
            }
            // 归属更新放在数据写入成功之后：v2OwnerRef 与 store 内容严格同源，
            // 即使本 try 意外抛错，ref 仍指旧归属，不会出现 (新owner, 旧数据) 排期组合
            v2OwnerRef.current = ownerKey
            // 恢复的是与云端不一致的草稿 = 存在未保存修改，补记 dirty（否则
            // hasUnsavedChanges 拦截/未保存提示全程不亮，与「草稿=未保存」语义矛盾）
            if (restoredDraft) isDirtyRef.current = true
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
                // 合并本地未保存简历（temp_ 项，刷新丢稿根治立项）：
                // 云端优先展示、本地项 append；merge 内部带云端去重与全量异常兜底
                const mergedResumes: StrategyItem[] = [...mappedResumes, ...mergeLocalResumes(mappedResumes)]
                setResumes(mergedResumes)
                // 同步刷新 ref 镜像（不等 useEffect）：异步回调链（拦截弹窗保存→继续复制/切换）
                // 恢复执行时读 resumesRef 拿到的就是刚 fetch 的最新列表
                resumesRef.current = mergedResumes

                if (currentEditingId) {
                    const target = mergedResumes.find((i: any) => i.record_id === currentEditingId)
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
        // temp_ 项尚未同步飞书，activate_resume 必然假失败（未保存项操作入口逐一排查覆盖）
        if (isTempResumeId(item.record_id)) {
            showToast('⚠️ 该简历尚未保存到飞书，请先点「保存并同步」')
            return
        }
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
        void confirmUnsavedGuard('create').then((proceed) => {
            if (!proceed) return
            // temp_ 前缀 id：让新建简历拥有独立草稿槽——新建最容易整篇丢内容，
            // 不应被排除在草稿机制外；保存链路本就把 temp_ 识别为新建（不传 record_id）
            const newTempId = makeTempResumeId()
            const newItem: StrategyItem = {
                name: '新建简历版本',
                content: DEFAULT_RESUME_MARKDOWN,
                status: '停用',
                record_id: newTempId,
                structured_json: createEmptyResume(),
            }
            // 立即进入左侧「我的简历」列表（置顶）：用户能直观看到"真的新建了一份"。
            // 数据本体仍只在本机（草稿槽/登记表），点「保存并同步」才落飞书简历表
            setResumes(prev => [newItem, ...prev.filter(r => r.record_id !== newTempId)])
            setEditingItem(newItem)
            // 登记本地未保存项：刷新后侧边栏仍可见、可点开恢复（刷新丢稿根治立项）
            upsertLocalResume(newTempId, '新建简历版本')
        })
    }

    const handleDuplicate = (id: string) => {
        void confirmUnsavedGuard('duplicate').then((proceed) => {
            if (!proceed) return
            // resumesRef 镜像最新列表：拦截弹窗选「保存修改」后 handleSave→fetchConfig 已刷新
            // resumes，闭包里的旧快照会把保存前的陈旧内容复制进副本
            let sourceId = id
            let itemToCopy = resumesRef.current.find(r => r.record_id === sourceId)
            // 弹窗里「保存修改」可能刚把 temp_ 草稿转正（旧 id 已不在列表）：
            // 按 editingItem 的当前归属找（fetchConfig 已把 editingItem 指向转正后的真实记录）
            if (!itemToCopy && editingItemRef.current?.name) {
                itemToCopy = resumesRef.current.find(r => r.name === editingItemRef.current!.name)
                if (itemToCopy) sourceId = itemToCopy.record_id || id
            }
            if (!itemToCopy) return

            const tempId = makeTempResumeId()
            const duplicatedItem: StrategyItem = {
                ...itemToCopy,
                name: `${itemToCopy.name} - 副本`,
                status: '停用',
                record_id: tempId
            }

            // 副本同样立即进入列表（插在源简历之后）：与新建一致的"看得见"体验；
            // 用解析出的 sourceId 定位（id 可能已因 temp_ 转正而失效），找不到则插到最前
            setResumes(prev => {
                const copy = [...prev]
                const srcIdx = copy.findIndex(r => r.record_id === sourceId)
                if (srcIdx >= 0) copy.splice(srcIdx + 1, 0, duplicatedItem)
                else copy.unshift(duplicatedItem)
                return copy
            })

            // 刷新丢稿根治：副本登记入本地未保存列表 + 结构化内容同步写一次草稿槽——
            // 复制后未编辑即刷新也能恢复源内容（agy plan-review R1 P0-3）
            upsertLocalResume(tempId, duplicatedItem.name, itemToCopy.content)
            if (itemToCopy.structured_json && typeof itemToCopy.structured_json === 'object') {
                writeResumeDraft(tempId, itemToCopy.structured_json)
            }

            setEditingItem(duplicatedItem)
            showToast('已为您创建副本，请修改后点击右上角「保存并同步」')
        })
    }

    const handleSave = async (): Promise<string | null> => {
        if (!editingItem || !editingItem.name.trim()) { alert("名称不能为空！"); return null }
        if (savingRef.current) return null
        savingRef.current = true
        setSaving(true)

        let payloadFields: any = {};
        let snapshotId: string | undefined = undefined;
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
            snapshotId = (latestJsonToSave as { _meta?: { snapshot_id?: string } })?._meta?.snapshot_id;
        }

        const actualRecordId = editingItem.record_id?.startsWith('temp_') ? undefined : editingItem.record_id;
        const payload = {
            table_type: "resume", record_id: actualRecordId,
            fields: payloadFields,
            // 原文快照 ID：后端据此写飞书快照字段并记录「初始解析 vs 本次保存」修正回流（老简历无此值）
            snapshot_id: snapshotId
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
                // 保存成功：丢弃本记录待写的草稿定时器（云端已最新，不能再写回草稿槽），
                // 清空本机草稿；并从本地未保存登记表移除（转正后飞书列表自然含它）；
                // 旧槽（temp_ 或无 id）已由上面 clearResumeDraft 覆盖
                resumeDraftScheduler.discardOwner(editingItem.record_id || RESUME_DRAFT_LOCAL_KEY)
                clearResumeDraft(editingItem.record_id || RESUME_DRAFT_LOCAL_KEY)
                removeLocalResume(editingItem.record_id || RESUME_DRAFT_LOCAL_KEY)
                setEditingItem(prev => prev ? { ...prev, record_id: newRecordId } : null)
                // 必须等待：resolveGuard('save') 在本函数返回后立即读 resumesRef，
                // 不 await 则 ref 仍是旧列表，temp_ 转正场景下副本会找不到源记录
                await fetchConfig(newRecordId)
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
        if (isTempResumeId(item.record_id)) {
            resumeDraftScheduler.discardOwner(item.record_id) // 取消在途排期，防复活刚清的槽（R1 P1-2）
            removeLocalResume(item.record_id)
            clearResumeDraft(item.record_id)
            return
        }

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
            confirmUnsavedGuard,
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
            {/* 未保存修改拦截：主按钮=保存修改（右，用户默认预期），次按钮=放弃修改（左） */}
            <Dialog open={unsavedGuard !== null} onOpenChange={(open) => { if (!open && !guardSaving) resolveGuard('cancel') }}>
                <DialogContent className="sm:max-w-md border-slate-200 bg-white">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2 text-base font-bold text-slate-900">
                            <FileWarning className="size-4 text-amber-500" />
                            当前简历有未保存的修改
                        </DialogTitle>
                        <DialogDescription className="mt-1 text-[13px] leading-relaxed text-slate-600">
                            {unsavedGuard?.scene === 'create' && '建议你先保存后再新建，否则这些修改将被丢弃。'}
                            {unsavedGuard?.scene === 'duplicate' && '建议你先保存后再复制，否则这些修改将丢失（复制的是已保存内容）。'}
                            {unsavedGuard?.scene === 'switch' && '建议你先保存后再切换，否则这些修改将丢失。'}
                        </DialogDescription>
                    </DialogHeader>
                    <div className="mt-2 flex items-center justify-end gap-2.5">
                        <button
                            type="button"
                            disabled={guardSaving}
                            onClick={() => resolveGuard('discard')}
                            className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-50"
                        >
                            放弃修改
                        </button>
                        <button
                            type="button"
                            disabled={guardSaving}
                            onClick={() => resolveGuard('save')}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-slate-700 disabled:opacity-60"
                        >
                            {guardSaving ? (
                                <><RefreshCw className="size-3.5 animate-spin" />正在保存...</>
                            ) : (
                                <><Save className="size-3.5" />保存修改</>
                            )}
                        </button>
                    </div>
                </DialogContent>
            </Dialog>
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
