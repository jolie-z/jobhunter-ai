import { describe, it, expect } from 'vitest'
import { INTERVIEW_FOLLOW_STATUSES, isInterviewFollowStatus } from './interview-status'

// 面试态单一事实源（2026-10-11 训练营白名单漂移事故回归锁）：
// 状态下拉 PRESET_STATUSES 主动提供「面试中」，训练营白名单却曾是内联 6 值不认识它
// ——「哪些状态算面试态」必须只从此常量取词。

describe('isInterviewFollowStatus', () => {
  it('预设状态「面试中」必须被识别为面试态（事故原案例）', () => {
    expect(isInterviewFollowStatus("面试中")).toBe(true)
  })

  it('训练营历史白名单 6 值继续命中（兼容存量数据）', () => {
    for (const s of ["待面试", "一面", "二面", "三面", "Offer", "已下发Offer"]) {
      expect(isInterviewFollowStatus(s)).toBe(true)
    }
  })

  it('「已约面」（漏斗族状态）与首尾空白容忍', () => {
    expect(isInterviewFollowStatus("已约面")).toBe(true)
    expect(isInterviewFollowStatus(" 面试中 ")).toBe(true)
  })

  it('非面试态不误收（含「面」字陷阱词与普通状态）', () => {
    expect(isInterviewFollowStatus("已拒绝面试")).toBe(false)
    expect(isInterviewFollowStatus("简历人工复核")).toBe(false)
    expect(isInterviewFollowStatus("")).toBe(false)
    expect(isInterviewFollowStatus(null)).toBe(false)
    expect(isInterviewFollowStatus(undefined)).toBe(false)
  })

  it('常量含全部关键值', () => {
    for (const s of ["面试中", "已约面"]) {
      expect(INTERVIEW_FOLLOW_STATUSES).toContain(s)
    }
  })
})
