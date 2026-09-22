"use client"

import { useCallback, useState } from "react"
import { EdgeDownloadDialog } from "@/components/shared/edge-download-dialog"
import {
  FALLBACK_EDGE_DOWNLOAD_URL,
  EDGE_MISSING_MESSAGE,
  EDGE_NOT_INSTALLED,
  fetchEdgeStatus,
  type EdgeLaunchResult,
} from "@/lib/platform-auth"

/**
 * 唤起浏览器前的 Edge 安装守卫（全站唤起入口共用）：
 * 先探测本机是否安装 Edge，未安装直接弹「下载 Edge」引导，不再白点一次唤起；
 * 探测被绕过（后端不可达时放行）则由唤起接口的 edge_not_installed 结构化错误兜底弹窗。
 *
 * 用法：const { guardLaunch, edgeDialog } = useEdgeLaunchGuard()
 *       const result = await guardLaunch(() => launchPlatformEdge(platform))
 *       组件树末尾渲染 {edgeDialog}
 */
export function useEdgeLaunchGuard() {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [downloadUrl, setDownloadUrl] = useState(FALLBACK_EDGE_DOWNLOAD_URL)

  const openMissing = useCallback((url?: string) => {
    if (url) setDownloadUrl(url)
    setDialogOpen(true)
  }, [])

  const guardLaunch = useCallback(
    async (launch: () => Promise<EdgeLaunchResult>): Promise<EdgeLaunchResult> => {
      const status = await fetchEdgeStatus()
      if (!status.installed) {
        openMissing(status.downloadUrl)
        return {
          ok: false,
          message: EDGE_MISSING_MESSAGE,
          code: EDGE_NOT_INSTALLED,
          downloadUrl: status.downloadUrl,
        }
      }
      const result = await launch()
      if (!result.ok && result.code === EDGE_NOT_INSTALLED) {
        openMissing(result.downloadUrl)
      }
      return result
    },
    [openMissing]
  )

  const edgeDialog = (
    <EdgeDownloadDialog open={dialogOpen} onOpenChange={setDialogOpen} downloadUrl={downloadUrl} />
  )

  return { guardLaunch, edgeDialog }
}
