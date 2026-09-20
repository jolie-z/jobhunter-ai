import { ResumeData, ResumeDataV2, ExperienceV2, ProjectV2, EducationV2, ResumeSection } from "@/types/resume"
import { matchStandardModule } from "@/lib/resume-converter"

export function convertFlatToV2(flatData: ResumeData): ResumeDataV2 {
  const v2: ResumeDataV2 = {
    personalInfo: {
      name: flatData.header?.name || "候选人",
      title: (flatData.header?.intention || "").replace("求职意向：", "").trim(),
      email: "",
      phone: "",
      location: ""
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
    moduleOrder: ['personalInfo', 'summary', 'workExperience', 'personalProjects', 'education', 'technicalSkills'],
    moduleTitles: {
      personalInfo: '个人信息',
      summary: '个人总结',
      workExperience: '工作经历',
      personalProjects: '项目经历',
      education: '教育背景',
      technicalSkills: '专业技能'
    }
  }

  if (flatData.header?.contact) {
    const parts = flatData.header.contact.split('|').map((s: string) => s.trim())
    if (parts.length > 0) v2.personalInfo.phone = parts[0]
    if (parts.length > 1) v2.personalInfo.email = parts[1]
  }

  const parseExperiences = (content: string, type: 'work' | 'project' | 'edu') => {
    const items = []
    const blocks = content.split(/(?=\*\*.*?\*\*)/).filter(Boolean)
    
    for (const block of blocks) {
      let titleLine = ""
      let descStr = block
      const titleMatch = block.match(/^\*\*(.*?)\*\*\n?([\s\S]*)/)
      if (titleMatch) {
        titleLine = titleMatch[1]
        descStr = titleMatch[2]
      }
      const parts = titleLine.split('·').map((s: string) => s.trim())
      
      if (type === 'work') {
        items.push({
          company: parts[0] || "",
          title: parts[1] || "",
          years: parts[2] || "",
          description: descStr.split('\n').filter((s: string) => s.trim() !== '')
        } as ExperienceV2)
      } else if (type === 'project') {
        items.push({
          name: parts[0] || "",
          role: parts[1] || "",
          years: parts[2] || "",
          description: descStr.split('\n').filter((s: string) => s.trim() !== '')
        } as ProjectV2)
      } else if (type === 'edu') {
        items.push({
          institution: parts[0] || "",
          major: parts[1] || "",
          degree: parts[2] || "", 
          years: parts[3] || "",
          description: descStr.trim()
        } as EducationV2)
      }
    }
    return items
  }

  flatData.sections.forEach((section: ResumeSection) => {
    const title = section.title.trim()
    const content = section.content.trim()
    if (!content) return

    // 同义词语义匹配（个人陈述/自我评价/个人优势等均可命中 summary），与后端同口径
    const mod = matchStandardModule(title)
    if (mod === "summary") {
      v2.summary = content
    } else if (mod === "skills") {
      v2.additional!.technicalSkills = content.split('\n').filter((s: string) => s.trim() !== '')
    } else if (mod === "work") {
      v2.workExperience = parseExperiences(content, 'work') as ExperienceV2[]
    } else if (mod === "project") {
      v2.personalProjects = parseExperiences(content, 'project') as ProjectV2[]
    } else if (mod === "edu") {
      v2.education = parseExperiences(content, 'edu') as EducationV2[]
    }
  })

  return v2
}
