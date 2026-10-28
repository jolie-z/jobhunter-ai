import { render, screen, act, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { UpdateBadge } from './update-badge'
import { isNewerVersion } from '@/lib/app-update'

// 顶栏「新版本」下载角标：策略通道下发更新信息（桌面壳 IPC），
// 仅当 latest > 当前版本时亮起；无桌面壳/无更新不渲染。

function mockShell(currentVersion: string, updateInfo: unknown) {
  ;(window as any).appConfig = {
    appVersion: currentVersion,
    getUpdateInfo: () => Promise.resolve(updateInfo),
  }
}

describe('UpdateBadge 更新角标', () => {
  const originalConfig = (window as any).appConfig

  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(() => {
    if (originalConfig === undefined) delete (window as any).appConfig
    else (window as any).appConfig = originalConfig
  })

  it('有更新：亮起角标并展示最新版本号与下载链接', async () => {
    mockShell('0.1.9', {
      latestVersion: '0.1.10',
      downloadUrl: 'http://example.com/JobHunter-Setup-0.1.10.exe',
      notice: '',
    })
    render(<UpdateBadge />)
    await waitFor(() => {
      expect(screen.getByText(/新版本 v0\.1\.10/)).toBeTruthy()
    })
    const link = screen.getByRole('link') as HTMLAnchorElement
    expect(link.href).toContain('JobHunter-Setup-0.1.10.exe')
  })

  it('已是最新版本：不渲染角标', async () => {
    mockShell('0.1.10', {
      latestVersion: '0.1.10',
      downloadUrl: 'http://example.com/x.exe',
      notice: '',
    })
    render(<UpdateBadge />)
    await act(async () => { await Promise.resolve() })
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('无桌面壳（浏览器 dev）：不渲染角标', async () => {
    delete (window as any).appConfig
    render(<UpdateBadge />)
    await act(async () => { await Promise.resolve() })
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('策略带 release_notes：hover 卡片渲染版本号/日期/分区条目', async () => {
    mockShell('0.2.0', {
      latestVersion: '0.2.1',
      downloadUrl: 'http://example.com/JobHunter-Setup-0.2.1.exe',
      notice: '',
      releaseNotes: {
        version: '0.2.1',
        date: '2026-10-12',
        sections: [
          { title: '新功能', items: ['岗位画像升级详细核对版', '画像来源可点击'] },
          { title: '调整', items: ['取消每日自动重建'] },
        ],
      },
    })
    render(<UpdateBadge />)
    await waitFor(() => {
      expect(screen.getByText(/新版本 v0\.2\.1/)).toBeTruthy()
    })
    // Radix HoverCard 内容默认打开才挂载：模拟 hover 触发
    fireEvent.pointerEnter(screen.getByText(/新版本 v0\.2\.1/).closest('a')!)
    await waitFor(() => {
      expect(screen.getByText('v0.2.1 更新日志')).toBeTruthy()
    })
    expect(screen.getByText('2026-10-12')).toBeTruthy()
    expect(screen.getByText('新功能')).toBeTruthy()
    expect(screen.getByText('岗位画像升级详细核对版')).toBeTruthy()
    expect(screen.getByText('取消每日自动重建')).toBeTruthy()
    // 角标本体仍是下载链接
    const link = screen.getAllByRole('link').find((el) => (el as HTMLAnchorElement).href.includes('0.2.1.exe'))
    expect(link).toBeTruthy()
  })

  it('策略无 release_notes：不渲染日志卡片结构，退化为纯链接', async () => {
    mockShell('0.2.0', {
      latestVersion: '0.2.1',
      downloadUrl: 'http://example.com/x.exe',
      notice: '',
    })
    render(<UpdateBadge />)
    await waitFor(() => {
      expect(screen.getByText(/新版本 v0\.2\.1/)).toBeTruthy()
    })
    expect(screen.queryByText(/更新日志/)).toBeNull()
  })

  it('isNewerVersion：逐段数字比较（0.2.0 > 0.1.99）', () => {
    expect(isNewerVersion('0.1.10', '0.1.9')).toBe(true)
    expect(isNewerVersion('0.2.0', '0.1.99')).toBe(true)
    expect(isNewerVersion('0.1.9', '0.1.10')).toBe(false)
    expect(isNewerVersion('0.1.9', '0.1.9')).toBe(false)
    expect(isNewerVersion('v0.2.0', '0.1.9')).toBe(true)
    expect(isNewerVersion('abc', '0.1.9')).toBe(false)
    expect(isNewerVersion('0.2.0', '')).toBe(false)
    // 缺段补零：1.0 ≡ 1.0.0（审查 R1 倒挂缺陷锚点）
    expect(isNewerVersion('1.0.1', '1.0')).toBe(true)
    expect(isNewerVersion('1.0', '1.0.0')).toBe(false)
  })
})
