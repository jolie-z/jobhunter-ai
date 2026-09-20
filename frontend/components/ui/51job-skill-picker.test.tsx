import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { Job51SkillPicker } from "./51job-skill-picker"
import fs from "fs"
import path from "path"

const mockSkillsJson = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../public/51job_skills.json"), "utf-8")
)

describe("Job51SkillPicker Component", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/51job_skills.json") {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(mockSkillsJson),
          })
        }
        return Promise.reject(new Error("Unknown url"))
      })
    )
  })

  it("renders 5 official categories and excludes 语言类", async () => {
    render(
      <Job51SkillPicker
        open={true}
        onClose={vi.fn()}
        selectedCode=""
        onConfirm={vi.fn()}
      />
    )

    await waitFor(() => {
      expect(screen.getByText("大数据类")).toBeDefined()
    })

    expect(screen.getByText("开发编程类")).toBeDefined()
    expect(screen.getByText("多媒体设计类")).toBeDefined()
    expect(screen.getByText("办公应用软件")).toBeDefined()
    expect(screen.getByText("财务管理类")).toBeDefined()
    expect(screen.queryByText("语言类")).toBeNull()
  })

  it("switches categories and displays corresponding skills", async () => {
    render(
      <Job51SkillPicker
        open={true}
        onClose={vi.fn()}
        selectedCode=""
        onConfirm={vi.fn()}
      />
    )

    await waitFor(() => {
      expect(screen.getByText("大数据类")).toBeDefined()
    })

    // Click on 开发编程类
    fireEvent.click(screen.getByText("开发编程类"))
    expect(screen.getByText("Python")).toBeDefined()
    expect(screen.getByText("Web前端")).toBeDefined()
    expect(screen.getByText("Golang")).toBeDefined()
  })

  it("filters skills by search input", async () => {
    render(
      <Job51SkillPicker
        open={true}
        onClose={vi.fn()}
        selectedCode=""
        onConfirm={vi.fn()}
      />
    )

    await waitFor(() => {
      expect(screen.getByText("大数据类")).toBeDefined()
    })

    const searchInput = screen.getByPlaceholderText("请输入")
    fireEvent.change(searchInput, { target: { value: "sql" } })

    expect(screen.getByText("SQL")).toBeDefined()
    expect(screen.getByText("MySQL")).toBeDefined()
    expect(screen.getByText("SQL Server")).toBeDefined()
  })

  it("disables skills matching disabledCodes and disabledNames with 已添加 label", async () => {
    render(
      <Job51SkillPicker
        open={true}
        onClose={vi.fn()}
        selectedCode=""
        onConfirm={vi.fn()}
        disabledCodes={["0215"]} // SQL
        disabledNames={["Python"]}
      />
    )

    await waitFor(() => {
      expect(screen.getByText("大数据类")).toBeDefined()
    })

    // SQL in 大数据类
    const buttons = screen.getAllByRole("button")
    const sqlButton = buttons.find((b) => b.textContent?.startsWith("SQL") && !b.textContent?.includes("Server"))!
    expect(sqlButton).toBeDefined()
    expect(sqlButton.getAttribute("disabled")).not.toBeNull()
    expect(sqlButton.textContent).toContain("已添加")

    // Switch to 开发编程类 and check Python
    fireEvent.click(screen.getByText("开发编程类"))
    const pythonButton = screen.getAllByRole("button").find((b) => b.textContent?.includes("Python"))!
    expect(pythonButton).toBeDefined()
    expect(pythonButton.getAttribute("disabled")).not.toBeNull()
    expect(pythonButton.textContent).toContain("已添加")
  })

  it("calls onConfirm and onClose when clicking an available skill", async () => {
    const handleConfirm = vi.fn()
    const handleClose = vi.fn()

    render(
      <Job51SkillPicker
        open={true}
        onClose={handleClose}
        selectedCode=""
        onConfirm={handleConfirm}
      />
    )

    await waitFor(() => {
      expect(screen.getByText("大数据类")).toBeDefined()
    })

    // Click on Web前端
    fireEvent.click(screen.getByText("开发编程类"))
    const webButton = screen.getAllByRole("button").find(b => b.textContent?.trim() === "Web前端")!
    fireEvent.click(webButton)

    expect(handleConfirm).toHaveBeenCalledWith("0416", "Web前端", "开发编程类")
    expect(handleClose).toHaveBeenCalled()
  })
})
