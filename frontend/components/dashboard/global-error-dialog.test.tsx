import { render, screen, act, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { GlobalErrorDialog } from './global-error-dialog'
import { showGlobalError, subscribeGlobalError } from './global-error-bus'

// 统一意外错误弹窗：详情透传（取证关键）+ 桌面壳导出诊断日志桥 + web 无桥降级。

const originalConfig = (window as { appConfig?: unknown }).appConfig

function mockBridge(exportImpl?: () => Promise<string | null>) {
  ;(window as { appConfig?: unknown }).appConfig = {
    backendBase: 'http://127.0.0.1:8000',
    ...(exportImpl ? { exportDiagnostics: exportImpl } : {}),
  }
}

async function openDialog(title: string, detail: string) {
  render(<GlobalErrorDialog />)
  await act(async () => { showGlobalError({ title, detail }) })
}

beforeEach(() => { vi.clearAllMocks() })
afterEach(() => {
  ;(window as { appConfig?: unknown }).appConfig = originalConfig
})

describe('GlobalErrorDialog 全局意外错误弹窗', () => {
  it('showGlobalError 唤起弹窗：标题与后端 detail（含响应快照）原样透传', async () => {
    mockBridge(() => Promise.resolve('JobHunter诊断_x.zip'))
    const snapshot = "保存简历响应非JSON（HTTP 200）: 'null{\"x\":1}'"
    await openDialog('❌ 保存失败', snapshot)
    expect(screen.getByText('❌ 保存失败')).toBeTruthy()
    expect(screen.getByText(new RegExp(snapshot.replace(/[{}'"]/g, (c) => `\\${c}`)))).toBeTruthy()
  })

  it('桌面壳有桥：导出按钮可见，点击调用桥并反馈文件名', async () => {
    const exportMock = vi.fn(() => Promise.resolve('/Users/x/Desktop/JobHunter诊断_2026.zip'))
    mockBridge(exportMock)
    await openDialog('❌ 保存失败', 'boom')
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /导出诊断日志/ })) })
    await waitFor(() => {
      expect(screen.getByText(/JobHunter诊断_2026\.zip/)).toBeTruthy()
    })
    expect(exportMock).toHaveBeenCalledTimes(1)
  })

  it('web 无桥：隐藏导出按钮，降级为复制详情', async () => {
    mockBridge() // 有 appConfig 但无 exportDiagnostics
    await openDialog('❌ 网络错误', 'Failed to fetch')
    expect(screen.queryByRole('button', { name: /导出诊断日志/ })).toBeNull()
    expect(screen.getByRole('button', { name: /复制详情/ })).toBeTruthy()
  })

  it('弹窗未挂载时 showGlobalError 退化为 alert，不丢现场', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    try {
      // 不渲染 GlobalErrorDialog（模拟未挂载页面），订阅位为空
      const unsub = subscribeGlobalError(() => {})
      unsub()
      showGlobalError({ title: '❌ 保存失败', detail: 'HTTP 500' })
      expect(alertSpy).toHaveBeenCalledWith('❌ 保存失败\nHTTP 500')
    } finally {
      alertSpy.mockRestore()
    }
  })
})
