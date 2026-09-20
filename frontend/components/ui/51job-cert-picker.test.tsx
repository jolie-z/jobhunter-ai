import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { Job51CertPicker } from "./51job-cert-picker"
import fs from "fs"
import path from "path"

const certDictPath = path.resolve(__dirname, "../../public/51job_certificates.json")
const mockCertData = JSON.parse(fs.readFileSync(certDictPath, "utf-8"))

describe("Job51CertPicker Component", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url.includes("51job_certificates.json")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(mockCertData),
          })
        }
        return Promise.reject(new Error("Not found"))
      })
    )
  })

  it("renders picker modal with categories when open is true", async () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()

    render(
      <Job51CertPicker
        open={true}
        onClose={onClose}
        selected={["0815"]}
        onConfirm={onConfirm}
        maxSelect={20}
      />
    )

    await waitFor(() => {
      expect(screen.getByText("选择证书")).toBeDefined()
    })

    // Check categories
    expect(screen.getByText("语言证书")).toBeDefined()
    expect(screen.getByText("职称证书")).toBeDefined()
    expect(screen.getByText("微软证书")).toBeDefined()
    expect(screen.getByText("交通/运输/物流证书")).toBeDefined()
  })

  it("supports searching certificates and selecting up to 20", async () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()

    render(
      <Job51CertPicker
        open={true}
        onClose={onClose}
        selected={[]}
        onConfirm={onConfirm}
        maxSelect={20}
      />
    )

    await waitFor(() => {
      expect(screen.getByPlaceholderText("请输入")).toBeDefined()
    })

    const searchInput = screen.getByPlaceholderText("请输入")
    fireEvent.change(searchInput, { target: { value: "驾照" } })

    await waitFor(() => {
      expect(screen.getByText("C1驾照")).toBeDefined()
    })

    // Click to select
    const c1Btn = screen.getByText("C1驾照")
    fireEvent.click(c1Btn)

    // Click confirm
    const confirmBtn = screen.getByText("确定")
    fireEvent.click(confirmBtn)

    expect(onConfirm).toHaveBeenCalledWith(["0815"])
  })

  it("correctly handles 20 certificates limit", async () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()

    const twentyCodes = [
      '0815', '0108', '0117', '0507', '0513', '1006', '1005', '1009', '1004', '0903',
      '0907', '0906', '0902', '0914', '0305', '0378', '0308', '0331', '0321', '0368'
    ]

    render(
      <Job51CertPicker
        open={true}
        onClose={onClose}
        selected={twentyCodes}
        onConfirm={onConfirm}
        maxSelect={20}
      />
    )

    await waitFor(() => {
      expect(screen.getByText("已选 (20 / 20)")).toBeDefined()
    })

    // Both ACCA and 英国皇家 should be in the selected list
    expect(screen.getByText("ACCA特许公认会计师")).toBeDefined()
    expect(screen.getByText("英国皇家特许会计师")).toBeDefined()
  })
})
