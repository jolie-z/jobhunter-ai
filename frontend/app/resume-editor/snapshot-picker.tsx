/**
 * 平台回写快照选择器（Q-M5-3 接页面：GET /api/platforms/{p}/snapshots 快照清单 UI）。
 * 供各平台回写面板工具条嵌入：选择历史快照 → 回调 onRollback(snapshotId)。
 * 各平台快照条目字段名不一（id/snapshot_id、size/size_bytes），此处做归一。
 */
"use client"

import { API_BASE } from "@/lib/api"
import { useState, useEffect } from "react"
import { History, Loader2 } from "lucide-react"

interface SnapshotItem {
  id?: string
  snapshot_id?: string
  filename?: string
  created_at?: string
  size?: number
  size_bytes?: number
}

export function SnapshotPicker({ platform, onRollback, rollingBack = false }: {
  platform: string
  onRollback: (snapshotId: string) => void
  rollingBack?: boolean
}) {
  const [snapshots, setSnapshots] = useState<SnapshotItem[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState("")

  useEffect(() => {
    setSelected("")
    let cancelled = false
    setLoading(true)
    fetch(`${API_BASE}/api/platforms/${platform}/snapshots`)
      .then((r) => r.json())
      .then((json) => { if (!cancelled) setSnapshots(Array.isArray(json.snapshots) ? json.snapshots : []) })
      .catch(() => { if (!cancelled) setSnapshots([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [platform])

  const items = snapshots
    .map((s) => ({
      id: String(s.snapshot_id ?? s.id ?? s.filename ?? ""),
      createdAt: s.created_at || s.filename || "",
      size: s.size_bytes ?? s.size ?? 0,
    }))
    .filter((s) => s.id)

  return (
    <div className="flex items-center gap-1.5 shrink-0">
      {loading ? <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin" /> : <History className="w-3.5 h-3.5 text-gray-400" />}
      <select
        className="h-7 max-w-[190px] text-xs border border-gray-200 rounded-md bg-white px-1.5 text-gray-600 focus:outline-none cursor-pointer disabled:cursor-not-allowed"
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        disabled={loading || items.length === 0}
        title={loading ? "快照清单加载中..." : items.length === 0 ? "暂无历史快照" : "选择要回滚的历史快照"}
      >
        <option value="">{loading ? "快照加载中..." : `历史快照（${items.length}）`}</option>
        {items.map((s) => (
          <option key={s.id} value={s.id}>
            {s.createdAt}{s.size ? ` · ${(s.size / 1024).toFixed(0)}KB` : ""}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => selected && onRollback(selected)}
        disabled={!selected || rollingBack}
        className="h-7 px-2 text-xs rounded-md border border-gray-200 bg-white hover:bg-gray-50 text-gray-600 disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
        title="将平台本地数据恢复至所选历史快照"
      >
        {rollingBack ? "恢复中..." : "回滚"}
      </button>
    </div>
  )
}
