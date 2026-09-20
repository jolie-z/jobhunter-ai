import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"
import { JobCardMaterials } from "./job-card-materials"
import type { PipelineJob } from "@/store/pipeline-store"

/**
 * 已投递卡片物料规范回归（2026-09-15）：
 * - 长图简历为 BOSS 微聊专属，猎聘/智联/51job 一律屏蔽（此前猎聘误展【长图简历】）
 * - PDF 简历仅附件投递平台外发，BOSS 微聊只发长图（此前 BOSS 误展【PDF简历】）
 * - 欢迎语按精投/海投区分文案：专用欢迎语 / 通用欢迎语
 * - 打招呼回执只信 greeting / greeting_failed 真实标记
 */
const deliveredJob = (overrides: Partial<PipelineJob> = {}): PipelineJob =>
  ({
    job_id: "recvt9eIwK6VPD",
    job_name: "智能座舱产品经理",
    company_name: "华勤技术",
    platform: "liepin",
    status: "delivered",
    delivery_materials: { pdf: true, image: true, greeting: true, greeting_failed: false },
    ...overrides,
  }) as PipelineJob

const renderDelivered = (
  job: PipelineJob,
  flags: { isCustomJob?: boolean; isZhilian?: boolean; isBoss?: boolean } = {}
) =>
  render(
    <JobCardMaterials
      job={job}
      isWaiting={false}
      isReadyToDeliver={false}
      isDelivered={true}
      isCustomJob={flags.isCustomJob ?? false}
      isZhilian={flags.isZhilian ?? false}
      isBoss={flags.isBoss ?? false}
      onPreview={vi.fn()}
    />
  )

describe("JobCardMaterials 已投递物料规范", () => {
  it("猎聘海投：展示 PDF简历 + 通用欢迎语，屏蔽长图简历（即使飞书沉淀了长图备份）", () => {
    renderDelivered(deliveredJob(), { isCustomJob: false })

    expect(screen.getByText("PDF简历")).toBeTruthy()
    expect(screen.getByText("通用欢迎语")).toBeTruthy()
    expect(screen.queryByText("长图简历")).toBeNull()
    expect(screen.queryByText("专用欢迎语")).toBeNull()
    expect(screen.queryByText("打招呼未送达")).toBeNull()
  })

  it("猎聘精投：欢迎语文案切换为专用欢迎语，仍屏蔽长图简历", () => {
    renderDelivered(deliveredJob({ review_type: "custom_tailored" } as Partial<PipelineJob>), { isCustomJob: true })

    expect(screen.getByText("PDF简历")).toBeTruthy()
    expect(screen.getByText("专用欢迎语")).toBeTruthy()
    expect(screen.queryByText("通用欢迎语")).toBeNull()
    expect(screen.queryByText("长图简历")).toBeNull()
  })

  it("BOSS 已投递：长图简历为专属物料正常展示；即使飞书沉淀了 PDF 备份也严格屏蔽 PDF简历", () => {
    renderDelivered(deliveredJob({ platform: "boss" }), { isBoss: true })

    expect(screen.getByText("长图简历")).toBeTruthy()
    expect(screen.queryByText("PDF简历")).toBeNull()
  })

  it("打招呼未送达真实回执：隐藏送达欢迎语，改为黄色警示 chip", () => {
    renderDelivered(
      deliveredJob({ delivery_materials: { pdf: true, image: false, greeting: false, greeting_failed: true } }),
      { isCustomJob: false }
    )

    expect(screen.getByText("打招呼未送达")).toBeTruthy()
    expect(screen.queryByText("通用欢迎语")).toBeNull()
    expect(screen.queryByText("专用欢迎语")).toBeNull()
  })

  it("51job 已投递：只展示 PDF简历，严格不展示任何欢迎语（契约 greeting: false）", () => {
    renderDelivered(
      deliveredJob({
        platform: "51job",
        delivery_materials: { pdf: true, image: false, greeting: false, greeting_failed: false },
      }),
      { isCustomJob: false }
    )

    expect(screen.getByText("PDF简历")).toBeTruthy()
    expect(screen.queryByText("通用欢迎语")).toBeNull()
    expect(screen.queryByText("专用欢迎语")).toBeNull()
    expect(screen.queryByText("打招呼未送达")).toBeNull()
  })

  it("待投递阶段：supportsGreeting 为 false 时隐藏欢迎语核验按钮，为 true 时正常展示", () => {
    const { rerender } = render(
      <JobCardMaterials
        job={deliveredJob({ status: "ready_to_deliver" })}
        isWaiting={true}
        isReadyToDeliver={false}
        isDelivered={false}
        isCustomJob={false}
        isZhilian={false}
        supportsGreeting={false}
        onPreview={vi.fn()}
      />
    )
    expect(screen.queryByText("欢迎语")).toBeNull()

    rerender(
      <JobCardMaterials
        job={deliveredJob({ status: "ready_to_deliver" })}
        isWaiting={true}
        isReadyToDeliver={false}
        isDelivered={false}
        isCustomJob={false}
        isZhilian={false}
        supportsGreeting={true}
        onPreview={vi.fn()}
      />
    )
    expect(screen.getByText("欢迎语")).toBeTruthy()
  })
})
