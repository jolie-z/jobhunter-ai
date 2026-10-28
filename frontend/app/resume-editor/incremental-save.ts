/**
 * 增量保存载荷构建（2026-10-23 保存接口模块级合并改造配套）。
 *
 * 后端 POST /api/resume-editor/save/{platform} 已改为模块级增量合并：只发被修改的
 * 模块，未发送的模块在服务端原样保留。本模块用深比较筛出变化模块，根治
 * 「读全量 → 内存改 → 写全量」模式下旧内存快照覆盖并发写入（采集 vs 编辑）的丢更新。
 */

/** 递归深比较（简历 JSON 仅数十 KB，性能无虞；不做 JSON.stringify 以规避键序假阴性） */
export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return false
  if (Array.isArray(a) !== Array.isArray(b)) return false
  const keysA = Object.keys(a as Record<string, unknown>)
  const keysB = Object.keys(b as Record<string, unknown>)
  if (keysA.length !== keysB.length) return false
  for (const key of keysA) {
    if (!Object.prototype.hasOwnProperty.call(b, key)) return false
    if (!deepEqual((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key])) {
      return false
    }
  }
  return true
}

/**
 * 构建增量保存载荷：仅包含与 baseline（改前内存数据）深比较有内容差异的模块。
 * - baseline 缺失/未加载（首载失败等）时退化为发送全量 updated，不劣于旧行为；
 * - baseline 健全但未检出任何差异时返回 {}（后端合并为 no-op）——避免意外触发的
 *   保存把服务端并发写入（如后台采集）用旧快照整份盖回（double-check P2 采纳）；
 * - 不做「键缺失 → null 删除」推导（防组件半载误删整模块），整模块删除是后端显式协议。
 */
export function buildIncrementalSavePayload(
  updated: object,
  baseline: object | undefined | null,
): Record<string, unknown> {
  const updatedRecord = updated as Record<string, unknown>
  const base = (baseline ?? {}) as Record<string, unknown>
  if (Object.keys(base).length === 0) return updatedRecord
  const changed: Record<string, unknown> = {}
  for (const key of Object.keys(updatedRecord)) {
    if (!deepEqual(updatedRecord[key], base[key])) changed[key] = updatedRecord[key]
  }
  return changed
}
