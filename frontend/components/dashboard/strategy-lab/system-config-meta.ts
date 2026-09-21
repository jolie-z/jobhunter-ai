// 系统底层配置 — 分组展示元数据（必填/选填、备注、配置教程）
// key 必须与后端 service.py CONFIG_GROUPS 的 group 名称完全一致

export interface TutorialStep {
  title: string
  desc: string
}

export interface Tutorial {
  title: string
  intro: string
  steps: TutorialStep[]
  tip?: string
}

export interface GroupMeta {
  required: boolean
  note?: string
  tutorial?: Tutorial
  diagnose?: boolean  // 该分组支持「检测/测试连通性」（LLM 大模型 / 飞书）
}

export const GROUP_META: Record<string, GroupMeta> = {
  "LLM 大模型": {
    required: true,
    diagnose: true,
    tutorial: {
      title: "LLM 大模型配置教程",
      intro: "系统的核心推理引擎。支持任意 OpenAI 兼容的服务（小米 Mimo、OpenAI、DeepSeek、Moonshot 等），只要 Base URL 与模型名相互匹配即可。",
      steps: [
        { title: "获取 API Key", desc: "前往模型服务商控制台创建密钥。例如，\n小米 Mimo：platform.xiaomimimo.com\nOpenAI：platform.openai.com/api-keys\nDeepSeek：platform.deepseek.com\nQwen：bailian.console.aliyun.com\nKimi：platform.moonshot.cn/console/api-keys" },
        { title: "填写 Base URL", desc: "填入对应的 OpenAI 兼容端点，通常以 /v1 结尾。例如，\n小米 Mimo：https://api.xiaomimimo.com/v1\nOpenAI：https://api.openai.com/v1\nDeepSeek：https://api.deepseek.com/v1\nQwen：https://dashscope.aliyuncs.com/compatible-mode/v1\nKimi：https://api.moonshot.cn/v1" },
        { title: "填写推理模型", desc: "填入主力对话模型名，如 mimo-v2.5-pro、gpt-4o、deepseek-chat。岗位评估、简历改写、飞书聊天助理等都走这个模型。" },
        { title: "填写视觉模型", desc: "填入支持图片输入的模型名，如 mimo-v2.5、gpt-4o。用于简历图片解析等场景。" },
      ],
      tip: "推理模型与视觉模型可以是同一家服务商的不同模型，也可以混搭不同服务商（只要各自的 Key 与 Base URL 对应）。保存后即时生效，无需重启。",
    },
  },

  "视觉通道 (可选)": {
    required: false,
    note: "独立视觉（图片识别）通道。主 LLM 网关不支持图片输入时，把这里指向支持视觉模型的供应商即可；不填则默认复用「LLM 大模型」的 Key 与 Base URL。",
  },

  "数据清洗 LLM": {
    required: false,
    note: "如不填写默认走「LLM 大模型」。用于爬虫数据清洗，可单独配置更便宜的模型以节省主力模型额度。也可在 .env 设 USE_MAIN_LLM_FOR_CLEANER=true 强制走主通道。",
  },

  "飞书": {
    required: true,
    diagnose: true,
    tutorial: {
      title: "飞书密钥与数据表配置教程",
      intro: "飞书多维表格（Bitable）是系统的数据中枢，岗位、简历、策略、偏好都存在这里。需要先创建一个飞书应用拿到凭证，再拿到各张表的 ID。新手推荐按 docs/feishu-setup.md 完整手册一步步来。",
      steps: [
        { title: "创建自建应用", desc: "打开飞书开放平台 open.feishu.cn → 开发者后台 → 创建企业自建应用。" },
        { title: "拿 App ID / App Secret", desc: "进入应用的「凭证与基础信息」页面，复制 App ID（cli_ 开头）和 App Secret。" },
        { title: "开通多维表格权限", desc: "在「权限管理」中搜索并开通多维表格相关权限（如 bitable:app、bitable:record 的读写权限），然后创建版本并发布（不发布不生效！）。" },
        { title: "把应用加为协作者", desc: "打开你的多维表格文档 → 右上角「分享」→ 把刚创建的应用添加为协作者并给可编辑权限，否则应用无法读写。" },
        { title: "拿 App Token", desc: "打开多维表格文档，浏览器地址栏中 /base/ 后面那串字符就是 App Token（如 CFkBYourAppTokenPlaceholder）。" },
        { title: "拿各数据表 ID", desc: "在多维表格里切换到对应的表（岗位/策略/简历等），地址栏 table= 后面的就是该表 Table ID（如 tblyYourTableIdPlaceholder），逐张复制填入。" },
        { title: "检测连通性", desc: "填写完成后点击「飞书」分组的「检测连通性」按钮，系统会逐项验证凭证、文档、数据表、群机器人与长连接，并给出每项的修复指引。" },
      ],
      tip: "App Token 是整个文档的标识，所有表共用；Table ID 是每张表各自的标识，需要分别获取。保存后即时生效（飞书长连接会自动用新凭证重连）。",
    },
  },

  "搜索/情报": {
    required: false,
    note: "用于公司岗位的外部情报联网搜索（AI 初评背调、面试 Copilot 靶向刷新、面试前自动调研公司动态）。Serper 为主引擎，Tavily 为降级备用：Serper 未配置或请求失败时自动切换 Tavily；两个都不填则跳过情报增强，不影响主流程。",
    tutorial: {
      title: "公司情报引擎配置教程（Serper 主 + Tavily 备）",
      intro: "Serper 是 Google 搜索的官方管道，系统用它 4 路并发侦察公司情报（核心业务 / 竞品地位 / AI 技术布局 / 近一个月融资裁员财报新闻）并让 LLM 汇总成简报。Tavily 是为 LLM 设计的网页抓取管道，无时间过滤、易混入工商信息类档案页噪声，仅在 Serper 不可用时降级使用。",
      steps: [
        { title: "注册 Serper（主引擎，必配）", desc: "前往 serper.dev 注册，免费赠送 2500 次查询额度。" },
        { title: "复制 API Key", desc: "登录后进入 Dashboard → API Key 页面，点击复制。" },
        { title: "填入配置", desc: "把 Key 粘贴到「Serper API Key（主引擎）」输入框并保存，初评背调与面试情报即刻生效。" },
        { title: "配置 Tavily（可选，降级备用）", desc: "前往 tavily.com 注册（每月约 1000 次免费额度，Key 以 tvly- 开头），填入「Tavily API Key（降级备用）」。未配置时 Serper 故障将直接跳过情报增强。" },
      ],
      tip: "两者怎么选：要查公司近期动态（新闻、融资、业务）用 Serper——Google 排序 + 时间窗 + 干净摘要；Tavily 适合整页内容抽取（RAG 场景），作为兜底保底可用。",
    },
  },

  "语音识别 (火山引擎)": {
    required: false,
    note: "用于所有语音按钮下的语音流式输入（边说边转文字）。不填则默认调用网页自带的语音输入。保存后需重启后端生效。",
    tutorial: {
      title: "火山引擎语音识别配置教程",
      intro: "系统使用火山引擎（豆包）的流式语音识别 V3 做面试语音转文字。",
      steps: [
        { title: "开通语音技术", desc: "前往火山引擎控制台 console.volcengine.com → 搜索「语音技术」→ 开通流式语音识别服务。" },
        { title: "创建应用拿 App ID", desc: "在语音控制台创建应用，获取 App ID（纯数字）。" },
        { title: "获取 Token", desc: "在「访问凭证 / 鉴权」页面生成并复制访问 Token。" },
        { title: "填写 Resource ID", desc: "默认填 volc.seedasr.sauc.duration 即可（按时长计费的资源包标识）。" },
      ],
      tip: "火山引擎对新用户有免费试用额度，需先在控制台完成开通和计费方式设置。",
    },
  },

  "地图 (高德)": {
    required: false,
    note: "用于面试卡片提醒的路线规划（地理编码面试地址）。不填则面试卡片不显示地图路线。",
    tutorial: {
      title: "高德地图 API 配置教程",
      intro: "系统使用高德开放平台的 Web 服务 API 做地理编码，把面试地址解析为坐标用于路线规划。",
      steps: [
        { title: "注册开发者账号", desc: "前往高德开放平台 lbs.amap.com 注册并完成开发者认证。" },
        { title: "创建应用与 Key", desc: "进入控制台 → 应用管理 → 我的应用 → 创建新应用 → 添加 Key，服务平台务必选「Web服务」。" },
        { title: "复制 Key", desc: "生成后复制该 Web 服务 Key，填入「API Key」输入框。" },
        { title: "Base URL 保持默认", desc: "Base URL 默认 https://restapi.amap.com/v3/geocode/geo，一般无需修改。" },
      ],
      tip: "一定要选「Web服务」类型的 Key，选成「Web端(JS API)」会鉴权失败。",
    },
  },
}

// ==========================================
// 飞书聊天指令功能 — 启用前置条件 & 教程
// autoKey：对应「检测连通性」结果里的检查项，检测结果可自动点亮该步骤
// ==========================================
export interface ChatOpsChecklistItem {
  label: string
  detail: string
  configKey?: string  // 对应后端配置字段，用于自动检测是否已填写
  autoKey?: string    // 对应诊断接口 checks[].key：credentials / chats / ws，检测后自动点亮
}

export const FEISHU_CHATOPS_CHECKLIST: ChatOpsChecklistItem[] = [
  { label: "飞书 App ID / App Secret", detail: "上方「飞书」分组中填写", configKey: "FEISHU_APP_ID", autoKey: "credentials" },
  { label: "开启机器人能力", detail: "飞书开放平台 → 应用 → 添加应用能力 → 机器人", autoKey: "chats" },
  { label: "事件订阅改为「长连接」", detail: "事件与回调 → 事件配置 → 订阅方式 → 使用长连接接收事件", autoKey: "ws" },
  { label: "添加消息事件", detail: "事件配置 → 添加事件 → im.message.receive_v1（接收消息）" },
  { label: "开通 IM 权限", detail: "权限管理 → 搜索 im:message → 开通读写权限 → 创建版本并发布", autoKey: "chats" },
  { label: "把机器人拉入群聊", detail: "打开目标飞书群 → 设置 → 群机器人 → 添加你的应用", autoKey: "chats" },
  { label: "后端服务运行中", detail: "uvicorn app.main:app --port 8000（启动后自动建立 WebSocket 长连接）", autoKey: "ws" },
]

export const FEISHU_CHATOPS_TUTORIAL: Tutorial = {
  title: "飞书聊天指令功能启用教程",
  intro: "启用后，你可以在飞书群里 @机器人 用自然语言指挥求职助理 Agent（如「看看整体数据」「发今天的日报」「帮这个岗位评估一下」）。无需公网 IP、域名或内网穿透。完整图文手册见 docs/feishu-setup.md。",
  steps: [
    { title: "确认飞书凭证已填写", desc: "在上方「飞书」分组中填入 App ID（cli_ 开头）和 App Secret。这是 WebSocket 长连接鉴权的基础。" },
    { title: "开启机器人能力", desc: "打开飞书开放平台 open.feishu.cn → 开发者后台 → 你的应用 → 左侧「添加应用能力」→ 勾选「机器人」→ 保存。" },
    { title: "切换事件订阅为长连接", desc: "进入应用 → 左侧「事件与回调」→「事件配置」→ 将订阅方式从「请求地址」切换为「使用长连接接收事件」→ 保存。" },
    { title: "添加消息接收事件", desc: "在事件配置页面 → 「添加事件」→ 搜索 im.message.receive_v1（接收消息 v2.0）→ 勾选 → 保存。" },
    { title: "开通 IM 消息权限", desc: "左侧「权限管理」→ 搜索 im:message → 开通「获取与发送单聊、群组消息」权限 → 点击「创建版本」发布（不发布不生效！）。" },
    { title: "把机器人拉入目标群", desc: "打开你想用来下指令的飞书群 → 群设置 → 群机器人 → 添加机器人 → 选择你创建的应用。" },
    { title: "启动后端服务", desc: "在 backend 目录执行：\nuvicorn app.main:app --port 8000\n\n启动后日志中会出现：\n✅ 飞书 WebSocket 长连接已启动\n\n看到这行说明长连接建立成功。" },
    { title: "在群里测试", desc: "在飞书群里发送：@你的机器人 ping\n\n如果收到 🏓 pong 回复，说明全链路畅通！\n\n之后就可以用自然语言指挥 Agent 了，例如：\n· 「看看整体数据」「发今天的日报」\n· 「帮我找一下 字节 的 后端 岗」\n· 「帮这个岗位评估一下」\n· 「把这条改成已投递」" },
  ],
  tip: "长连接模式无需公网 IP、域名或 Cloudflare Tunnel。只要你的电脑能访问外网，后端启动后就会主动连接飞书服务器，事件通过这条连接推下来。在配置页保存飞书凭证会自动用新凭证重连，无需重启。",
}

// ==========================================
// 飞书 ChatOps 指令话术（兜底数据）
// 运行时优先从后端 GET /api/chatops/tools 拉取（以后端 TOOL_META 为唯一真源），
// 仅当后端未启动/接口异常时才使用这份静态兜底。内容需与后端 TOOL_META 保持同步。
// ==========================================
export interface ChatOpsCommand {
  tool: string
  desc: string
  phrases: string[]
}

export interface ChatOpsCommandGroup {
  category: string
  icon: string
  commands: ChatOpsCommand[]
}

export const CHATOPS_COMMANDS: ChatOpsCommandGroup[] = [
  {
    category: "岗位与简历",
    icon: "📋",
    commands: [
      { tool: "locate_job", desc: "按公司名+岗位名定位岗位表中的记录", phrases: ["帮我找一下 字节 的 后端 岗", "定位一下这家公司的岗位", "看看表里有没有这个岗位"] },
      { tool: "read_job_resume", desc: "读取岗位全量画像（链接/薪资/评估/简历内容）", phrases: ["把这个岗位的链接发我", "这个岗位评估里写了什么", "看看这个岗位的详情"] },
      { tool: "query_company_intel", desc: "查询公司业务情报与近期动态（缓存优先，可联网搜索）", phrases: ["查一下这家公司的背景", "这家公司最近有什么动态", "看看这家公司的AI布局"] },
      { tool: "edit_resume_json", desc: "按自然语言指令修改定制简历（先出草案待确认）", phrases: ["把这份简历往数据方向改一改", "突出一下我的大模型项目经验", "简历里少写点运维内容"] },
      { tool: "confirm_and_render_materials", desc: "确认修改草案，正式写回并重新渲染 PDF/长图物料", phrases: ["确认生成", "就按这个出物料", "可以了，写回吧"] },
      { tool: "cancel_resume_edit", desc: "放弃当前简历修改草案，表格保持原样", phrases: ["取消修改", "不改了", "放弃这次改动"] },
      { tool: "update_follow_status", desc: "更新单个岗位的跟进状态（单条写操作）", phrases: ["这条改成已投递", "标记为面试中", "这个岗位标记已拒绝"] },
    ],
  },
  {
    category: "评估与进度",
    icon: "🚀",
    commands: [
      { tool: "start_evaluation", desc: "对岗位发起 AI 评估流水线（后台跑，进度卡实时更新）", phrases: ["评估一下这个岗位", "帮这个岗位跑一轮评估", "深度评估这家公司"] },
      { tool: "check_evaluation_progress", desc: "查询岗位评估进度（评估中/已完成/评级）", phrases: ["评估好了吗", "评估进度怎么样", "跑到哪一步了"] },
      { tool: "check_progress", desc: "查询后台任务进度（批量任务/评估流水线）", phrases: ["现在跑到哪了", "任务完成了吗", "看看当前进度"] },
    ],
  },
  {
    category: "表格维护",
    icon: "🧹",
    commands: [
      { tool: "check_table_hygiene", desc: "岗位表体检：重复岗位、过期积压统计（只读）", phrases: ["岗位表干不干净", "有多少重复岗位", "体检一下岗位表"] },
      { tool: "archive_duplicate_jobs", desc: "归档重复岗位（先体检出清单、用户同意后执行）", phrases: ["把重复的归档了吧", "清理一下重复岗位", "按刚才的清单归档"] },
      { tool: "start_liveness_check", desc: "启动一批过期岗位的链接存活检测（后台跑）", phrases: ["查查哪些岗位失效了", "检测一下链接存活", "把死链岗位找出来"] },
      { tool: "check_liveness_progress", desc: "查询存活检测批次进度", phrases: ["存活检测跑到哪了", "死链检查完了吗"] },
      { tool: "review_duplicate_suspects", desc: "复核疑似重复岗位（只读，出放行建议与边界对比）", phrases: ["复核一下疑似重复", "那些重复岗位怎么处理", "看看重复嫌疑清单"] },
      { tool: "approve_duplicate_suspects", desc: "放行用户明确点名的疑似重复岗位（记入白名单）", phrases: ["前两条放行", "这几条不是重复，放了吧", "把这条放出来"] },
    ],
  },
  {
    category: "数据与战报",
    icon: "📊",
    commands: [
      { tool: "query_dashboard", desc: "数据看板：总览/漏斗/平台对比/趋势", phrases: ["看看整体数据", "给我看漏斗转化", "各平台对比怎么样", "最近一周趋势如何"] },
      { tool: "send_report", desc: "生成并推送战报（日报/周报/月报/终报）到接收群", phrases: ["发今天的日报", "生成本周周报", "出一份月报", "收工，发个终报"] },
    ],
  },
]
