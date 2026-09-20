import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"
import { SchemaDiffDrawer, type SchemaDiffReport } from "./schema-diff-drawer"

describe("SchemaDiffDrawer 组件", () => {
  const mockDiff: SchemaDiffReport = {
    platform: "zhilian",
    has_changes: true,
    summary: "新增 1 个字段，下线 1 个废弃字段",
    added_fields: [
      { module: "training", field: "trainAddress", type: "array_item_field", sample: "北京市海淀区" },
    ],
    removed_fields: [
      { module: "training", field: "oldCertificate", last_value: "已作废" },
    ],
    new_modules: [
      { module: "patentModule", type: "array", item_count: 1 },
    ],
    removed_modules: [],
    sub_list_changes: [],
  }

  it("当 isOpen 为 false 时不渲染", () => {
    const { container } = render(
      <SchemaDiffDrawer
        isOpen={false}
        onClose={vi.fn()}
        diff={mockDiff}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it("正确呈现变动摘要、新增字段、废弃字段与全新模块", () => {
    render(
      <SchemaDiffDrawer
        isOpen={true}
        onClose={vi.fn()}
        diff={mockDiff}
        platformLabel="智联招聘"
      />
    )

    expect(screen.getByText(/智联招聘 · 模版动态自适应体检/)).toBeDefined()
    expect(screen.getByText(/新增 1 个字段，下线 1 个废弃字段/)).toBeDefined()
    expect(screen.getByText("trainAddress")).toBeDefined()
    expect(screen.getByText("oldCertificate")).toBeDefined()
    expect(screen.getByText("patentModule")).toBeDefined()
    expect(screen.getByText("确认一键同步模版")).toBeDefined()
  })

  it("点击关闭/暂不处理按钮调用 onClose", () => {
    const onClose = vi.fn()
    render(
      <SchemaDiffDrawer
        isOpen={true}
        onClose={onClose}
        diff={mockDiff}
      />
    )

    const cancelBtn = screen.getByText("暂不处理 (忽略)")
    fireEvent.click(cancelBtn)
    expect(onClose).toHaveBeenCalled()
  })
})
