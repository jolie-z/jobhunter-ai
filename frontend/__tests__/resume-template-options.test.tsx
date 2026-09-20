import React from "react"
import { describe, it, expect } from "vitest"
import { render } from "@testing-library/react"
import ResumeColorV2 from "@/components/resume-print/resume-color-v2"
import type { ResumeDataV2 } from "@/types/resume"

describe("ResumeColorV2 & Template Safety", () => {
  it("renders correctly without crashing when description is a string instead of string[]", () => {
    const rawData = {
      personalInfo: {
        name: "张三",
        title: "信息化咨询顾问",
        email: "demo@test.com",
        phone: "13800000000",
        location: "广州",
      },
      summary: "资深产品专家",
      workExperience: [
        {
          company: "某电商集团",
          title: "电商数据专家",
          years: "2020-2023",
          // 关键边界：description 为 string 而非 string[]
          description: "负责核心电商数据大盘与自动化构建" as any,
        },
      ],
      personalProjects: [
        {
          name: "Auto-JobHunter",
          role: "owner",
          years: "2026-至今",
          // 关键边界：description 为 string 而非 string[]
          description: "全自动求职系统" as any,
        },
      ],
      education: [
        {
          institution: "临江大学",
          major: "信息管理",
          degree: "本科",
          years: "2016-2020",
        },
      ],
      additional: {
        technicalSkills: ["Python", "FastAPI", "React"],
        languages: ["英语 CET-6"],
        certificationsTraining: ["PMP"],
      },
      moduleOrder: ["personalInfo", "summary", "workExperience", "personalProjects", "education", "additional"],
      moduleTitles: {},
    } as ResumeDataV2

    const { container } = render(<ResumeColorV2 data={rawData} />)
    expect(container).toBeDefined()
    expect(container.textContent).toContain("张 三")
    expect(container.textContent).toContain("某电商集团")
    expect(container.textContent).toContain("负责核心电商数据大盘与自动化构建")
    expect(container.textContent).toContain("Auto-JobHunter")
  })

  it("renders correctly when description is an array of strings", () => {
    const rawData = {
      personalInfo: {
        name: "张三",
        title: "全栈工程师",
        email: "zhangsan@test.com",
        phone: "13900000000",
        location: "深圳",
      },
      summary: "AI 应用全栈开发",
      workExperience: [
        {
          company: "腾讯",
          title: "前端技术负责人",
          years: "2021-2024",
          description: ["负责微前端架构演进", "搭建 CI/CD 自动化门禁"],
        },
      ],
      personalProjects: [],
      education: [],
      additional: {
        technicalSkills: ["TypeScript", "Next.js"],
        languages: [],
        certificationsTraining: [],
      },
      moduleOrder: ["personalInfo", "summary", "workExperience"],
      moduleTitles: {},
    } as ResumeDataV2

    const { container } = render(<ResumeColorV2 data={rawData} />)
    expect(container.textContent).toContain("张 三")
    expect(container.textContent).toContain("负责微前端架构演进")
  })

  it("checks ExportActionGroup renders 彩色模版 and DIY模版 correctly based on env", async () => {
    const { fireEvent, screen } = await import("@testing-library/react")
    const { ExportActionGroup } = await import(
      "@/components/dashboard/features/v2-resume-editor/components/export-action-group"
    )
    const { container } = render(<ExportActionGroup />)
    const button = container.querySelector('[data-testid="export-menu-trigger"]')
    expect(button).toBeDefined()
    if (button) {
      fireEvent.pointerDown(button)
      expect(document.body.textContent).toContain("PDF · 彩色模版")
      expect(document.body.textContent).toContain("图片 · 彩色模版")
      // 当 NEXT_PUBLIC_ENABLE_DIY_TEMPLATE=true 时，渲染 DIY 模版；未开启时则隐藏
      if (process.env.NEXT_PUBLIC_ENABLE_DIY_TEMPLATE === "true") {
        expect(document.body.textContent).toContain("PDF · DIY模版")
        expect(document.body.textContent).toContain("图片 · DIY模版")
      } else {
        expect(document.body.textContent).not.toContain("PDF · DIY模版")
        expect(document.body.textContent).not.toContain("图片 · DIY模版")
      }
    }
  })
})
