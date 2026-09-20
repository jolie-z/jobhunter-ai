import { describe, it, expect } from "vitest"
import {
  formatMarkdownPangu,
  searchResumeMatches,
  replaceResumeText,
} from "../components/dashboard/features/v2-resume-editor/utils/resume-search-utils"
import type { ResumeDataV2 } from "@/types/resume"

describe("resume-search-utils", () => {
  const mockResume: ResumeDataV2 = {
    personalInfo: {
      name: "张三",
      title: "资深Python工程师",
      email: "zhangsan@example.com",
      phone: "13800000000",
      location: "北京",
    },
    summary: "精通Python后端架构，熟练掌握英语CET6，能够无障碍阅读英语技术文档。",
    workExperience: [
      {
        company: "某知名科技有限公司",
        title: "高级研发工程师",
        years: "2021-至今",
        description: [
          "负责核心微服务架构搭建，提升系统吞吐量30%。",
          "与海外团队配合，全英语进行技术方案沟通和评审。",
        ],
      },
      {
        company: "早年创业团队",
        title: "全栈开发",
        years: "2019-2021",
        // 测试单行 string 类型的 description 保型性
        description: "负责 Python 爬虫和英语自动化文档整理。" as any,
      },
    ],
    personalProjects: [
      {
        name: "开源AI改写助理",
        role: "核心架构师",
        years: "2023-至今",
        description: [
          "基于FastAPI和Next.js开发，支持自动化简历诊断与改写。",
        ],
      },
    ],
    education: [
      {
        institution: "北京理工大学",
        major: "计算机科学与技术",
        degree: "硕士",
        years: "2018-2021",
        description: "英语六级成绩620分，发表多篇顶级会议论文。",
      },
    ],
    additional: {
      technicalSkills: [
        "熟练掌握Python、TypeScript",
        "具备良好的英语听说读写能力",
      ],
      languages: ["英语 CET6", "普通话一级乙等"],
      certificationsTraining: [],
    },
    moduleOrder: ["summary", "workExperience", "personalProjects", "education", "additional"],
    moduleTitles: {},
  }

  describe("formatMarkdownPangu", () => {
    it("should format CJK and alphanumeric spacing properly", () => {
      const raw = "精通Python后端开发，使用Docker进行容器化部署。"
      const formatted = formatMarkdownPangu(raw)
      expect(formatted).toBe("精通 Python 后端开发，使用 Docker 进行容器化部署。")
    })

    it("should normalize em dashes and remove list trailing punctuations", () => {
      const raw = "- 负责技术选型——微服务化架构。\n- 优化数据库索引；"
      const formatted = formatMarkdownPangu(raw)
      expect(formatted).toBe("- 负责技术选型 — 微服务化架构\n- 优化数据库索引")
    })
  })

  describe("searchResumeMatches", () => {
    it("should find all occurrences of '英语' and produce flat 1:1 matches", () => {
      const result = searchResumeMatches(mockResume, "英语")
      // summary: 2次
      // workExperience[0].description[1]: 1次
      // workExperience[1].description: 1次
      // education[0].description: 1次
      // additional.technicalSkills[1]: 1次
      // additional.languages[0]: 1次
      // 合计: 7次
      expect(result.totalMatches).toBe(7)
      // 核心验证：matches 必须彻底展平，matches.length 严格等于 totalMatches
      expect(result.matches.length).toBe(7)
      expect(result.matches[0].field).toBe("个人总结")
      expect(result.matches[0].matchIndex).toBe(0)
      expect(result.matches[1].matchIndex).toBe(1)
      expect(result.matches[0].sectionId).toBe("summary")
      expect(result.matches[1].sectionId).toBe("summary")
      expect(result.matches[2].sectionId).toBe("workExperience")
    })

    it("should support case-insensitive searching", () => {
      const result = searchResumeMatches(mockResume, "python")
      // personalInfo.title: 1次 ("Python工程师")
      // summary: 1次 ("精通Python后端架构")
      // workExperience[1].description: 1次 ("Python 爬虫")
      // additional.technicalSkills[0]: 1次 ("熟练掌握Python")
      expect(result.totalMatches).toBe(4)
      expect(result.matches.length).toBe(4)
    })

    it("should handle empty or whitespace query gracefully", () => {
      expect(searchResumeMatches(mockResume, "").totalMatches).toBe(0)
      expect(searchResumeMatches(mockResume, "   ").totalMatches).toBe(0)
      expect(searchResumeMatches(null, "英语").totalMatches).toBe(0)
    })
  })

  describe("replaceResumeText", () => {
    it("should replace all occurrences when replaceAll is true", () => {
      const result = replaceResumeText(mockResume, "英语", "English", true)
      expect(result.replacedCount).toBe(7)
      expect(result.nextData.summary).toContain("English")
      expect(result.nextData.summary).not.toContain("英语")
      expect(result.nextData.education?.[0].description).toContain("English六级")
      expect(result.nextData.additional?.languages?.[0]).toContain("English CET6")
    })

    it("should support case-insensitive replacement (search 'python' -> replace 'Golang')", () => {
      const result = replaceResumeText(mockResume, "python", "Golang", true)
      expect(result.replacedCount).toBe(4)
      expect(result.nextData.personalInfo?.title).toBe("资深Golang工程师")
      expect(result.nextData.summary).toContain("精通Golang后端架构")
    })

    it("should strictly preserve string type description without converting to array", () => {
      const result = replaceResumeText(mockResume, "英语", "English", true)
      const desc1 = result.nextData.workExperience?.[1].description
      // 必须严格是 string 类型，绝不能被 .split('\n') 破坏为 string[]
      expect(typeof desc1).toBe("string")
      expect(desc1).toBe("负责 Python 爬虫和English自动化文档整理。")
    })

    it("should replace targetMatchIndex correctly when replaceAll is false", () => {
      const result = replaceResumeText(mockResume, "英语", "English", false, 0)
      expect(result.replacedCount).toBe(1)
      // 第 0 处命中在 summary 的第一处，第二处仍在
      expect(result.nextData.summary).toContain("熟练掌握EnglishCET6")
      expect(result.nextData.summary).toContain("阅读英语技术文档")
    })

    it("should not mutate the original resume data", () => {
      const originalSummary = mockResume.summary
      replaceResumeText(mockResume, "英语", "English", true)
      expect(mockResume.summary).toBe(originalSummary)
    })
  })

  describe("custom modules & archived scope (P2-5)", () => {
    const resumeWithCustom: ResumeDataV2 = {
      ...mockResume,
      customModules: {
        "custom_1700000000000": [
          {
            company: "质检专用公司",
            title: "质检岗位",
            years: "2024",
            description: ["负责质检标记词ZQCHECKME相关工作"],
            "自定义备注": "含ZQCHECKME的自定义KV字段",
            _key: "itm_test",
          } as any,
        ],
      },
      archivedProjects: [
        { name: "被切除的项目ZQCHECKME", description: ["归档描述ZQCHECKME"] } as any,
      ],
      archivedWorkExperience: [
        { company: "归档公司ZQCHECKME", title: "归档职位", description: ["归档工作ZQCHECKME"] } as any,
      ],
    } as any

    it("should find matches inside custom modules, archived lists and personalInfo custom fields", () => {
      const r = searchResumeMatches(resumeWithCustom, "ZQCHECKME")
      // 自定义模块2处（描述+KV字段） + 归档项目2处 + 归档工作2处 = 6
      expect(r.totalMatches).toBe(6)
      const sIds = r.matches.map(m => m.sectionId)
      expect(sIds).toContain("custom_1700000000000-0")
      expect(sIds).toContain("archivedProjects")
      expect(sIds).toContain("archivedWorkExperience")
    })

    it("should find matches inside personalInfo custom fields but skip avatar_url", () => {
      const r = searchResumeMatches(
        { ...mockResume, personalInfo: { ...mockResume.personalInfo, 微信: "wx-ZQCHECKME", avatar_url: "https://img.example.com/ZQCHECKME.png" } as any },
        "ZQCHECKME"
      )
      expect(r.totalMatches).toBe(1)
      expect(r.matches[0].path).toBe("personalInfo.微信")
    })

    it("should keep search/replace field sets symmetric for archived work title (P1 regression lock)", () => {
      // 归档工作经历的 title（职位名）是典型查找目标：检索与替换计数必须一致
      const r = searchResumeMatches(resumeWithCustom, "归档职位")
      expect(r.totalMatches).toBe(1)
      const replaced = replaceResumeText(resumeWithCustom, "归档职位", "新职位", true)
      expect(replaced.replacedCount).toBe(r.totalMatches)
      expect((replaced.nextData.archivedWorkExperience as any)[0].title).toBe("新职位")
    })

    it("should replace text inside custom modules and archived lists", () => {
      const result = replaceResumeText(resumeWithCustom, "ZQCHECKME", "已替换", true)
      expect(result.replacedCount).toBe(6)
      const item: any = (result.nextData.customModules as any)["custom_1700000000000"][0]
      expect(item.description[0]).toContain("已替换")
      expect(item["自定义备注"]).toBe("含已替换的自定义KV字段")
      expect((result.nextData.archivedProjects as any)[0].name).toBe("被切除的项目已替换")
      expect((result.nextData.archivedWorkExperience as any)[0].company).toBe("归档公司已替换")
      // 数据形态保持：_key 不动、description 仍是数组
      expect(item._key).toBe("itm_test")
      expect(Array.isArray(item.description)).toBe(true)
    })
  })
})
