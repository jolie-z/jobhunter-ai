// 简历本机草稿的防抖排期器（2026-09-23 简历库七项修复#4，R3 审查 P1 重构）
//
// 为什么不用单个 setTimeout ref：防抖定时器若全局单槽，"编辑 A 后 2s 内切到 B 再保存 B"
// 这类序列会互相清除/误写（agy code-review R3 P1）。本模块按 owner（record_id）独立排期，
// 写入目标与数据快照在排期时绑定，切换/保存互不干扰。
//
// 纯逻辑零 React 依赖，便于 vitest fake timers 直接验证时序竞态。

export type DraftWriteFn = (owner: string, data: unknown) => void

export interface DraftScheduler {
    /** 为 owner 排期一次防抖写入；同 owner 重排期会覆盖上一次（数据以最后一次为准） */
    schedule: (owner: string, data: unknown) => void
    /** 保存成功后调用：丢弃 owner 的待写定时器（云端已是最新，不能再写回草稿槽） */
    discardOwner: (owner: string) => void
    /** 立即落盘所有待写草稿并清空（pagehide/关页/卸载时调用；关页不触发 React unmount） */
    flushAll: () => void
    pendingOwners: () => string[]
}

export function createDraftScheduler(write: DraftWriteFn, delayMs: number): DraftScheduler {
    // owner -> { timer, data }。data 是排期时的 structuredClone 深拷贝快照，与 owner 在
    // 同一次调用中绑定，触发时不再读任何可变引用（根治"触发时 owner 已漂移"的跨记录串写；
    // 深拷贝同时隔离下游对嵌套字段的了就地变异——agy double-check R2 P2）
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
        // 测试探针：供 fake-timers 用例断言待写集合（生产代码不消费）
        pendingOwners() {
            return [...pending.keys()]
        },
    }
}
