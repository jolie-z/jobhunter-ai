好的，我已经完整扒清了整个链路。以下是详细的架构梳理：

---

## 📋 配置大盘 → 简历库 → 简历改写 → PDF预览 → PDF保存/图片保存 全链路

### 🗂️ 核心文件清单

| 层级 | 文件 | 职责 |
|---|---|---|
| **页面入口** | `frontend/components/dashboard/resume-builder/index.tsx` | 简历库主页面，包含所有操作按钮 |
| **全局状态** | `frontend/hooks/use-strategy-store.tsx` | 简历数据 CRUD + 飞书同步 |
| **V2 数据 Store** | `frontend/hooks/use-resume-v2-store.tsx` | 结构化 JSON 简历数据 |
| **预览组件** | `frontend/components/resume-print/resume-classic.tsx` | A4 纸排版渲染（前端预览 & PDF 共用） |
| **打印页面** | `frontend/app/print/resume/page.tsx` | 无头浏览器访问的 SSR 页面 |
| **PDF 渲染器** | `backend/app/core/pdf_renderer.py` | Playwright 无头 Chromium 生成 PDF |
| **后端路由** | `backend/app/strategy/router.py` | `/resume-pdf` 和 `/resume-images` 接口 |
| **飞书上传** | `backend/common/feishu_api.py` | 文件上传 + 附件回写 |
| **类型定义** | `frontend/types/resume.ts` | `ResumeDataV2` 结构化 JSON 类型 |

---

### 🔗 完整数据流

```
┌─────────────────────────────────────────────────────────┐
│  1. 简历改写（配置大盘-简历库）                              │
│     resume-builder/index.tsx                             │
│     ┌───────────────────────────────────┐                │
│     │  useResumeV2Store (JSON 结构化)    │                │
│     │  personalInfo / workExperience /  │                │
│     │  education / projects / summary   │                │
│     └───────────┬───────────────────────┘                │
│                 │                                        │
│     ┌───────────▼───────────────────────┐                │
│     │  各卡片组件编辑（Markdown 编辑器）   │                │
│     │  MarkdownEditor / ExperienceList  │                │
│     └───────────┬───────────────────────┘                │
│                 │ handleSave()                           │
│                 ▼                                        │
│     POST /api/strategy/save                              │
│     { 简历版本, 简历内容(MD), 个人信息(MD),                  │
│       结构化数据(JSON), 当前状态 }                          │
│                 │                                        │
│                 ▼                                        │
│     飞书多维表格「简历库」                                  │
│     字段: 简历内容 / 个人信息 / 结构化数据                    │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  2. PDF 预览（前端 Dialog 弹窗）                           │
│     resume-builder/index.tsx :305-329                    │
│                                                         │
│     <Dialog> → <ResumeClassic data={resumeData} />       │
│     ① 直接用 useResumeV2Store 的 JSON 数据               │
│     ② ResumeClassic 接收 ResumeDataV2 渲染               │
│     ③ 固定 A4 尺寸 (794px × 1123px)                      │
│     ④ CSS: resume-print / classic.module.css             │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  3. 保存 PDF（后端 Playwright 渲染）                      │
│     resume-builder/index.tsx :58-81                      │
│                                                         │
│  前端:                                                   │
│    ① await handleSave()  ← 先强制同步最新数据到飞书       │
│    ② POST /api/strategy/resume-pdf                       │
│       { record_id, page_size: "A4" }                     │
│                                                         │
│  后端 router.py :594-622:                                │
│    ③ 拼 URL: /print/resume?record_id=xxx                │
│    ④ render_resume_pdf(url)                              │
│                                                         │
│  pdf_renderer.py:                                        │
│    ⑤ Playwright 启动无头 Chromium                        │
│    ⑥ 访问 frontend SSR 页面                              │
│    ⑦ 等待 .resume-print 元素 + 字体加载                   │
│    ⑧ page.pdf(format="A4") → PDF bytes                  │
│                                                         │
│  router.py 继续:                                         │
│    ⑨ upload_file_to_feishu(pdf_bytes) → file_token      │
│    ⑩ update_feishu_resume_attachment(record_id, token)  │
│       回写飞书「简历附件」字段                              │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  4. 保存图片（PDF → PNG 切片）                            │
│     resume-builder/index.tsx :86-109                     │
│                                                         │
│  前端:                                                   │
│    ① await handleSave()  ← 先同步                       │
│    ② POST /api/strategy/resume-images                    │
│       { record_id, page_size: "A4" }                     │
│                                                         │
│  后端 router.py :624-663:                                │
│    ③ 同样走 Playwright 生成 PDF bytes                    │
│    ④ fitz.open(pdf_bytes)  ← PyMuPDF                    │
│    ⑤ 逐页 page.get_pixmap(dpi=300) → PNG bytes          │
│    ⑥ 每页 upload_file_to_feishu(png_bytes) → token      │
│    ⑦ update_feishu_resume_images(record_id, tokens[])   │
│       回写飞书「简历图片」字段                              │
└─────────────────────────────────────────────────────────┘
```

---

### 🔑 关键设计要点

**1. 数据格式：前端编辑用 JSON，存储/传输混用 Markdown + JSON**

- `useResumeV2Store` 维护的是 `ResumeDataV2`（纯 JSON 结构化对象）
- `handleSave` 时同时保存两种格式到飞书：
  - `简历内容` 字段 = Markdown 文本（由 `serializeBlocksToMarkdown` 生成）
  - `结构化数据` 字段 = JSON 字符串（由 `resumeDataToStructuredJson` 生成）

**2. PDF 渲染原理：后端不自己拼 HTML，而是用 Playwright 访问前端页面**

- `pdf_renderer.py` 启动无头 Chromium → 访问 `http://localhost:3000/print/resume?record_id=xxx`
- `print/resume/page.tsx` 是一个 SSR 页面，从后端 API 拉取 JSON 数据 → 用 `ResumeClassic` 组件渲染
- Playwright 等待 `.resume-print` 元素渲染完成后调用 `page.pdf()`
- 这样保证 PDF 和前端预览完全一致（所见即所得）

**3. 保存前强制同步**

- `handleSavePdf` 和 `handleSaveImages` 都会在调用 API 前先执行 `await handleSave()`
- 确保飞书上的数据是最新版本，后端 Playwright 渲染时拿到的才是最新排版