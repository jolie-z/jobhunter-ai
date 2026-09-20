好的，我已经通过三个 Explore agent 完成了深度调查。让我为你整理一份完整的沉浸工作台-简历编辑区全链路分析报告：

---

## 📊 沉浸工作台-简历编辑区 全链路深度分析报告

### 一、系统架构概览

沉浸工作台存在**两套编辑器并存**的设计：

| 编辑器 | 数据模型 | UI 形态 | 使用场景 |
|---|---|---|---|
| `LegacyRawResumeEditor` | `ResumeData`（Markdown 结构） | 原始 Markdown 编辑画布 | 无多 Agent 数据时 |
| `ResumeCanvasColumn` | `ResumeModule[]`（双栏对比） | 左右 Diff 对比面板 | 有多 Agent 改写数据时 |

---

### 二、简历改写全链路

#### 2.1 核心文件清单

**前端核心：**
- `frontend/components/dashboard/features/legacy-raw-resume-editor.tsx` - 旧版编辑器
- `frontend/components/dashboard/resume-canvas/resume-canvas-column.tsx` - 新版编辑器
- `frontend/components/dashboard/job-detail-workspace.tsx` - 工作台主容器
- `frontend/lib/resume-converter.ts` - 格式转换工具

**后端核心：**
- `backend/app/jobs/router.py` - API 路由
- `backend/app/jobs/action_service.py` - 业务逻辑
- `backend/multi_agent_workflow/agent_workflow.py` - 四 Agent 流水线

#### 2.2 多 Agent 深度改写流程

```
前端触发 handleMultiAgentRewrite()
    ↓
组装 Markdown 全文（从 sections/modules）
    ↓
POST /api/agents/deep-rewrite
    {job_id, original_resume(Markdown), jd_text, diagnosis_report}
    ↓
后端返回 task_id，启动异步流水线
    ↓
前端通过 SSE 监听实时日志
    ↓
四 Agent LangGraph 流水线：
  Agent 1 (Retriever) - 粗筛打捞：解析+评分+截断
  Agent 2 (Rewriter) - 首席重构：STAR法则改写
  Agent 3 (Surgeon) - ATS微创：关键词注入（当前已断开）
  Agent 4 (Formatter) - 排版大师：输出纯 Markdown
    ↓
final_markdown 写入飞书"多Agent改写简历"字段
    ↓
SSE 推送 done 事件，携带 job_updates
    ↓
前端热刷新，自动切换到 ResumeCanvasColumn 视图
```

#### 2.3 单工具改写（Grill/ATS/Prune 等）

各工具组件独立调用后端 API：

| 工具 | API 端点 | 数据格式 |
|---|---|---|
| `AtsAligner` | `/api/strategy/ats_align` | Markdown 文本 |
| `ExperienceGriller` | `/api/strategy/grill_experience` | Markdown 文本 |
| `ProjectPruner` | `/api/strategy/filter_projects` | Markdown 文本 |
| `WorkCompressor` | `/api/strategy/compress_work_experience` | Markdown 文本 |
| `InitialDraftReviewer` | `/api/strategy/initial_draft` | Markdown 文本 |
| `AiModuleSyncInline` | `/api/strategy/sync_basic_module` | Markdown 文本 |

---

### 三、PDF 预览全链路

#### 3.1 核心结论

**沉浸工作台的"PDF 预览"是 HTML/CSS 模拟的 A4 纸张排版预览**，不是真正的 PDF 文件预览。

#### 3.2 涉及文件

- `frontend/components/dashboard/features/v2-resume-editor.tsx` - 预览入口
- `frontend/components/resume-print/resume-classic-markdown.tsx` - 预览组件
- `frontend/components/shared/md-preview.tsx` - 行内预览

#### 3.3 预览流程

```
用户点击"纸张排版预览"按钮
    ↓
设置 isPreviewOpen = true
    ↓
渲染 Dialog 弹窗（840px × 90vh）
    ↓
使用 ResumeClassicMarkdown 组件
    ↓
数据来源：resumeData（ResumeData 类型）
    ↓
通过 ReactMarkdown 渲染 Markdown 内容
    ↓
模拟 A4 纸张（794px × 1123px）
```

#### 3.4 与配置大盘的差异

| 特性 | 沉浸工作台 | 配置大盘 |
|---|---|---|
| **预览组件** | `ResumeClassicMarkdown` | `ResumeClassic` |
| **数据类型** | `ResumeData`（Markdown 结构） | `ResumeDataV2`（JSON 结构） |
| **渲染方式** | `ReactMarkdown` 渲染 | 直接渲染结构化字段 |
| **数据来源** | 实时从编辑器获取 | 从飞书 API 获取 |

---

### 四、PDF/图片保存全链路

#### 4.1 核心发现

**PDF 和图片保存使用的是 JSON 格式**，不是 Markdown！

#### 4.2 涉及文件

**前端：**
- `frontend/components/dashboard/features/v2-resume-editor.tsx` - `handleExportWithSave`
- `frontend/components/dashboard/job-detail-workspace.tsx` - `handleExport`
- `frontend/app/print/job-resume/page.tsx` - Playwright 渲染页面

**后端：**
- `backend/app/jobs/router.py` - `export_resume`
- `backend/app/services/export_service.py` - `process_dynamic_export`
- `backend/app/core/pdf_renderer.py` - Playwright 渲染

#### 4.3 PDF 保存流程（Playwright 高保真渲染）

```
用户点击"导出 PDF"
    ↓
handleExportWithSave("pdf")
    ↓
① 先调用 handleSaveResume(true) 静默保存到飞书
    POST /api/save_manual_resume
    {job_id, resume_text(Markdown), structured_json(JSON)}
    ↓
② 调用 onExport("pdf")
    ↓
handleExportWithTemplate("pdf")
    ↓
③ GET /api/templates 获取模板列表（可选）
    ↓
handleExport("pdf", templateName?)
    ↓
④ POST /export_resume
    {job_id, export_type:"pdf", resume_data(JSON), template_name}
    ↓
后端 export_service.py:
    ↓
⑤ 拼接 URL: /print/job-resume?job_id={job_id}
    ↓
⑥ Playwright 渲染：
    - 启动无头 Chromium
    - 访问前端 SSR 页面
    - 等待 .resume-print 元素
    - page.pdf(format="A4")
    ↓
⑦ 上传 PDF 到飞书云空间
    ↓
⑧ 回写飞书记录"PDF备份"字段
```

#### 4.4 图片保存流程（模板渲染）

```
用户点击"导出图片"
    ↓
handleExportWithSave("image")
    ↓
注意：图片导出不强制先保存！
    ↓
handleExport("image")
    ↓
POST /export_resume
    {job_id, export_type:"image", resume_data(JSON)}
    ↓
后端 export_service.py:
    ↓
① DocxTemplate 渲染 .docx
    ↓
② docx2pdf.convert() 转 PDF
    ↓
③ pdf2image.convert_from_path() 切图（300dpi）
    ↓
④ 每页生成 JPEG 文件
    ↓
⑤ 并发上传所有图片到飞书
    ↓
⑥ 回写飞书记录"图片保存"字段
```

#### 4.5 数据格式转换全过程

```
前端内存 ResumeData (JS对象)
    |
    |-- [导出PDF/图片/Word] --> 直接作为 JSON 传给后端 resume_data 字段
    |                             |
    |                             v
    |                         后端 context 组装：
    |                           header.name / contact / intention
    |                           sections[].title / content_raw
    |                             |
    |                             |-- [PDF分支] --> Playwright 渲染
    |                             |     前端 /print/job-resume 页面：
    |                             |       1. 从飞书拉取 manualRefinedResume (Markdown)
    |                             |       2. markdownToResumeData() -> ResumeData
    |                             |       3. ResumeClassicMarkdown 组件渲染 HTML
    |                             |       4. Playwright page.pdf() -> PDF字节
    |                             |
    |                             |-- [Word分支] --> DocxTemplate.render(context)
    |                             |                  -> .docx 文件
    |                             |
    |                             |-- [图片分支] --> .docx -> .pdf -> pdf2image -> .jpg
    |
    |-- [保存到飞书] --> resumeDataToMarkdown() -> Markdown字符串 -> resume_text 字段
    |                    resumeDataToStructuredJson() -> JSON对象 -> structured_json 字段
```

---

### 五、关键差异对比

| 维度 | 沉浸工作台 | 配置大盘 |
|---|---|---|
| **编辑器** | `LegacyRawResumeEditor` / `ResumeCanvasColumn` | `ResumeBuilder`（V2 卡片式） |
| **数据模型** | `ResumeData`（Markdown 结构） | `ResumeDataV2`（JSON 结构） |
| **预览组件** | `ResumeClassicMarkdown` | `ResumeClassic` |
| **预览数据源** | 实时从编辑器获取 | 从飞书 API 获取 |
| **导出 API** | `/export_resume` | `/api/strategy/resume-pdf` |
| **导出数据格式** | JSON（`resume_data`） | `record_id`（从飞书拉取） |
| **PDF 渲染** | Playwright（高保真） | Playwright（高保真） |
| **图片渲染** | 模板渲染（docx2pdf） | Playwright + PyMuPDF |
| **保存 API** | `/api/save_manual_resume` | `/api/strategy/save` |

---

### 六、迁移方案关键点

基于以上分析，如果要将配置大盘的逻辑迁移到沉浸工作台，需要注意：

1. **数据格式统一**：配置大盘使用 `ResumeDataV2`（JSON），沉浸工作台使用 `ResumeData`（Markdown 结构）
2. **预览组件复用**：可以复用 `ResumeClassic` 组件，但需要数据格式转换
3. **导出 API 统一**：两个区域使用不同的 API 端点
4. **保存逻辑统一**：需要统一保存到飞书的数据格式

需要我进一步分析具体的迁移方案吗？