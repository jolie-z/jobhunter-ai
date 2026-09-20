import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"
import { DynamicFieldSlot } from "./dynamic-field-slot"

describe("DynamicFieldSlot 组件", () => {
  it("无动态未声明字段时不渲染任何内容", () => {
    const data = { name: "张三", title: "研发" }
    const { container } = render(
      <DynamicFieldSlot
        data={data}
        excludeKeys={["name", "title"]}
        onChange={vi.fn()}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it("自动渲染标量新字段并响应输入修改", () => {
    const onChange = vi.fn()
    const data = {
      name: "张三",
      patentCode: "CN10001",
      remoteWork: true,
    }
    render(
      <DynamicFieldSlot
        data={data}
        excludeKeys={["name"]}
        onChange={onChange}
      />
    )

    expect(screen.getByText("patentCode")).toBeDefined()
    const input = screen.getByDisplayValue("CN10001")
    fireEvent.change(input, { target: { value: "CN99999" } })
    expect(onChange).toHaveBeenCalledWith("patentCode", "CN99999")
  })

  it("自动渲染标签组 (Tag Chips) 并支持添加与删除", () => {
    const onChange = vi.fn()
    const data = {
      name: "张三",
      customKeywords: ["AI Agent", "FastAPI"],
    }
    render(
      <DynamicFieldSlot
        data={data}
        excludeKeys={["name"]}
        onChange={onChange}
      />
    )

    expect(screen.getByText("customKeywords")).toBeDefined()
    expect(screen.getByText("AI Agent")).toBeDefined()
    expect(screen.getByText("FastAPI")).toBeDefined()

    // 触发删除一个 tag
    const deleteBtns = screen.getAllByRole("button", { name: "×" })
    fireEvent.click(deleteBtns[0])
    expect(onChange).toHaveBeenCalledWith("customKeywords", ["FastAPI"])
  })

  it("自动渲染嵌套对象子列表 (Sub-lists) 并支持编辑", () => {
    const onChange = vi.fn()
    const data = {
      name: "张三",
      achievements: [
        { title: "季度技术之星", rank: "Top 1" }
      ],
    }
    render(
      <DynamicFieldSlot
        data={data}
        excludeKeys={["name"]}
        onChange={onChange}
      />
    )

    expect(screen.getByText("achievements")).toBeDefined()
    const titleInput = screen.getByDisplayValue("季度技术之星")
    fireEvent.change(titleInput, { target: { value: "年度突出贡献奖" } })
    expect(onChange).toHaveBeenCalledWith("achievements", [
      { title: "年度突出贡献奖", rank: "Top 1" }
    ])
  })

  it("自动过滤平台底层系统元数据与时间戳字段（resumeId, createTime 等）", () => {
    const data = {
      name: "张三",
      resumeId: "369525152",
      createTime: "2020-09-12 00:21:51",
      moduleId: "0006",
      complete: true,
      workVocationalSkills: ["NLP"],
    }
    const { container } = render(
      <DynamicFieldSlot
        data={data}
        excludeKeys={["name"]}
        onChange={vi.fn()}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it("支持从 template 模版对象中动态反射提取已知字段，零配置自动排除", () => {
    const template = {
      schoolName: "",
      degree: "",
      major: "",
    }
    const data = {
      schoolName: "清华大学",
      degree: "本科",
      major: "计算机",
      extraHonor: "一等奖学金",
    }
    render(
      <DynamicFieldSlot
        data={data}
        template={template}
        onChange={vi.fn()}
      />
    )
    // template 里的字段均被动态排除，仅渲染真正的业务新增 extraHonor
    expect(screen.queryByText("schoolName")).toBeNull()
    expect(screen.getByText("extraHonor")).toBeDefined()
  })
})
