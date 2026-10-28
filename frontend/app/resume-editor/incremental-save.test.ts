import { describe, expect, it } from "vitest"

import { buildIncrementalSavePayload, deepEqual } from "./incremental-save"

describe("deepEqual", () => {
  it("原始值相等与对象引用相等", () => {
    expect(deepEqual(1, 1)).toBe(true)
    expect(deepEqual("a", "a")).toBe(true)
    expect(deepEqual(null, null)).toBe(true)
    const obj = { v: 1 }
    expect(deepEqual(obj, obj)).toBe(true)
  })

  it("内容相同但引用不同的嵌套对象视为相等", () => {
    expect(deepEqual({ a: { b: [1, 2, { c: 3 }] } }, { a: { b: [1, 2, { c: 3 }] } })).toBe(true)
  })

  it("嵌套列表中一项内容变化即不等（深比较核心职责）", () => {
    expect(deepEqual({ list: [{ x: 1 }, { x: 2 }] }, { list: [{ x: 1 }, { x: 9 }] })).toBe(false)
  })

  it("键数量不同 / 数组与对象 / null 与对象 均不等", () => {
    expect(deepEqual({ a: 1 }, { a: 1, b: 2 })).toBe(false)
    expect(deepEqual([1, 2], { 0: 1, 1: 2 })).toBe(false)
    expect(deepEqual(null, {})).toBe(false)
  })
})

describe("buildIncrementalSavePayload", () => {
  const baseline = {
    a: { v: 1 },
    b: { v: 2 },
    c: { list: [{ x: 1 }] },
  }

  it("单模块变更：载荷只含该模块", () => {
    const updated = { ...baseline, a: { v: 9 } }
    expect(buildIncrementalSavePayload(updated, baseline)).toEqual({ a: { v: 9 } })
  })

  it("多模块变更：载荷含全部变更模块", () => {
    const updated = { ...baseline, a: { v: 9 }, c: { list: [{ x: 1 }, { x: 2 }] } }
    expect(Object.keys(buildIncrementalSavePayload(updated, baseline)).sort()).toEqual(["a", "c"])
  })

  it("baseline 健全但未检出差异：返回 {}（后端 no-op，防意外保存盖回并发写入）", () => {
    const updated = { ...baseline, a: { ...baseline.a } }
    expect(buildIncrementalSavePayload(updated, baseline)).toEqual({})
  })

  it("plan-review P0 关联场景：新引用且内容变化（含后续原地改）必须被深比较检出", () => {
    // 深比较的真实职责：模块拿到新引用后内容才被改（引用比对在此同样有效），
    // 以及内容与基线相同的新引用被正确跳过。基线与 updated 共享同一对象的原地
    // 改写任何比较都无法检出（基线即存活状态本身），防线是组件侧不可变更新纪律。
    const base = { a: { v: 1 }, b: { v: 2 } }
    const updated = { ...base, b: { v: 2 } } // b 为内容相同的新引用
    ;(updated.b as { v: number }).v = 3 // 随后原地改内容
    const payload = buildIncrementalSavePayload(updated, base)
    expect(Object.keys(payload)).toEqual(["b"])
    expect(payload.b).toEqual({ v: 3 })
  })

  it("内容与基线相同的新引用被跳过（浅引用比对会误发的场景）", () => {
    const base = { a: { v: 1 }, b: { v: 2 } }
    const updated = { ...base, a: { v: 9 }, b: { ...base.b } } // b 新引用但内容未变
    expect(buildIncrementalSavePayload(updated, base)).toEqual({ a: { v: 9 } })
  })

  it("baseline 为空/未加载：退化为发送全量（内容等价）", () => {
    const updated = { a: { v: 1 }, b: { v: 2 } }
    expect(buildIncrementalSavePayload(updated, undefined)).toEqual(updated)
    expect(buildIncrementalSavePayload(updated, {})).toEqual(updated)
  })

  it("不做键缺失→null 删除推导：updated 中被移除的键不产生删除指令", () => {
    const updated = { b: { v: 2 } } // a 被移除，b 内容未变
    const payload = buildIncrementalSavePayload(updated, baseline)
    expect(payload).toEqual({}) // 无内容差异 → no-op；绝不生成 { a: null }
    expect("a" in payload).toBe(false)
  })
})
