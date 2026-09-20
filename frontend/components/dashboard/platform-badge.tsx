/**
 * 平台品牌徽标（移植自 v0 设计）。
 *
 * 实体品牌色方块 + 白色字符（B/猎/51/智/小/他），下方配合平台名文字。
 * 接受 v0 枚举 Platform；中文平台名的归一由 lib/job-data.ts 完成。
 */

import { cn } from "@/lib/utils"
import { type Platform, PLATFORM_CONFIG } from "@/lib/job-data"

interface PlatformBadgeProps {
  platform: Platform
  size?: "sm" | "md"
}

// 官方品牌色实体背景 + 白色内容
const PLATFORM_BRAND: Record<Platform, { bg: string; display: React.ReactNode }> = {
  boss: {
    bg: "bg-emerald-500",
    display: <span className="font-black text-white leading-none select-none">B</span>,
  },
  liepin: {
    bg: "bg-orange-500",
    display: <span className="font-black text-white leading-none select-none">猎</span>,
  },
  job51: {
    bg: "bg-yellow-400",
    display: <span className="font-black text-white leading-none select-none">51</span>,
  },
  zhilian: {
    bg: "bg-blue-600",
    display: <span className="font-black text-white leading-none select-none">智</span>,
  },
  xiaohongshu: {
    bg: "bg-red-500",
    display: <span className="font-black text-white leading-none select-none text-[9px]">RED</span>,
  },
  other: {
    bg: "bg-slate-400",
    display: <span className="font-black text-white leading-none select-none">他</span>,
  },
}

export function PlatformBadge({ platform, size = "md" }: PlatformBadgeProps) {
  const brand = PLATFORM_BRAND[platform]
  const name = PLATFORM_CONFIG[platform].name

  return (
    <div
      className={cn(
        "rounded-xl flex items-center justify-center shrink-0 shadow-sm",
        brand.bg,
        size === "md" ? "size-11 text-sm" : "size-9 text-xs"
      )}
      title={name}
      aria-label={`来源平台：${name}`}
    >
      {brand.display}
    </div>
  )
}
