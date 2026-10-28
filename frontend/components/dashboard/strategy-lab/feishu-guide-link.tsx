"use client"

// 飞书接入手册在线入口按钮（system-config / chatops-guide-card 共用）。
// 教程正文维护在服务器端（telemetry/public/guide/feishu.html），App 内只放外链——
// 更新教程无需重新发包（2026-10-09 起，原内置全文弹窗已下线，见 frontend/lib/guide-urls.ts）。
import { BookOpen } from "lucide-react"

import { FEISHU_GUIDE_URL, openGuide } from "@/lib/guide-urls"

export function FeishuFullGuideButton() {
  return (
    <button
      type="button"
      onClick={() => openGuide(FEISHU_GUIDE_URL)}
      className="mt-3 flex w-full items-center justify-between rounded-xl border border-blue-200 bg-blue-50/80 px-4 py-3 text-left transition-colors hover:bg-blue-100/80"
    >
      <span>
        <span className="block text-[13px] font-semibold text-blue-900">打开完整图文教程（从零到 ping 通）</span>
        <span className="mt-0.5 block text-xs text-blue-700/80">在线版持续更新：创建应用、复制表格模板、权限与发布、事件与回调、连通性自检与排错 FAQ 全流程</span>
      </span>
      <BookOpen className="size-4 shrink-0 text-blue-700" />
    </button>
  )
}
