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
  partial?: boolean
  artifact_count?: number
  expected_artifact_count?: number
  engine?: "official" | "agent"
  result_kind?: "resume" | "markdown" | "json"
  has_resume_output?: boolean
  archive_error?: string
}

export interface SkillOutputSpec {
  filename: string
  title?: string
  required?: boolean
  is_final?: boolean
  kind?: string
  is_resume?: boolean
}

export interface SkillContractSummary {
  engine: "official" | "agent"
  output_kind: "resume" | "markdown" | "json"
  expected_output_count: number
  has_resume_output: boolean
  final_artifact?: string | null
  postprocess?: string
  final_source?: string
}

export interface SkillTokenEstimate {
  point: number
  low: number
  high: number
  source: "history" | "heuristic"
  sample_count?: number
}

export interface SkillScanReport {
  skill_id: string
  name?: string
  is_package?: boolean
  references_count?: number
  contract: {
    engine: "official" | "agent"
    output_kind: "resume" | "markdown" | "json"
    final_artifact?: string | null
    final_source?: string
    postprocess?: string
    writeback?: string
    outputs: SkillOutputSpec[]
    expected_artifact_count: number
    has_resume_output: boolean
    output_count_source?: string
    warnings?: string[]
  }
  summary?: SkillContractSummary
  estimated_tokens: SkillTokenEstimate
  estimate_scope: "skill_only" | "history_full_run" | "skill_and_inputs"
  warnings?: string[]
}

export interface SkillPreflightReport {
  skill_id: string
  name?: string
  engine: "official" | "agent"
  result_kind: "resume" | "markdown" | "json"
  has_resume_output: boolean
  expected_artifact_count: number
  final_artifact?: string | null
  final_source?: string
  outputs: SkillOutputSpec[]
  output_count_source?: string
  warnings: string[]
  will_load: {
    skill_md: boolean
    skill_chars: number
    references_count: number
    jd_chars: number
    resume_chars: number
    diagnosis_injected: boolean
    resume_library_mode: boolean
  }
  estimated_tokens: SkillTokenEstimate
  estimate_scope: "skill_and_inputs"
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

/**
 * 读取全局 A级岗位画像供前端 LLM 消费方注入（简历库 Skill 改写、经历拷问），无内容时返回空串。
 *
 * 双轨契约（2026-10-12）：下游 LLM 消费方注入「附：下游速览」速览版（meta.llm_brief，
 * ~2k tokens），人读弹窗才取 data 完整版（~1 万字符）。旧报告/迁移值无速览区块
 * （llm_brief 缺失或空串）时回退完整版，与后端 get_global_jd_report() 回退口径一致。
 * 前端新的 LLM 消费方一律走这里取画像，不要再直取 /get_jd_report 的 data。
 */
export async function fetchGlobalJdReport(): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/api/strategy/get_jd_report`)
    const json = await res.json().catch(() => null)
    if (res.ok && json?.status === "success") {
      const brief = String(json.meta?.llm_brief ?? "").trim()
      return brief || String(json.data ?? "")
    }
    return ""
  } catch {
    return ""
  }
}

/** 上传/选择前扫描技能包：产物清单、是否含简历、token 预估（仅技能包）。 */
export async function scanSkill(skillId: string): Promise<SkillScanReport | null> {
  if (!skillId) return null
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 15000)
  try {
    const res = await fetch(
      `${API_BASE}/api/resume-editor/skills/${encodeURIComponent(skillId)}/scan`,
      { signal: controller.signal },
    )
    const json = await res.json().catch(() => null)
    if (!res.ok || !json?.success || !json?.data) return null
    return json.data as SkillScanReport
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

/** 执行前预检：读取 JD/简历上下文（不调用 LLM），返回产物契约与 token 预估。 */
export async function preflightSkillRewrite(params: SkillRewriteParams): Promise<SkillPreflightReport> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 30000)
  try {
    const res = await fetch(`${API_BASE}/api/strategy/skill_rewrite_preflight`, {
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
    if (!res.ok || !json || json.status !== "success" || !json.data) {
      throw new Error(json?.detail || `执行前预检失败（HTTP ${res.status}）`)
    }
    return json.data as SkillPreflightReport
  } catch (err: any) {
    if (controller.signal.aborted) {
      throw new Error("执行前预检超时（30 秒），请检查后端服务后重试")
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

// ===== 看板分流判据 =====
// 官方剧本与单文件自定义技能都走单轮标准引擎（事件稀疏），不弹「作战推演看板」；
// 仅多文件技能包（is_package 且 references_count>0，与后端 engine_facade 路由到
// 多轮 Agent 的判据同源）才弹看板——保证「弹看板必有真推演，有推演必弹看板」。

/** 官方剧本 ID 集合（选择器未选/默认值均视为官方剧本，无需查列表）——全库唯一判据，禁止内联比对 */
const OFFICIAL_SKILL_IDS = new Set(["", "resume_rewrite", "default"])

export function isOfficialSkillId(skillId?: string | null): boolean {
  return !skillId || OFFICIAL_SKILL_IDS.has(skillId)
}

interface SkillMetaBrief {
  id: string
  name: string
  is_package: boolean
  references_count: number
  contract_summary?: SkillContractSummary | null
}

let _skillsMetaCache: { at: number; skills: SkillMetaBrief[] } | null = null
const _SKILLS_META_TTL_MS = 5 * 60 * 1000

/** 上传/删除技能后清缓存，保证下一次 isPackageSkill/skillDisplayName 读到新契约。 */
export function invalidateSkillsMetaCache(): void {
  _skillsMetaCache = null
}

async function fetchSkillsMeta(): Promise<SkillMetaBrief[] | null> {
  if (_skillsMetaCache && Date.now() - _skillsMetaCache.at < _SKILLS_META_TTL_MS) {
    return _skillsMetaCache.skills
  }
  try {
    const res = await fetch(`${API_BASE}/api/resume-editor/skills/`)
    const json = await res.json().catch(() => null)
    if (!res.ok || !json?.success || !Array.isArray(json.skills)) return null
    const skills: SkillMetaBrief[] = json.skills.map((s: any) => ({
      id: String(s.id ?? ""),
      name: String(s.name ?? ""),
      is_package: Boolean(s.is_package),
      references_count: Number(s.references_count ?? 0),
      contract_summary: s.contract_summary ?? null,
    }))
    _skillsMetaCache = { at: Date.now(), skills }
    return skills
  } catch {
    return null
  }
}

/**
 * 该技能是否为多文件技能包（走多轮 Agent 推演，值得弹实时看板）。
 * 列表拉取失败时回退 true（保持既有弹看板行为，宁多勿缺）。
 */
export async function isPackageSkill(skillId?: string | null): Promise<boolean> {
  if (isOfficialSkillId(skillId)) return false
  const skills = await fetchSkillsMeta()
  if (!skills) return true
  const meta = skills.find((s) => s.id === skillId)
  if (!meta) return true
  // 契约优先：单文件通用 skill 也可能被后端路由到渐进式 agent
  if (meta.contract_summary?.engine) return meta.contract_summary.engine === "agent"
  return meta.is_package && meta.references_count > 0
}

/** 技能的界面显示名：官方剧本统一中文名，自定义优先元数据 name，兜底原始 id */
export async function skillDisplayName(skillId?: string | null): Promise<string> {
  if (isOfficialSkillId(skillId)) return "官方标准剧本"
  const skills = await fetchSkillsMeta()
  const meta = skills?.find((s) => s.id === skillId)
  return meta?.name || String(skillId)
}
