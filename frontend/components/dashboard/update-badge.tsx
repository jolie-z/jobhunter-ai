"use client"

import { useEffect, useState } from "react"
import { Download } from "lucide-react"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { fetchAppUpdateInfo, currentAppVersion, isNewerVersion, type AppUpdateInfo } from "@/lib/app-update"

/**
 * 顶栏「新版本」下载角标（与 ZCode 同款交互）：策略通道下发最新版本信息，
 * 比当前版本新时亮起；hover 弹出更新日志卡片（版本号/日期/修复内容），
 * 点击用系统浏览器打开官方下载地址。
 * 无桌面壳（浏览器 dev）或无更新时不渲染；策略未配 release_notes 时退化为纯链接。
 */
export function UpdateBadge() {
  const [update, setUpdate] = useState<AppUpdateInfo | null>(null)

  useEffect(() => {
    let cancelled = false
    const check = async () => {
      try {
        const info = await fetchAppUpdateInfo()
        const current = currentAppVersion()
        const hasUpdate = !!info && !!info.latestVersion && isNewerVersion(info.latestVersion, current)
        if (!cancelled) setUpdate(hasUpdate ? info : null)
      } catch {
        if (!cancelled) setUpdate(null)
      }
    }
    check()
    const timer = setInterval(check, 10 * 60 * 1000) // 策略缓存 6h 刷新一次，10min 轮询足够及时
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  if (!update) return null

  const notes = update.releaseNotes?.sections?.length ? update.releaseNotes : null

  const badge = (
    <a
      href={update.downloadUrl || "#"}
      target="_blank"
      rel="noopener noreferrer"
      title={notes ? undefined : update.notice || `发现新版本 v${update.latestVersion}，点击下载（当前 v${currentAppVersion()}）`}
      className="relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 transition-all animate-in fade-in slide-in-from-top-1 duration-300"
    >
      <Download className="size-3.5" />
      <span>新版本 v{update.latestVersion}</span>
      <span className="absolute -top-1 -right-1 flex size-2.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex size-2.5 rounded-full bg-emerald-500" />
      </span>
    </a>
  )

  // 无更新日志：保持原纯链接（title 提示）
  if (!notes) return badge

  return (
    <HoverCard openDelay={120} closeDelay={100}>
      <HoverCardTrigger asChild>{badge}</HoverCardTrigger>
      <HoverCardContent className="w-80 max-h-80 overflow-y-auto p-4" align="end">
        <div className="text-sm font-semibold">{`v${notes.version || update.latestVersion} 更新日志`}</div>
        {notes.date && <div className="mt-0.5 text-xs text-muted-foreground">{notes.date}</div>}
        <div className="mt-3 space-y-3">
          {notes.sections!.map((section, sectionIndex) => (
            <div key={sectionIndex}>
              <div className="text-xs font-semibold text-foreground">{section.title}</div>
              <ul className="mt-1 space-y-1">
                {(Array.isArray(section.items) ? section.items : []).map((item, itemIndex) => (
                  <li key={itemIndex} className="list-disc list-inside text-xs leading-relaxed text-muted-foreground">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-3 border-t border-border pt-2 text-[11px] text-muted-foreground">
          点击角标下载安装包，覆盖安装即可完成升级
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}
