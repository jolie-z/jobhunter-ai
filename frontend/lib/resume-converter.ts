import type { ResumeData, ResumeSection, ResumeDataV2, PersonalInfoV2, ExperienceV2, EducationV2, ProjectV2 } from "@/types/resume"
import { stripConfidenceTags } from "./utils/text-formatters"

export interface ResumeSubModule {
  id: string
  title: string
  content: string
}

export interface ResumeModule {
  id: string
  type: 'basic' | 'experience'
  title: string
  content?: string
  subModules?: ResumeSubModule[]
}

let blockCounter = 0
const genId = () => `blk-${Date.now()}-${++blockCounter}`

/**
 * 🌟 双向绑定解析器：将 Markdown 文本解析为结构化 Block 模块数组
 */
export function parseMarkdownToBlocks(md: string): ResumeModule[] {
  if (!md || !md.trim()) return []
  md = stripConfidenceTags(md)
  const blocks: ResumeModule[] = []
  
  // 匹配行首单个 #，兼容 "# 标题" 和无空格的 "#标题"，同时严格排除 "##"
  const sections = md.split(/(?=^#[^#\n])/m).filter(s => s.trim())

  for (const section of sections) {
    const lines = section.split('\n')
    const firstLine = lines[0].trim()

    let title = firstLine
    if (title.startsWith('# ')) {
      title = title.substring(2).trim()
    } else if (title.startsWith('#')) {
      title = title.substring(1).trim()
    }

    const type = (title.includes('经历') || title.includes('项目') || title.includes('工作')) ? 'experience' : 'basic'
    // 🌟 自动过滤独立的 **** 或 --- 隔离行
    const rawLines = lines.slice(1).filter(l => {
      const trimmed = l.trim()
      return trimmed !== '****' && trimmed !== '---' && trimmed !== '***' && trimmed !== '----------------'
    })
    const remainingText = rawLines.join('\n').trim()

    if (type === 'experience') {
      const subSections = remainingText.split(/(?=^##[^#\n])|(?=^(?:-\s*)?\*\*.*?\*\*)/m).filter(s => s.trim())
      
      const subModules: ResumeSubModule[] = []
      for (const sub of subSections) {
        const subLines = sub.split('\n')
        let subTitle = subLines[0].trim()
        
        subTitle = subTitle.replace(/^##\s*/, '').replace(/^-\s*/, '')
        if (subTitle.startsWith('**') && subTitle.endsWith('**')) {
          subTitle = subTitle.substring(2, subTitle.length - 2).trim()
        }
        subTitle = subTitle.replace(/：$/, '').replace(/:$/, '')
        
        const subContentLines = subLines.slice(1).filter(l => {
          const trimmed = l.trim()
          return trimmed !== '****' && trimmed !== '---' && trimmed !== '***'
        })
        const subContent = subContentLines.join('\n').trim()
        subModules.push({
          id: genId(),
          title: subTitle || '未命名经历',
          content: subContent
        })
      }
      blocks.push({
        id: genId(),
        type: 'experience',
        title,
        subModules
      })
    } else {
      blocks.push({
        id: genId(),
        type: 'basic',
        title,
        content: remainingText
      })
    }
  }
  return blocks
}

/**
 * 🌟 序列化引擎：将结构化 Block 模块数组转换为 Markdown 全文
 */
export function serializeBlocksToMarkdown(blocks: ResumeModule[]): string {
  return blocks.map(block => {
    if (block.type === 'experience' && block.subModules) {
      const subs = block.subModules.map(sub => {
        const header = sub.title ? `**${sub.title}**` : ''
        const cleanSubContent = (sub.content || '').replace(/^(\*{3,4}|-{3,4})\s*\n?/gm, '').trim()
        return [header, cleanSubContent].filter(Boolean).join('\n')
      }).join('\n\n')
      return `# ${block.title}\n\n${subs}`
    } else {
      const cleanContent = (block.content || '').replace(/^(\*{3,4}|-{3,4})\s*\n?/gm, '').trim()
      return `# ${block.title}\n\n${cleanContent}`
    }
  }).join('\n\n')
}

/**
 * 🌟 互转工具：将前端现有的 ResumeData 转换为 Markdown 全文
 */
export function resumeDataToMarkdown(resumeData: ResumeData): string {
  const mdParts: string[] = []
  if (resumeData.header) {
    const headerLines = [
      `# 个人信息`,
      `**${resumeData.header.name || ''}**`,
      `求职意向：${resumeData.header.intention || ''}`,
      `联系方式：${resumeData.header.contact || ''}`
    ].filter(Boolean)
    mdParts.push(headerLines.join('\n'))
  }

  for (const sec of resumeData.sections || []) {
    if (!sec.title?.trim() && !sec.content?.trim()) continue
    if (sec.isArchived) continue
    const prefix = sec.level === 2 ? '##' : '#'
    mdParts.push(`${prefix} ${sec.title}\n\n${sec.content?.trim() || ''}`)
  }
  return mdParts.join('\n\n').trim()
}

/**
 * 🌟 互转工具：将 Markdown 全文解析重构为 ResumeData 对象
 */
export function markdownToResumeData(md: string, currentHeader?: ResumeData['header']): ResumeData {
  const blocks = parseMarkdownToBlocks(md)
  const sections: ResumeSection[] = []

  let header = currentHeader || { name: '求职者', contact: '', intention: '' }

  blocks.forEach(block => {
    if (block.title.includes('个人信息') || block.title.includes('基本信息')) {
      const content = block.content || ''
      const nameMatch = content.match(/\*\*(.*?)\*\*/) || content.match(/姓名[:：]\s*(.*)/)
      const contactMatch = content.match(/联系方式[:：]\s*(.*)/) || content.match(/电话[:：]\s*(.*)/)
      const intentionMatch = content.match(/求职意向[:：]\s*(.*)/)

      header = {
        name: nameMatch ? nameMatch[1].trim() : header.name,
        contact: contactMatch ? contactMatch[1].trim() : header.contact,
        intention: intentionMatch ? intentionMatch[1].trim() : header.intention,
      }
    } else if (block.type === 'experience' && block.subModules && block.subModules.length > 0) {
      // 顶级分类，如 # 项目经历
      sections.push({
        id: block.id,
        title: block.title,
        content: '',
        level: 1
      })
      // 子经验模块，如 ## 项目名称
      block.subModules.forEach(sub => {
        sections.push({
          id: sub.id,
          title: sub.title,
          content: sub.content,
          level: 2
        })
      })
    } else {
      sections.push({
        id: block.id,
        title: block.title,
        content: block.content || '',
        level: 1
      })
    }
  })

  return {
    header,
    sections
  }
}

/**
 * 🌟 模块标题同义词匹配：用户自定义标题（个人陈述/自我评价/个人优势等）-> 标准模块 key
 * 与后端 agent_mapper._MODULE_TITLE_SYNONYMS 同语义口径，避免标题改名导致映射丢失
 */
export function matchStandardModule(title: string): "summary" | "skills" | "work" | "project" | "edu" | null {
  const t = (title || "").trim().toLowerCase()
  if (!t) return null
  const hit = (arr: string[]) => arr.some(s => t.includes(s))
  if (hit(["总结", "自评", "优势", "陈述", "自我介绍", "简介", "关于我", "summary", "profile", "about"])) return "summary"
  if (hit(["技能", "特长", "技术栈", "其他", "additional", "skills"])) return "skills"
  if (hit(["工作", "职业经历", "实习", "work"])) return "work"
  if (hit(["项目", "project"])) return "project"
  if (hit(["教育", "学历", "education"])) return "edu"
  return null
}

/**
 * 🌟 结构化 JSON 互转工具：生成可存入飞书「结构化数据」字典的对象
 */
export function resumeDataToStructuredJson(resumeData: ResumeData): Record<string, any> {
  const structured: Record<string, any> = {
    personalInfo: {
      name: resumeData.header?.name || "",
      contact: resumeData.header?.contact || "",
      intention: resumeData.header?.intention || ""
    },
    sections: (resumeData.sections || []).map(s => ({
      id: s.id,
      title: s.title,
      content: s.content,
      level: s.level || 1,
      isAtsAligned: s.isAtsAligned || false,
      isGrilled: s.isGrilled || false,
      isSynced: s.isSynced || false
    }))
  }
  return structured
}

/**
 * 🌟 JSON 转换器：将扁平的 ResumeData (Markdown模块) 转换为结构化的 ResumeDataV2
 */
/**
 * 🌟 新版 Skill 条目标题拆分：「职位 / 岗位 (公司) (2024.04-至今)」→ 主体、时间、公司括号
 */
function splitEntryHeading(title: string): { main: string; years: string; trailingParen: string; parenIndex: number } {
  const trimmed = (title || "").trim()
  const yearsMatch = trimmed.match(/[（(]((?:19|20)\d{2}[^（）)]*)[）)]\s*$/)
  const years = yearsMatch ? yearsMatch[1].trim() : ""
  const afterYears = yearsMatch ? trimmed.slice(0, yearsMatch.index).trim() : trimmed
  // 只记录尾部括号内容（工作经历里通常是公司名），是否剥离由调用方决定（项目名保留完整如 "(MVP)"）
  const parenMatch = afterYears.match(/[（(]([^（）)]*)[）)]\s*$/)
  const trailingParen = parenMatch ? parenMatch[1].trim() : ""
  return { main: afterYears, years, trailingParen, parenIndex: parenMatch ? (parenMatch.index ?? -1) : -1 }
}

export function resumeDataToResumeDataV2(resumeData: ResumeData): ResumeDataV2 {
  const result: ResumeDataV2 = {
    personalInfo: {
      name: resumeData.header?.name || "",
      title: (resumeData.header?.intention || "").split('|')[0]?.trim() || "",
      email: "",
      phone: "",
      location: "",
      website: ""
    },
    summary: "",
    workExperience: [],
    education: [],
    personalProjects: [],
    additional: {
      technicalSkills: [],
      languages: [],
      certificationsTraining: []
    },
    moduleOrder: ["summary", "workExperience", "personalProjects", "education", "additional"],
    moduleTitles: {
      summary: "个人总结",
      workExperience: "工作经历",
      personalProjects: "项目经历",
      education: "教育背景",
      additional: "其他信息"
    }
  }

  // 尝试从 header.contact 提取邮箱和电话
  if (resumeData.header?.contact) {
    const contactParts = resumeData.header.contact.split('|').map(s => s.trim())
    for (const part of contactParts) {
      if (part.includes('@')) result.personalInfo.email = part
      else if (/\d{11}/.test(part)) result.personalInfo.phone = part
      else if (!result.personalInfo.location) result.personalInfo.location = part
    }
  }

  const sections = resumeData.sections || []
  let currentTopLevel: ResumeSection | null = null

  for (const sec of sections) {
    if (sec.level === 1) {
      currentTopLevel = sec
      const mod = matchStandardModule(sec.title)
      if (mod === "summary") {
        result.summary = sec.content
      } else if (mod === "skills") {
        const lines = sec.content.split('\n').map(l => l.replace(/^- /, '').trim()).filter(Boolean)
        result.additional.technicalSkills.push(...lines)
      } else if (mod === "edu") {
        // 逐行结构化：「- 学校 - 专业 - 学历 (2015.07-2019.07)」
        for (const rawLine of sec.content.split('\n')) {
          const line = rawLine.replace(/^-\s*/, '').trim()
          if (!line) continue
          const yearsMatch = line.match(/[（(]((?:19|20)\d{2}[^（）)]*)[）)]\s*$/)
          const years = yearsMatch ? yearsMatch[1].trim() : ""
          const main = (yearsMatch ? line.slice(0, yearsMatch.index) : line).trim()
          const parts = main.split(/\s*[-–—]\s*/).map(s => s.trim()).filter(Boolean)
          if (!parts.length) continue
          result.education.push({
            institution: parts[0] || "",
            major: parts[1] || "",
            degree: parts[2] || "",
            years,
          })
        }
      }
    } else if (sec.level === 2 && currentTopLevel) {
      const parentMod = matchStandardModule(currentTopLevel.title)
      const titleLines = sec.title.split('|').map(s => s.trim())
      const descLines = sec.content.split('\n').filter(Boolean)

      if (parentMod === "work") {
        const { main, years, trailingParen, parenIndex } = splitEntryHeading(sec.title)
        result.workExperience.push({
          // 工作条目「职位 / 岗位 (公司) (时间)」：公司取尾部括号，职位为剥离后的主体
          company: trailingParen,
          title: trailingParen && parenIndex >= 0 ? main.slice(0, parenIndex).trim() : main,
          years,
          description: descLines
        })
      } else if (parentMod === "project") {
        const { main, years } = splitEntryHeading(sec.title)
        result.personalProjects.push({
          name: main,
          role: "",
          years,
          description: descLines
        })
      }
    }
  }

  return result
}
