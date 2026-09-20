import React from "react"
import { render, screen, fireEvent, act } from "@testing-library/react"
import { describe, it, expect, beforeEach } from "vitest"
import { PersonalInfo } from "./personal-info"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"

describe("PersonalInfo Component Continuous Typing & Focus Stability", () => {
  beforeEach(() => {
    useResumeV2Store.getState().setResumeData({
      personalInfo: {
        name: "",
        title: "AI产品岗",
        phone: "147-123-1234",
        email: "test@example.com",
        location: "广州",
        website: "https://github.com/test",
      },
      moduleOrder: ["summary", "workExperience"],
    } as any)
  })

  it("renders standard fields with placeholders", () => {
    render(<PersonalInfo />)
    expect(screen.getByPlaceholderText("请输入姓名")).toBeTruthy()
    expect(screen.getByPlaceholderText("如：前端开发工程师")).toBeTruthy()
    expect(screen.getByPlaceholderText("请输入手机号")).toBeTruthy()
    expect(screen.getByPlaceholderText("请输入邮箱")).toBeTruthy()
  })

  it("supports continuous typing into name input without losing focus or resetting DOM elements", () => {
    render(<PersonalInfo />)
    const nameInput = screen.getByPlaceholderText("请输入姓名") as HTMLInputElement

    // 模拟用户连续打字 "张", "三", "AI"
    nameInput.focus()
    expect(document.activeElement).toBe(nameInput)

    act(() => {
      fireEvent.change(nameInput, { target: { value: "张" } })
    })
    expect(nameInput.value).toBe("张")
    // 关键断言：输入框 DOM 节点未被卸载重建，焦点必须依然保持在当前输入框上
    expect(document.activeElement).toBe(nameInput)

    act(() => {
      fireEvent.change(nameInput, { target: { value: "张三" } })
    })
    expect(nameInput.value).toBe("张三")
    expect(document.activeElement).toBe(nameInput)

    act(() => {
      fireEvent.change(nameInput, { target: { value: "张三 AI" } })
    })
    expect(nameInput.value).toBe("张三 AI")
    expect(document.activeElement).toBe(nameInput)

    // 验证 Zustand store 数据同步一致
    expect(useResumeV2Store.getState().resumeData?.personalInfo?.name).toBe("张三 AI")
  })

  it("allows adding custom fields and typing into them continuously", () => {
    render(<PersonalInfo />)
    const addCustomBtn = screen.getByText("新增自定义字段")
    act(() => {
      fireEvent.click(addCustomBtn)
    })

    const customInputs = screen.getAllByPlaceholderText("请输入内容") as HTMLInputElement[]
    const customInput = customInputs[customInputs.length - 1]

    customInput.focus()
    expect(document.activeElement).toBe(customInput)

    act(() => {
      fireEvent.change(customInput, { target: { value: "全栈开发者" } })
    })
    expect(customInput.value).toBe("全栈开发者")
    expect(document.activeElement).toBe(customInput)
  })
})
