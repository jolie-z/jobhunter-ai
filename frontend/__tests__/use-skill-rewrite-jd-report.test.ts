import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", () => ({ API_BASE: "http://backend.test" }))

import { fetchGlobalJdReport } from "@/hooks/use-skill-rewrite"

/**
 * 简历库模式改写的画像输入（2026-10-16 复核修复）：
 * 双轨契约下下游 LLM 消费方必须吃 meta.llm_brief 速览版，
 * 旧报告无速览区块时回退 data 完整版；空画像守卫（返回空串）行为不变。
 */

const FULL = "# 全局 A 级岗位能力画像\n## 一、硬技能\n……（约一万字符的详细版）"
const BRIEF = "- 硬技能：Python/SQL/LangChain\n- 软技能：跨部门协作\n- 业务经验：电商/医药\n- 加分项：RAG 落地"

function stubFetch(body: unknown, ok = true) {
  const fetchMock = vi.fn().mockResolvedValue({ ok, json: async () => body })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("fetchGlobalJdReport 双轨契约", () => {
  it("有速览区块时返回 meta.llm_brief，而不是 data 完整版", async () => {
    const fetchMock = stubFetch({ status: "success", data: FULL, meta: { llm_brief: BRIEF } })
    await expect(fetchGlobalJdReport()).resolves.toBe(BRIEF)
    expect(fetchMock).toHaveBeenCalledWith("http://backend.test/api/strategy/get_jd_report")
  })

  it("旧报告 meta 无 llm_brief 键时回退完整版", async () => {
    stubFetch({ status: "success", data: FULL, meta: { generated_at: "2026-10-12T14:59:59" } })
    await expect(fetchGlobalJdReport()).resolves.toBe(FULL)
  })

  it("llm_brief 为空串或纯空白时回退完整版", async () => {
    stubFetch({ status: "success", data: FULL, meta: { llm_brief: "   \n" } })
    await expect(fetchGlobalJdReport()).resolves.toBe(FULL)
  })

  it("meta 缺失时回退完整版（不因可选链断裂而抛错）", async () => {
    stubFetch({ status: "success", data: FULL })
    await expect(fetchGlobalJdReport()).resolves.toBe(FULL)
  })

  it("速览与完整版都空时返回空串（空画像守卫触发）", async () => {
    stubFetch({ status: "success", data: null, meta: { llm_brief: "" } })
    await expect(fetchGlobalJdReport()).resolves.toBe("")
  })

  it("后端 status 非 success 时返回空串", async () => {
    stubFetch({ status: "error", message: "boom", data: FULL, meta: { llm_brief: BRIEF } })
    await expect(fetchGlobalJdReport()).resolves.toBe("")
  })

  it("HTTP 非 2xx 时返回空串", async () => {
    stubFetch({ status: "success", data: FULL, meta: { llm_brief: BRIEF } }, false)
    await expect(fetchGlobalJdReport()).resolves.toBe("")
  })

  it("fetch 抛错时返回空串", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")))
    await expect(fetchGlobalJdReport()).resolves.toBe("")
  })
})
