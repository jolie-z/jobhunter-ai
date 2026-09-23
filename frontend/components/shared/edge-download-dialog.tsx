"use client"

import { Download, Globe } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { EDGE_MISSING_MESSAGE, FALLBACK_EDGE_DOWNLOAD_URL } from "@/lib/platform-auth"

interface EdgeDownloadDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  downloadUrl: string
}

// 纵深防御：下载链接虽来自自家后端，仍只放行官方域名的 https 页面。
// 允许域从兜底常量派生（单一真源）：后端改下载域时此处白名单随之更新，
// 若新域与本域不符会安全回落到 FALLBACK（而非静默放行陌生域）
function safeDownloadUrl(url: string): string {
  const fallbackHost = new URL(FALLBACK_EDGE_DOWNLOAD_URL).hostname
  try {
    const u = new URL(url)
    const host = u.hostname
    if (u.protocol === "https:" && (host === fallbackHost || host.endsWith(`.${fallbackHost}`))) {
      return url
    }
  } catch {
    // 非法 URL 落到兜底
  }
  return FALLBACK_EDGE_DOWNLOAD_URL
}

/**
 * 本机未安装 Microsoft Edge 时的下载引导弹窗。
 * 全站唤起浏览器入口共用（授权监控 / 指挥中心会话栏 / 简历同步中心），
 * 下载链接以后端探测接口返回为准。
 */
export function EdgeDownloadDialog({ open, onOpenChange, downloadUrl }: EdgeDownloadDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Globe className="h-4 w-4 text-sky-500" />
            {EDGE_MISSING_MESSAGE}
          </DialogTitle>
          <DialogDescription className="text-xs leading-relaxed">
            各求职平台（BOSS 直聘 / 智联 / 猎聘 / 前程无忧）的扫码登录与自动投递，
            都通过系统拉起的专用 Edge 浏览器执行。请先下载安装 Microsoft Edge，
            安装完成后回到本页重新唤起即可。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            稍后再说
          </Button>
          <Button
            size="sm"
            onClick={() => window.open(safeDownloadUrl(downloadUrl), "_blank", "noopener,noreferrer")}
          >
            <Download className="h-3.5 w-3.5" />
            前往下载 Edge
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
