/**
 * 自定义模块条目的打印辅助（2026-10-28 自定义模块原文保真改造）。
 *
 * 数据形态：归一化后新条目只含 description；存量老条目可能带 company/title/years；
 * 任意条目都可携带用户在编辑器「新增字段」自建的标量 KV。
 * 打印侧三条铁律：
 * 1. 表头行（company/title/years 三列）仅在有内容时渲染，纯 description 条目不留空行；
 * 2. 标准键之外的标量键 = 用户自建字段，必须拼行打印——否则用户自己画的字段永远不上纸；
 * 3. description 每个元素独立成块：单 \n 会被 Markdown 当段内软换行揉进同一段，PDF 上塌成一行。
 */

/** 打印模板条目头/正文已专门处理的标准键 */
export const CUSTOM_ITEM_PRINT_STD_KEYS = new Set([
  "company", "title", "years", "location", "description", "originalContent", "_key", "id",
])

export interface ItemPrintExtra {
  key: string
  value: string
}

/** 提取条目上用户自建的标量 KV 字段；值为空/纯空白的字段剔除，避免打印出悬空的「字段名：」 */
export function extractItemPrintExtras(item: object): ItemPrintExtra[] {
  return Object.entries(item as Record<string, unknown>)
    .filter(([k, v]) => v !== null && v !== undefined && typeof v !== "object" && !CUSTOM_ITEM_PRINT_STD_KEYS.has(k))
    .map(([k, v]) => ({ key: k, value: String(v).trim() }))
    .filter(({ value }) => value !== "")
}

/** 「字段名：值」用间隔点连成一行；由模板决定样式，这里只管文案 */
export function formatItemPrintExtras(extras: ItemPrintExtra[]): string {
  return extras.map(({ key, value }) => `${key}：${value}`).join(" · ")
}

/**
 * description → Markdown 源文：数组元素用空行连接使每个元素独立成块（带 `- ` 的行变松散列表，
 * p 已被模板覆写为 span.block，视觉几乎不变）。纯空白元素剔除，避免多出空段；不 trim 内容本身，
 * 以免破坏嵌套列表的缩进。
 */
export function joinDescriptionBlocks(desc: unknown): string {
  if (Array.isArray(desc)) {
    return desc.map(String).filter((s) => s.trim() !== "").join("\n\n")
  }
  if (typeof desc === "string" || typeof desc === "number") return String(desc)
  return ""
}
