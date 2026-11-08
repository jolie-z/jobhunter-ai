import React from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react"

import { DiagnosticsExportCard } from "@/components/dashboard/strategy-lab/diagnostics-export"

/**
 * 底层配置页「内测诊断通道」卡片：
 * 无 preload 桥（纯 web 开发态）降级为「浏览器模式」禁用卡（按钮置灰 + 引导文案，
 * 不再整卡隐藏）；有桥时导出/打开文件夹两按钮的状态反馈
 * （loading → 成功/失败内联 hint）与统一错误弹窗（global-error-dialog）同范式。
 */

const setBridge = (config: Record<string, unknown> | undefined) => {
  if (config === undefined) delete (window as { appConfig?: unknown }).appConfig
  else (window as { appConfig?: unknown }).appConfig = config
}

afterEach(() => {
  cleanup()
  setBridge(undefined)
  vi.restoreAllMocks()
})

describe("DiagnosticsExportCard 诊断通道卡片", () => {
  it("无 preload 桥时降级为「浏览器模式」禁用卡（组件契约：保留引导不再整卡隐藏）", () => {
    const { container, getByText } = render(<DiagnosticsExportCard />)
    expect(getByText("浏览器模式")).toBeTruthy()
    expect(container.textContent).toContain("当前是浏览器模式：导出诊断日志 / 打开日志文件夹需要在 JobHunter 桌面客户端中使用")
    // 两按钮均置灰：web 态不可误触导出
    expect(container.querySelectorAll("button[disabled]").length).toBe(2)
  })

  it("导出成功：按钮进入 loading，hint 展示桌面包文件名", async () => {
    setBridge({ exportDiagnostics: vi.fn().mockResolvedValue("C:\\Users\\t\\Desktop\\JobHunter诊断_20261029.zip") })
    const { container, getByText } = render(<DiagnosticsExportCard />)
    fireEvent.click(getByText("导出诊断日志"))
    expect(getByText("正在导出…")).toBeTruthy()
    await waitFor(() => expect(container.textContent).toContain("诊断包已保存到桌面：JobHunter诊断_20261029.zip"))
  })

  it("导出失败（IPC 返回 null / 桥抛异常）：hint 展示托盘兜底引导", async () => {
    setBridge({ exportDiagnostics: vi.fn().mockResolvedValue(null) })
    const first = render(<DiagnosticsExportCard />)
    fireEvent.click(first.getByText("导出诊断日志"))
    await waitFor(() => expect(first.container.textContent).toContain("请通过托盘菜单「导出诊断日志」重试"))
    first.unmount()

    setBridge({ exportDiagnostics: vi.fn().mockRejectedValue(new Error("ipc broken")) })
    const second = render(<DiagnosticsExportCard />)
    fireEvent.click(second.getByText("导出诊断日志"))
    await waitFor(() => expect(second.container.textContent).toContain("请通过托盘菜单「导出诊断日志」重试"))
  })

  it("打开日志文件夹：调 openLogFolder 桥，成功/失败均有对应 hint", async () => {
    // 卡片可见性锚在 exportDiagnostics 桥上（两桥在桌面壳始终成对注入），此处需一并给
    setBridge({ exportDiagnostics: vi.fn(), openLogFolder: vi.fn().mockResolvedValue(true) })
    const ok = render(<DiagnosticsExportCard />)
    fireEvent.click(ok.getByText("打开日志文件夹"))
    await waitFor(() => expect(ok.container.textContent).toContain("已在文件管理器中定位日志文件"))
    ok.unmount()

    setBridge({ exportDiagnostics: vi.fn(), openLogFolder: vi.fn().mockResolvedValue(false) })
    const fail = render(<DiagnosticsExportCard />)
    fireEvent.click(fail.getByText("打开日志文件夹"))
    await waitFor(() => expect(fail.container.textContent).toContain("可手动前往 %APPDATA%"))
  })
})
