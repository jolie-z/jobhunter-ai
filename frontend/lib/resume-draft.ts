// 简历本机草稿（localStorage 槽位）+ 防抖排期器
//
// 槽位（2026-09-23 简历库七项修复#4，自 use-strategy-store.tsx 下沉）：
//   key = jobhunter:resume-draft:v1:<record_id>，值 = { savedAt, structured }
//   写入 = 画布变更经 createDraftScheduler 防抖；恢复 = load effect 选中时本机稿优先；
//   清除 = 保存并同步成功 / 记录删除；过期 = purgeExpiredResumeRegistry（见 resume-draft-registry.ts，
//   与登记表同一次扫描原子清理）。
// 边界：仅存用户本机浏览器（明文，7 天 TTL）；落飞书仍只由「保存并同步」显式触发。
// 注意：槽位仅服务已同步飞书的记录与 temp_ 新建记录（temp_ 由 handleCreateNew/handleDuplicate
// 发放），历史遗留的 local-draft 固定槽位已废弃，常量仅保留作清理与哨兵用途。

export const RESUME_DRAFT_KEY_PREFIX = "jobhunter:resume-draft:v1:"
export const RESUME_DRAFT_TTL_MS = 7 * 24 * 3600 * 1000
/** 历史遗留：曾作新建简历的固定槽位（已被 temp_ 随机 id 取代），现仅剩清理与哨兵用途 */
export const RESUME_DRAFT_LOCAL_KEY = "local-draft"
/** 画布变更 → 草稿落盘的防抖间隔（store 与测试共同引用，避免双处维护） */
export const RESUME_DRAFT_DEBOUNCE_MS = 2000

export interface ResumeDraftPayload {
    savedAt: number
    /** 结构化简历内容（ResumeDataV2）；any 以兼容 store 历史消费方的直接赋值 */
    structured: any
}

export function readResumeDraft(recordKey: string): ResumeDraftPayload | null {
    if (typeof window === "undefined" || !recordKey) return null
    try {
        const raw = window.localStorage.getItem(RESUME_DRAFT_KEY_PREFIX + recordKey)
        if (!raw) return null
        const parsed = JSON.parse(raw) as ResumeDraftPayload
        if (!parsed?.savedAt || typeof parsed.structured !== "object" || Date.now() - parsed.savedAt > RESUME_DRAFT_TTL_MS) {
            window.localStorage.removeItem(RESUME_DRAFT_KEY_PREFIX + recordKey)
            return null
        }
        return parsed
    } catch {
        return null
    }
}

export function writeResumeDraft(recordKey: string, structured: any) {
    if (typeof window === "undefined" || !recordKey || !structured) return
    try {
        const payload: ResumeDraftPayload = { savedAt: Date.now(), structured }
        window.localStorage.setItem(RESUME_DRAFT_KEY_PREFIX + recordKey, JSON.stringify(payload))
    } catch {
        // 存储空间满等异常静默：草稿是尽力而为的兜底，不阻塞编辑主流程
    }
}

export function clearResumeDraft(recordKey: string) {
    if (typeof window === "undefined" || !recordKey) return
    try {
        window.localStorage.removeItem(RESUME_DRAFT_KEY_PREFIX + recordKey)
    } catch {
        // 同上，静默
    }
}

export function peekResumeDraftSavedAt(recordKey: string): number | null {
    if (typeof window === "undefined" || !recordKey) return null
    try {
        const raw = window.localStorage.getItem(RESUME_DRAFT_KEY_PREFIX + recordKey)
        if (!raw) return null
        const parsed = JSON.parse(raw) as ResumeDraftPayload
        return parsed?.savedAt ?? null
    } catch {
        return null
    }
}

// ---------------------------------------------------------------------------
// 防抖排期器：per-owner 独立定时器 + 排期时绑定数据快照
// （时序竞态设计与用例见 resume-draft.test.ts）
// ---------------------------------------------------------------------------

export type DraftWriteFn = (owner: string, data: unknown) => void

export interface DraftScheduler {
    /** 为 owner 排期一次防抖写入；同 owner 重排期会覆盖上一次（数据以最后一次为准） */
    schedule: (owner: string, data: unknown) => void
    /** 保存成功后调用：丢弃 owner 的待写定时器（云端已是最新，不能再写回草稿槽） */
    discardOwner: (owner: string) => void
    /** 立即落盘所有待写草稿并清空（pagehide/关页/卸载时调用；关页不触发 React unmount） */
    flushAll: () => void
    /** 测试探针：待写集合（生产代码不消费） */
    pendingOwners: () => string[]
}

export function createDraftScheduler(write: DraftWriteFn, delayMs: number): DraftScheduler {
    // owner -> { timer, data }。data 是排期时的 structuredClone 深拷贝快照，与 owner 在
    // 同一次调用中绑定，触发时不再读任何可变引用（根治"触发时 owner 已漂移"的跨记录串写；
    // 深拷贝同时隔离下游对嵌套字段的就地变异）
    const pending = new Map<string, { timer: ReturnType<typeof setTimeout>; data: unknown }>()

    return {
        schedule(owner, data) {
            if (!owner || !data) return
            const prev = pending.get(owner)
            if (prev) clearTimeout(prev.timer)
            const snapshot = structuredClone(data)
            const timer = setTimeout(() => {
                pending.delete(owner)
                write(owner, snapshot)
            }, delayMs)
            pending.set(owner, { timer, data: snapshot })
        },
        discardOwner(owner) {
            const prev = pending.get(owner)
            if (prev) {
                clearTimeout(prev.timer)
                pending.delete(owner)
            }
        },
        flushAll() {
            for (const [owner, entry] of pending) {
                clearTimeout(entry.timer)
                write(owner, entry.data)
            }
            pending.clear()
        },
        pendingOwners() {
            return [...pending.keys()]
        },
    }
}
