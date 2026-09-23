// 本地未保存简历登记表纯函数用例（agy plan-review 2026-09-23 三轮收敛的落地验证）
// 覆盖：temp_ 门禁 / 读-改-写损坏自愈 / 过期锚点槽联动 / 非 temp_ 垃圾行剔除 / 写失败静默
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
    listLocalResumes,
    upsertLocalResume,
    removeLocalResume,
    purgeExpiredResumeRegistry,
    mergeLocalResumes,
} from "./resume-draft-registry"
import { writeResumeDraft, RESUME_DRAFT_TTL_MS } from "./resume-draft"
import { DEFAULT_RESUME_MARKDOWN } from "./resume-blocks"

const REGISTRY_KEY = "jobhunter:local-resumes:v1"

function rawRegistry(): any[] {
    return JSON.parse(localStorage.getItem(REGISTRY_KEY) || "[]")
}

beforeEach(() => {
    localStorage.clear()
})

afterEach(() => {
    vi.restoreAllMocks()
})

describe("upsertLocalResume", () => {
    it("仅 temp_ 前缀生效：云端正式 id 不入表", () => {
        upsertLocalResume("recABC123", "云端简历")
        expect(rawRegistry()).toHaveLength(0)
        upsertLocalResume("temp_123_abc", "本地新建")
        expect(rawRegistry()).toHaveLength(1)
    })

    it("name/content 均未变化时跳过写盘（写放大优化，setItem 调用次数断言）", () => {
        upsertLocalResume("temp_1", "A") // 首次登记：1 次写
        const setItemSpy = vi.spyOn(Storage.prototype, "setItem")
        upsertLocalResume("temp_1", "A") // 未变化：不写盘
        upsertLocalResume("temp_1", "A") // 再未变化：仍不写
        expect(setItemSpy).not.toHaveBeenCalled()
        setItemSpy.mockRestore()
        upsertLocalResume("temp_1", "A-改名") // 变化：写
        expect(rawRegistry()[0].name).toBe("A-改名")
    })

    it("无 content 的 upsert 保留既有 content 快照（副本首次编辑不抹快照）", () => {
        upsertLocalResume("temp_2", "源简历 - 副本", "# 源正文")
        upsertLocalResume("temp_2", "源简历 - 副本") // 画布编辑触发的 2 参 upsert
        expect(rawRegistry()[0].content).toBe("# 源正文") // 快照仍在
    })

    it("空 name 的 upsert 保留既有 name（name 是未保存项刷新后唯一可辨识信息，不允许被清空）", () => {
        upsertLocalResume("temp_3", "有名字的简历")
        upsertLocalResume("temp_3", "") // 空名窗口（防御：store 已守卫，registry 二道防线）
        expect(rawRegistry()[0].name).toBe("有名字的简历")
    })

    it("容量上限：超过 50 条剔除 savedAt 最旧的项（含其草稿槽）", () => {
        for (let i = 0; i < 51; i++) {
            upsertLocalResume(`temp_bulk_${i}`, `简历${i}`)
        }
        const items = rawRegistry()
        expect(items).toHaveLength(50)
        expect(items.some((i: any) => i.record_id === "temp_bulk_0")).toBe(false) // 最旧被剔
        expect(items.some((i: any) => i.record_id === "temp_bulk_50")).toBe(true) // 最新保留
        expect(localStorage.getItem("jobhunter:resume-draft:v1:temp_bulk_0")).toBeNull() // 槽同清
    })
})

describe("mergeLocalResumes 列表合并（fetchConfig 生产路径核心分支）", () => {
    it("云端同名项被剔除（去重防御纵深），本地项按登记顺序返回", () => {
        upsertLocalResume("temp_1", "本地甲")
        upsertLocalResume("temp_2", "本地乙")
        // 混入一条与云端同 record_id 的脏数据（历史脏数据场景）
        localStorage.setItem(
            REGISTRY_KEY,
            JSON.stringify([...rawRegistry(), { record_id: "recCloud", name: "脏数据", content: "# 脏", savedAt: Date.now() }])
        )
        const merged = mergeLocalResumes([{ record_id: "recCloud" }, { record_id: "recOther" }])
        expect(merged.map(i => i.record_id)).toEqual(["temp_1", "temp_2"]) // recCloud 被剔除
    })

    it("无 content 快照的登记项映射为默认模板；status 固定停用", () => {
        upsertLocalResume("temp_1", "新建未编辑") // 新建项无 content 快照
        const merged = mergeLocalResumes([])
        expect(merged).toHaveLength(1)
        expect(merged[0].content).toBe(DEFAULT_RESUME_MARKDOWN)
        expect(merged[0].status).toBe("停用")
    })
})

describe("损坏登记表自愈（含备份键回收）", () => {
    it("损坏 JSON：备份原值 → 重置空表 → 后续写恢复；不静默覆盖损坏数据", () => {
        const corrupt = "{broken json!!"
        localStorage.setItem(REGISTRY_KEY, corrupt)
        const { readFailed } = listLocalResumes()
        expect(readFailed).toBe(true)
        // 备份存在且内容为损坏原值
        const backupKey = Object.keys(localStorage).find(k => k.startsWith(REGISTRY_KEY + ".corrupt-"))
        expect(backupKey).toBeTruthy()
        expect(localStorage.getItem(backupKey!)).toBe(corrupt)
        // 主表已重置，后续写恢复正常
        upsertLocalResume("temp_9", "恢复后写入")
        expect(rawRegistry()).toHaveLength(1)
    })

    it("损坏备份键（.corrupt-*）由 purge 按 TTL 回收，防全文快照永久残留", () => {
        const stale = Date.now() - RESUME_DRAFT_TTL_MS - 1000
        localStorage.setItem(`${REGISTRY_KEY}.corrupt-${stale}`, "{old}")
        localStorage.setItem(`${REGISTRY_KEY}.corrupt-${stale + 500}`, "{newer}")
        purgeExpiredResumeRegistry()
        const remaining = Object.keys(localStorage).filter(k => k.startsWith(REGISTRY_KEY + ".corrupt-"))
        expect(remaining).toHaveLength(0) // 两份均超 TTL → 全删
    })

    it("损坏备份键未超 TTL：多份并发只保留最新一份", () => {
        localStorage.setItem(`${REGISTRY_KEY}.corrupt-${Date.now() - 5000}`, "{old}")
        localStorage.setItem(`${REGISTRY_KEY}.corrupt-${Date.now() - 1000}`, "{new}")
        purgeExpiredResumeRegistry()
        const remaining = Object.keys(localStorage).filter(k => k.startsWith(REGISTRY_KEY + ".corrupt-"))
        expect(remaining).toHaveLength(1)
        expect(localStorage.getItem(remaining[0])).toBe("{new}")
    })
})

describe("purgeExpiredResumeRegistry 过期锚点槽联动（agy plan-review R2 H3/R3 P1-2）", () => {
    it("活跃编辑（槽新鲜）→ 登记表 savedAt 虽过期也不误清", () => {
        upsertLocalResume("temp_1", "活跃草稿")
        // 登记表 savedAt 人为拨老（超过 TTL），但草稿槽刚写入（新鲜）
        const aged = rawRegistry().map(i => ({ ...i, savedAt: Date.now() - RESUME_DRAFT_TTL_MS - 1000 }))
        localStorage.setItem(REGISTRY_KEY, JSON.stringify(aged))
        writeResumeDraft("temp_1", { summary: "编辑中" })

        purgeExpiredResumeRegistry()
        expect(listLocalResumes().items).toHaveLength(1)
        expect(localStorage.getItem("jobhunter:resume-draft:v1:temp_1")).toBeTruthy()
    })

    it("新建未编辑（槽缺失）→ 7 天宽限期内保留，期满清除", () => {
        upsertLocalResume("temp_1", "新建未编辑")
        purgeExpiredResumeRegistry()
        expect(listLocalResumes().items).toHaveLength(1) // 宽限期内不清

        const aged = rawRegistry().map(i => ({ ...i, savedAt: Date.now() - RESUME_DRAFT_TTL_MS - 1000 }))
        localStorage.setItem(REGISTRY_KEY, JSON.stringify(aged))
        purgeExpiredResumeRegistry()
        expect(listLocalResumes().items).toHaveLength(0)
    })

    it("槽过期 → 槽与登记表项同清；非 temp_ 垃圾行一律剔除", () => {
        upsertLocalResume("temp_1", "旧草稿")
        writeResumeDraft("temp_1", { summary: "old" })
        // 人为把槽拨老
        const slotKey = "jobhunter:resume-draft:v1:temp_1"
        const slot = JSON.parse(localStorage.getItem(slotKey)!)
        slot.savedAt = Date.now() - RESUME_DRAFT_TTL_MS - 1000
        localStorage.setItem(slotKey, JSON.stringify(slot))
        // 混入非 temp_ 垃圾行
        localStorage.setItem(REGISTRY_KEY, JSON.stringify([...rawRegistry(), { record_id: "recCloud", name: "脏数据", savedAt: Date.now() }]))

        purgeExpiredResumeRegistry()
        expect(listLocalResumes().items).toHaveLength(0)
        expect(localStorage.getItem(slotKey)).toBeNull()
    })
})

describe("removeLocalResume 与写失败静默", () => {
    it("remove 移除目标项", () => {
        upsertLocalResume("temp_1", "A")
        upsertLocalResume("temp_2", "B")
        removeLocalResume("temp_1")
        expect(rawRegistry().map((i: any) => i.record_id)).toEqual(["temp_2"])
    })

    it("localStorage.setItem 抛错（配额满等）：静默不打断主流程", () => {
        upsertLocalResume("temp_1", "A") // 先建立表（读成功）
        const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
            throw new Error("QuotaExceededError")
        })
        expect(() => upsertLocalResume("temp_1", "A-改名")).not.toThrow()
        expect(() => removeLocalResume("temp_1")).not.toThrow()
        expect(() => purgeExpiredResumeRegistry()).not.toThrow()
        spy.mockRestore()
    })
})
