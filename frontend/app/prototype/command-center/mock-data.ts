/**
 * PROTOTYPE — 模拟数据（高保真版）
 * 覆盖：抓取配置、清洗规则、AI评估参数、投递配置、日志历史
 * 非生产代码，验证后删除。
 */

export const STAGES = [
  { key: "scraping", label: "平台抓取", icon: "🕷️" },
  { key: "cleaning", label: "规则清洗", icon: "🧹" },
  { key: "feishu_sync", label: "飞书推送", icon: "📤" },
  { key: "evaluating", label: "AI初评", icon: "🤖" },
  { key: "deep_eval", label: "深度评估", icon: "🔍" },
  { key: "rewriting", label: "简历改写", icon: "✍️" },
  { key: "greeting", label: "打招呼语", icon: "👋" },
  { key: "review", label: "待审批", icon: "⏸️" },
  { key: "delivering", label: "自动投递", icon: "🚀" },
] as const

export type StageKey = (typeof STAGES)[number]["key"]

// ─── 链路运行状态 ───

export const MOCK_STAGE_STATUS: Record<string, "pending" | "running" | "done"> = {
  scraping: "done",
  cleaning: "done",
  feishu_sync: "done",
  evaluating: "running",
  deep_eval: "pending",
  rewriting: "pending",
  greeting: "pending",
  review: "pending",
  delivering: "pending",
}

export const MOCK_SCRAPE_PROGRESS: Record<string, { current: number; total: number }> = {
  boss: { current: 18, total: 20 },
  liepin: { current: 15, total: 20 },
  "51job": { current: 20, total: 20 },
  zhilian: { current: 12, total: 20 },
  xiaohongshu: { current: 12, total: 30 },
}

export const MOCK_CLEANING_CHANNELS = {
  xhs: { raw: 12, afterHardRule: 10, afterAiScout: 8, label: "小红书" },
  platforms: { raw: 53, afterHardRule: 32, afterAiScout: 20, label: "招聘平台" },
}

export const MOCK_FEISHU_CHANNELS = {
  xhs: { synced: 8, pending: 4, label: "小红书" },
  platforms: { synced: 20, pending: 12, label: "招聘平台" },
}

// ─── 岗位数据 ───

export const MOCK_JOBS = [
  { job_id: "rec001", job_name: "高级前端工程师", company: "字节跳动", platform: "boss", grade: "A", status: "done", node: "evaluate_node", salary: "30-50K" },
  { job_id: "rec002", job_name: "React 全栈开发", company: "腾讯", platform: "liepin", grade: "B", status: "done", node: "evaluate_node", salary: "25-40K" },
  { job_id: "rec003", job_name: "Web 前端实习生", company: "网易", platform: "51job", grade: "C", status: "running", node: "evaluate_node", salary: "4-6K" },
  { job_id: "rec004", job_name: "资深 UI 工程师", company: "阿里巴巴", platform: "boss", grade: "A", status: "running", node: "evaluate_node", salary: "35-55K" },
  { job_id: "rec005", job_name: "前端架构师", company: "华为", platform: "zhilian", grade: "B", status: "running", node: "evaluate_node", salary: "40-60K" },
  { job_id: "rec006", job_name: "小程序开发工程师", company: "美团", platform: "51job", grade: "C", status: "waiting", node: "manual_review_node", salary: "20-35K" },
  { job_id: "rec007", job_name: "Node.js 全栈", company: "小红书", platform: "liepin", grade: "A", status: "delivered", node: "delivery_node", salary: "30-45K" },
  { job_id: "rec008", job_name: "前端团队负责人", company: "京东", platform: "boss", grade: "B", status: "waiting", node: "manual_review_node", salary: "45-70K" },
]

// ─── 抓取配置（模拟） ───

export const MOCK_SCRAPE_CONFIG = {
  keyword: "前端开发",
  city: "广州",
  salary: "不限",
  platforms: {
    boss: { enabled: true, limit: 20, online: true },
    liepin: { enabled: true, limit: 20, online: true },
    "51job": { enabled: true, limit: 20, online: true },
    zhilian: { enabled: true, limit: 20, online: false },
    xiaohongshu: { enabled: false, limit: 0, online: true },
  } as Record<string, { enabled: boolean; limit: number; online: boolean }>,
}

export const SALARY_TIERS = ["不限", "3K以下", "3-5K", "5-10K", "10-15K", "15-20K", "20-30K", "30-50K", "50K以上"]

// Boss直聘城市列表（来源：backend/boss_scraper/boss_cli/constants.py CITY_CODES）
export const CITY_GROUPS: { group: string; cities: string[] }[] = [
  { group: "一线", cities: ["北京", "上海", "广州", "深圳"] },
  { group: "新一线", cities: ["杭州", "成都", "南京", "武汉", "西安", "苏州", "长沙", "天津", "重庆", "郑州", "东莞", "佛山", "合肥", "青岛", "宁波", "沈阳", "昆明"] },
  { group: "二线", cities: ["大连", "厦门", "珠海", "无锡", "福州", "济南", "哈尔滨", "长春", "南昌", "贵阳", "南宁", "石家庄", "太原", "兰州", "海口", "常州", "温州", "嘉兴", "徐州"] },
  { group: "其他", cities: ["全国", "香港", "远程"] },
]

// 各平台登录授权端口已统一由后端唯一配置区提供（backend/app/session/registry.py），
// 前端通过 lib/platform-auth.ts 的 fetchPlatformMeta() 获取，禁止在此另存副本。

// ─── 清洗规则配置（模拟） ───

export const MOCK_CLEANING_RULES = [
  { id: 1, name: "薪资下限过滤", desc: "低于设定薪资的岗位直接淘汰", enabled: true, param: "≥ 8K" },
  { id: 2, name: "学历过滤", desc: "过滤学历要求高于硕士的岗位", enabled: true, param: "本科及以上" },
  { id: 3, name: "关键词黑名单", desc: "包含黑名单关键词的岗位淘汰", enabled: true, param: "外包, 外派, 驻场" },
  { id: 4, name: "公司规模过滤", desc: "过滤少于50人的公司", enabled: false, param: "≥ 50人" },
  { id: 5, name: "经验要求过滤", desc: "过滤要求10年以上经验的岗位", enabled: true, param: "≤ 5年" },
  { id: 6, name: "重复岗位去重", desc: "同一公司同一标题只保留最新", enabled: true, param: "" },
]

// ─── AI 评估参数（模拟） ───

export const MOCK_AI_EVAL_CONFIG = {
  model: "mimo-v2.5-pro",
  concurrency: 5,
  rules: [
    "岗位与「前端开发」方向匹配度 ≥ 70%",
    "非纯管理岗（需含技术内容）",
    "公司非黑名单企业",
    "薪资范围与期望重叠",
    "工作地点在广州或支持远程",
    "非实习/兼职（除非明确标注）",
    "JD 描述完整（≥ 100字）",
    "发布时间 ≤ 7天",
  ],
  gradeThresholds: { A: "≥ 90分", B: "≥ 75分", C: "≥ 60分", D: "< 60分" },
}

// ─── 投递配置（模拟） ───

export const MOCK_DELIVERY_CONFIG = {
  platforms: {
    boss: { enabled: true, method: "打招呼语" },
    liepin: { enabled: true, method: "打招呼语" },
    "51job": { enabled: true, method: "附件简历" },
    zhilian: { enabled: true, method: "附件简历" },
  } as Record<string, { enabled: boolean; method: string }>,
  autoGrades: ["C"] as string[],
  resumeSource: "基础简历",
}

// ─── 日志 ───

export const MOCK_LOGS = [
  "[19:41:02] 全链路启动: 前端开发 / 广州",
  "[19:41:03] 开始抓取 Boss直聘 (limit=20)",
  "[19:41:03] 开始抓取 猎聘 (limit=20)",
  "[19:41:04] 开始抓取 前程无忧 (limit=20)",
  "[19:41:04] 开始抓取 智联招聘 (limit=20)",
  "[19:41:28] Boss直聘 抓取完成: 18/20 条入库",
  "[19:41:31] 猎聘 抓取完成: 15/20 条入库",
  "[19:41:35] 前程无忧 抓取完成: 20/20 条入库",
  "[19:41:40] 智联招聘 抓取完成: 12/20 条入库",
  "[19:41:41] 规则清洗开始: Tier1 硬规则过滤",
  "[19:41:55] 硬规则过滤完成: 65→42 条通过",
  "[19:41:56] AI 侦察兵开始: Semaphore(5) 并发评估",
  "[19:42:18] AI 侦察兵完成: 42→28 条通过",
  "[19:42:19] 飞书推送: sync_sqlite_to_feishu 开始",
  "[19:42:25] 飞书推送完成: 28 条新线索已同步",
  "[19:42:26] 深度评估开始: 10 岗位并发 (mimo-v2.5-pro)",
  "[19:42:47] 评估完成: rec001=A, rec002=B, rec003=C ...",
  "[19:42:48] 简历改写: rec001(A), rec002(B) 进入改写",
  "[19:43:10] 改写完成，进入人工审批断点",
  "[19:43:11] C级岗位 rec003 自动投递 Boss直聘...",
]

// ─── 历史运行记录 ───

export const MOCK_RUN_HISTORY = [
  { id: "pipeline_647086f4", time: "2026-07-24 19:41", duration: "11min", status: "done", scraped: 65, evaluated: 10, delivered: 2 },
  { id: "pipeline_a3f21bc9", time: "2026-07-24 09:00", duration: "8min", status: "done", scraped: 48, evaluated: 8, delivered: 3 },
  { id: "pipeline_7e9d02aa", time: "2026-07-23 09:00", duration: "9min", status: "done", scraped: 52, evaluated: 12, delivered: 4 },
  { id: "pipeline_c1b84f02", time: "2026-07-22 19:34", duration: "—", status: "error", scraped: 30, evaluated: 0, delivered: 0 },
]

// ─── 摘要 ───

export const MOCK_SUMMARY = {
  total_scraped: 65,
  total_cleaned: 42,
  total_evaluated: 10,
  grade_a: 3,
  grade_b: 4,
  grade_c: 2,
  grade_other: 1,
  delivered: 2,
  pending_review: 5,
}

// ─── 常量 ───

export const PLATFORM_LABELS: Record<string, string> = {
  boss: "Boss直聘",
  liepin: "猎聘",
  "51job": "前程无忧",
  zhilian: "智联招聘",
  xiaohongshu: "小红书",
}

export const GRADE_COLORS: Record<string, string> = {
  A: "bg-emerald-50 text-emerald-700 border-emerald-200",
  B: "bg-blue-50 text-blue-700 border-blue-200",
  C: "bg-amber-50 text-amber-700 border-amber-200",
  D: "bg-gray-50 text-gray-500 border-gray-200",
}
