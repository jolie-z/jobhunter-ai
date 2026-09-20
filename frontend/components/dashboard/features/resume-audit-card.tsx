"use client"

import React, { useMemo } from "react"
import ReactMarkdown from "react-markdown"

interface ResumeAuditCardProps {
  auditText: string
}

interface AuditRow {
  claim: string
  evidence: string
  risk: string
}

interface AuditSection {
  title: string
  rows: AuditRow[]
}

function parseResumeAudit(text: string): AuditSection[] {
  const sections: AuditSection[] = []
  let current: AuditSection | null = null
  const lines = text.split("\n")

  for (let line of lines) {
    line = line.trim()
    if (!line) continue

    // 匹配章节标题：【模块名】 或 **【模块名】** 或 ### 【模块名】
    const secMatch = line.match(/^[#*\s]*【(.+?)】/)
    if (secMatch) {
      current = { title: secMatch[1].trim(), rows: [] }
      sections.push(current)
      continue
    }

    // 若尚未进入任何【】模块，先初始化默认分区
    if (!current) {
      current = { title: "综合审计", rows: [] }
      sections.push(current)
    }

    // 清理 markdown 列表符号（- , * , 1. 等）
    const cleanLine = line.replace(/^[\*\-\d\.]+\s*/, "").trim()

    // 过滤 markdown 表格分隔线（形如 |---|---| ）
    if (/^\|?[\s\-:|]+\|?$/.test(cleanLine)) continue

    // 过滤纯静态表头行（避免原文本中含有 | 原文主张 | 证据核验 | 风险等级 | 被当成数据行）
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

    // 分支 1：包含显式「风险等级」文字
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
      // 分支 2：以管道符 | 分隔
      const cols = cleanLine.split("|").map((c) => c.trim()).filter(Boolean)
      if (cols.length >= 3) {
        claim = cols[0]
        evidence = cols[1]
        risk = cols.slice(2).join(" | ")
      } else if (cols.length === 2) {
        claim = cols[0]
        evidence = cols[1]
      } else if (cols.length === 1) {
        claim = cols[0]
      }
    } else {
      // 分支 3：普通行文本
      claim = cleanLine
    }

    // 清洗字段前缀（如 原文主张:、证据核验:、风险等级:）
    claim = claim.replace(/^(原文主张|候选人主张|主张)[：:]\s*/, "").trim()
    evidence = evidence.replace(/^(证据核验|核验|证据)[：:]\s*/, "").trim()
    risk = risk.replace(/^(风险等级|风险)[：:]\s*/, "").trim()

    if (claim || evidence || risk) {
      current.rows.push({ claim, evidence, risk })
    }
  }

  // 仅保留存在有效行数据的模块，避免空表头暴露
  return sections.filter((s) => s.rows.length > 0)
}

export function parseRiskDetail(rawRisk: string) {
  // 1. 剥离已有 emoji 符号，避免前置 icon 与文本自带 emoji 造成双重重复
  const clean = rawRisk.replace(/[✅⚠️❌•]/g, "").trim()

  // 2. 提取括号内的辅助说明（如 "但关联度低"、"但与JD技术要求无关"）
  let note = ""
  const noteMatch = clean.match(/[（(](.+?)[）)]/)
  if (noteMatch) {
    note = noteMatch[1].trim()
  }

  // 3. 提取核心等级词（仅保留 安全 / 谨慎 / 高风险）
  const isSafe = rawRisk.includes("安全") || rawRisk.includes("✅")
  const isCaution = rawRisk.includes("谨慎") || rawRisk.includes("⚠️")
  const isDanger = rawRisk.includes("高风险") || rawRisk.includes("❌") || rawRisk.includes("危险")

  let label = "安全"
  let icon = "✅"
  let badgeStyle = "bg-emerald-50 text-emerald-700 border-emerald-200/80 dark:bg-emerald-950/30 dark:text-emerald-300"

  if (isDanger) {
    label = "高风险"
    icon = "❌"
    badgeStyle = "bg-rose-50 text-rose-700 border-rose-200/80 dark:bg-rose-950/30 dark:text-rose-300"
  } else if (isCaution) {
    label = "谨慎"
    icon = "⚠️"
    badgeStyle = "bg-amber-50 text-amber-700 border-amber-200/80 dark:bg-amber-950/30 dark:text-amber-300"
  } else if (isSafe) {
    label = "安全"
    icon = "✅"
    badgeStyle = "bg-emerald-50 text-emerald-700 border-emerald-200/80 dark:bg-emerald-950/30 dark:text-emerald-300"
  } else {
    label = clean.replace(/[（(].+?[）)]/g, "").trim() || "未标注"
    icon = "•"
    badgeStyle = "bg-zinc-100 text-zinc-600 border-zinc-200 dark:bg-zinc-800 dark:text-zinc-400"
  }

  return { label, icon, note, badgeStyle }
}

export function ResumeAuditCard({ auditText }: ResumeAuditCardProps) {
  const sections = useMemo(() => {
    if (!auditText || !auditText.trim()) return []
    return parseResumeAudit(auditText)
  }, [auditText])

  if (!auditText || !auditText.trim()) {
    return null
  }

  const totalPoints = sections.reduce((sum, s) => sum + s.rows.length, 0)

  // 若成功解析出至少一个有效模块，渲染美观的数据矩阵表格
  if (sections.length > 0) {
    return (
      <div className="border border-amber-200/90 dark:border-amber-900/40 bg-amber-50/30 dark:bg-amber-950/20 rounded-lg p-2.5">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-[10px] font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wide flex items-center gap-1">
            <span>🔍 02·简历逐行审计</span>
          </h4>
          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-100/80 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 font-medium">
            共审计 {totalPoints} 项
          </span>
        </div>

        <div className="space-y-3.5 max-h-[500px] overflow-y-auto pr-1">
          {sections.map((sec, si) => (
            <div key={si} className="space-y-1.5">
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-semibold text-zinc-700 dark:text-zinc-300 bg-white/90 dark:bg-zinc-800/90 border border-zinc-200/70 dark:border-zinc-700/60 px-2 py-0.5 rounded shadow-xs">
                  {sec.title}
                </span>
                <span className="text-[9px] text-zinc-400 font-mono">
                  ({sec.rows.length})
                </span>
              </div>

              <div className="overflow-hidden rounded-md border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900/70">
                <table className="w-full text-[10px] border-collapse table-fixed">
                  <thead>
                    <tr className="text-left text-zinc-400 dark:text-zinc-500 border-b border-zinc-100 dark:border-zinc-800 bg-zinc-50/70 dark:bg-zinc-900/90">
                      <th className="py-1.5 pl-2.5 pr-2 font-medium w-[32%]">原文主张</th>
                      <th className="py-1.5 pr-2 font-medium w-[44%]">证据核验</th>
                      <th className="py-1.5 pr-2.5 font-medium w-[24%]">风险等级</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/80">
                    {sec.rows.map((row, ri) => {
                      const { label, icon, note, badgeStyle } = parseRiskDetail(row.risk)

                      return (
                        <tr key={ri} className="align-top hover:bg-zinc-50/50 dark:hover:bg-zinc-800/30 transition-colors">
                          <td className="py-2 pl-2.5 pr-2 text-zinc-800 dark:text-zinc-200 leading-snug font-normal break-words">
                            {row.claim}
                          </td>
                          <td className="py-2 pr-2 text-zinc-500 dark:text-zinc-400 leading-snug break-words">
                            {row.evidence || "-"}
                          </td>
                          <td className="py-2 pr-2.5">
                            <div className="flex flex-col items-start gap-1">
                              <span
                                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] font-medium whitespace-nowrap leading-none ${badgeStyle}`}
                              >
                                <span className="text-[10px] leading-none">{icon}</span>
                                <span>{label}</span>
                              </span>
                              {note && (
                                <span className="text-[9px] text-zinc-400 dark:text-zinc-500 leading-tight break-words">
                                  {note}
                                </span>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // 兜底排版：使用 Markdown 优雅呈现，不破坏页面结构
  return (
    <div className="border border-amber-200 bg-amber-50/30 dark:bg-amber-950/20 rounded-md p-2.5">
      <h4 className="text-[10px] font-semibold text-amber-700 dark:text-amber-400 mb-2 uppercase tracking-wide">
        🔍 02·简历逐行审计
      </h4>
      <div className="text-[11px] text-zinc-600 dark:text-zinc-400 leading-relaxed max-h-[400px] overflow-y-auto">
        <ReactMarkdown>{auditText}</ReactMarkdown>
      </div>
    </div>
  )
}
