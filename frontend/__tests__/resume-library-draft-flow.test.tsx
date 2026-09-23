/**
 * 简历库草稿/登记表组件级时序测试（刷新丢稿根治立项）
 *
 * 用 real Provider + fake timers 把多轮审查人工推演过的时序固化为机器断言：
 * 1. 串写回归：编辑 A → 2s 内切 B → 冲刷后槽与登记表各归各主，绝不交叉（双向时间断言防假绿）
 * 2. 恢复链路：预置草稿槽 → 选中 → 画布恢复本机稿且 dirty 置位
 * 3. 列表合并 + 选中恢复：登记表 temp 项出现在 resumes、content 快照生效、草稿恢复
 * 4. 保存转正清理：handleSave 后跨冲刷点，登记表/草稿槽均不再含 temp id；
 *    转正后立即编辑新 record，排期归属必须跟着新 id 走（防旧 temp 槽复活）
 * 5. temp_ 项切换生效拦截：不发后端请求，走 toast 提示
 * 6. 复制链路：handleDuplicate 后登记表含 content 快照、草稿槽写入源结构化内容、画布切到副本
 * 7. 空名守卫：editingItem 无 name 时画布编辑只写草稿槽，登记表不被空名覆写/污染
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, act, cleanup } from "@testing-library/react"
import { useEffect } from "react"
import { StrategyStoreProvider, useStrategyStore, type StrategyItem } from "@/hooks/use-strategy-store"
import { useResumeV2Store, createEmptyResume } from "@/hooks/use-resume-v2-store"
import { RESUME_DRAFT_DEBOUNCE_MS, readResumeDraft, writeResumeDraft } from "@/lib/resume-draft"
import { listLocalResumes } from "@/lib/resume-draft-registry"
import { DEFAULT_RESUME_MARKDOWN } from "@/lib/resume-blocks"

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }))

vi.mock("@/lib/api", () => ({
    apiFetch: (url: string, init?: RequestInit) => mocks.apiFetch(url, init),
    API_BASE: "",
    getApiBase: () => "",
}))

vi.mock("@/components/dashboard/config-gate-dialog", () => ({
    ConfigGateDialog: () => null,
}))

let cloudResumes: any[]
let savedRecordId: string

function makeApi() {
    mocks.apiFetch.mockReset()
    mocks.apiFetch.mockImplementation(async (url: string) => {
        if (url.includes("/api/strategy/config")) {
            return {
                ok: true, status: 200,
                json: async () => ({ status: "success", resumes: cloudResumes }),
            } as Response
        }
        if (url.includes("/api/strategy/save")) {
            return {
                ok: true, status: 200,
                json: async () => ({ status: "success", record_id: savedRecordId }),
            } as Response
        }
        throw new Error("unexpected api: " + url)
    })
}

type StoreProbe = ReturnType<typeof useStrategyStore> & { toastMsg: string }

function Probe({ onReady }: { onReady: (s: StoreProbe) => void }) {
    const store = useStrategyStore()
    useEffect(() => { onReady(store) }) // 每次渲染上报最新句柄
    return null
}

function renderProvider(onReady: (s: StoreProbe) => void) {
    let latest: StoreProbe
    const wrapped = (s: StoreProbe) => { latest = s; onReady(s) }
    render(
        <StrategyStoreProvider>
            <Probe onReady={wrapped} />
        </StrategyStoreProvider>
    )
    return () => latest!
}

const probe = (fn: () => StoreProbe) => fn()

async function enterResumeSection(fn: () => StoreProbe) {
    await act(async () => {
        probe(fn).setSection("resume")
        await Promise.resolve()
    })
}

/** fake timers 下 waitFor 的内置轮询定时器会被冻结，改用推进假时钟的条件轮询 */
async function until(fn: () => boolean, what: string) {
    for (let i = 0; i < 100; i++) {
        if (fn()) return
        await act(async () => { await vi.advanceTimersByTimeAsync(10) })
    }
    throw new Error("condition not met: " + what)
}

describe("简历库草稿组件级时序（real Provider + fake timers）", () => {
    let probeFn: () => StoreProbe

    beforeEach(() => {
        vi.useFakeTimers()
        localStorage.clear()
        cloudResumes = [
            { record_id: "recA", version_name: "云上简历A", content: DEFAULT_RESUME_MARKDOWN, status: "停用", avatar_url: "", structured_json: { summary: "云端A原始", moduleOrder: [], moduleTitles: {} } },
            { record_id: "recB", version_name: "云上简历B", content: DEFAULT_RESUME_MARKDOWN, status: "停用", avatar_url: "", structured_json: { summary: "云端B原始", moduleOrder: [], moduleTitles: {} } },
        ]
        savedRecordId = "recSaved"
        makeApi()
        useResumeV2Store.getState().setResumeData(createEmptyResume())
    })

    afterEach(() => {
        cleanup() // RTL 卸载 Provider，防模块级 scheduler 的旧订阅跨用例写入
        vi.useRealTimers()
    })

    async function mountAndEnter() {
        await act(async () => {
            probeFn = renderProvider(vi.fn())
            await Promise.resolve()
        })
        await enterResumeSection(probeFn)
    }

    async function editCanvas(summary: string) {
        await act(async () => {
            useResumeV2Store.getState().setResumeData({ summary, moduleOrder: [], moduleTitles: {} } as any)
            await Promise.resolve()
        })
    }

    it("用例1 串写回归：编辑 A 后 2s 内切 B，草稿槽各归各主且登记表无云端项（双向断言）", async () => {
        await mountAndEnter()
        await act(async () => {
            probe(probeFn).setEditingItem(cloudResumes[0])
            await Promise.resolve()
        })
        await editCanvas("A-编辑后")
        // 未冲刷：不落盘（双向断言前半）
        await act(async () => { await vi.advanceTimersByTimeAsync(RESUME_DRAFT_DEBOUNCE_MS - 400) })
        expect(readResumeDraft("recA")).toBeNull()

        await act(async () => {
            probe(probeFn).setEditingItem(cloudResumes[1])
            await Promise.resolve()
        })
        await editCanvas("B-编辑后")
        await act(async () => { await vi.advanceTimersByTimeAsync(RESUME_DRAFT_DEBOUNCE_MS + 100) })

        const slotA = readResumeDraft("recA")
        const slotB = readResumeDraft("recB")
        expect(slotA?.structured?.summary).toBe("A-编辑后")
        expect(slotB?.structured?.summary).toBe("B-编辑后")
        expect(slotA?.structured?.summary).not.toBe("B-编辑后") // 穷尽：无交叉
        expect(slotB?.structured?.summary).not.toBe("A-编辑后")
        // 登记表：云端 id 被门禁拒绝，不入表
        expect(listLocalResumes().items).toHaveLength(0)
    })

    it("用例2 恢复链路：预置草稿槽后选中，画布恢复本机稿且 dirty 置位", async () => {
        writeResumeDraft("recA", { summary: "本机未保存稿", moduleOrder: [], moduleTitles: {} })
        await mountAndEnter()
        await until(() => probe(probeFn).resumes.length > 0, "fetchConfig 填充 resumes")
        await act(async () => {
            probe(probeFn).setEditingItem(cloudResumes[0])
            await Promise.resolve()
        })
        await until(() => useResumeV2Store.getState().resumeData?.summary === "本机未保存稿", "画布恢复本机稿")
        expect(probe(probeFn).hasUnsavedChanges()).toBe(true)
    })

    it("用例3 列表合并 + 选中恢复：temp 项出现在 resumes、content 快照生效、草稿恢复", async () => {
        const tempId = "temp_888_xyz"
        localStorage.setItem(
            "jobhunter:local-resumes:v1",
            JSON.stringify([{ record_id: tempId, name: "我的新建简历", content: "# 自定义正文", savedAt: Date.now() }])
        )
        writeResumeDraft(tempId, { summary: "新建的画布内容", moduleOrder: [], moduleTitles: {} })

        await mountAndEnter()
        await until(() => probe(probeFn).resumes.some(r => r.record_id === tempId), "resumes 含 temp 项")
        const localItem = probe(probeFn).resumes.find(r => r.record_id === tempId)!
        expect(localItem.name).toBe("我的新建简历")
        expect(localItem.content).toBe("# 自定义正文") // content 快照生效，非默认模板
        expect(localItem.status).toBe("停用")

        await act(async () => {
            probe(probeFn).setEditingItem(localItem)
            await Promise.resolve()
        })
        await until(() => useResumeV2Store.getState().resumeData?.summary === "新建的画布内容", "画布恢复草稿")
    })

    it("用例4 保存转正清理：handleSave 后跨冲刷点，登记表与草稿槽均不含 temp id", async () => {
        const tempId = "temp_777_abc"
        localStorage.setItem(
            "jobhunter:local-resumes:v1",
            JSON.stringify([{ record_id: tempId, name: "待转正", savedAt: Date.now() }])
        )
        writeResumeDraft(tempId, { summary: "待转正内容", moduleOrder: [], moduleTitles: {} })

        await mountAndEnter()
        await act(async () => {
            probe(probeFn).setEditingItem({ record_id: tempId, name: "待转正", content: DEFAULT_RESUME_MARKDOWN, status: "停用" })
            await Promise.resolve()
        })
        await editCanvas("转正前编辑") // 制造在途排期

        let savedId: string | null = null
        await act(async () => {
            savedId = await probe(probeFn).handleSave()
            await Promise.resolve()
        })
        expect(savedId).toBe("recSaved")
        // 跨过冲刷点：在途排期若未被正确丢弃，这里会复活草稿
        await act(async () => { await vi.advanceTimersByTimeAsync(RESUME_DRAFT_DEBOUNCE_MS + 200) })
        expect(readResumeDraft(tempId)).toBeNull()
        const registry = JSON.parse(localStorage.getItem("jobhunter:local-resumes:v1") || "[]")
        expect(registry.some((i: any) => i.record_id === tempId)).toBe(false)
        // 转正后的正式记录进入后续列表（fetchConfig 回调以转正 id 拉取）
        cloudResumes = [...cloudResumes, { record_id: "recSaved", version_name: "待转正", content: DEFAULT_RESUME_MARKDOWN, status: "停用", avatar_url: "", structured_json: {} }]
        await act(async () => {
            await probe(probeFn).fetchConfig("recSaved")
            await Promise.resolve()
        })
        expect(probe(probeFn).resumes.some(r => r.record_id === "recSaved")).toBe(true)

        // 转正后立即编辑新 record：排期归属必须是新正式 id（防旧 temp 槽复活/串写）
        await editCanvas("转正后编辑")
        await act(async () => { await vi.advanceTimersByTimeAsync(RESUME_DRAFT_DEBOUNCE_MS + 100) })
        expect(readResumeDraft("recSaved")?.structured?.summary).toBe("转正后编辑")
        expect(readResumeDraft(tempId)).toBeNull()
    })

    it("用例5 temp_ 项切换生效被拦截：不发后端请求，走 toast 提示", async () => {
        await mountAndEnter()
        await act(async () => {
            probe(probeFn).handleToggleResumeStatus({ stopPropagation: () => {} } as any, {
                record_id: "temp_x", name: "未保存", content: "", status: "停用",
            } as any)
            await Promise.resolve()
        })
        expect(mocks.apiFetch).not.toHaveBeenCalledWith(expect.stringContaining("activate_resume"), expect.anything())
        expect(probe(probeFn).toastMsg).toContain("保存并同步")
    })

    it("用例6 复制链路：handleDuplicate 后登记表含 content 快照、草稿槽写入源结构化内容", async () => {
        await mountAndEnter()
        await until(() => probe(probeFn).resumes.length > 0, "fetchConfig 填充 resumes")
        await act(async () => {
            probe(probeFn).handleDuplicate("recA")
            await Promise.resolve()
        })
        const reg = listLocalResumes().items
        expect(reg).toHaveLength(1)
        expect(reg[0].name).toBe("云上简历A - 副本")
        expect(reg[0].content).toBe(DEFAULT_RESUME_MARKDOWN) // 源 content 快照入表
        const slot = readResumeDraft(reg[0].record_id)
        expect(slot?.structured?.summary).toBe("云端A原始") // 源 structured_json 同步写槽
        // 画布切到副本
        await until(() => probe(probeFn).editingItem?.record_id === reg[0].record_id, "画布切到副本")
    })

    it("用例7 空名守卫：editingItem 无 name 时画布编辑只写草稿槽，登记表不被空名项污染", async () => {
        await mountAndEnter()
        await act(async () => {
            probe(probeFn).setEditingItem({ record_id: "temp_noname", name: "", content: "", status: "停用" } as StrategyItem)
            await Promise.resolve()
        })
        await editCanvas("无名编辑")
        await act(async () => { await vi.advanceTimersByTimeAsync(RESUME_DRAFT_DEBOUNCE_MS + 100) })
        // 草稿排期照旧（草稿按 id 隔离，不依赖 name）
        expect(readResumeDraft("temp_noname")?.structured?.summary).toBe("无名编辑")
        // 登记表：空名 upsert 被拒（store 主守卫 + registry 二道防线），无空名项入表
        const reg = listLocalResumes().items
        expect(reg.some(i => i.record_id === "temp_noname")).toBe(false)
        expect(reg.every(i => i.name !== "")).toBe(true)
    })
})
