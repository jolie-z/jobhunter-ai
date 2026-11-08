import { describe, it, expect } from 'vitest'
import { nowLocalString } from './local-time'

describe('nowLocalString', () => {
  it('输出与后端快照一致的 "YYYY-MM-DD HH:mm:ss" 本地时间串', () => {
    // 用本地时间构造，避免测试机时区不同导致断言漂移
    const d = new Date(2026, 9, 30, 21, 15, 4)
    expect(nowLocalString(d)).toBe('2026-10-30 21:15:04')
  })

  it('月/日/时/分/秒均补零', () => {
    const d = new Date(2026, 0, 2, 3, 4, 5)
    expect(nowLocalString(d)).toBe('2026-01-02 03:04:05')
  })
})
