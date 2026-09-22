import { PersonalInfo } from "@/lib/personal-info-parser"

export interface ResumeSection {
  id: string
  title: string
  content: string
  level?: 1 | 2
  isArchived?: boolean
  originalContent?: string
  isDrafted?: boolean
  isAtsAligned?: boolean
  isGrilled?: boolean
  isSynced?: boolean
}

export interface ResumeData {
  header: {
    name: string
    contact: string
    intention: string
    parsedInfo?: PersonalInfo
  }
  sections: ResumeSection[]
  structuredJson?: Record<string, any>
  rawMarkdown?: string
}

export interface RewriteAnnotItem {
  subtitle: string
  rationale: string
}

export interface RewriteAnnotGroup {
  section: "project" | "work"
  title: string
  items: RewriteAnnotItem[]
}

// ---------------------------------------------------------------------------
// V2 Pure JSON Types (Matching Backend Schema)
// ---------------------------------------------------------------------------

export interface PersonalInfoV2 {
  name: string
  title: string
  email: string
  phone: string
  location: string
  website?: string | null
  avatar_url?: string | null
}

export interface ExperienceV2 {
  /** 渲染层稳定 React key（v2 store 注入，随数据持久化），下标 key 在删除/排序时会错位 */
  _key?: string
  title: string
  company: string
  location?: string | null
  years: string
  description: string[]
  originalContent?: string
}

export interface EducationV2 {
  /** 同 ExperienceV2._key */
  _key?: string
  institution: string
  major: string
  degree: string
  years: string
  description?: string | null
}

export interface ProjectV2 {
  /** 同 ExperienceV2._key */
  _key?: string
  name: string
  role: string
  years: string
  description: string[]
  originalContent?: string
}

export interface AdditionalInfoV2 {
  /** 技能概述：解析自"专业技能"段落的散文/描述性文字（七项修复#2 新增，旧数据无此字段） */
  skillOverview?: string
  technicalSkills: string[]
  languages: string[]
  certificationsTraining: string[]
}

export interface ResumeDataV2 {
  personalInfo: PersonalInfoV2
  summary: string
  workExperience: ExperienceV2[]
  archivedWorkExperience?: ExperienceV2[]
  education: EducationV2[]
  personalProjects: ProjectV2[]
  archivedProjects?: ProjectV2[]
  additional: AdditionalInfoV2
  moduleOrder: string[]
  moduleTitles: Record<string, string>
  customModules?: Record<string, ExperienceV2[]>
}
