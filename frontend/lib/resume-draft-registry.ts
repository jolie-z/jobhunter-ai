// 本地未保存简历登记表（2026-09-23 立项：新建/复制简历刷新丢稿根治）
//
// 解决的问题：新建/复制产生的未保存简历（temp_ 前缀 id）此前只存在于内存，
// 刷新后飞书列表恢复不出它，草稿槽虽在但无入口可达。登记表记录这些 temp_ 项的
// 元数据（record_id/name/content 快照），fetchConfig 恢复列表时合并进侧边栏；
// 选中后由 load effect 读草稿槽恢复内容本体。
//
// 设计约束（2026-09-23 方案审查多轮收敛）：
// - 仅登记 temp_ 前缀 id（门禁在 upsert 内）——云端正式记录永不入表，杜绝列表重复；
// - content? 快照仅 handleDuplicate 携带（源简历 content）；新建不携带（映射取默认模板）。
//   前提不变量：简历库 UI 内不存在 content 编辑入口（__tests__/resume-content-invariant.test.ts 锁定）；
// - readFailed 哨兵：登记表损坏时备份原值并重置空表，写路径恢复，不做永久静默；
//   备份键（.corrupt-<ts>）由 purge 按 TTL 回收，防全文快照永久残留本机；
// - 过期锚点：槽存在按槽 savedAt、槽缺失按登记表 savedAt（TTL 同 7 天）——活跃编辑永不误清，
//   新建未编辑项 7 天内保留；purge 同一次扫描原子清理「草稿槽 + 登记表」并剔除非 temp_ 垃圾行。
// 已知限制：多标签页并发为 last-write-wins（单用户单标签场景）。

import {
    RESUME_DRAFT_KEY_PREFIX,
    RESUME_DRAFT_TTL_MS,
    peekResumeDraftSavedAt,
    clearResumeDraft,
} from "./resume-draft"
import { DEFAULT_RESUME_MARKDOWN } from "./resume-blocks"

const LOCAL_RESUME_REGISTRY_KEY = "jobhunter:local-resumes:v1"

export interface LocalResumeMeta {
    record_id: string
    name: string
    /** 内容快照：仅 handleDuplicate 携带（源 content）；新建项缺省 → 映射取默认模板 */
    content?: string
    savedAt: number
}

/** 登记表容量上限：单条含整篇 markdown 快照，超限剔最旧防配额撑爆使「刷新不丢」静默失效 */
const MAX_REGISTRY_ENTRIES = 50

/**
 * temp_ 未保存简历 id 工厂（前缀单源）：
 * 毫秒时间戳 + 随机后缀，防同一毫秒连发的 id 碰撞。
 */
export function makeTempResumeId(): string {
    return `temp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

/** temp_ 前缀判断的对外单源（store 等处共用，防字面量散落） */
export function isTempResumeId(recordId: string | undefined | null): boolean {
    return !!recordId && recordId.startsWith("temp_")
}

/**
 * 读取登记表。损坏时备份原值（*.corrupt-<ts>）并重置空表、console.warn 一次——
 * 写路径随之自然恢复，不做永久静默禁写；备份键由 purgeExpiredResumeRegistry 按 TTL 回收。
 */
export function listLocalResumes(): { items: LocalResumeMeta[]; readFailed: boolean } {
    if (typeof window === "undefined") return { items: [], readFailed: false }
    try {
        const raw = window.localStorage.getItem(LOCAL_RESUME_REGISTRY_KEY)
        if (!raw) return { items: [], readFailed: false }
        const parsed = JSON.parse(raw) as LocalResumeMeta[]
        if (!Array.isArray(parsed)) throw new Error("registry not an array")
        return { items: parsed.filter(i => i?.record_id), readFailed: false }
    } catch {
        // 自愈：备份损坏原值（带时间戳防覆盖）→ 重置空表 → 告警一次
        try {
            const raw = window.localStorage.getItem(LOCAL_RESUME_REGISTRY_KEY)
            if (raw) {
                window.localStorage.setItem(`${LOCAL_RESUME_REGISTRY_KEY}.corrupt-${Date.now()}`, raw)
                window.localStorage.removeItem(LOCAL_RESUME_REGISTRY_KEY)
            }
            console.warn("[resume-draft-registry] 登记表损坏，已备份并重置（后续保存恢复正常）")
        } catch {
            // 备份也失败（如配额满）：保持静默降级
        }
        return { items: [], readFailed: true }
    }
}

function writeRegistry(items: LocalResumeMeta[]) {
    window.localStorage.setItem(LOCAL_RESUME_REGISTRY_KEY, JSON.stringify(items))
}

/** 登记或更新一个未保存简历（仅 temp_ 前缀生效；name/content 均未变化时跳过写盘防写放大） */
export function upsertLocalResume(recordId: string, name: string, content?: string) {
    if (typeof window === "undefined") return
    if (!isTempResumeId(recordId)) return // 门禁：云端正式记录永不入表
    try {
        const { items } = listLocalResumes()
        const existing = items.find(i => i.record_id === recordId)
        // 空名防御（二道防线，store 层已有主守卫）：name 是未保存项刷新后唯一可辨识
        // 信息——空名沿用既有名；新项无既有名则无事可登记，拒绝空名覆写/入表
        const safeName = name || existing?.name || ""
        if (!safeName) return
        const nextContent = content !== undefined ? content : existing?.content // 无参 upsert 保留既有快照
        const contentUnchanged = existing && (existing.content ?? undefined) === (nextContent ?? undefined)
        if (existing && existing.name === safeName && contentUnchanged) return // 写放大优化
        const next = items.filter(i => i.record_id !== recordId)
        next.push({
            record_id: recordId,
            name: safeName,
            ...(nextContent !== undefined ? { content: nextContent } : {}),
            savedAt: Date.now(),
        })
        // 容量上限：超限剔最旧（连草稿槽一起清，防孤儿槽与全文快照长期驻留）
        while (next.length > MAX_REGISTRY_ENTRIES) {
            let oldestIdx = 0
            for (let i = 1; i < next.length; i++) {
                if (next[i].savedAt < next[oldestIdx].savedAt) oldestIdx = i
            }
            clearResumeDraft(next[oldestIdx].record_id)
            next.splice(oldestIdx, 1)
        }
        writeRegistry(next)
    } catch {
        // 配额满/隐私模式等：登记是尽力而为，不阻塞创建/编辑主流程
    }
}

/** 移除登记项（保存转正 / 用户删除时调用） */
export function removeLocalResume(recordId: string) {
    if (typeof window === "undefined" || !recordId) return
    try {
        const { items } = listLocalResumes()
        const next = items.filter(i => i.record_id !== recordId)
        if (next.length !== items.length) writeRegistry(next)
    } catch {
        // 静默
    }
}

/** 未保存简历项（与 StrategyItem 结构化兼容：缺省 avatar_url/structured_json 均为可选字段） */
export interface UnsavedResumeItem {
    record_id: string
    name: string
    content: string
    status: string
}

/**
 * 与飞书列表合并：产出未保存简历项（append 在云端之后）。
 * 显式构造返回对象避免泛型欺骗；云端 Set 去重作防御纵深（防历史脏数据）。
 */
export function mergeLocalResumes(mappedResumes: Array<{ record_id?: string }>): UnsavedResumeItem[] {
    const cloudIds = new Set(mappedResumes.map(r => r.record_id).filter(Boolean) as string[])
    const { items } = listLocalResumes()
    return items
        .filter(i => !cloudIds.has(i.record_id))
        .map(i => ({
            record_id: i.record_id,
            name: i.name,
            content: i.content ?? DEFAULT_RESUME_MARKDOWN,
            status: "停用",
        }))
}

/**
 * 过期清理（与草稿槽同一次扫描原子处理）：
 * 判定顺序至关重要——必须先在槽仍在盘上时读其 savedAt 完成登记表判定，再删槽；
 * 反过来会把"槽过期"误判成"槽缺失"走宽限分支（写用例时实测抓到）。
 * - 登记表项过期锚点：槽存在按槽 savedAt、槽缺失按登记表 savedAt（TTL 同 7 天）——
 *   活跃编辑永不误清，新建未编辑项 7 天内保留；
 * - 非 temp_ 条目（历史脏数据）一律剔除；无登记项的孤儿过期槽（已删简历残留）同轮清理；
 * - 损坏备份键（.corrupt-<ts>，内容是含全文快照的登记表原值）按 TTL 回收且只留最新一份。
 */
export function purgeExpiredResumeRegistry() {
    if (typeof window === "undefined") return
    try {
        const now = Date.now()
        const { items } = listLocalResumes()

        // 1) 登记表判定（槽尚在盘上，可读真实 savedAt）
        const kept: LocalResumeMeta[] = []
        const droppedIds: string[] = []
        for (const i of items) {
            if (!isTempResumeId(i.record_id)) { droppedIds.push(i.record_id); continue } // 垃圾行：仅剔登记，
            // 不动槽——其 id 可能正是云端正式记录，槽是用户正常编辑的草稿
            const draftSavedAt = peekResumeDraftSavedAt(i.record_id)
            const expired = draftSavedAt
                ? now - draftSavedAt > RESUME_DRAFT_TTL_MS
                : now - i.savedAt > RESUME_DRAFT_TTL_MS
            if (expired) droppedIds.push(i.record_id)
            else kept.push(i)
        }
        if (droppedIds.length > 0) writeRegistry(kept)

        // 2) 被清的 temp_ 项连槽删除（垃圾行的槽不动，由步骤 3 按过期口径兜底）
        droppedIds.forEach(id => { if (isTempResumeId(id)) clearResumeDraft(id) })

        // 3) 孤儿过期槽清理（无登记项的残留槽，如已删除简历）
        const liveIds = new Set(kept.map(i => i.record_id))
        const orphanKeys: string[] = []
        for (let i = 0; i < window.localStorage.length; i++) {
            const key = window.localStorage.key(i)
            if (!key || !key.startsWith(RESUME_DRAFT_KEY_PREFIX)) continue
            const id = key.slice(RESUME_DRAFT_KEY_PREFIX.length)
            if (liveIds.has(id)) continue // 活跃项的槽由上面的过期判定负责
            const savedAt = peekResumeDraftSavedAt(id)
            if (!savedAt || now - savedAt > RESUME_DRAFT_TTL_MS) orphanKeys.push(key)
        }
        orphanKeys.forEach(key => window.localStorage.removeItem(key))

        // 4) 损坏备份键回收（.corrupt-<ts>）：只留最新一份，最新一份也按 7 天 TTL 删除；
        //    键名内嵌时间戳，无法解析的按垃圾处理。防全文快照永久残留本机。
        const corruptPrefix = LOCAL_RESUME_REGISTRY_KEY + ".corrupt-"
        const corruptKeys: string[] = []
        for (let i = 0; i < window.localStorage.length; i++) {
            const key = window.localStorage.key(i)
            if (key && key.startsWith(corruptPrefix)) corruptKeys.push(key)
        }
        if (corruptKeys.length > 0) {
            corruptKeys.sort((a, b) => Number(b.slice(corruptPrefix.length)) - Number(a.slice(corruptPrefix.length)))
            corruptKeys.slice(1).forEach(key => window.localStorage.removeItem(key)) // 只留最新
            const ts = Number(corruptKeys[0].slice(corruptPrefix.length))
            if (!Number.isFinite(ts) || now - ts > RESUME_DRAFT_TTL_MS) {
                window.localStorage.removeItem(corruptKeys[0])
            }
        }
    } catch {
        // 静默：清理失败不影响主流程，下轮再试
    }
}
