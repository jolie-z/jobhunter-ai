import type { ResumeDataV2 } from "@/types/resume"

/**
 * 描述字段统一转行数组：数据经飞书/AI 改写回流后 description 可能退化为字符串
 * （全局排版保型逻辑会保持字符串形态），直接 .join 会 TypeError 崩面板，此处兜底
 */
export function asLines(desc: unknown): string[] {
  if (Array.isArray(desc)) return desc.filter(x => typeof x === "string") as string[]
  if (typeof desc === "string") return desc ? desc.split("\n") : []
  return []
}

/**
 * L1 本地即时规则排版：中英文空格规范化、破折号统一、去列表末尾句号
 * 纯字符串变换，耗时 < 1ms
 */
export function formatMarkdownPangu(content: string): string {
  if (!content) return ""

  // 1. 中英文与数字混排加空格（盘古排版规则）
  let res = content
    .replace(/([\u4e00-\u9fa5])([a-zA-Z0-9])/g, "$1 $2")
    .replace(/([a-zA-Z0-9])([\u4e00-\u9fa5])/g, "$1 $2")

  // 2. 破折号与多余空格规范化
  res = res.replace(/——/g, " — ").replace(/[ \t]{2,}/g, " ")

  // 3. 列表项（- / * / 1.）去除末尾中文句号或分号，保持干净
  const lines = res.split("\n").map(line => {
    const trimmed = line.trimEnd()
    if (/^(\s*[-*]|\s*\d+\.)/.test(trimmed)) {
      return trimmed.replace(/[。；;]$/, "")
    }
    return trimmed
  })

  return lines.join("\n")
}

/**
 * 经历描述 bullet 规范化（L1 本地排版第二步）：
 * 经历/项目描述的行大多是纯文本（无列表前缀），markdown 渲染不出圆点，
 * 是"排版丑"观感的主因之一。此处把已经"一句一行"的描述行统一补上 '- ' 前缀，
 * 渲染层（编辑器 ReactMarkdown 与打印模板 CSS）即出现标准 bullet point。
 *
 * 保守规则（只补不删、不动结构）：
 * - 空行保留（加粗小标题上下空行的既定排版约定不受影响）；
 * - 已是列表项（- / * / 1.）、加粗小标题（**x** 或 "标题：" 独行）、引用、代码、表格行不动；
 * - 连续纯文本行视为要点逐行补齐，避免半列表半纯文本的参差观感。
 */
export function normalizeBulletLines(content: string): string {
  if (!content) return ""
  return content
    .split("\n")
    .map(line => {
      const trimmed = line.trim()
      if (trimmed === "") return line // 空行原样
      // 加粗小标题独行必须先于星号列表判定（** 开头会被 [\-*+] 分支误吞）；
      // 仅加粗标记包裹整行（后跟冒号/空格/结尾）才算小标题，加粗起头接正文的行要补符
      if (/^\*\*.+\*\*(:|：)?\s*$/.test(trimmed)) return line
      if (/^(\s*[-+]|\s*\*(?!\*)|\s*\d+[.、)]|\s*>|\s*```|\s*\||\s*#+\s)/.test(line)) return line // 列表(-/*/1.)/引用/代码/表格/markdown 标题
      // 短"标题："行（如 技术栈：…）：仅当冒号前无加粗标记时豁免——加粗起头的是正文要点行，要补符
      if (!/^\*\*/.test(trimmed) && /^[^：:]{2,12}[：:]\s*\S/.test(trimmed) && trimmed.length <= 60) return line
      return `- ${trimmed}`
    })
    .join("\n")
}

export interface MatchLocation {
  matchIndex: number
  path: string
  field: string
  text: string
  sectionId: string
  charIndex: number
}

export interface SearchResult {
  totalMatches: number
  matches: MatchLocation[]
}

/**
 * 统计并逐次定位 ResumeDataV2 树中的全部关键词匹配项（展开为扁平序列）
 */
export function searchResumeMatches(resumeData: ResumeDataV2 | null, query: string): SearchResult {
  if (!resumeData || !query || !query.trim()) {
    return { totalMatches: 0, matches: [] }
  }

  const q = query.toLowerCase()
  let totalMatches = 0
  const matches: MatchLocation[] = []

  const recordOccurrences = (path: string, field: string, val: string | null | undefined, sectionId?: string) => {
    if (!val) return
    const sId = sectionId || path.split("[")[0].split(".")[0]
    let pos = val.toLowerCase().indexOf(q)
    while (pos !== -1) {
      matches.push({
        matchIndex: totalMatches,
        path,
        field,
        text: val,
        sectionId: sId,
        charIndex: pos,
      })
      totalMatches++
      pos = val.toLowerCase().indexOf(q, pos + q.length)
    }
  }

  // 1. 个人信息（标准字段 + 用户自定义字段；avatar_url 为图片链接不参与文本检索）
  if (resumeData.personalInfo) {
    const p = resumeData.personalInfo
    recordOccurrences("personalInfo.name", "姓名", p.name, "personalInfo")
    recordOccurrences("personalInfo.title", "期望职位", p.title, "personalInfo")
    recordOccurrences("personalInfo.email", "邮箱", p.email, "personalInfo")
    recordOccurrences("personalInfo.phone", "电话", p.phone, "personalInfo")
    recordOccurrences("personalInfo.location", "所在城市", p.location, "personalInfo")
    recordOccurrences("personalInfo.website", "个人网站", p.website, "personalInfo")
    Object.entries(p).forEach(([k, v]) => {
      if (["name", "title", "email", "phone", "location", "website", "avatar_url"].includes(k)) return
      if (typeof v === "string") recordOccurrences(`personalInfo.${k}`, k, v, "personalInfo")
    })
  }

  // 2. 个人总结
  recordOccurrences("summary", "个人总结", resumeData.summary, "summary")

  // 3. 工作经历
  resumeData.workExperience?.forEach((w, wIdx) => {
    recordOccurrences(`workExperience[${wIdx}].company`, "公司", w.company, "workExperience")
    recordOccurrences(`workExperience[${wIdx}].title`, "职位", w.title, "workExperience")
    if (Array.isArray(w.description)) {
      w.description.forEach((d, dIdx) => {
        recordOccurrences(`workExperience[${wIdx}].description[${dIdx}]`, `工作描述 ${dIdx + 1}`, d, "workExperience")
      })
    } else if (typeof (w as any).description === "string") {
      recordOccurrences(`workExperience[${wIdx}].description`, "工作描述", (w as any).description, "workExperience")
    }
  })

  // 4. 项目经历
  resumeData.personalProjects?.forEach((p, pIdx) => {
    recordOccurrences(`personalProjects[${pIdx}].name`, "项目名", p.name, "personalProjects")
    recordOccurrences(`personalProjects[${pIdx}].role`, "角色", p.role, "personalProjects")
    if (Array.isArray(p.description)) {
      p.description.forEach((d, dIdx) => {
        recordOccurrences(`personalProjects[${pIdx}].description[${dIdx}]`, `项目描述 ${dIdx + 1}`, d, "personalProjects")
      })
    } else if (typeof (p as any).description === "string") {
      recordOccurrences(`personalProjects[${pIdx}].description`, "项目描述", (p as any).description, "personalProjects")
    }
  })

  // 5. 教育背景
  resumeData.education?.forEach((e, eIdx) => {
    recordOccurrences(`education[${eIdx}].institution`, "学校", e.institution, "education")
    recordOccurrences(`education[${eIdx}].major`, "专业", e.major, "education")
    recordOccurrences(`education[${eIdx}].degree`, "学历", e.degree, "education")
    recordOccurrences(`education[${eIdx}].description`, "在校经历", e.description, "education")
  })

  // 6. 专业技能与其他
  if (resumeData.additional?.technicalSkills) {
    resumeData.additional.technicalSkills.forEach((s, sIdx) => {
      recordOccurrences(`additional.technicalSkills[${sIdx}]`, `技能项 ${sIdx + 1}`, s, "additional")
    })
  }
  if (resumeData.additional?.languages) {
    resumeData.additional.languages.forEach((l, lIdx) => {
      recordOccurrences(`additional.languages[${lIdx}]`, `语言能力 ${lIdx + 1}`, l, "additional")
    })
  }
  if (resumeData.additional?.certificationsTraining) {
    resumeData.additional.certificationsTraining.forEach((c, cIdx) => {
      recordOccurrences(`additional.certificationsTraining[${cIdx}]`, `证书培训 ${cIdx + 1}`, c, "additional")
    })
  }

  // 7. 自定义模块（新增任意一级模块，画布可见可编辑，必须与 DOM 高亮计数一致）
  if (resumeData.customModules) {
    Object.entries(resumeData.customModules).forEach(([modKey, items]) => {
      (items || []).forEach((item: any, idx: number) => {
        const sId = `${modKey}-${idx}`
        Object.entries(item || {}).forEach(([k, v]) => {
          if (k === "_key" || k === "id") return
          if (typeof v === "string") {
            recordOccurrences(`customModules.${modKey}[${idx}].${k}`, k, v, sId)
          } else if (Array.isArray(v) && v.every(x => typeof x === "string")) {
            v.forEach((line, li) => {
              recordOccurrences(`customModules.${modKey}[${idx}].${k}[${li}]`, `${k} ${li + 1}`, line, sId)
            })
          }
        })
      })
    })
  }

  // 8. 归档区（工作经历还原站 / 项目回收站，面板打开时同样参与 DOM 高亮）
  // 字段集与顺序必须与 replaceResumeText 归档段严格一致，保证单替换 targetMatchIndex 对位
  const scanArchivedList = (list: any[], label: string, basePath: string, sId: string, fields: string[]) => {
    list.forEach((item, idx) => {
      fields.forEach(f => {
        if (typeof item?.[f] === "string") {
          recordOccurrences(`${basePath}[${idx}].${f}`, `${label}·${f}`, item[f], sId)
        }
      })
      if (Array.isArray(item.description)) {
        item.description.forEach((d: string, dIdx: number) => {
          recordOccurrences(`${basePath}[${idx}].description[${dIdx}]`, `${label}描述 ${dIdx + 1}`, d, sId)
        })
      } else if (typeof item.description === "string") {
        recordOccurrences(`${basePath}[${idx}].description`, `${label}描述`, item.description, sId)
      }
    })
  }
  scanArchivedList(resumeData.archivedProjects || [], "项目（归档）", "archivedProjects", "archivedProjects", ["name"])
  scanArchivedList(resumeData.archivedWorkExperience || [], "工作（归档）", "archivedWorkExperience", "archivedWorkExperience", ["company", "title"])

  return { totalMatches, matches }
}

/**
 * 递归深度替换简历中的文本（纯不可变更新，严格保持数据形态与大小写不敏感匹配）
 */
export function replaceResumeText(
  resumeData: ResumeDataV2,
  findText: string,
  replaceText: string,
  replaceAll: boolean,
  targetMatchIndex = 0
): { nextData: ResumeDataV2; replacedCount: number } {
  if (!findText) {
    return { nextData: resumeData, replacedCount: 0 }
  }

  let currentGlobalMatch = 0
  let replacedCount = 0

  const replaceInString = (input: string): string => {
    if (!input) return input
    const lowerInput = input.toLowerCase()
    const lowerFind = findText.toLowerCase()
    if (!lowerInput.includes(lowerFind)) return input

    if (replaceAll) {
      // 全局替换（大小写不敏感，正则安全转义精确替换）
      const escaped = findText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      const regex = new RegExp(escaped, "gi")
      const matches = input.match(regex)
      if (matches) {
        replacedCount += matches.length
        return input.replace(regex, () => replaceText)
      }
      return input
    }

    // 单次替换：仅替换第 targetMatchIndex 处匹配（基于小写定位，保留其余部分原样）
    let result = ""
    let lastIndex = 0
    let pos = lowerInput.indexOf(lowerFind, lastIndex)

    while (pos !== -1) {
      if (currentGlobalMatch === targetMatchIndex) {
        result += input.substring(lastIndex, pos) + replaceText
        lastIndex = pos + findText.length
        replacedCount++
        currentGlobalMatch++
        break
      }
      currentGlobalMatch++
      result += input.substring(lastIndex, pos + findText.length)
      lastIndex = pos + findText.length
      pos = lowerInput.indexOf(lowerFind, lastIndex)
    }

    result += input.substring(lastIndex)
    return result
  }

  const next: ResumeDataV2 = {
    ...resumeData,
    // 个人信息：标准字段 + 自定义字段一并替换；avatar_url 为图片链接不参与
    personalInfo: (() => {
      const pi: any = { ...resumeData.personalInfo }
      const standardOrder = ["name", "title", "email", "phone", "location", "website"]
      // 与检索顺序严格一致：先 6 个标准键，再其余自定义键（avatar_url 图片链接不参与）
      standardOrder.forEach(k => {
        if (typeof pi[k] === "string") pi[k] = replaceInString(pi[k])
      })
      Object.keys(pi).forEach(k => {
        if (k === "avatar_url" || standardOrder.includes(k)) return
        if (typeof pi[k] === "string") pi[k] = replaceInString(pi[k])
      })
      return pi
    })(),
    summary: replaceInString(resumeData.summary || ""),
    workExperience: (resumeData.workExperience || []).map(w => ({
      ...w,
      company: replaceInString(w.company || ""),
      title: replaceInString(w.title || ""),
      description: (Array.isArray(w.description)
        ? w.description.map(d => replaceInString(d))
        : typeof (w as any).description === "string"
        ? replaceInString((w as any).description)
        : w.description) as any,
    })),
    personalProjects: (resumeData.personalProjects || []).map(p => ({
      ...p,
      name: replaceInString(p.name || ""),
      role: replaceInString(p.role || ""),
      description: (Array.isArray(p.description)
        ? p.description.map(d => replaceInString(d))
        : typeof (p as any).description === "string"
        ? replaceInString((p as any).description)
        : p.description) as any,
    })),
    education: (resumeData.education || []).map(e => ({
      ...e,
      institution: replaceInString(e.institution || ""),
      major: replaceInString(e.major || ""),
      degree: replaceInString(e.degree || ""),
      description: e.description ? replaceInString(e.description) : e.description,
    })),
    additional: {
      ...resumeData.additional,
      technicalSkills: (resumeData.additional?.technicalSkills || []).map(s => replaceInString(s)),
      languages: (resumeData.additional?.languages || []).map(l => replaceInString(l)),
      certificationsTraining: (resumeData.additional?.certificationsTraining || []).map(c => replaceInString(c)),
    },
    // 自定义模块条目：所有字符串字段（含描述数组与用户自建 KV）一并替换
    customModules: (() => {
      const cms = resumeData.customModules || {}
      const nextModules: typeof cms = {}
      Object.entries(cms).forEach(([modKey, items]) => {
        nextModules[modKey] = (items || []).map((item: any) => {
          const nextItem: any = { ...item }
          Object.keys(nextItem).forEach(k => {
            if (k === "_key" || k === "id") return
            if (typeof nextItem[k] === "string") {
              nextItem[k] = replaceInString(nextItem[k])
            } else if (Array.isArray(nextItem[k]) && nextItem[k].every(x => typeof x === "string")) {
              nextItem[k] = nextItem[k].map((d: string) => replaceInString(d))
            }
          })
          return nextItem
        })
      })
      return nextModules
    })(),
    // 归档区（还原站/回收站面板可见，保持与检索一致）
    archivedProjects: (resumeData.archivedProjects || []).map(p => ({
      ...p,
      name: replaceInString(p.name || ""),
      description: (Array.isArray(p.description)
        ? p.description.map(d => replaceInString(d))
        : typeof p.description === "string"
        ? replaceInString(p.description)
        : p.description) as any,
    })),
    archivedWorkExperience: (resumeData.archivedWorkExperience || []).map(w => ({
      ...w,
      company: replaceInString(w.company || ""),
      title: replaceInString(w.title || ""),
      description: (Array.isArray(w.description)
        ? w.description.map((d: string) => replaceInString(d))
        : typeof w.description === "string"
        ? replaceInString(w.description)
        : w.description) as any,
    })),
  }

  return { nextData: next, replacedCount }
}
