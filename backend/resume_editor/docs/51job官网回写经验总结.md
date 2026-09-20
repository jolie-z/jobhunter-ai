# 51job 官网简历回写经验总结（2026-08）

> 继 BOSS（拦截 token + fetch 回放）、猎聘（pusher + 模块勾选）之后的第三个真实回写平台。
> 脚本：`backend/resume_editor/platforms/job51_write_back.py`

## 一、技术路线：页面内 resumeApi 直调（比 BOSS 更简单）

51job 简历中心是 Vue2 + Nuxt SSR，页面 Vue 原型上挂了一套 RESTful API 封装：

```js
var vm = document.querySelector('#__nuxt').__vue__;
var ra = vm.$api.resumeApi;          // 底层 axios 实例 baseURL=https://cupid.51job.com
var pc = findByName(vm, 'PCResume', 0);  // 简历主组件
var rid = String(pc.$data.resumeInfo.resumeId);   // 369525152
```

- **无需手动管理 token**：页面上下文调用自动带 cookie 鉴权（BOSS 需拦截 token 回放，51job 直接调方法）
- 响应包络：`{status:"1", message:"成功", resultbody:{...}}`；norm 辅助 `(r && r.resultbody !== undefined) ? r : (r && r.data)`
- `resumeInfo` 里所有列表条目都带官网 id → **按 id 匹配（edit/add/del）是确定性策略**

### 已标定端点签名（参数顺序以 toString 为准）

| 操作 | 方法 | 签名（rid=简历id） |
|---|---|---|
| 自我介绍 | editSelfIntroduction | `(rid, {selfIntroduction, api_key:'51job'})` |
| 工作经历 | editWorkExp / addWorkExp / delWorkExp | `(rid, id, data)` / `(rid, data)` / `(rid, id)` |
| 项目 | getProjectEdit / getProjectAdd / getProjectDel | 同上 |
| 教育 | editEducation / addEducation / delEducation | 同上（add 返回 `resultbody.data.id`） |
| 技能 | getSkillItEdit / getSkillItAdd / getSkillItDel | 同上 |
| 语言 | languageEdit / languageAdd / languageDel | 同上；**languageDel 官网源码实际打 /skill-it/{id}** |
| 证书 | getCertificateEdit / getCertificateDel | `(rid, id, data)` / `(rid, id)` 单条 |
| 求职意向 | editIntention / addIntention / delIntention | `(id, data)` / `(data)` / `(id)` —— **无 rid** |

### 不可用/放弃

- `editBaseInfo` → 返回「版本升级请重新选择」(status=100004)，任意 payload 形状都失败 → **basic_info HARD_SKIP**（且 name/mobile/email/wechat 是脱敏值）
- `multiEditCertification` → 官网组件无任何调用方（死 API），wrapped/bare 两种参数都在 axios 层报 TypeError → **certificates 不支持 add**，仅单条 edit/del

## 二、关键坑

1. **「至今」表示不一致**：官网存 `endTime: null`，本地快照存 `"至今"`。no-op 判定与复核必须归一化（`_norm_time`），edit 载荷要把 `"至今"` 转回 `None`，否则永远误判有差异。
2. **macOS 系统代理拦截 localhost**：Python urllib 连 127.0.0.1:9227（Edge CDP）会超时，curl 不受影响。所有脚本/子进程必须注入 `NO_PROXY=127.0.0.1,localhost`（resume_server.py 已在 subprocess env 里强制注入）。
3. **DrissionPage run_js 默认 30s 超时**：连续多个 API 调用或慢请求要传 `timeout=60+`。
4. **官网数据可能随时变动**：no-op 验证通过后官网仍可能被手动修改（本次实测发现项目文案被改、多出空教育条目），回写前必须现拉官网数据做 diff，不能信任旧快照。
5. **探针残留清理**：add→del 幂等探针若取 newId 的层级写错（resultbody.data.id 嵌套），会残留测试条目，务必回读官网确认并删除。

## 三、回写策略

- 数据源：`51job_writeback.json` 快照（writeback-save 端点生成）优先，回退 `51job_fields.json`
- 模块：self_introduction / intentions / works / projects / educations / skills / language / certifications（basic_info、personalSkills HARD_SKIP）
- 语义：**全量覆盖** —— 同 id 且业务键有差异 → edit；本地无 id → add；官网多余 → del
- no-op 短路：业务键全一致的条目跳过，与官网完全一致的模块整体跳过
- 复核：回写后重新导航拉官网数据，逐模块比对业务键 + 条数（BOSS 经验「复核必须覆盖全字段」）

## 四、接入方式

- CLI：`python job51_write_back.py [--dry-run] [--json] [--paths works,skills]`，输出 `RESULT_JSON:` 标记行
- `/api/agent-map/write-back`：`{platform:"51job", dry_run, paths}`（与 boss 共用端点，WRITE_BACK_SCRIPTS 映射）
- `/api/unified/sync-back`：51job 与猎聘同模式（读快照、传 paths、不依赖 unified_resume.json）
- 前端 `51job-tab.tsx`：顶部 sticky「51job 模块回写」操作条（模块勾选 + 保存快照 + 两步确认），仿猎聘；注意回写成功后**不要调 onRefresh**（loading=true 会闪掉反馈文字）

## 五、验证记录

- no-op：8 个 edit 端点全部 status=1；educations/projects/skills add→del 幂等探针通过
- 真实回写：projects edit + educations del 2/2 成功，复核 ✓
- 端点联调：write-back（dry_run/真实）、writeback-save、sync-back 全部 200
- UI：3001 临时实例浏览器实测，两步确认 → `✓ 无需回写（全部与官网一致）`

## 六、主简历映射（51job Tab 顶部报告卡）

- 闭环：顶部操作区勾选 51job → 「映射」→ 报告卡展示在 51job Tab 顶部 → 两步确认「应用映射到 51job」→ 写入 51job_fields.json → 「保存快照」→ 「回写选中模块」
- LLM 映射（map_platform）优先；LLM 不可用（无 Key/429 余额不足/JSON 无效）自动兜底 `map_platform_rules` 确定性规则映射，报告 warnings 标明引擎与原因
- 规则映射范围：个人优势←summary、works/projects/educations 的文本+时间字段；选项类字段（求职意向/技能代码/语言/证书）保留官网原值；条数相等按序对齐，不等按起始月精确匹配
- 坑：agent_mapper.load_env_config / resume_server._load_llm_config 原先硬编码主 repo 的 .env 相对路径，worktree 布局解析不到 → 改为「优先本项目 backend/.env，回退旧路径」，worktree 需拷贝 .env
- 坑：_fallback_certificates 会给 schema 无 certificates 模块的平台（51job 用 certifications）补一个死字段 → 已加守卫跳过
