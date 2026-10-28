/**
 * 面试态跟进状态词 —— 单一事实源（2026-10-11）。
 *
 * 背景：面试训练营待战列表此前用内联白名单（无「面试中」），而状态下拉预设、
 * 状态徽章、转化漏斗、列表筛选都认识「面试中」——用户把岗位标成面试中恰恰最需要
 * 备战，训练营却看不见（状态词表漂移的又一同族病）。凡「哪些跟进状态算面试态」
 * 的判断一律从这里取词，禁止再内联。
 *
 * 注意：「面试中」在 PRESET_STATUSES（app/page.tsx 状态下拉）中是一等公民；
 * 一面/二面/三面 为历史数据兼容值（状态下拉预设无此三项，仅手动输入产生）。
 */
export const INTERVIEW_FOLLOW_STATUSES = [
  "待面试",
  "面试中",
  "已约面",
  "一面",
  "二面",
  "三面",
  "Offer",
  "已下发Offer",
] as const

export type InterviewFollowStatus = (typeof INTERVIEW_FOLLOW_STATUSES)[number]

/** 空态提示文案（从常量动态生成，杜绝与词表漂移——R1 P2） */
export const INTERVIEW_STATUS_HINT = INTERVIEW_FOLLOW_STATUSES.slice(0, -1).join(" / ")

export function isInterviewFollowStatus(status: string | null | undefined): boolean {
  // includes 的字面量联合参数需放宽：运行时输入是任意用户自定义状态词
  return (INTERVIEW_FOLLOW_STATUSES as readonly string[]).includes((status || "").trim())
}
