import React from "react"
import { render, screen } from "@testing-library/react"
import { describe, it, expect } from "vitest"
import { ResumeClassic } from "./resume-classic"
import type { ResumeDataV2 } from "@/types/resume"

// 2026-10-28 自定义模块原文保真改造的打印侧回归：
// 曾经「PDF 预览有、编辑器没有」（LLM 塞进 company/title 的内容编辑器不渲染），
// 改造后数据出口归一化为纯 description；打印模板需同时照顾新老两种形态 + 用户自建 KV 字段。

function buildData(customModules: NonNullable<ResumeDataV2["customModules"]>): ResumeDataV2 {
  return {
    personalInfo: { name: "张三", title: "", email: "", phone: "", location: "" },
    summary: "",
    workExperience: [],
    education: [],
    personalProjects: [],
    additional: { skillOverview: "", technicalSkills: [], languages: [], certificationsTraining: [] },
    moduleOrder: ["publications"],
    moduleTitles: { publications: "论文及专著" },
    customModules,
  }
}

describe("ResumeClassic 自定义模块原文保真", () => {
  it("纯 description 条目（归一化后的新数据）：每行独立成块，不留空表头行", () => {
    render(
      <ResumeClassic
        data={buildData({
          publications: [
            { title: "", company: "", years: "", description: ["第一作者 (In preparation)", "PNAS 121(40): e2402741121"] },
          ],
        })}
      />
    )
    // 两行必须是两个独立的块：单 \n 会被 Markdown 当软换行揉进同一个 span、PDF 上塌成一行
    const blocks = Array.from(document.querySelectorAll("span.block")).map((el) => el.textContent?.trim())
    expect(blocks).toEqual(["第一作者 (In preparation)", "PNAS 121(40): e2402741121"])
    // 无 company/title/years → 不应渲染表头 grid 行
    expect(document.querySelector("h4")).toBeNull()
  })

  it("老数据非空标准字段：表头三列照常渲染，不破坏老用户资产", () => {
    render(
      <ResumeClassic
        data={buildData({
          publications: [{ title: "国家奖学金", company: "教育部", years: "2021", description: [] }],
        })}
      />
    )
    expect(screen.getByText("教育部")).toBeTruthy()
    expect(screen.getByText("国家奖学金")).toBeTruthy()
    expect(screen.getByText("2021")).toBeTruthy()
  })

  it("用户自建 KV 字段：拼行打印，不再「编辑器可见、PDF 消失」", () => {
    render(
      <ResumeClassic
        data={buildData({
          publications: [
            { title: "", company: "", years: "", description: ["正文内容"], "级别": "国家级" } as never,
          ],
        })}
      />
    )
    expect(screen.getByText("正文内容")).toBeTruthy()
    expect(screen.getByText("级别：国家级")).toBeTruthy()
  })

  it("值为空/纯空白的自建字段不渲染，不出悬空的「字段名：」", () => {
    render(
      <ResumeClassic
        data={buildData({
          publications: [
            { title: "", company: "", years: "", description: ["正文内容"], "备注": "   ", "级别": "" } as never,
          ],
        })}
      />
    )
    expect(screen.getByText("正文内容")).toBeTruthy()
    expect(screen.queryByText(/备注/)).toBeNull()
    expect(screen.queryByText(/级别/)).toBeNull()
  })
})
