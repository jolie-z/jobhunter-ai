import { describe, expect, it } from "vitest"
import { WAKE_DEATH_WATCH_MS, findWakeDeaths } from "./platform-session-bar"

const mk = (platform: string, is_alive: boolean, display_name = platform) => ({
  platform,
  display_name,
  is_alive,
})

describe("findWakeDeaths 唤起后死亡监视", () => {
  const now = 1_000_000
  const watch = new Map([["liepin", now + WAKE_DEATH_WATCH_MS]])

  it("观察窗口内 存活→掉线 判定为异常退出", () => {
    const deaths = findWakeDeaths([mk("liepin", true)], [mk("liepin", false)], watch, now)
    expect(deaths).toEqual([{ platform: "liepin", display_name: "liepin" }])
  })

  it("上一轮本就不在线 → 不告警", () => {
    const deaths = findWakeDeaths([mk("liepin", false)], [mk("liepin", false)], watch, now)
    expect(deaths).toEqual([])
  })

  it("超出观察窗口 → 不告警", () => {
    const expired = new Map([["liepin", now - 1]])
    const deaths = findWakeDeaths([mk("liepin", true)], [mk("liepin", false)], expired, now)
    expect(deaths).toEqual([])
  })

  it("仍然存活 → 不告警", () => {
    const deaths = findWakeDeaths([mk("liepin", true)], [mk("liepin", true)], watch, now)
    expect(deaths).toEqual([])
  })

  it("未被监视的平台掉线 → 不告警（如用户主动关闭全部）", () => {
    const deaths = findWakeDeaths([mk("boss", true)], [mk("boss", false)], watch, now)
    expect(deaths).toEqual([])
  })

  it("多平台混合：只报窗口内翻转的那一个", () => {
    const w = new Map([
      ["liepin", now + 60_000],
      ["boss", now - 60_000],
    ])
    const prev = [mk("liepin", true), mk("boss", true), mk("zhilian", false)]
    const curr = [mk("liepin", false), mk("boss", false), mk("zhilian", false, "智联")]
    const deaths = findWakeDeaths(prev, curr, w, now)
    expect(deaths).toEqual([{ platform: "liepin", display_name: "liepin" }])
  })
})
