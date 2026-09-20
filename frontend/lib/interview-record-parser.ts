export interface InterviewRecordItem {
  id: string
  timestamp: string
  role: string
  style: string
  roleDisplay: string
  styleDisplay: string
  body: string
  rawBlock: string
}

const ROLE_LABEL_MAP: Record<string, string> = {
  hr: "HRBP",
  boss: "大老板",
  business: "业务线",
}

const STYLE_LABEL_MAP: Record<string, string> = {
  coach: "教练陪跑",
  real: "全真模拟",
}

/**
 * 自适应解析飞书中的长文本面试记录：
 * 1. 优先提取嵌入式的隐式元数据 <!-- RECORD_ID:xxx -->
 * 2. 平滑兼容存量无元数据的纯 Markdown 切分块
 * 3. 产出强类型、具备稳定 ID 的结构化记录列表
 */
export function parseInterviewRecords(rawMarkdown: string): InterviewRecordItem[] {
  if (!rawMarkdown || typeof rawMarkdown !== "string") return []

  const blockRegex = /(?:<!--\s*RECORD_ID:([A-Za-z0-9_\-]+)\s*-->\s*)?###\s*🕒\s*面试练习记录\s*\((.*?)\)(?:[^\n]*\[ROLE:(.*?)\|STYLE:(.*?)\])?([\s\S]*?)(?=(?:<!--\s*RECORD_ID:[A-Za-z0-9_\-]+\s*-->\s*)?###\s*🕒\s*面试练习记录|$)/g

  const items: InterviewRecordItem[] = []
  let match: RegExpExecArray | null
  let index = 0

  while ((match = blockRegex.exec(rawMarkdown)) !== null) {
    const rawMatch = match[0].trim()
    if (!rawMatch) continue

    const explicitId = match[1]?.trim()
    const timestamp = match[2]?.trim() || "未知时间"
    const rawRole = match[3]?.trim().toLowerCase() || "business"
    const rawStyle = match[4]?.trim().toLowerCase() || "coach"
    let body = match[5]?.trim() || ""

    // 清理尾部分割线 ---
    body = body.replace(/\n\s*---\s*$/, "").trim()

    // 稳定 ID：新版用 explicitId，旧存量按时间戳与索引派生
    const recordId = explicitId || `legacy_${timestamp.replace(/[^0-9]/g, "") || "session"}_${index}`

    const roleDisplay = ROLE_LABEL_MAP[rawRole] || "业务线"
    const styleDisplay = STYLE_LABEL_MAP[rawStyle] || "教练陪跑"

    items.push({
      id: recordId,
      timestamp,
      role: rawRole,
      style: rawStyle,
      roleDisplay,
      styleDisplay,
      body,
      rawBlock: rawMatch,
    })

    index++
  }

  return items
}

/**
 * 将结构化列表安全序列化为标准 Markdown 文本以持久化到飞书
 */
export function serializeInterviewRecords(records: InterviewRecordItem[]): string {
  if (!records || records.length === 0) return ""

  return records
    .map(r => {
      const idComment = `<!-- RECORD_ID:${r.id} -->`
      const header = `### 🕒 面试练习记录 (${r.timestamp}) [ROLE:${r.role}|STYLE:${r.style}]`
      return `${idComment}\n${header}\n${r.body}\n\n---\n\n`
    })
    .join("")
}

/**
 * 从原始 Markdown 中外科手术式移除一条练习记录（按稳定 ID 或旧版 rawBlock 匹配）。
 * 与 serializeInterviewRecords(剩余记录) 的全量重写不同，本函数只删除目标块本身，
 * 块外的任何零散文本（如手动批注、非标准格式内容）都会原样保留。
 */
export function removeRecordFromMarkdown(rawMarkdown: string, idOrBlock: string): string {
  if (!rawMarkdown || !idOrBlock) return rawMarkdown

  const records = parseInterviewRecords(rawMarkdown)
  const target = records.find(r => r.id === idOrBlock || r.rawBlock === idOrBlock)
  if (!target) return rawMarkdown

  const remaining = rawMarkdown.replace(target.rawBlock, "")
  // 清理删除后残留的连续空行并收紧首尾
  return remaining.replace(/\n{3,}/g, "\n\n").trim()
}
