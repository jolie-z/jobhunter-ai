/**
 * 岗位详情（JD）结构化解析。
 *
 * 背景（2026-10-30）：猎聘采集链路拿到的正文是 textContent 语义——<p>/<br>/<li>
 * 的分段边界全部塌成空格，存库即一整行（BOSS 已在采集端按 HTML 还原，猎聘没有）。
 * 前端渲染层做一次结构化还原：识别章节标题（岗位职责/任职要求/一、岗位职责…）
 * 与编号条目（1、/1./（1）/①），把「一团文字」还原成标题 + 条目 + 段落。
 *
 * 纯函数、零依赖，便于单测；对已带换行的平台（BOSS/51job/智联）是幂等的。
 */

export type JobDescriptionBlock =
  | { kind: "heading"; text: string }
  | { kind: "item"; marker: string; text: string }
  | { kind: "paragraph"; text: string }

/** 章节标题词表：命中后单独成段，按最长优先匹配（避免「岗位要求」被「岗位」截断）。 */
const HEADING_WORDS = [
  "岗位职责",
  "工作职责",
  "职位职责",
  "核心职责",
  "主要职责",
  "职责描述",
  "工作内容",
  "岗位内容",
  "职位描述",
  "岗位描述",
  "岗位介绍",
  "职位介绍",
  "任职要求",
  "任职资格",
  "岗位要求",
  "职位要求",
  "技能要求",
  "能力要求",
  "其他要求",
  "加分项",
  "优先条件",
  "岗位亮点",
  "职位亮点",
  "岗位福利",
  "福利待遇",
  "薪资福利",
  "公司介绍",
  "团队介绍",
  "岗位定位",
  "岗位目标",
  "我们提供",
  "我们希望",
  "你将负责",
  "工作地点",
  "联系方式",
  "面试流程",
]

const HEADING_ALT = [...HEADING_WORDS]
  .sort((a, b) => b.length - a.length)
  .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
  .join("|")

// 句读边界：标题/条目必须出现在句首或这些字符之后，避免把正文里的词误判成结构。
// 冒号在列内：兼容「任职要求：（1）…」「任职要求：① …」这种紧贴标题的编号。
const BOUNDARY = "[\\s。；;！!？?、,，：:]"

// 标题：可选中式序号（一、）+ 标题词 + 可选冒号；无冒号时要求后接空白/行尾/编号条目。
const HEADING_RE = new RegExp(
  `(^|${BOUNDARY})(?:([一二三四五六七八九十]{1,3})\\s*[、.．]\\s*)?(${HEADING_ALT})\\s*([：:]|(?=\\s|$|\\d{1,2}\\s*[、.．]))`,
  "g"
)

// 【岗位职责】/【任职要求】式方括号标题：JD 里几乎只用于章节名，命中即按标题处理。
const BRACKET_HEADING_RE = new RegExp(`(^|${BOUNDARY})【\\s*([^】\\n]{1,24}?)\\s*】`, "g")

// 自由命名的中文序号章节：一、Agent设计与搭建 1、……（标题词不在词表里，
// 靠「后面紧跟编号条目或冒号」识别，避免把「一、二线城市」这类正文误判）。
const CN_SECTION_RE = new RegExp(
  `(^|${BOUNDARY})([一二三四五六七八九十]{1,3})\\s*[、.．]\\s*([^\\s。；;！!？?：:]{2,16})(?=\\s*[：:]|\\s+\\d{1,2}\\s*[、.．)）])`,
  "g"
)

// 独占一行的中文序号标题（已带换行的 JD）：一、岗位职责 / 二、核心职责：
const CN_LINE_HEADING_RE =
  /^([一二三四五六七八九十]{1,3})\s*[、.．]\s*([^。；;！!？?：:]{2,20})\s*[：:]?$/

// 编号条目：阿拉伯数字（1、/1./1）/（1））、带圈数字（①-⑳）。
const ITEM_RE = new RegExp(
  `(^|${BOUNDARY})((?:[（(]\\s*\\d{1,2}\\s*[)）])|(?:[①-⑳])|(?:\\d{1,2}\\s*[、.．)）]))`,
  "g"
)

const CIRCLED_RE = /^[①-⑳]$/

function normalizeWhitespace(text: string): string {
  return text
    .replace(/\r\n?/g, "\n")
    .replace(/[\u00a0\u3000]/g, " ")
    .replace(/[ \t]+/g, " ")
    .trim()
}

function normalizeMarker(raw: string): string {
  if (CIRCLED_RE.test(raw)) return raw
  const digits = raw.match(/\d{1,2}/)
  return digits ? digits[0] : raw
}

/** 阿拉伯数字编号后紧跟数字时是小数/版本号（1.5 万、3.0），不是条目。 */
function isFalseItem(marker: string, text: string, markerEnd: number): boolean {
  if (!/^\d{1,2}\s*[.．)）]$/.test(marker)) return false
  const next = text[markerEnd] || ""
  return /\d/.test(next)
}

type Cut = { index: number; end: number; block: JobDescriptionBlock }

function collectCuts(text: string): Cut[] {
  const cuts: Cut[] = []
  let match: RegExpExecArray | null

  HEADING_RE.lastIndex = 0
  while ((match = HEADING_RE.exec(text)) !== null) {
    const prefix = match[1] || ""
    const numeral = match[2] || ""
    const word = match[3]
    const start = match.index + prefix.length
    const label = numeral ? `${numeral}、${word}` : word
    cuts.push({
      index: start,
      end: match.index + match[0].length,
      block: { kind: "heading", text: label },
    })
  }

  BRACKET_HEADING_RE.lastIndex = 0
  while ((match = BRACKET_HEADING_RE.exec(text)) !== null) {
    const prefix = match[1] || ""
    const label = (match[2] || "").trim()
    if (!label) continue
    cuts.push({
      index: match.index + prefix.length,
      end: match.index + match[0].length,
      block: { kind: "heading", text: label },
    })
  }

  CN_SECTION_RE.lastIndex = 0
  while ((match = CN_SECTION_RE.exec(text)) !== null) {
    const prefix = match[1] || ""
    const numeral = match[2]
    const title = match[3]
    cuts.push({
      index: match.index + prefix.length,
      end: match.index + match[0].length,
      block: { kind: "heading", text: `${numeral}、${title}` },
    })
  }

  ITEM_RE.lastIndex = 0
  while ((match = ITEM_RE.exec(text)) !== null) {
    const prefix = match[1] || ""
    const marker = match[2]
    const markerEnd = match.index + match[0].length
    if (isFalseItem(marker, text, markerEnd)) continue
    cuts.push({
      index: match.index + prefix.length,
      end: markerEnd,
      block: { kind: "item", marker: normalizeMarker(marker), text: "" },
    })
  }

  // 同一位置可能被多个正则命中（如「一、岗位职责」同时命中中文序号标题与标题词），
  // 按起点排序后保留外层匹配，丢弃被前一个切点覆盖的内层切点。
  const sorted = cuts.sort((a, b) => a.index - b.index || b.end - a.end)
  const deduped: Cut[] = []
  let lastEnd = -1
  for (const cut of sorted) {
    if (cut.index < lastEnd) continue
    deduped.push(cut)
    lastEnd = Math.max(lastEnd, cut.end)
  }
  return deduped
}

/**
 * 把 JD 文本解析为结构化块。
 * - 已有换行的文本：逐行处理，行内再识别标题/条目；
 * - 整行塌缩的文本：按标题词与编号切分。
 */
export function parseJobDescription(raw: string): JobDescriptionBlock[] {
  if (!raw || !raw.trim()) return []

  const normalized = normalizeWhitespace(raw).replace(/^[：:]+/, "")
  if (!normalized) return []

  const blocks: JobDescriptionBlock[] = []
  for (const line of normalized.split("\n")) {
    const text = line.trim()
    if (!text) continue
    // 独占一行的中文序号标题：一、岗位职责 / 二、核心职责：（已带换行的 JD）
    const cnLine = text.match(CN_LINE_HEADING_RE)
    if (cnLine) {
      blocks.push({ kind: "heading", text: `${cnLine[1]}、${cnLine[2].trim()}` })
      continue
    }
    blocks.push(...parseLine(text))
  }
  return blocks
}

function parseLine(text: string): JobDescriptionBlock[] {
  const blocks: JobDescriptionBlock[] = []
  const cuts = collectCuts(text)

  // 逐个切点消费：切点之前的文本按段落处理，切点自身产出标题/条目，
  // 条目正文一直延伸到下一个切点。
  let cursor = 0
  let pendingItem: Extract<JobDescriptionBlock, { kind: "item" }> | null = null

  const flushItem = (end: number) => {
    if (!pendingItem) return
    const body = text.slice(cursor, end).replace(/[；;，,、\s]+$/, "").trim()
    if (body) {
      blocks.push({ ...pendingItem, text: body })
    }
    pendingItem = null
  }

  for (const cut of cuts) {
    if (cut.index < cursor) continue // 落在上一条目正文内的切点（极少见），忽略

    if (pendingItem) {
      flushItem(cut.index)
    } else {
      const between = text.slice(cursor, cut.index).trim()
      if (between) blocks.push({ kind: "paragraph", text: between })
    }

    if (cut.block.kind === "item") {
      pendingItem = cut.block
      cursor = cut.end
    } else {
      blocks.push(cut.block)
      cursor = cut.end
    }
  }

  if (pendingItem) {
    flushItem(text.length)
  } else {
    const tail = text.slice(cursor).trim()
    if (tail) blocks.push({ kind: "paragraph", text: tail })
  }

  return blocks
}
