import { API_BASE } from "@/lib/api"
/**
 * Skill 简历改写 —— 共享调用层
 * ============================
 * 定制面板（岗位模式）与 配置大盘-简历库（简历库模式）共用此模块，
 * 都打到同一个后端端点 /api/strategy/skill_rewrite_and_save，
 * 后续改动 skill 改写逻辑只需改这一处 + 后端端点。
 */

export interface SkillRewriteParams {
  /** JD 文本：岗位模式=岗位 JD；简历库模式=A级岗位画像 */
  jd_text: string
  /** 岗位/场景名称（用于日志与记忆检索） */
  job_name: string
  /** 岗位记录 ID（岗位模式必传；简历库模式可选，传了会附带该岗位的诊断报告） */
  job_id?: string
  /** 简历库记录 ID：传入即走简历库模式（底稿与落盘都是该记录的结构化数据） */
  resume_record_id?: string
  /** 动态技能 ID（可选，指定自定义 .md 技能剧本） */
  skill_id?: string
  /** 是否将 AI 岗位诊断报告（毒点与高杠杆点）作为上下文注入改写 Prompt */
  include_diagnosis?: boolean
}

export interface SkillRewriteResult {
  parsed_json: Record<string, any>
  markdown: string
  usage: Record<string, any>
}

/**
 * 执行 Skill 改写。同步等待后端 SOP 跑完（通常需要 1-3 分钟），失败时抛 Error。
 * 内置 10 分钟超时兜底：后端假死/网络中断时不再永久挂起。
 */
export async function runSkillRewrite(params: SkillRewriteParams): Promise<SkillRewriteResult> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10 * 60 * 1000)
  try {
    const res = await fetch(`${API_BASE}/api/strategy/skill_rewrite_and_save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: params.job_id ?? "",
        jd_text: params.jd_text,
        job_name: params.job_name,
        resume_record_id: params.resume_record_id,
        skill_id: params.skill_id,
        include_diagnosis: params.include_diagnosis ?? true,
      }),
      signal: controller.signal,
    })
    const json = await res.json().catch(() => null)
    if (!res.ok || !json || json.status !== "success") {
      throw new Error(json?.detail || `Skill 改写失败（HTTP ${res.status}）`)
    }
    return json.data as SkillRewriteResult
  } catch (err) {
    if (controller.signal.aborted) {
      throw new Error("Skill 改写等待超时（10 分钟），请检查后端服务后重试")
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

/**
 * 异步启动 Skill 改写智能体，秒级返回 task_id，供前端建立 SSE 实时推演流。
 */
export async function startAsyncSkillRewrite(params: SkillRewriteParams): Promise<string> {
  const res = await fetch(`${API_BASE}/api/strategy/skill_rewrite_async`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_id: params.job_id ?? "",
      jd_text: params.jd_text,
      job_name: params.job_name,
      resume_record_id: params.resume_record_id,
      skill_id: params.skill_id,
      include_diagnosis: params.include_diagnosis ?? true,
    }),
  })
  const json = await res.json().catch(() => null)
  if (!res.ok || !json || json.status !== "success" || !json.task_id) {
    throw new Error(json?.detail || `启动异步推演任务失败（HTTP ${res.status}）`)
  }
  return json.task_id as string
}

/** 读取全局 A级岗位画像（简历库模式的 JD 输入），无内容时返回空串 */
export async function fetchGlobalJdReport(): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/api/strategy/get_jd_report`)
    const json = await res.json().catch(() => null)
    if (res.ok && json?.status === "success") return String(json.data ?? "")
    return ""
  } catch {
    return ""
  }
}
