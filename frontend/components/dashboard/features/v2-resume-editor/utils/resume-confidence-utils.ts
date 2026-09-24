/**
 * 解析置信度展示辅助（纯函数）。
 */

export type ModuleConfidence = Record<string, string | undefined>

/** 取所有「待确认」（置信度 low）的模块 key，按传入顺序返回。 */
export function getPendingModuleKeys(confidence: ModuleConfidence | undefined | null): string[] {
  if (!confidence) return []
  return Object.entries(confidence)
    .filter(([, v]) => v === "low")
    .map(([k]) => k)
}
