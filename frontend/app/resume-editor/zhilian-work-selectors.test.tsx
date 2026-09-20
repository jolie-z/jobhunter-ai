import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, fireEvent, cleanup } from "@testing-library/react"
import { SkillSelect } from "./zhilian-work-selectors"

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("SkillSelect Custom Skill Input", () => {
  it("allows entering custom skill in other skills section and pressing Enter to add tag", () => {
    const handleChange = vi.fn()
    render(
      <SkillSelect
        jobTypeId=""
        value={[]}
        onChange={handleChange}
      />
    )

    // Open modal
    const trigger = screen.getByText("点击添加技能标签")
    fireEvent.click(trigger)

    expect(screen.getByText("丰富专业技能，招聘方会更加了解你~~")).toBeDefined()

    // Find the "+ 自定义" button in "其他技能"
    const customBtns = screen.getAllByText("+ 自定义")
    // Click the last one which corresponds to 其他技能
    fireEvent.click(customBtns[customBtns.length - 1])

    // Find the input
    const input = screen.getByPlaceholderText("输入后回车")
    expect(input).toBeDefined()

    // Type "openai" and press Enter
    fireEvent.change(input, { target: { value: "openai" } })
    fireEvent.keyDown(input, { key: "Enter" })

    // The tag "openai" should now appear in the bottom selected list
    expect(screen.getByText("openai")).toBeDefined()
    expect(screen.getByText("确定 · 1")).toBeDefined()

    // Click confirm
    fireEvent.click(screen.getByText("确定 · 1"))
    expect(handleChange).toHaveBeenCalledWith([
      expect.objectContaining({
        name: "openai",
        isCustom: true,
        pathId: -1,
      }),
    ])
  })
})
