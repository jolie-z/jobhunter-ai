# BOSS直聘「汇总新」映射经验总结

> 沉淀自 BOSS直聘 平台 agent 映射（汇总新 Tab）的全部开发与踩坑经验，
> 供猎聘 / 前程无忧 / 智联招聘 平台复用。代码位置：`backend/resume_editor/agent_mapper.py`。

## 一、总体架构

核心流程：**主简历（飞书简历库）→ LLM 映射 → 执行报告（fields/unfilled/warnings）→ 人工审核编辑 → 应用到平台**。

两条链路，职责不同：

- **生成链 `map_platform`**（调 LLM）：
  `validate_mapping_result → _normalize_array_items → _normalize_object_fields → _strip_markdown → _enforce_verbatim_description → _fallback_skills → _fallback_expectations → _trim_expectations → _sort_array_items_by_start_desc → _fallback_certificates → _attach_translations → _attach_field_options → _validate_option_consistency`

- **恢复链 `restore_report`**（不调 LLM，刷新/重启省 token）：
  `_attach_translations → _normalize_array_items → _fallback_expectations → _trim_expectations → _normalize_object_fields → _strip_markdown → _fallback_certificates → _ensure_unfilled_fields → _attach_field_options → 剔除旧「不在平台选项中」告警 → _validate_option_consistency`

**两链差异是刻意设计**：restore 不执行 `_enforce_verbatim_description`（逐字恢复主简历原文）、`_sort_array_items_by_start_desc`（按时间倒序排）、`_fallback_skills`——这三者会覆盖/打乱用户手动编辑过的内容；而类型归一化、兜底、裁剪、选项校验双链都跑，保证历史数据也干净。

## 二、Prompt 硬约束体系（build_mapping_prompt）

LLM（mimo v2.5-pro）自律性有限，**每条硬约束都要有对应的后端后处理兜底**，prompt 只是第一层。现行规则：

1. **只输出主简历真实存在的信息，严禁编造**（"了解"级也不脑补成"精通"）。
2. **枚举字段必须从「平台字段取值约束」列表精确选择**；列表内无精确匹配 → 填空字符串 `""` 并写入 warnings，**禁止近似匹配、禁止编造新词**。数组条目的枚举字段（position/industry）同样适用。
3. `*Translation` 派生字段不用填（系统自动推导）。
4. **数组条目 key 必须与「现有条目字段」完全一致**，每个 key 都给值（无内容给空串，禁止省略/null）；布尔字段输出 true/false；时间拆年/月字段。
   - **skills 是全任务唯一允许 agent 发挥提炼的字段**（仅 BOSS 工作经历）：从该条经历描述提炼 3~6 个关键词（≤12 字、禁整句、先去重再按重要度排序），无线索输出 `[]`，禁混入其他条目/板块。
4b. **文本内容字段逐字照抄主简历原文（最高优先级硬约束）**：描述/成就/自我评价等自由文本逐字保留，禁改写/重组/压缩/扩写/润色/混入其他板块/凭记忆补写；多段数组完整保留所有段落；输出剥离 Markdown（`**`、`-`、`#`、反引号）转纯文本。
4c. **公司名等自由文本同样逐字照抄**；职位/行业枚举仍按规则 2。
4d. **期望职位类型上限**：全职（jobType=fulltime）最多 3 条、兼职（parttime）最多 1 条；平台现有条目必须原样保留（禁转类型、禁增减条数）；无线索放 unfilled，禁凭空猜测。
5. 无信息字段放 unfilled + reason；**certificates 特殊**：优先从经历/技能推断 → 无则沿用平台现有值（confidence=low）→ 平台也空则 `[]`，不进 unfilled（模块保留可手动新增）。
6. 每字段给 confidence（high/medium/low）。
7. 已与主简历一致的现有值也要输出，便于整体核对。

**经验**：给 mimo 增加 prompt 约束会挤占注意力、降低改写质量，约束要精炼；凡是 LLM 反复违反的规则（转类型、清空数组、丢段落），必须在后端加确定性后处理，不要指望改 prompt 就能根治。

## 三、后端兜底链（数据层最后防线）

按生成链顺序，每个函数解决一类 LLM 实际犯过的错：

| 函数 | 职责 | 对应踩过的坑 |
|---|---|---|
| `validate_mapping_result` | schema 校验、枚举值逐项校验 | LLM 编造行业/职位 code |
| `_normalize_array_items` | hideResume 字符串→布尔；skills 清洗（`_clean_skill_tags`：去重 casefold/滤空串纯标点/滤 >40 字整句/限 6）；聚合串按顿号逗号拆分；月前导零去除；**非 work_experience 数组删除残留 skills 键** | LLM 输出 `"false"`、整句技能、聚合串、`"04"` 月 |
| `_strip_markdown` | 全字段剥离 Markdown 符号（对纯文本幂等） | LLM 输出带 `**加粗**`、列表符 |
| `_enforce_verbatim_description` | 与主简历逐条 diff，不一致/丢段落 → 覆盖为原文 + warning | LLM 压缩/改写描述、只留第一段 |
| `_fallback_skills` | 条目 skills 为空 → 用主简历该条经历的 skills 字段兜底（按公司名+时间匹配条目） | LLM 偶尔不提炼技能 |
| `_fallback_expectations` | LLM 输出空期望 → 沿用平台现有值（移除 unfilled + warning） | LLM 以"主简历无线索"为由擅自清空平台已有期望 |
| `_trim_expectations` | 全职>3/兼职>1 → 保序裁剪 + warning；**仅对条目含 jobType 字段的平台生效** | LLM 输出 4 条全职 |
| `_sort_array_items_by_start_desc` | 工作/项目按起始时间倒序（仅生成链） | 平台展示习惯最新在前 |
| `_fallback_certificates` | 空证书 → 沿用平台现有值，模块始终保留 | 平台已填证书被 LLM 清空 |
| `_validate_option_consistency` | 报告值 vs 平台选项一致性告警；兼职 position 聚合串跳过不误报 | 选项映射表升级后历史非法值需新鲜告警 |

**复用要点**：这些函数全部按 `path`/结构特征判断、与平台无关，新平台接入自动生效；唯一平台相关的是「条目是否含 jobType」——`_trim_expectations` 用 `any("jobType" in it)` 探测，无 jobType 的平台（猎聘/前程无忧/智联）自动跳过，**不需要改代码**。

## 四、skills 三层保障（BOSS 独有，唯一发挥字段）

1. **prompt 层**：规则 4 中 skills 是唯一不受 4b/4c 照抄约束的字段（见上）。
2. **清洗层** `_clean_skill_tags`：去重（大小写不敏感保序）、滤空串/纯标点/超 40 字整句、最多 6 个。
3. **兜底层** `_fallback_skills`：LLM 输出空 → 取主简历对应条目的 skills/skillTags/skill_tags/skillsList 字段清洗后填入。

**归属约束**：skills 键仅属 work_experience 条目。所有平台的 `*_fields.json` 数组 schema 都没有 skills 键（它是 BOSS 官网「拥有技能」字段，前端兜底渲染：`agent-tab.tsx` 中仅当 `path === "work_experience"` 时补 skills 列）。projects/education 等其他数组的残留 skills 键在 `_normalize_array_items` 中直接删除（生成+恢复双路径），不补空。

## 五、前端交互约束与数据层必须双保险

expectations 上限的教训：**只在前端拦交互入口是不够的**——LLM 绕过前端直接生成数据。完整方案是三层：

1. **前端交互层**（agent-tab.tsx）：`EXPECTATION_FULLTIME_MAX=3 / PARTTIME_MAX=1`，`countExpectationType` 按类型分开计数；保存校验（编辑全职改兼职超限时拦截「无法保存：兼职期望职位最多 1 组」）；新增按钮满额禁用，文案显示「全职 n/3 · 兼职 n/1」。
2. **prompt 层**：规则 4d。
3. **数据层**：`_trim_expectations`（生成+恢复双跑，历史超限数据恢复时也会被清理）。

其他前端经验：

- **共享组件按类型判断的坑**：`expectation-editor.tsx` 满额判断必须绑定 `form.jobType`——否则全职满 3 后切兼职页，保存按钮仍显示「全职已满」被禁用。
- **LimitTextarea 不能 clamp 输入**：超限内容也要允许自由删减（只红字+计数提示），保存/应用时 `validateBeforeWrite` 拦截；onChange 里截断会导致连删除操作都被拒。
- **含 button 的字段勿用 `<label>` 包裹**：label 激活会把点击转发给内部 button（chip 删除 ×）导致误删，用 div。
- UI 偏好：全局操作放页面顶部不重复；破坏性操作两步确认+撤销；操作反馈就地淡入淡出不弹 toast。

## 六、平台差异速查（接入新平台前必看）

| 平台 | expectations 条目结构 | jobType | trim 是否生效 |
|---|---|---|---|
| BOSS直聘 | jobType/position/city/otherCities/salary/industries | ✅ | ✅ 全职≤3 兼职≤1 |
| 猎聘 | position/city/other_cities/industries/salary_min/salary_max/salary_months | ❌ | 自动跳过 |
| 前程无忧 | 现有值为空（待采集） | ❌ | 自动跳过 |
| 智联招聘 | 现有值为空（待采集） | ❌ | 自动跳过 |

四平台 work_experience schema 均无 skills 键——skills 是 BOSS 前端兜底渲染字段，其他平台不需要；`_normalize_array_items` 的按 path 清理逻辑自动覆盖新平台。

## 七、新平台接入 Checklist

1. 准备 `data/{platform}_fields.json`：完整 schema + `current_value`（平台采集现有值）+ 各字段 options。
2. `_build_options_prompt_text` 补平台特有取值约束段（如 BOSS 的 jobType 中文释义、兼职偏好列表）。
3. 确认该平台数组条目结构：有无 jobType（决定 trim 是否生效）、时间字段命名（年/月拆分）、布尔字段。
4. 跑 `flatten_schema` 确认字段树完整；`build_mapping_prompt` 输出的「现有条目字段」与真实条目一致。
5. 测试：prompt 断言 + 该平台结构特异的 normalize/validate 用例。
6. E2E：POST `/api/agent-map/generate` → GET `/api/agent-map/reports`，逐模块核对 fields/unfilled/warnings；**条目对比按名称/时间匹配，不按索引**（51job 曾因同月两项目排序不同导致写错条目的假成功）。
7. 前端 tab 接入：枚举字段带 options 渲染下拉，自由文本字段不附加选项（避免误报「不在平台选项中」）。

## 八、测试与验收 SOP

- **修 bug 流程**（用户要求）：先写回归测试（红）→ 修到绿 → 跑全量 → 交人工验收。
- 后端：`cd backend && python -m pytest resume_editor/test_agent_mapper.py -q`（当前 88 passed，基线只升不降）。
- 前端：`cd frontend && ./node_modules/.bin/vitest run`（当前 120 passed）+ `tsc --noEmit`。
- **改后端代码必须 kill + 重启 `resume_server.py --port 8003`** 再 E2E，否则跑的是旧代码。
- **Radix Dialog 测试坑**：模态打开时背景整棵子树被 aria-hidden，`getByRole` 查不到背景元素（`getByText` 可以）；断言背景按钮前先点「取消」关闭弹窗。
- jsdom 中 `isTrusted=true` 的 click 可能来自程序化触发或 label 激活，神秘点击先查这两类。

## 九、原则备忘

- **映射 = 严格照抄拆分**：描述/公司名逐字保留主简历原文，禁止 LLM 重写或引入其他板块；润色需求走评估改写模块，不在映射环节做。
- **主简历未提供的字段也要出现在报告**（unfilled + `_ensure_unfilled_fields` 展示在字段列表，低置信+平台现有值/类型默认+note 说明沿用原因），对象字段展开子字段。
- **区分「字段不存在」❌ 与「字段存在但值为空」⬜**，不混为一谈。
- **数据可能已存在时先轻量拉取，仍无再调 LLM**，区分操作成本。
- Agent 做 80-90% + 人审报告，效率远高于逐字段手工编辑；但每条自动化承诺都要有确定性兜底。
