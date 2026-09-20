import { matchStandardModule } from "../resume-converter";
import type { ResumeData, ResumeSection, RewriteAnnotGroup, RewriteAnnotItem } from "@/types/resume"
import { parsePersonalInfo, type PersonalInfo } from "@/lib/personal-info-parser"
import { safeParseJSON } from "./json-parser"

export const DEFAULT_RESUME: ResumeData = {
  header: {
    name: "候选人",
    contact: "手机号 | 邮箱",
    intention: "求职意向：AI产品经理",
  },
  sections: [
    { id: "summary", title: "个人总结", content: "请在这里填写个人总结。" },
    { id: "skills", title: "专业技能", content: "请在这里填写专业技能。" },
    { id: "project", title: "项目经历", content: "请在这里填写项目经历。" },
    { id: "work", title: "工作经历", content: "请在这里填写工作经历。" },
    { id: "education", title: "教育背景", content: "请在这里填写教育背景。" },
  ],
}

export function parseAiRewriteAnnotations(jsonStr: string): {
  groups: RewriteAnnotGroup[]
  hasAny: boolean
} {
  const data = safeParseJSON(jsonStr)

  // 🚀 前端拦截解析：如果识别为纯 Markdown 字符串，执行正则定点提取
  if (typeof data === 'string') {
    const items: RewriteAnnotItem[] = [];

    // 1. 提取正文中所有散落的 Copilot 优化思路 ( > 💡 Copilot 优化思路：... )
    const rationaleRegex = /(?:\n|^)>\s*💡\s*Copilot\s*优化思路[：:]?\s*([^\n]+)/gi;
    let match;
    let rationaleCount = 1;
    while ((match = rationaleRegex.exec(data)) !== null) {
      if (match[1].trim()) {
        items.push({ subtitle: `优化点 ${rationaleCount++}`, rationale: match[1].trim() });
      }
    }

    // 2. 提取末尾的待办与补充清单
    const todoRegex = /(?:\n|^)#\s*待办与补充清单\s*\n([\s\S]*?)(?=(?:\n#\s)|$)/i;
    const todoMatch = data.match(todoRegex);
    if (todoMatch && todoMatch[1].trim()) {
      const cleanTodo = todoMatch[1].trim().replace(/^\s*[-*•]\s*/gm, '• ');
      items.push({ subtitle: "待办与数据补充", rationale: cleanTodo });
    }

    // 🌟 新增 3：提取顶部混合的 JSON 说明块
    const jsonBlockMatch = data.match(/(?:\n|^)\s*(\{[\s\S]*?\})\s*(?=\n#|\n##)/);
    if (jsonBlockMatch) {
      try {
        const parsedData = JSON.parse(jsonBlockMatch[1]);
        if (parsedData.missing_data_requests && Array.isArray(parsedData.missing_data_requests)) {
          parsedData.missing_data_requests.forEach((req: any) => {
            items.push({ subtitle: `📝 待补充 (${req.field})`, rationale: req.question });
          });
        }
        if (parsedData.rewrite_rationale) {
          Object.entries(parsedData.rewrite_rationale).forEach(([key, val]) => {
            items.push({ subtitle: `💡 改写思路 (${key})`, rationale: String(val) });
          });
        }
      } catch (e) {
        console.warn("解析前置JSON说明失败", e);
      }
    }

    // 🌟 新增 4：提取底部的重构说明
    const bottomNoteMatch = data.match(/(?:\n|^)(?:---|___)?\s*\n?\s*\**重构说明\**[：:]\s*([\s\S]*)$/i);
    if (bottomNoteMatch && bottomNoteMatch[1].trim()) {
      items.push({ subtitle: "📋 整体重构说明", rationale: bottomNoteMatch[1].trim() });
    }

    // 如果提取到了任何一条，就组装成指定的结构返回
    if (items.length > 0) {
      return {
        groups: [{
          section: "project",
          title: "AI 整体改写说明",
          items: items
        }],
        hasAny: true
      };
    }

    return { groups: [], hasAny: false };
  }


  if (!data || typeof data !== "object") {
    return { groups: [], hasAny: false }
  }

  const groups: RewriteAnnotGroup[] = []
  let hasAny = false

  // 🌟 新结构：projects 的 rewrite_rationale 在项目对象的顶层
  if (Array.isArray(data.projects)) {
    for (const p of data.projects) {
      if (!p || typeof p !== "object") continue
      const rec = p as Record<string, unknown>
      const titleRaw = rec.project_name
      const title = titleRaw != null && String(titleRaw).trim() ? String(titleRaw).trim() : "未命名项目"
      const items: RewriteAnnotItem[] = []

      // 🌟 直接从项目对象提取 rewrite_rationale
      const rat = rec.rewrite_rationale
      if (rat != null && String(rat).trim()) {
        hasAny = true
        items.push({ subtitle: "全局重构", rationale: String(rat).trim() })
      } else {
        // 兼容旧结构：从 star_a_actions 中提取
        const actions = rec.star_a_actions
        if (Array.isArray(actions)) {
          for (const act of actions) {
            if (!act || typeof act !== "object") continue
            const a = act as Record<string, unknown>
            const oldRat = a.rewrite_rationale
            if (oldRat == null || !String(oldRat).trim()) continue
            hasAny = true
            const sub = a.subtitle != null ? String(a.subtitle).trim() : ""
            items.push({ subtitle: sub, rationale: String(oldRat).trim() })
          }
        }
      }

      if (items.length > 0) {
        groups.push({ section: "project", title, items })
      }
    }
  }

  // 🌟 新结构：work_experience 的 rewrite_rationale 在工作对象的顶层
  if (Array.isArray(data.work_experience)) {
    for (const w of data.work_experience) {
      if (!w || typeof w !== "object") continue
      const rec = w as Record<string, unknown>
      const company = rec.company_name != null ? String(rec.company_name).trim() : rec.company != null ? String(rec.company).trim() : ""
      const title = company || "未命名公司"
      const items: RewriteAnnotItem[] = []

      // 🌟 直接从工作对象提取 rewrite_rationale
      const rat = rec.rewrite_rationale
      if (rat != null && String(rat).trim()) {
        hasAny = true
        items.push({ subtitle: "全局重构", rationale: String(rat).trim() })
      } else {
        // 兼容旧结构：从 actions 中提取
        const actions = rec.actions
        if (Array.isArray(actions)) {
          for (const act of actions) {
            if (!act || typeof act !== "object") continue
            const a = act as Record<string, unknown>
            const oldRat = a.rewrite_rationale
            if (oldRat == null || !String(oldRat).trim()) continue
            hasAny = true
            const sub = a.subtitle != null ? String(a.subtitle).trim() : ""
            items.push({ subtitle: sub, rationale: String(oldRat).trim() })
          }
        }
      }

      if (items.length > 0) {
        groups.push({ section: "work", title, items })
      }
    }
  }

  return { groups, hasAny }
}

export function transformJsonToResumeData(data: any): ResumeData {
  if (!data || typeof data !== "object") return DEFAULT_RESUME

  if (data.header && typeof data.header === "object" && Array.isArray(data.sections) && data.sections.length > 0) {
    const header = data.header
    const sections: ResumeSection[] = data.sections.map((s: any, index: number) => ({
      id: String(s?.id ?? `section-${index}`),
      title: String(s?.title ?? `模块${index + 1}`),
      content: String(s?.content ?? ""),
    }))
    return {
      header: {
        name: String(header.name ?? DEFAULT_RESUME.header.name),
        contact: String(header.contact ?? DEFAULT_RESUME.header.contact),
        intention: String(header.intention ?? DEFAULT_RESUME.header.intention),
      },
      sections,
    }
  }

  const pi = data.personal_info ?? {}
  const phone = String(pi.phone ?? pi.mobile ?? "").trim()
  const email = String(pi.email ?? "").trim()
  let contact = ""
  if (typeof pi.contact === "string" && pi.contact.trim()) {
    contact = pi.contact.trim()
  } else if (phone || email) {
    contact = [phone, email].filter(Boolean).join(" | ")
  } else {
    contact = DEFAULT_RESUME.header.contact
  }

  const header = {
    name: String(pi.name ?? DEFAULT_RESUME.header.name),
    contact,
    intention: DEFAULT_RESUME.header.intention,
  }

  const summaryContent = typeof data.summary === "string" ? data.summary : ""

  let skillsContent = ""
  if (Array.isArray(data.skills)) {
    const blocks: string[] = []
    for (const sk of data.skills) {
      const category = sk?.category != null ? String(sk.category).trim() : ""
      const descriptions = Array.isArray(sk?.descriptions) ? sk.descriptions : []
      const body = descriptions.map((d: any) => String(d ?? "").trim()).filter(Boolean).join("\n")

      if (category && body) {
        blocks.push(`**【${category}】**\n${body}`)
      } else if (category) {
        blocks.push(`**【${category}】**`)
      } else if (body) {
        blocks.push(body)
      }
    }
    skillsContent = blocks.join("\n\n")
  }

  let projectContent = ""
  if (Array.isArray(data.projects)) {
    const projectBlocks: string[] = []
    for (const p of data.projects) {
      const projectName = p?.project_name != null ? String(p.project_name).trim() : ""
      const role = p?.role != null ? String(p.role).trim() : ""
      const time = p?.time != null ? String(p.time).trim() : ""
      const headLine = [projectName, role, time].filter(Boolean).join(" · ")

      let text = headLine ? `**${headLine}**\n` : ""

      // 🌟 新结构：source_link
      const sourceLink = p?.source_link != null ? String(p.source_link).trim() : ""
      if (sourceLink) text += `${sourceLink}\n`

      // 🌟 新结构：tech_stack
      const techStack = p?.tech_stack != null ? String(p.tech_stack).trim() : ""
      if (techStack) text += `${techStack}\n`

      // 🌟 新结构：background
      const background = p?.background != null ? String(p.background).trim() : ""
      if (background) text += `${background}\n`

      // 🌟 新结构：implementation (包含 title 和 points 数组)
      if (p?.implementation && typeof p.implementation === "object") {
        const implTitle = p.implementation.title != null ? String(p.implementation.title).trim() : ""
        if (implTitle) text += `${implTitle}\n`

        if (Array.isArray(p.implementation.points)) {
          for (const point of p.implementation.points) {
            const pointText = String(point ?? "").trim()
            if (pointText) text += `${pointText}\n`
          }
        }
      }

      // 🌟 新结构：results
      const results = p?.results != null ? String(p.results).trim() : ""
      if (results) text += `${results}\n`

      // 兼容旧结构（如果新字段都不存在，尝试旧的 STAR 结构）
      if (!sourceLink && !techStack && !background && !p?.implementation && !results) {
        const bg = p?.star_s_background != null ? String(p.star_s_background).trim() : ""
        if (bg) text += `${bg}\n`

        const task = p?.star_t_task != null ? String(p.star_t_task).trim() : ""
        if (task) text += `${task}\n`

        if (Array.isArray(p?.star_a_actions)) {
          for (const act of p.star_a_actions) {
            const subtitle = act?.subtitle != null ? String(act.subtitle).trim() : ""
            const description = act?.description != null ? String(act.description).trim() : ""
            if (!subtitle && !description) continue

            if (subtitle && description) {
              text += `• **${subtitle}**：${description}\n`
            } else if (subtitle) {
              text += `• **${subtitle}**：\n`
            } else {
              text += `• ${description}\n`
            }
          }
        }

        const oldResults = p?.star_r_results != null ? String(p.star_r_results).trim() : ""
        if (oldResults) text += `${oldResults}\n`
      }

      if (text.trim()) projectBlocks.push(text.trim())
    }
    projectContent = projectBlocks.join("\n\n")
  }

  let workContent = ""
  if (Array.isArray(data.work_experience)) {
    const workBlocks: string[] = []
    for (const w of data.work_experience) {
      const company = w?.company_name != null ? String(w.company_name).trim() : w?.company != null ? String(w.company).trim() : ""
      const title = w?.title != null ? String(w.title).trim() : w?.position != null ? String(w.position).trim() : ""
      const time = w?.time != null ? String(w.time).trim() : ""
      const headLine = [company, title, time].filter(Boolean).join(" · ")

      let text = headLine ? `**${headLine}**\n` : ""

      // 🌟 新结构：experience_points 数组
      if (Array.isArray(w?.experience_points)) {
        for (const point of w.experience_points) {
          const pointText = String(point ?? "").trim()
          if (pointText) text += `${pointText}\n`
        }
      } else if (Array.isArray(w?.actions)) {
        // 兼容旧结构：actions 数组
        for (const a of w.actions) {
          const subtitle = a?.subtitle != null ? String(a.subtitle).trim() : ""
          const description = a?.description != null ? String(a.description).trim() : ""
          const result = a?.result != null ? String(a.result).trim() : ""

          if (subtitle || description) {
            if (subtitle && description) {
              text += `• **${subtitle}**：${description}\n`
            } else if (subtitle) {
              text += `• **${subtitle}**：\n`
            } else {
              text += `• ${description}\n`
            }
          }
          if (result) text += `${result}\n`
        }
      }

      if (text.trim()) workBlocks.push(text.trim())
    }
    workContent = workBlocks.join("\n\n")
  }

  let educationContent = ""
  if (Array.isArray(data.education)) {
    educationContent = data.education
      .map((e: any) => {
        const school = e?.school != null ? String(e.school) : ""
        const degree = e?.degree != null ? String(e.degree) : ""
        const time = e?.time != null ? String(e.time) : ""
        return [school, degree, time].filter(Boolean).join(" · ")
      })
      .filter(Boolean)
      .join("\n")
  }

  const sections: ResumeSection[] = [
    { id: "summary", title: "个人总结", content: summaryContent },
    { id: "skills", title: "专业技能", content: skillsContent },
    { id: "project", title: "项目经历", content: projectContent },
    { id: "work", title: "工作经历", content: workContent },
    { id: "education", title: "教育背景", content: educationContent },
  ]

  return { header, sections }
}

export function extractFeishuText(fieldData: any): string {
  if (!fieldData) return "";
  if (typeof fieldData === "string") return fieldData.trim();
  // 如果飞书传来的是富文本数组格式，提取其中的文本
  if (Array.isArray(fieldData)) {
    return fieldData.map(item => {
      if (typeof item === "string") return item;
      if (item.text) return item.text;
      if (item.text_run?.content) return item.text_run.content;
      return "";
    }).join("").trim();
  }
  return String(fieldData).trim();
}

export function parseResumeData(raw: string): ResumeData | null {
  if (!raw || typeof raw !== 'string' || raw.trim() === '') return null;

  let parsed: any = null;
  // 仅当字符串明显具有 JSON 特征时，才尝试严格解析
  if (raw.trim().startsWith('{') || raw.trim().startsWith('[')) {
    parsed = safeParseJSON(raw);
  }

  // =========================================================
  // 🌟 核心修复 1：拦截新版改写逻辑
  // 如果解析出了 JSON，并且包含大模型新生成的 "rewritten_resume" 字段
  // 直接把这个长文本抠出来，并把类型变回 string，强制走下方的 Markdown 切割流！
  // =========================================================
  if (parsed && typeof parsed === 'object' && typeof parsed.rewritten_resume === 'string') {
    parsed = parsed.rewritten_resume;
  }

  // 如果解析出来为空，或者是纯字符串（说明是 Markdown 文本），进入 Markdown 解析流
  if (!parsed || typeof parsed === 'string') {
    let pureMarkdown = typeof parsed === 'string' ? parsed : raw;

    // =========================================================
    // 🌟 核心修复 2：彻底消灭字面上的 \n
    // 将所有可能的字面转义符（如 \n 或 \\n）强制替换为 JavaScript 内存里的真换行符
    // 这样渲染在 Textarea 时就会是真正的回车换行！
    // =========================================================
    pureMarkdown = pureMarkdown.replace(/\\n/g, '\n');

    // 清理大模型多余的思考与标记（保留你原有的 7 个核心拦截逻辑）
    const todoIndex = pureMarkdown.search(/(?:\n|^)#\s*待办与补充清单/i);
    if (todoIndex !== -1) pureMarkdown = pureMarkdown.slice(0, todoIndex);
    pureMarkdown = pureMarkdown.replace(/(?:\n|^)>\s*💡\s*Copilot\s*优化思路[^\n]*/gi, '');
    const oldAnnotationRegex = /(?:\n|^)(?:---*\s*\n)?(?:#+\s*)?(?:\*\*|__)?(?:改写说明|修改说明|修改理由|简历改写与对标批注)(?:\*\*|__)?(?:：|:)?\s*\n/i;
    const matchIndex = pureMarkdown.search(oldAnnotationRegex);
    if (matchIndex !== -1) pureMarkdown = pureMarkdown.slice(0, matchIndex);
    pureMarkdown = pureMarkdown.replace(/(?:\n|^)#\s*简历重构方案\s*\n/gi, '\n');
    pureMarkdown = pureMarkdown.replace(/(?:\n|^)\s*\{[\s\S]*?"rewrite_rationale"[\s\S]*?\}\s*(?=\n#|\n##|$)/g, '\n');
    pureMarkdown = pureMarkdown.replace(/(?:\n|^)(?:---|___)?\s*\n?\s*\**重构说明\**[：:][\s\S]*$/i, '\n');
    // \s+ 必须有空白：否则会误把 ### 三级条目降级成 #，破坏「模块/条目」层级
    pureMarkdown = pureMarkdown.replace(/(?:\n|^)##\s+#\s*/g, '\n# ');
    
    // 🌟 提取并解析个人信息模块
    let extractedParsedInfo: PersonalInfo | undefined = undefined;
    const personalInfoMatch = pureMarkdown.match(/(?:^|\n)#\s*个人信息\s*\n([\s\S]*?)(?=\n#\s|\Z)/);
    if (personalInfoMatch) {
      extractedParsedInfo = parsePersonalInfo(personalInfoMatch[0]);
      // 从 markdown 中移除该模块
      pureMarkdown = pureMarkdown.replace(personalInfoMatch[0], '\n');
    }

    pureMarkdown = pureMarkdown.replace(/\n{3,}/g, '\n\n').trim();

    const lines = pureMarkdown.split('\n');
    const sections: ResumeSection[] = [];
    let currentTitle = "";
    let currentContent: string[] = [];

    let currentLevel: 1 | 2 = 1;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const match1 = line.match(/^#([^#].*)$/);
      const match2 = line.match(/^##([^#].*)$/);
      const match3 = line.match(/^###([^#].*)$/);

      if (match1 || match2 || match3) {
        if (currentTitle || currentContent.join('').trim()) {
          const cleanContent = currentContent.join('\n').replace(/^(\*{3,4}|-{3,4})\s*\n?/gm, '').trim();
          sections.push({
            id: `md-section-${sections.length}-${Date.now() + i}`,
            title: currentTitle || "未命名模块",
            content: cleanContent,
            level: currentLevel
          });
        }
        currentTitle = (match1 ? match1[1] : match2 ? match2[1] : match3 ? match3[1] : "").trim();
        currentLevel = match1 ? 1 : 2; // ## 与 ### 先记为 2，由下方提升逻辑归位模块头
        currentContent = [];
      } else {
        const trimmed = line.trim();
        if (trimmed !== '****' && trimmed !== '---' && trimmed !== '***' && trimmed !== '----------------') {
          currentContent.push(line);
        }
      }
    }
    if (currentTitle || currentContent.join('').trim()) {
      const cleanContent = currentContent.join('\n').replace(/^(\*{3,4}|-{3,4})\s*\n?/gm, '').trim();
      sections.push({
        id: `md-section-${sections.length}-${Date.now() + 999}`,
        title: currentTitle || "导入内容",
        content: cleanContent,
        level: currentLevel
      });
    }
    
    // 🌟 新版 Skill 兼容：整份简历只用 ## 模块头 + ### 条目（没有 # 一级标题）时，
    // 按标准模块关键词把模块头提升为 level 1、条目保持 level 2，
    // 使 resumeDataToResumeDataV2 的「父模块→条目」归档逻辑正常工作
    if (sections.length > 0 && !sections.some(s => s.level === 1)) {
      for (const s of sections) {
        s.level = matchStandardModule(s.title) ? 1 : 2;
      }
    }

    // 组装并格式化 Header
    const finalHeader = { ...DEFAULT_RESUME.header };
    if (extractedParsedInfo) {
      finalHeader.parsedInfo = extractedParsedInfo;
      // 第一行：姓名
      finalHeader.name = extractedParsedInfo.name || "候选人";
      
      // 第二行：手机号 | 邮箱
      const formatPhone = (p: string) => p.replace(/[^\d]/g, '').replace(/^(\d{3})(\d{4})(\d{4})$/, '$1-$2-$3') || p;
      const phoneField = extractedParsedInfo.fields.find(f => f.label.includes('手机') || f.label.includes('电话'));
      const emailField = extractedParsedInfo.fields.find(f => f.label.includes('邮箱'));
      const contacts = [];
      if (phoneField && phoneField.value) contacts.push(formatPhone(phoneField.value));
      if (emailField && emailField.value) contacts.push(emailField.value);
      if (contacts.length > 0) {
        finalHeader.contact = contacts.join(' | ');
      }
      
      // 第三行：其他字段
      const otherFields = extractedParsedInfo.fields.filter(f => !f.label.includes('手机') && !f.label.includes('电话') && !f.label.includes('邮箱'));
      const extraStrs = otherFields.map(f => `${f.label}：${f.value}`);
      const jobTitleStr = extractedParsedInfo.jobTitle ? `求职意向：${extractedParsedInfo.jobTitle}` : "求职意向：";
      finalHeader.intention = [jobTitleStr, ...extraStrs].join(' | ');
    }

    return {
      ...DEFAULT_RESUME,
      header: finalHeader,
      sections: sections
    };
  }

  // 对于没有 rewritten_resume 的老 JSON，继续走老逻辑兜底
  return transformJsonToResumeData(parsed);
}
