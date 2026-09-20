# BOSS直聘 官网在线简历回写 经验总结

> 适用：把本地 `{platform}_fields.json`（汇总新映射后的本地草稿）自动回写到平台官网在线简历。
> BOSS 已跑通全流程（2026-08-04：首轮 16/16 全模块成功；次轮「本地为准全量覆盖」13 动作全成功 + 复核全过 + 重新采集一致性验证）。其他平台（猎聘/51job/智联）复用本方法论。

## 一、总体策略：拦截真实 token + 页面内 fetch 回放

不逐字段点 UI（慢且脆弱），而是复用官网自己的保存 API：

1. DrissionPage 连接已登录浏览器（BOSS 端口 19222）
2. 监听页面自身的 `geek/preview/data.json` 请求，捕获**新鲜的双 token** 与官网当前数据
3. 在页面上下文内用 `fetch()` 回放各模块保存 API（自动携带浏览器 cookie）
4. 回写后重新拉 preview 复核（对比关键字段）

### Token 机制（BOSS 特有，最重要的一课）

- BOSS wapi 请求需要两个头：`zp_token` 与 `token`
- 免头 fetch → `code=121`；过期 zp_token → `code=122`；新鲜 zp_token → 通过
- `zp_token` **每次页面加载都会刷新**，不能缓存复用旧的
- `token`（如 `EhGsARRInqbEzc8`）会话级稳定
- **策略**：回写启动时先监听 `preview/data.json` 请求头拿新鲜双 token，之后所有 fetch 复用；遇 121/122 自动重新监听刷新一次重试

### 请求格式

- POST body：`application/x-www-form-urlencoded`（URLSearchParams 构造）
- 必带头：`zp_token`、`token`、`X-Requested-With: XMLHttpRequest`
- 在页面上下文 fetch（自动带 cookie），不要脱离页面用 curl

## 二、各模块保存 API 与报文（全部实机验证 code=0）

| 模块 | 端点 | 关键 payload |
|------|------|-------------|
| 个人优势 | `/wapi/zpgeek/resume/userdesc/save.json` | `advantage=<text>` |
| 工作经历 | `/wapi/zpgeek/resume/workexp/save.json` | `id,position,customPositionName,companyName,industryCode,industryName,emphasis,department,startDate(YYYY-MM),endDate(''=至今),workContent,workPerformance,isPublic,workType,entrance=1,industrySource=-1,riskTipType=1` |
| 项目经历 | `/wapi/zpgeek/resume/projectexp/save.json` | `id,name,roleName,description,url,performance,startDate,endDate,entrance=1,riskTipType=1` |
| 证书 | `/wapi/zpgeek/resume/certification/save.json` | `certJson=[{"name":"...","type":0}]`（JSON 字符串） |
| 驻外 | `/wapi/zpgeek/overseastraitoptions/collectinformation/save.json` | `duration=<code>&country=<codes逗号>&language=<codes>&showStatus=<0/1>` |
| 期望职位-更新 | `/wapi/zpgeek/resume/expect/save.json` | `positionType,position(职位码),lowSalary,highSalary,industryCodes,location,subLocation,locationName,id,freshGraduate,fullUpdate=false,otherPositionCodeStr,otherLocationCodeStr` |
| 期望职位-新增 | `/wapi/zpgeek/resume/expect/save.json` | 同上但**不带 id** → 新增（返回新 encryptId）；⚠️ 已删除条目的旧 id 复用会报 `code=200210`「期望不存在，可能已被删除」 |
| 期望职位-删除 | `/wapi/zpgeek/resume/expect/delete.json` | `id=<encryptId>` → code=0；⚠️ `fullUpdate=true` **不会**删除多余条目（实测无效），删除必须走此端点 |
| 教育经历 | `/wapi/zpgeek/resume/eduexp/save.json` | `school,schoolId,degree(码),major,eduType,startDate(年份),endDate(年份),eduDescription,thesisTitle,thesisDesc,id,majorRanking,course,entrance=1,riskTipType=1` |
| 基础信息 | `/wapi/zpgeek/resume/baseinfo/save.json` | `name,birthday(YYYY-MM),gender(0/1),nameShowType,startWorkDate(YYYY-MM),applyStatus(0-3),freshGraduate` |

### 码表（运行时从 API 拉取，勿硬编码）

- 国家：`/wapi/zpgeek/overseastraitoptions/country/config/query.json` → `zpData.configList`（树形）
- 语言：`/wapi/zpgeek/overseastraitoptions/language/config/query.json` → `zpData.configList`
- 行业：`/wapi/zpCommon/data/industry.json` → `zpData`（树形）
- 城市：`/wapi/zpCommon/data/city.json` → `zpData.cityList`（树形，含 subLevelModelList）
- 职位：`/wapi/zpgeek/common/data/expectposition.json?cityCode=<城市码>&version=1` → `zpData.config`（树形，子 key 为 **subLevelModelList**，约 990 个职位；映射例：机器学习→101301、AI产品经理→110110、数据分析师→100511、项目专员/助理→100603、项目经理/主管→100601）
- 驻外时长：**无配置 API**（404），需实机标定 hidden input。标定值：
  `偶尔出差:11, 频繁出差:12, 1个月内:10, 1~3个月:1, 3~6个月:2, 6~12个月:3, 1年:4, 2年:5, 3年:6, 4年:7, 5年以上:8, 长期驻外:9`

### 官网数据键名（preview/data.json，采集与回写共用）

- 期望列表：`expectList`（兼职=独立条目 `positionType:1`，全职 `positionType:0`；`positionName` 是职位中文名）
- 教育列表：**`educationExpList`**（不是 eduExpList！）；`startYear/endYear` 是字符串年份
- 基础信息：`baseInfo`（`birthday` 为 8 位字符串 `19961101`、`startWorkDate` 为 int `20190701`——保存报文统一 YYYY-MM，须 `_to_ym` 归一化）
- 项目业绩键：`performance`（采集端曾误读 `achievement` 导致业绩丢失，见第七节）

## 三、回写范围与安全防线（按勾选全量回写）

前端把**勾选的字段**（`paths`）传给后端，勾选什么就回写什么——certificates / expectations / education / baseinfo 均支持回写，确认文案动态显示勾选模块，未勾选任何字段时禁止回写。

### ⛔ HARD_SKIP：账号级/覆盖类风险字段，勾选了也强制排除

- **name**：官网显示脱敏昵称（如"张女士"），回写真实姓名触发**改名审核**
- **phone / email / wechat**：本地采集的是脱敏值，回写会覆盖真实联系方式
- **experience_years**：无保存 API

### ⚠️ 全量覆盖语义（2026-08-04 起：本地为准，删多余/补缺失）

- **certificates**：`certJson` 为**全量覆盖**语义。本地非空且与官网不同 → 覆盖（官网多出的证书会被删除，如 5→3）；与官网一致 → skip「与官网一致，无需回写」；本地为空 → skip。**不再有子集保护**（历史教训：子集保护会导致本地删掉的证书永远删不掉）
- **expectations**：三态回写（见第四节）——匹配对更新 / 本地未匹配**新增** / 官网未匹配**删除**。**不再保留官网多余条目**

### 模块级跳过（非风险，属于"无变化不动作"）

- **baseinfo**：与官网逐字段对比，**与官网一致则跳过**（`_baseinfo_unchanged`）；`None/''` 与 `0` 视为相等（int 比较），避免空官方 baseInfo 导致误写
- **expectations / education / work / projects**：本地为空或**无可匹配条目**时 skip（附原因），不产生空写动作

### 字段级保留策略（工作经历/项目）

- **保留官网的**：`id`、`position`（职位码，码体系字段不碰）、`customPositionName`、`emphasis`、`isPublic`、`workType`
- **写入本地的**：公司/部门/日期/内容/业绩/行业
- 行业名→码映射失败时**沿用官网原行业**（不置空）

## 四、条目匹配策略（踩坑后的最终方案）

- **工作经历**：按起始年月匹配；条数相等时剩余条目**按序兜底配对**
- **项目经历**：条数相等时**直接按序配对**（回写覆盖全部内容字段 + 保留官网 id，任何双射的最终态都 = 本地数据）；条数不等才走 url → 起始年月匹配
- **求职期望**（**全量覆盖三态**，`match_expect_items`）：
  - 兼职（本地 jobType=parttime）：`positions` 逐个按**职位名**匹配官网兼职条目（positionType:1）
  - 全职：按 `positionName` 匹配官网全职条目（positionType:0）
  - **匹配对 → 更新**：save.json 带官网 id（保留官网条目 id，全职 `position` 码沿用官网）
  - **本地未匹配 → 新增**：save.json **不带 id**；兼职用职位名查 expectposition.json 映射码，全职用本地 `position` 查码；location 用 city_tree 映射本地 city，`positionType` 按 jobType
  - **官网未匹配 → 删除**：`expect/delete.json` + `id=<encryptId>`
  - 兼职组在官网 UI 上合并为 1 个显示条目（3 兼职 = 1 组），但数据上是独立条目，删除走 API 不走 UI（JS click 对组删除链接无效，且页面常驻「上传附件简历」弹窗的「确定」按钮易误点）
- **教育经历**：条数相等**按序配对**；不等时按**学校名 + 起始年份**匹配；`degree` 码映射失败沿用官方码
- 教训：中文改写后 token 重叠度低 + 日期歧义（多条同年月），靠内容相似度匹配会错配；按序配对最确定

## 五、复核（verify）必须覆盖全字段

回写后重新拉 preview，逐模块对比。**教训**：首轮 verify 只比了项目描述没比业绩，导致采集端丢业绩的 bug 没被 verify 拦下。现已补上 `performance` 对比。

期望三态 verify（`verify_results` 判断顺序：先判 `"delete" in endpoint`）：
- **删除**：payload 的 `id` 不再出现在新 expectList 中 → 已生效
- **更新**：`id` 存在且低薪/高薪/职位码一致 → 已生效
- **新增**：`position` 码 + `positionType` 同时出现在新 expectList → 已出现

## 六、前端交互

- 「同步回 BOSS直聘官网」按钮在 BOSS 平台底部操作栏，紫色，**两步确认**（点→紫色确认栏→确认回写）
- **勾选联动**：确认文案动态显示勾选模块（`将勾选模块（个人优势 / 工作经历 / 项目经历 / …）的本地数据回写覆盖 BOSS直聘官网在线简历，确认？`）；**未勾选任何字段时点击按钮直接拦截**（就地提示"请先勾选要回写的字段"），不发请求
- 回写中 loading，成功/失败在按钮下方就地淡入提示（5s 淡出），不用全局 toast
- 后端端点：`POST /api/agent-map/write-back`（body 带 `paths`，subprocess 调 `boss_write_back.py --json --paths ...`，timeout 300s，解析 `RESULT_JSON:` 标记行）

## 七、一个采集端 bug（本轮回写复核时发现并修复）

- 项目业绩在 preview 中的键是 **`performance`**，collector 误读 `p.get("achievement")`（不存在的键）→ 业绩永远空串
- 修复：抽出纯函数 `extract_project_items(zp)`，改读 `performance`；补回归测试 `test_boss_collector.py`
- 教训：**采集与回写的字段键必须对齐**；写回后"采集→diff 本地"是最有效的端到端验证

## 八、复用清单（迁移到其他平台时）

1. 用 DrissionPage 连接该平台已登录浏览器（端口见 PLATFORM_PORTS）
2. 探测该平台在线简历的数据接口 + 保存接口（监听 XHR / 找前端框架 store）
3. 摸清鉴权机制（cookie / token / 签名），确定能否在页面上下文 fetch 回放
4. 逐模块标定保存报文 + 码表（优先运行时拉取）
5. 定义回写范围 + 跳过防线（账号级字段、全量覆盖语义、码体系字段）
6. 条目匹配 + 字段保留策略
7. 回写后采集复核一致性

## 关键文件

- 回写核心：`backend/resume_editor/platforms/boss_write_back.py`（纯函数可测 + 浏览器编排分离，CLI `--dry-run`/`--json`/`--paths`）
- 端点：`backend/resume_server.py` `POST /api/agent-map/write-back`
- 前端：`frontend/app/resume-editor/agent-tab.tsx` `handleWriteBack`
- 测试：`test_boss_write_back.py`（61 例）、`test_boss_collector.py`（2 例）、`agent-tab.test.tsx`（7 例回写按钮）
