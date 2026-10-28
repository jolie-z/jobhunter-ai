"use client"

/**
 * 应用更新信息（策略通道下发，桌面壳 IPC 提供数据）。
 *
 * 数据链路：运营服务器 /api/policy（Ed25519 签名）→ 桌面壳验签缓存 →
 * window.appConfig.getUpdateInfo() → 本模块 → 顶栏更新角标。
 * 浏览器直接访问 dev 前端时无桌面壳（window.appConfig 缺失），恒返回 null。
 */

/** 更新日志（策略通道 release_notes 透传；缺失/结构不符为 null，角标退化为纯链接） */
export interface ReleaseNotes {
  version?: string
  date?: string
  sections?: { title: string; items: string[] }[]
}

export interface AppUpdateInfo {
  /** 最新版本号（x.y.z） */
  latestVersion: string
  /** 安装包下载地址（系统浏览器打开） */
  downloadUrl: string
  /** 可选公告文案 */
  notice: string
  /** 可选更新日志（角标 hover 卡片渲染） */
  releaseNotes?: ReleaseNotes | null
}

export function fetchAppUpdateInfo(): Promise<AppUpdateInfo | null> {
  try {
    const getter = (window as any).appConfig?.getUpdateInfo
    if (typeof getter !== "function") return Promise.resolve(null)
    return Promise.resolve(getter())
  } catch {
    return Promise.resolve(null)
  }
}

/** 当前应用版本（桌面壳注入；浏览器环境返回空串，角标逻辑视为无更新） */
export function currentAppVersion(): string {
  return String((window as any).appConfig?.appVersion || "")
}

/** latest 是否比 current 更新（x.y.z 数字逐段比较；缺段补 0，"1.0"≡"1.0.0"；解析失败视为不更新） */
export function isNewerVersion(latest: string, current: string): boolean {
  const parse = (v: string) => {
    const parts = String(v || "")
      .trim()
      .replace(/^v/i, "")
      .split(/[.-]/)
      .slice(0, 3)
    while (parts.length < 3) parts.push("0")
    return parts.map((n) => (/^\d+$/.test(n) ? Number(n) : null))
  }
  if (!current) return false
  const pl = parse(latest)
  const pc = parse(current)
  for (let i = 0; i < 3; i++) {
    const a = pl[i]
    const b = pc[i]
    if (a === null || b === null) return false
    if (a !== b) return a > b
  }
  return false
}
