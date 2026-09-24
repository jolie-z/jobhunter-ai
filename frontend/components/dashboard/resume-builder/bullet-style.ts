/**
 * 列表符号样式库（Office 风格符号参考）+ 纯函数变换。
 *
 * 数据层仍是 markdown 字符串：
 * - 「标准圆点 / 数字编号」写回真列表（- / 1.），保留悬挂缩进与 ATS 解析安全性；
 * - 特殊符号（○ ■ ◆ ▸ ➢ 一、① a)）以文本前缀形式存在，编辑器与导出 PDF 按原样呈现。
 *
 * applyListStyle 只重排「已经是列表形态」的行（markdown 列表、已知符号前缀、编号前缀），
 * 绝不碰普通正文行；应用范围由调用方决定（通常为当前模块整体），以保证符号风格统一。
 */

export interface ListStyleOption {
  id: string
  label: string
  sample: string
  group: "unordered" | "ordered"
}

export const LIST_STYLE_OPTIONS: ListStyleOption[] = [
  { id: "disc", label: "标准圆点", sample: "•", group: "unordered" },
  { id: "circle", label: "空心圆", sample: "○", group: "unordered" },
  { id: "square", label: "实心方块", sample: "■", group: "unordered" },
  { id: "diamond", label: "实心菱形", sample: "◆", group: "unordered" },
  { id: "triangle", label: "三角箭头", sample: "▸", group: "unordered" },
  { id: "arrow", label: "鱼尾箭头", sample: "➢", group: "unordered" },
  { id: "num", label: "数字编号", sample: "1.", group: "ordered" },
  { id: "cn", label: "中文编号", sample: "一、", group: "ordered" },
  { id: "circled", label: "圆圈数字", sample: "①", group: "ordered" },
  { id: "alpha", label: "字母编号", sample: "a)", group: "ordered" },
]

/** 可识别为「符号 bullet」的前缀字符（含 Word/常见简历导入件中的变体） */
export const GLYPH_BULLETS = ["•", "●", "○", "■", "□", "◆", "◇", "▸", "►", "➢", "➤", "★", "✦", "·"]

const GLYPH_LINE_RE = new RegExp(`^(\\s*)([${GLYPH_BULLETS.join("")}])\\s+(\\S.*)$`)
const MD_UNORDERED_RE = /^(\s*)[-+]\s+(\S.*)$/
// 单个 * 后跟空白才是列表；** 加粗起头的行（如 **要点**：xxx）不能被吞
const MD_STAR_RE = /^(\s*)\*\s+(\S.*)$/
// `.`/`)` 分隔符后必须至少一个空白（否则 `2023.09 - 2024.08`、`99.9%` 会被误判成列表）；
// `、` 是中文序号习惯允许紧贴，但限 1-3 位数字（`2023、` 这类年份不当列表）
const MD_ORDERED_RE = /^(\s*)(?:\d+[.)][ \t]+|\d{1,3}、\s*)(\S.*)$/
const CIRCLED_RE = /^(\s*)([\u2460-\u2473\u3251-\u325F\u32B1-\u32BF])\s*(\S.*)$/
const CN_ORDERED_RE = /^(\s*)[一二三四五六七八九十百]+\s*、\s*(\S.*)$/
const ALPHA_ORDERED_RE = /^(\s*)[a-zA-Z][).]\s+(\S.*)$/

/** 行是否带任何「列表/符号/编号」前缀（供 bullet 规范化守卫等复用） */
export function hasListStylePrefix(line: string): boolean {
  const t = line.trim()
  if (!t) return false
  return (
    MD_UNORDERED_RE.test(line) ||
    MD_STAR_RE.test(line) ||
    MD_ORDERED_RE.test(line) ||
    GLYPH_LINE_RE.test(line) ||
    CIRCLED_RE.test(line) ||
    CN_ORDERED_RE.test(t) ||
    ALPHA_ORDERED_RE.test(t)
  )
}

interface ListItem {
  indent: string
  text: string
}

function matchListItem(line: string): ListItem | null {
  let m = MD_UNORDERED_RE.exec(line) || MD_STAR_RE.exec(line)
  if (m) return { indent: m[1], text: m[2] }
  m = MD_ORDERED_RE.exec(line)
  if (m) return { indent: m[1], text: m[2] }
  m = GLYPH_LINE_RE.exec(line)
  if (m) return { indent: m[1], text: m[3] }
  m = CIRCLED_RE.exec(line)
  if (m) return { indent: m[1], text: m[3] }
  m = CN_ORDERED_RE.exec(line)
  if (m) return { indent: m[1], text: m[2] }
  m = ALPHA_ORDERED_RE.exec(line)
  if (m) return { indent: m[1], text: m[2] }
  return null
}

function toCnNumber(n: number): string {
  const digits = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
  if (n <= 0) return String(n)
  if (n < 10) return digits[n]
  if (n === 10) return "十"
  if (n < 20) return "十" + digits[n % 10]
  if (n < 100) {
    const tens = Math.floor(n / 10)
    const ones = n % 10
    return digits[tens] + "十" + (ones ? digits[ones] : "")
  }
  return String(n)
}

function toCircledNumber(n: number): string {
  if (n >= 1 && n <= 20) return String.fromCharCode(0x2460 + n - 1) // ①-⑳
  if (n >= 21 && n <= 35) return String.fromCharCode(0x3251 + n - 21) // ㉑-㉟
  return String.fromCharCode(0x32b1 + n - 36) // ㊱-㊿（调用方保证 n<=50）
}

function toAlphaNumber(n: number): string {
  let s = ""
  let v = n
  while (v > 0) {
    const rem = (v - 1) % 26
    s = String.fromCharCode(97 + rem) + s
    v = Math.floor((v - 1) / 26)
  }
  return s
}

function renderListItem(item: ListItem, styleId: string, counter: number): string {
  const { indent, text } = item
  switch (styleId) {
    case "disc":
      return `${indent}- ${text}`
    case "circle":
      return `${indent}○ ${text}`
    case "square":
      return `${indent}■ ${text}`
    case "diamond":
      return `${indent}◆ ${text}`
    case "triangle":
      return `${indent}▸ ${text}`
    case "arrow":
      return `${indent}➢ ${text}`
    case "num":
      return `${indent}${counter}. ${text}`
    case "cn":
      return `${indent}${toCnNumber(counter)}、${text}`
    case "circled":
      // 圆圈数字字符集仅覆盖 1-50，超出后退回普通数字编号；符号后统一空格分隔
      return counter <= 50
        ? `${indent}${toCircledNumber(counter)} ${text}`
        : `${indent}${counter}. ${text}`
    case "alpha":
      return `${indent}${toAlphaNumber(counter)}) ${text}`
    default:
      return `${indent}- ${text}`
  }
}

/**
 * 把内容中所有列表形态的行统一重排为指定符号/编号风格。
 * 编号在同一段连续列表内自增，遇到空行或普通正文行重置。
 */
export function applyListStyle(content: string, styleId: string): string {
  if (!content) return content
  const known = LIST_STYLE_OPTIONS.some((o) => o.id === styleId)
  if (!known) return content
  let counter = 0
  return content
    .split("\n")
    .map((line) => {
      const item = matchListItem(line)
      if (!item) {
        counter = 0
        return line
      }
      counter += 1
      return renderListItem(item, styleId, counter)
    })
    .join("\n")
}
