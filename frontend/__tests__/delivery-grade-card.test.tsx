// @vitest-environment jsdom
import React from "react"
import { describe, it, expect, vi } from "vitest"
import { render } from "@testing-library/react"
import { DeliveryGradeCard } from "@/components/command-center/drawers/delivery/delivery-grade-card"

/**
 * 存量等级清洗回归（防下线等级幽灵勾选与空集合停摆）：
 * - 部分非法（如含已下线 E）：挂载即回写清洗后的合法子集；
 * - 全非法（如只剩 E）：绝不回写空集合（全空=所有岗位挂人工审批，等于仅打开面板
 *   就静默停摆海投），必须回退到与后端 automation_configs 默认一致的 ["C","D","F"]；
 * - 全合法：不得触发回写。
 */
describe("DeliveryGradeCard 存量等级清洗", () => {
  it("部分非法等级：挂载时回写清洗后的合法子集", () => {
    const onChange = vi.fn()
    render(<DeliveryGradeCard grades={["A", "E"]} onChangeGrades={onChange} />)
    expect(onChange).toHaveBeenCalledWith(["A"])
  })

  it("全非法等级：回退默认海投轨集合，绝不回写空集合", () => {
    const onChange = vi.fn()
    render(<DeliveryGradeCard grades={["E"]} onChangeGrades={onChange} />)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).not.toHaveBeenCalledWith([])
    expect(onChange).toHaveBeenCalledWith(["C", "D", "F"])
  })

  it("全合法等级：不触发回写", () => {
    const onChange = vi.fn()
    render(<DeliveryGradeCard grades={["A", "C", "D", "F"]} onChangeGrades={onChange} />)
    expect(onChange).not.toHaveBeenCalled()
  })
})
