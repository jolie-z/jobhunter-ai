import { describe, it, expect } from "vitest"
import { parseInterviewRecords, serializeInterviewRecords, removeRecordFromMarkdown } from "./interview-record-parser"

describe("interview-record-parser", () => {
  it("应能平滑兼容解析存量旧版 Markdown 记录", () => {
    const legacyText = `
### 🕒 面试练习记录 (2026-09-05 10:00:00) [ROLE:business|STYLE:coach]
**🗣️ 面试官**: 请介绍一下你自己。
**👤 我**: 我是一名AI全栈工程师。

---

### 🕒 面试练习记录 (2026-09-05 11:30:00) [ROLE:boss|STYLE:real]
**🗣️ 面试官**: 你未来的职业规划是什么？
**👤 我**: 持续深耕软件工程与大模型应用。

---
`
    const records = parseInterviewRecords(legacyText)
    expect(records).toHaveLength(2)

    expect(records[0].timestamp).toBe("2026-09-05 10:00:00")
    expect(records[0].role).toBe("business")
    expect(records[0].style).toBe("coach")
    expect(records[0].roleDisplay).toBe("业务线")
    expect(records[0].styleDisplay).toBe("教练陪跑")
    expect(records[0].body).toContain("请介绍一下你自己")
    expect(records[0].id).toBeTruthy()

    expect(records[1].timestamp).toBe("2026-09-05 11:30:00")
    expect(records[1].role).toBe("boss")
    expect(records[1].style).toBe("real")
    expect(records[1].roleDisplay).toBe("大老板")
    expect(records[1].styleDisplay).toBe("全真模拟")
  })

  it("应能精确识别新版嵌入式 RECORD_ID 元数据", () => {
    const modernText = `
<!-- RECORD_ID:sess_1725538200_abc123 -->
### 🕒 面试练习记录 (2026-09-05 16:00:00) [ROLE:hr|STYLE:coach]
**🗣️ 面试官**: 你的期望薪资是多少？
**👤 我**: 25k。

---
`
    const records = parseInterviewRecords(modernText)
    expect(records).toHaveLength(1)
    expect(records[0].id).toBe("sess_1725538200_abc123")
    expect(records[0].roleDisplay).toBe("HRBP")
    expect(records[0].body).toContain("你的期望薪资是多少")
  })

  it("应能正确执行按 ID 过滤与序列化还原", () => {
    const raw = `
<!-- RECORD_ID:id_1 -->
### 🕒 面试练习记录 (2026-09-05 10:00:00) [ROLE:business|STYLE:coach]
第一场面试内容

---

<!-- RECORD_ID:id_2 -->
### 🕒 面试练习记录 (2026-09-05 12:00:00) [ROLE:hr|STYLE:real]
第二场面试内容

---
`
    const records = parseInterviewRecords(raw)
    expect(records).toHaveLength(2)

    // 删除 id_1
    const remaining = records.filter(r => r.id !== "id_1")
    const serialized = serializeInterviewRecords(remaining)

    expect(serialized).not.toContain("第一场面试内容")
    expect(serialized).toContain("第二场面试内容")
    expect(serialized).toContain("<!-- RECORD_ID:id_2 -->")
  })

  it("removeRecordFromMarkdown 应只移除目标块并保留块外零散文本", () => {
    const raw = `【手动批注：这场的自我介绍讲得不错，保留】

<!-- RECORD_ID:id_1 -->
### 🕒 面试练习记录 (2026-09-05 10:00:00) [ROLE:business|STYLE:coach]
第一场面试内容

---

### 🕒 面试练习记录 (2026-09-05 12:00:00) [ROLE:hr|STYLE:real]
第二场面试内容

---

【结尾备注：等待二面反馈】
`
    const result = removeRecordFromMarkdown(raw, "id_1")

    expect(result).not.toContain("第一场面试内容")
    expect(result).toContain("第二场面试内容")
    // 块外零散文本必须原样保留（旧的全量重写会丢掉它们）
    expect(result).toContain("【手动批注：这场的自我介绍讲得不错，保留】")
    expect(result).toContain("【结尾备注：等待二面反馈】")
    // 未匹配到 ID 时原文返回
    expect(removeRecordFromMarkdown(raw, "不存在的id")).toBe(raw)
  })
})
