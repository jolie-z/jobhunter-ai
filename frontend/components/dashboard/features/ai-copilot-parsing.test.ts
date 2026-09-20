import { describe, it, expect } from "vitest"

describe("Resume Audit & Dimension Parsing Test", () => {
  it("parses evaluation detail dimensions correctly without asterisks", () => {
    const raw = `**【角色匹配】** 5/5\n候选人独立交付5项业务级AI SaaS产品，熟练掌握Python、FastAPI和Agent架构。\n\n**【技能重合】** 4/5\nJD要求Python、FastAPI，候选人掌握良好。`

    const blocks = raw
      .split(/\n\s*\n|(?<=\n)(?=\*\*【|【)/)
      .map((b) => b.trim())
      .filter(Boolean)

    const items: { title: string; score: string; description: string }[] = []
    for (const b of blocks) {
      const match = b.match(
        /^(?:\*\*)?【([^\n】\*\:]+?)】(?:\*\*)?\s*[:：]?\s*([0-9\/\.\s分]+)?\s*\n*([\s\S]*)$/
      )
      if (match) {
        items.push({
          title: match[1].trim(),
          score: (match[2] || "").trim(),
          description: (match[3] || "").trim(),
        })
      }
    }

    expect(items).toHaveLength(2)
    expect(items[0].title).toBe("角色匹配")
    expect(items[0].score).toBe("5/5")
    expect(items[0].description).toContain("候选人独立交付5项业务级AI SaaS产品")
    expect(items[1].title).toBe("技能重合")
    expect(items[1].score).toBe("4/5")
  })

  it("parses resume audit pipe format without explicit '原文主张' prefix", () => {
    const auditText = `【个人总结】
AI应用全栈开发：独立负责并交付5项业务级AI SaaS产品 | 无直接后端开发项目对应，但“全栈”隐含后端。风险等级：⚠️谨慎
电商业务深度洞察：拥有近5年头部美妆集团核心电商运营与数据分析经验 | 体现业务理解，非技术硬技能。风险等级：✅安全

【项目经历：AI驱动的全链路自动化求职与简历定制系统】
技术栈包含FastAPI | 明确使用FastAPI。风险等级：✅安全
独立解决了高并发流控、CDP防风控接管 | 体现系统设计能力。风险等级：⚠️谨慎`

    const lines = auditText.split("\n")
    const sections: { title: string; rows: { claim: string; evidence: string; risk: string }[] }[] = []
    let current: { title: string; rows: { claim: string; evidence: string; risk: string }[] } | null = null

    for (let line of lines) {
      line = line.trim()
      if (!line) continue

      const secMatch = line.match(/^[#*\s]*【(.+?)】/)
      if (secMatch) {
        current = { title: secMatch[1].trim(), rows: [] }
        sections.push(current)
        continue
      }

      if (!current) {
        current = { title: "综合审计", rows: [] }
        sections.push(current)
      }

      const cleanLine = line.replace(/^[\*\-\d\.]+\s*/, "").trim()
      if (/^\|?[\s\-:|]+\|?$/.test(cleanLine)) continue
      if (
        cleanLine.includes("原文主张") &&
        cleanLine.includes("证据核验") &&
        !["✅", "⚠️", "❌", "安全", "谨慎", "高风险"].some((k) => cleanLine.includes(k))
      ) {
        continue
      }

      let claim = ""
      let evidence = ""
      let risk = ""

      if (cleanLine.includes("风险等级")) {
        const parts = cleanLine.split(/风险等级[：:]\s*/)
        risk = parts[1]?.trim() || ""
        const left = parts[0]?.trim().replace(/[\s|]+$/, "") || ""
        const leftCols = left.split("|").map((c) => c.trim()).filter(Boolean)
        if (leftCols.length >= 2) {
          claim = leftCols[0]
          evidence = leftCols.slice(1).join(" | ")
        } else if (leftCols.length === 1) {
          claim = leftCols[0]
        }
      } else if (cleanLine.includes("|")) {
        const cols = cleanLine.split("|").map((c) => c.trim()).filter(Boolean)
        if (cols.length >= 3) {
          claim = cols[0]
          evidence = cols[1]
          risk = cols.slice(2).join(" | ")
        } else if (cols.length === 2) {
          claim = cols[0]
          evidence = cols[1]
        }
      } else {
        claim = cleanLine
      }

      claim = claim.replace(/^(原文主张|候选人主张|主张)[：:]\s*/, "").trim()
      evidence = evidence.replace(/^(证据核验|核验|证据)[：:]\s*/, "").trim()
      risk = risk.replace(/^(风险等级|风险)[：:]\s*/, "").trim()

      if (claim || evidence || risk) {
        current.rows.push({ claim, evidence, risk })
      }
    }

    const filtered = sections.filter((s) => s.rows.length > 0)
    expect(filtered).toHaveLength(2)
    expect(filtered[0].title).toBe("个人总结")
    expect(filtered[0].rows).toHaveLength(2)
    expect(filtered[0].rows[0].claim).toContain("AI应用全栈开发")
    expect(filtered[0].rows[0].evidence).toContain("无直接后端开发项目对应")
    expect(filtered[0].rows[0].risk).toBe("⚠️谨慎")

    expect(filtered[1].title).toBe("项目经历：AI驱动的全链路自动化求职与简历定制系统")
    expect(filtered[1].rows).toHaveLength(2)
    expect(filtered[1].rows[0].claim).toBe("技术栈包含FastAPI")
    expect(filtered[1].rows[0].risk).toBe("✅安全")
  })

  it("extracts streamlined risk badges without duplicate emojis", async () => {
    const { parseRiskDetail } = await import("./resume-audit-card")

    const r1 = parseRiskDetail("⚠️谨慎")
    expect(r1.icon).toBe("⚠️")
    expect(r1.label).toBe("谨慎")
    expect(r1.note).toBe("")

    const r2 = parseRiskDetail("✅安全")
    expect(r2.icon).toBe("✅")
    expect(r2.label).toBe("安全")
    expect(r2.note).toBe("")

    const r3 = parseRiskDetail("✅安全（但关联度低）")
    expect(r3.icon).toBe("✅")
    expect(r3.label).toBe("安全")
    expect(r3.note).toBe("但关联度低")

    const r4 = parseRiskDetail("⚠️谨慎（但JD要求“计算机相关专业”，此为硬伤）")
    expect(r4.icon).toBe("⚠️")
    expect(r4.label).toBe("谨慎")
    expect(r4.note).toBe("但JD要求“计算机相关专业”，此为硬伤")

    const r5 = parseRiskDetail("❌高风险")
    expect(r5.icon).toBe("❌")
    expect(r5.label).toBe("高风险")
  })
})

