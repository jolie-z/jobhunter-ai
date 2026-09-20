"use client"

/**
 * PROTOTYPE — 全链路指挥中心
 * 仅保留 Variant B（蛇形轨道）
 */

import VariantB from "./variant-b"

export default function Page() {
  return (
    <div className="h-screen w-screen overflow-hidden bg-gray-50">
      <VariantB />
    </div>
  )
}
