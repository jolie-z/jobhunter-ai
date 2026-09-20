import { JobData } from "@/types/job"

// 后端 /api/jobs 列表项（瘦身后的 snake_case 结构；详情接口返回的是它的全字段超集）
export type JobsApiItem = {
  record_id?: string | number
  job_name?: string
  company_name?: string
  city?: string
  salary?: string
  follow_status?: string
  scale?: string
  industry?: string
  education?: string
  experience?: string
  ai_score?: number
  bg_score?: number
  skill_score?: number
  exp_score?: number
  skill_req?: string
  job_detail?: string
  hr_skills?: string[]
  benefits?: string[]
  hr_active?: string
  delivery_date?: string
  fetch_time?: string
  work_address?: string
  manual_refined_resume?: string
  my_review?: string
  ai_rewrite_json?: string
  dream_picture?: string
  ats_ability_analysis?: string
  strong_fit_assessment?: string
  risk_red_flags?: string
  deep_action_plan?: string
  resume_audit?: string
  composite_diagnosis_report?: string
  greeting_msg?: string
  platform?: string
  role?: string
  publish_date?: string
  second_qa_report?: string
  preliminary_score?: number
  bonus_words?: string
  deduction_words?: string
  grade?: string
  role_match?: number
  skills_align?: number
  seniority?: number
  compensation?: number
  interview_prob?: number
  company_stage?: number
  market_fit?: number
  growth?: number
  ai_evaluation_detail?: string
  job_link?: string
  [key: string]: unknown
}

// 把后端 snake_case 岗位记录映射为前端 JobData（camelCase）。
// 列表接口与详情接口共用：详情数据合并进来后再走同一个映射即可。
export function mapApiItemToJob(item: JobsApiItem, index: number): JobData {
  // 使用 platform + record_id 组合确保全局唯一 ID
  const platform = item.platform ?? "未知"
  const recordId = String(item.record_id ?? `temp-${index}`)
  const uniqueId = `${platform}-${recordId}`

  return {
    id: uniqueId,
    companyName: item.company_name ?? "未知公司",
    jobTitle: item.job_name ?? "未知职位",
    salary: item.salary ?? "-",
    location: item.city ?? "-",
    companyScale: item.scale ?? "-",
    industry: item.industry ?? "-",
    education: item.education ?? "-",
    experience: item.experience ?? "-",
    aiScore: Number(item.ai_score ?? 0),
    bgScore: Number(item.bg_score ?? 0),
    skillScore: Number(item.skill_score ?? 0),
    expScore: Number(item.exp_score ?? 0),
    skillReq: item.skill_req ?? "",
    hrActivity: item.hr_active ?? "-",
    followStatus: item.follow_status ?? "待投递",
    captureTime: item.fetch_time ?? "-",
    applyDate: item.delivery_date ?? "-",
    myReview: item.my_review ?? "-",
    workAddress: item.work_address ?? "-",
    hrSkills: Array.isArray(item.hr_skills) ? item.hr_skills : [],
    benefits: Array.isArray(item.benefits) ? item.benefits : [],
    jobDescription: item.job_detail ?? "",
    directLink: item.job_link && item.job_link !== "-" ? item.job_link : "#",
    aiRewriteJson: item.ai_rewrite_json ?? "",
    manualRefinedResume: item.manual_refined_resume ?? "",
    dreamPicture: item.dream_picture ?? "",
    atsAbilityAnalysis: item.ats_ability_analysis ?? "",
    resumeAudit: item.resume_audit ?? "",
    strongFitAssessment: item.strong_fit_assessment ?? "",
    riskRedFlags: item.risk_red_flags ?? "",
    deepActionPlan: item.deep_action_plan ?? "",
    compositeDiagnosisReport: item.composite_diagnosis_report ?? "",
    greetingMsg: item.greeting_msg ?? "",
    secondQaReport: item.second_qa_report ?? "",
    platform: platform,
    role: item.role ?? "未知",
    publishDate: item.publish_date ?? "-",
    preliminaryScore: Number(item.preliminary_score ?? 0),
    bonusWords: item.bonus_words ?? "-",
    deductionWords: item.deduction_words ?? "-",
    grade: item.grade ?? "",
    roleMatch: Number(item.role_match ?? 0),
    skillsAlign: Number(item.skills_align ?? 0),
    seniority: Number(item.seniority ?? 0),
    compensation: Number(item.compensation ?? 0),
    interviewProb: Number(item.interview_prob ?? 0),
    companyStage: Number(item.company_stage ?? 0),
    marketFit: Number(item.market_fit ?? 0),
    growth: Number(item.growth ?? 0),
    companyIntel: (item as any).company_ai_intel ?? (item as any)["公司业务情报"] ?? "",
    predictedQa: (item as any).predicted_qa ?? (item as any)["专属面试预测"] ?? "",
    live_interview_record: (item as any).live_interview_record ?? (item as any)["现场面试记录"] ?? "",
    resume_qa: (item as any).resume_qa ?? (item as any)["简历专项QA"] ?? "",
    // 后端 normalize_job_record 已从飞书"高德导航直达"字段抽出裸 URL；前端按钮优先使用此链接
    amapLink: (item as any).amap_link ?? "",
    interviewReport: (item as any).interview_prep_report ?? "",
    // 多Agent数据是标准的 Markdown，必须原样透传，不能压扁成纯文本
    multiAgentRewrite: (item as any).multi_agent_rewrite ?? (item as any)["多agent简历改写"] ?? "",
    aiEvaluationDetail: item.ai_evaluation_detail ?? "",
    jdText: item.job_detail ?? "",
    evaluationReport: item.ai_evaluation_detail ?? "",
    qaReport: item.second_qa_report ?? "",
    latestResumeText: item.ai_rewrite_json ?? "",
    interviewTime: (item as any).interview_time ?? (item as any)["面试时间"] ?? "",
    interviewLocation: (item as any).interview_location ?? (item as any)["面试地点"] ?? "",
  }
}
