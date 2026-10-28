import React from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { render, waitFor } from "@testing-library/react"

vi.mock("@/lib/api", () => ({ API_BASE: "http://backend.test" }))
vi.mock("@/hooks/use-dual-channel-voice", () => ({
  useDualChannelVoice: () => ({
    isRecording: false,
    activeEngine: null,
    streamingText: "",
    toggleRecording: () => {},
    clearStreamingText: () => {},
    stopRecording: () => {},
  }),
}))
vi.mock("@/hooks/use-skill-rewrite", () => ({ fetchGlobalJdReport: vi.fn() }))

import { fetchGlobalJdReport } from "@/hooks/use-skill-rewrite"
import { ExperienceGriller } from "@/components/dashboard/resume-builder/experience-griller"

/**
 * 经历拷问的画像注入（2026-10-17）：
 * 无 customJdContext 时经 fetchGlobalJdReport 取速览版作为 jd_report_context；
 * 无画像时沿用空上下文继续拷问；显式传 customJdContext 时不拉全局画像。
 */

const BRIEF = "- 硬技能：Python/SQL\n- 软技能：跨部门协作"
const FINAL_FRAME = 'event: final\ndata: {"question":"Q1","suggested_options":["a"],"is_finished":false,"blocks":[]}\n\n'

function sseBody(frames: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      frames.forEach((f) => controller.enqueue(enc.encode(f)))
      controller.close()
    },
  })
}

function stubGrillStream() {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, body: sseBody([FINAL_FRAME]) })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

function firstGrillBody(fetchMock: ReturnType<typeof vi.fn>) {
  const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/strategy/grill_experience_stream"))
  expect(call, "应向 grill_experience_stream 发起首轮拷问").toBeTruthy()
  return JSON.parse((call![1] as RequestInit).body as string)
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.mocked(fetchGlobalJdReport).mockReset()
})

describe("ExperienceGriller 画像注入", () => {
  it("无 customJdContext 时取速览版作为 jd_report_context，且不再直取 /get_jd_report", async () => {
    vi.mocked(fetchGlobalJdReport).mockResolvedValue(BRIEF)
    const fetchMock = stubGrillStream()

    render(<ExperienceGriller originalExperience="做了个数据报表" onAccept={() => {}} onCancel={() => {}} />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(fetchGlobalJdReport).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/get_jd_report"))).toBe(false)
    const body = firstGrillBody(fetchMock)
    expect(body.jd_report_context).toBe(BRIEF)
    expect(body.original_experience).toBe("做了个数据报表")
    expect(body.chat_history).toEqual([])
    expect(body.current_turn).toBe(1)
  })

  it("无画像（速览与完整版皆空）时以空上下文继续拷问", async () => {
    vi.mocked(fetchGlobalJdReport).mockResolvedValue("")
    const fetchMock = stubGrillStream()

    render(<ExperienceGriller originalExperience="经历" onAccept={() => {}} onCancel={() => {}} />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(firstGrillBody(fetchMock).jd_report_context).toBe("")
  })

  it("显式传入 customJdContext 时不拉全局画像，原样透传", async () => {
    const fetchMock = stubGrillStream()

    render(<ExperienceGriller originalExperience="经历" customJdContext="某岗位 JD 原文" onAccept={() => {}} onCancel={() => {}} />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(fetchGlobalJdReport).not.toHaveBeenCalled()
    expect(firstGrillBody(fetchMock).jd_report_context).toBe("某岗位 JD 原文")
  })
})
