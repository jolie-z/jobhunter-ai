// 草稿排期器时序竞态单测（agy double-check R2 P1-4 的可证伪验证要求）
// 用 fake timers 断言 write 的调用参数序列：编辑 A → 切 B → 触发/保存/关页，
// 任何序列下都绝不允许出现 (B, A-data) 或 (A, B-data) 形态的跨记录串写。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createDraftScheduler } from "./resume-draft"

type WriteCall = [string, unknown]

describe("createDraftScheduler 时序竞态", () => {
    let writes: WriteCall[]
    let scheduler: ReturnType<typeof createDraftScheduler>

    beforeEach(() => {
        vi.useFakeTimers()
        writes = []
        scheduler = createDraftScheduler((owner, data) => writes.push([owner, data]), 2000)
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    it("编辑 A 后 2s 内切换 B 并编辑 B：双方草稿各落各槽，绝无串写", () => {
        scheduler.schedule("recA", { name: "A-v1" })
        scheduler.schedule("recB", { name: "B-v1" }) // 模拟切换后编辑 B（per-owner 表互不干扰）
        vi.advanceTimersByTime(2000)

        expect(writes).toContainEqual(["recA", { name: "A-v1" }])
        expect(writes).toContainEqual(["recB", { name: "B-v1" }])
        expect(writes).toHaveLength(2)
        // 穷尽断言：不存在 (B, A-data) / (A, B-data)
        expect(writes.some(([o, d]) => o === "recB" && (d as any).name === "A-v1")).toBe(false)
        expect(writes.some(([o, d]) => o === "recA" && (d as any).name === "B-v1")).toBe(false)
    })

    it("编辑 A 后 2s 内切 B 并保存 B（discardOwner）：A 的待写定时器不被误清，B 不写回", () => {
        scheduler.schedule("recA", { name: "A-v1" })
        scheduler.discardOwner("recB") // 保存 B 成功：只清 B 自己的（本例中本就没有）
        vi.advanceTimersByTime(2000)

        // A 的草稿仍被写入（R3 审查 P1-1 分支 ii 的核心断言：保存别人的简历不清我的定时器）
        expect(writes).toContainEqual(["recA", { name: "A-v1" }])
    })

    it("保存成功后同 owner 的待写定时器被丢弃（云端已最新，不写回草稿槽）", () => {
        scheduler.schedule("recB", { name: "B-v2" })
        scheduler.discardOwner("recB")
        vi.advanceTimersByTime(5000)

        expect(writes).toHaveLength(0)
        expect(scheduler.pendingOwners()).toHaveLength(0)
    })

    it("pagehide/关页 flushAll：全部待写草稿立即落盘且定时器清空，之后不重复写", () => {
        scheduler.schedule("recA", { name: "A-v1" })
        scheduler.schedule("recB", { name: "B-v1" })
        scheduler.flushAll()

        expect(writes).toHaveLength(2)
        expect(scheduler.pendingOwners()).toHaveLength(0)
        vi.advanceTimersByTime(5000)
        expect(writes).toHaveLength(2) // 不重复写
    })

    it("同 owner 重排期：数据以最后一次为准，且只写一次", () => {
        scheduler.schedule("recA", { name: "A-v1" })
        vi.advanceTimersByTime(1500)
        scheduler.schedule("recA", { name: "A-v2" }) // 用户继续编辑
        vi.advanceTimersByTime(2000)

        expect(writes).toEqual([["recA", { name: "A-v2" }]])
    })

    it("快照深隔离：排期后就地改写原对象（含嵌套字段）不影响待写内容", () => {
        const data = { name: "A-v1", work: [{ bullets: ["b1"] }] }
        scheduler.schedule("recA", data)
        ;(data as any).name = "MUTATED"
        ;(data as any).work[0].bullets.push("MUTATED") // 嵌套变异同样被隔离
        vi.advanceTimersByTime(2000)

        expect(writes).toEqual([["recA", { name: "A-v1", work: [{ bullets: ["b1"] }] }]])
    })

    it("非法入参直接忽略：空 owner 或空数据不排期", () => {
        scheduler.schedule("", { a: 1 })
        scheduler.schedule("recA", null)
        expect(scheduler.pendingOwners()).toHaveLength(0)
    })
})
