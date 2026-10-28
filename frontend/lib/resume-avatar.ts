import { API_BASE } from "@/lib/api"

/**
 * 「飞书-我的简历库-当前状态=启用」底稿的照片地址。
 *
 * 单一事实源：workspace 装载链路（基线建立前回填进画布）与 PersonalInfo 挂载展示
 * 必须共用本函数——两处字符串严格同形，组件侧的同步写才能退化为等值 no-op。
 * 此前 PersonalInfo 内联实现同名逻辑、workspace 只认 /api/get_active_resume 的
 * JSON 内嵌照片，两侧来源分叉时组件回写落在基线之后 → 零编辑误报「未保存提醒」
 * （2026-10-22 根因，agy double-check PASS）。
 */
export async function fetchActiveResumeAvatar(): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/api/strategy/config`)
    const data = await res.json()
    if (data.status === "success" && Array.isArray(data.resumes)) {
      const activeResume = data.resumes.find(
        (r: { status?: string; avatar_url?: string }) => r.status === "启用" || r.status === "Active",
      )
      if (activeResume?.avatar_url) return activeResume.avatar_url
    }
  } catch (e) {
    console.error("获取启用底稿照片失败:", e)
  }
  return null
}
