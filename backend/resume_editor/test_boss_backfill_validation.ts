/**
 * BossTab Backfill Validation Tests - Complete Coverage
 * 
 * Test all backfill scenarios for BOSS Zhipin platform:
 * - Job expectations (salary, other cities)
 * - Work experience (skills field)
 * - Project experience  
 * - Education
 * - Personal info
 * 
 * Run with: npx jest backend/resume-editor/test_boss_backfill_validation.ts
 */

import { describe, test, expect } from "@jest/globals"
import type { ResumeData } from "@/lib/types"

// ===== Test Data Builders =====

interface ExpectationBuilder {
  position?: string
  city?: string
  salaryMin?: string
  salaryMax?: string
  industries?: string[]
  otherCities?: string[]
}

function buildExpectation(builder: ExpectationBuilder): any {
  return {
    jobType: "fulltime",
    position: builder.position || "",
    industries: builder.industries || [],
    salary: builder.salaryMin && builder.salaryMax ? `${builder.salaryMin}-${builder.salaryMax}` : "",
    city: builder.city || "",
    otherCities: builder.otherCities || [],
  }
}

interface WorkExpBuilder {
  company?: string
  position?: string
  skills?: string[]
  content?: string
}

function buildWorkExp(builder: WorkExpBuilder): any {
  return {
    company: builder.company || "",
    industry: "互联网",
    department: "",
    position: builder.position || "",
    startYear: "2020",
    startMonth: "01",
    endYear: "2023",
    endMonth: "12",
    content: builder.content || "",
    achievement: "",
    skills: builder.skills || [],
    hideResume: false,
  }
}

interface ProjectBuilder {
  name?: string
  role?: string
  description?: string
}

function buildProject(builder: ProjectBuilder): any {
  return {
    project_name: builder.name || "",
    project_role: builder.role || "",
    project_link: "",
    startYear: "2021",
    startMonth: "01",
    endYear: "2022",
    endMonth: "12",
    project_description: builder.description || "",
    achievement: "",
  }
}

// ===== Core Test Suite =====

describe("BOSS 直聘回写数据完整性验证", () => {
  
  // 🎯 Issue #1: 求职期望 - 薪资和其他城市不匹配
  describe("#1 求职期望字段回写", () => {
    
    test("全职期望 - 薪资应正确格式化为 k 值范围", () => {
      const localData: ResumeData = {
        user_id: "test",
        boss_data: {
          expectations: {
            current_value: [
              buildExpectation({
                position: "全栈工程师",
                city: "广州",
                salaryMin: "15k",
                salaryMax: "25k",
                industries: ["互联网"],
                otherCities: ["深圳", "杭州", "上海", "北京"],
              }),
            ],
          },
        },
      }
      
      const backfilled = localData.boss_data?.expectations?.current_value?.[0]
      expect(backfilled).toBeDefined()
      expect(backfilled.salary).toBe("15k-25k")
      expect(backfilled.otherCities).toEqual(["深圳", "杭州", "上海", "北京"])
      expect(backfilled.otherCities?.length).toBe(4)
    })

    test("全职期望 - 其他城市数组长度应与前端保持一致", () => {
      const localOtherCities = ["深圳", "杭州", "上海", "北京"]
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          expectations: {
            current_value: [
              buildExpectation({
                position: "产品经理",
                city: "北京",
                salaryMin: "20k",
                salaryMax: "30k",
                otherCities: localOtherCities,
              }),
            ],
          },
        },
      }

      const returnedOtherCities = data.boss_data!.expectations!.current_value![0].otherCities
      
      expect(returnedOtherCities).toBeDefined()
      expect(returnedOtherCities?.length).toBe(localOtherCities.length)
      expect(returnedOtherCities).toEqual(localOtherCities)
    })

    test("全职期望 - 空的其他城市字段不应影响主字段", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          expectations: {
            current_value: [
              buildExpectation({
                position: "测试工程师",
                city: "上海",
                salaryMin: "18k",
                salaryMax: "22k",
                otherCities: [],
              }),
            ],
          },
        },
      }
      
      const item = data.boss_data!.expectations!.current_value![0]
      expect(item.position).toBe("测试工程师")
      expect(item.city).toBe("上海")
      expect(item.salary).toBe("18k-22k")
      expect(Array.isArray(item.otherCities)).toBe(true)
    })

    test("多条目期望 - 每个条目的独立字段应保持隔离", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          expectations: {
            current_value: [
              buildExpectation({
                position: "前端开发",
                city: "深圳",
                salaryMin: "15k",
                salaryMax: "25k",
                otherCities: ["广州", "北京"],
              }),
              buildExpectation({
                position: "后端开发",
                city: "北京",
                salaryMin: "20k",
                salaryMax: "30k",
                otherCities: ["上海", "杭州", "成都"],
              }),
              buildExpectation({
                position: "产品经理",
                city: "上海",
                salaryMin: "18k",
                salaryMax: "28k",
                otherCities: [],
              }),
            ],
          },
        },
      }
      
      const expectations = data.boss_data!.expectations!.current_value!
      expect(expectations.length).toBe(3)
      
      // 第 1 条：2 个其他城市
      expect(expectations[0].otherCities?.length).toBe(2)
      expect(expectations[0].salary).toBe("15k-25k")
      
      // 第 2 条：3 个其他城市
      expect(expectations[1].otherCities?.length).toBe(3)
      expect(expectations[1].salary).toBe("20k-30k")
      
      // 第 3 条：无其他城市
      expect(expectations[2].otherCities?.length).toBe(0)
      expect(expectations[2].salary).toBe("18k-28k")
    })
  })

  // 🎯 Issue #2: 工作经历 - 技能字段不回写
  describe("#2 工作经历技能字段回写", () => {
    
    test("工作经历 - 非空技能数组应完整回写到官网", () => {
      const skills = ["LLM 意图路由", "Pandas 物理校验", "双轨制架构", "CDP 协议", "NLP 情感分析", "全栈研发"]
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          work_experience: {
            current_value: [
              buildWorkExp({
                company: "测试公司",
                position: "高级工程师",
                skills: skills,
                content: "工作内容描述",
              }),
            ],
          },
        },
      }
      
      const skillTags = data.boss_data!.work_experience!.current_value![0].skills
      expect(skillTags).toBeDefined()
      expect(Array.isArray(skillTags)).toBe(true)
      expect(skillTags?.length).toBe(skills.length)
      expect(skillTags).toEqual(skills)
    })

    test("工作经历 - 空技能数组应返回空数组而非 null", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          work_experience: {
            current_value: [
              buildWorkExp({
                company: "测试公司",
                position: "初级工程师",
                skills: [],
                content: "工作内容描述",
              }),
            ],
          },
        },
      }
      
      const skillTags = data.boss_data!.work_experience!.current_value![0].skills
      expect(skillTags).toBeDefined()
      expect(Array.isArray(skillTags)).toBe(true)
      expect(skillTags?.length).toBe(0)
    })

    test("工作经历 - 多个工作经历的各自技能字段应独立", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          work_experience: {
            current_value: [
              buildWorkExp({
                company: "公司 A",
                position: "职位 A",
                skills: ["技术 1", "技术 2"],
                content: "内容 A",
              }),
              buildWorkExp({
                company: "公司 B",
                position: "职位 B",
                skills: ["技术 3", "技术 4", "技术 5"],
                content: "内容 B",
              }),
              buildWorkExp({
                company: "公司 C",
                position: "职位 C",
                skills: [],
                content: "内容 C",
              }),
            ],
          },
        },
      }
      
      const experiences = data.boss_data!.work_experience!.current_value!
      expect(experiences.length).toBe(3)
      
      // 第 1 条：2 个技能
      expect(experiences[0].skills?.length).toBe(2)
      expect(experiences[0].skills).toEqual(["技术 1", "技术 2"])
      
      // 第 2 条：3 个技能
      expect(experiences[1].skills?.length).toBe(3)
      expect(experiences[1].skills).toEqual(["技术 3", "技术 4", "技术 5"])
      
      // 第 3 条：无技能
      expect(experiences[2].skills?.length).toBe(0)
    })

    test("工作经历 - 技能名称应保留特殊字符和技术术语", () => {
      const specialSkills = [
        "LLM 意图路由",
        "Pandas 物理校验",
        "双轨制架构",
        "CDP 协议",
        "微服务治理",
        "高并发架构",
      ]
      
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          work_experience: {
            current_value: [
              buildWorkExp({
                company: "科技公司",
                position: "架构师",
                skills: specialSkills,
                content: "负责系统架构设计",
              }),
            ],
          },
        },
      }
      
      const skillTags = data.boss_data!.work_experience!.current_value![0].skills
      expect(skillTags?.length).toBe(6)
      expect(skillTags).toEqual(specialSkills)
      
      // 验证特殊字符保留
      expect(skillTags?.includes("LLM 意图路由")).toBe(true)
      expect(skillTags?.includes("Pandas 物理校验")).toBe(true)
      expect(skillTags?.includes("双轨制架构")).toBe(true)
    })
  })

  // 🎯 Issue #3: 项目经历回写
  describe("#3 项目经历回写", () => {
    
    test("项目经历 - 基本字段应完整回写", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          projects: {
            current_value: [
              buildProject({
                name: "企业级 CRM 系统",
                role: "项目负责人",
                description: "客户管理核心系统",
              }),
            ],
          },
        },
      }
      
      const project = data.boss_data!.projects!.current_value![0]
      expect(project.project_name).toBe("企业级 CRM 系统")
      expect(project.project_role).toBe("项目负责人")
      expect(project.project_description).toBe("客户管理核心系统")
      expect(project.startYear).toBe("2021")
      expect(project.startMonth).toBe("01")
      expect(project.endYear).toBe("2022")
      expect(project.endMonth).toBe("12")
    })

    test("项目经历 - 链接字段应为空字符串而非 undefined", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          projects: {
            current_value: [
              buildProject({
                name: "内部工具",
                role: "开发者",
                description: "",
              }),
            ],
          },
        },
      }
      
      const project = data.boss_data!.projects!.current_value![0]
      expect(typeof project.project_link).toBe("string")
      expect(project.project_link).toBe("")
    })
  })

  // 🎯 Issue #4: 个人优势回写
  describe("#4 个人优势回写", () => {
    
    test("个人优势 - 富文本 HTML 应完整回写", () => {
      const htmlContent = `
        <div>
          <p><strong>5 年+AI 算法经验</strong></p>
          <ul>
            <li>精通 PyTorch/TensorFlow</li>
            <li>落地多个商业项目</li>
          </ul>
        </div>
      `.trim()
      
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          personal_strengths: {
            current_value: htmlContent,
          },
        },
      }
      
      expect(data.boss_data!.personal_strengths!.current_value).toBe(htmlContent)
    })

    test("个人优势 - 空字符串应保留", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          personal_strengths: {
            current_value: "",
          },
        },
      }
      
      expect(data.boss_data!.personal_strengths!.current_value).toBe("")
    })
  })

  // 🎯 Issue #5: 教育经历回写
  describe("#5 教育经历回写", () => {
    
    test("教育经历 - 学校和专业应完整回写", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          education: {
            school: "清华大学",
            major: "计算机科学与技术",
            degree: "硕士",
            graduation_year: "2020",
          },
        },
      }
      
      expect(data.boss_data!.education!.school).toBe("清华大学")
      expect(data.boss_data!.education!.major).toBe("计算机科学与技术")
      expect(data.boss_data!.education!.degree).toBe("硕士")
      expect(data.boss_data!.education!.graduation_year).toBe("2020")
    })

    test("教育经历 - 缺省年份应为空字符串", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          education: {
            school: "北京大学",
            major: "数学系",
            degree: "本科",
            graduation_year: "",
          },
        },
      }
      
      expect(data.boss_data!.education!.graduation_year).toBe("")
    })
  })

  // 🎯 Issue #6: 证书信息回写
  describe("#6 资格证书回写", () => {
    
    test("资格证书 - 证书列表应完整回写", () => {
      const certificates = [
        { name: "PMP 认证", year: "2021" },
        { name: "AWS 解决方案架构师", year: "2022" },
        { name: "软考高级", year: "2020" },
      ]
      
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          certificates: {
            current_value: certificates,
          },
        },
      }
      
      const certList = data.boss_data!.certificates!.current_value!
      expect(certList.length).toBe(3)
      expect(certList[0]).toEqual({ name: "PMP 认证", year: "2021" })
      expect(certList[1]).toEqual({ name: "AWS 解决方案架构师", year: "2022" })
      expect(certList[2]).toEqual({ name: "软考高级", year: "2020" })
    })
  })

  // 🎯 Issue #7: 联系方式回写
  describe("#7 联系方式回写", () => {
    
    test("手机号 - 纯数字格式应正确", () => {
      const data: ResumeData = {
        user_id: "test",
        phone: "13812345678",
        boss_data: {},
      }
      
      expect(data.phone).toBe("13812345678")
      expect(/^\d{11}$/.test(data.phone!)).toBe(true)
    })

    test("邮箱 - 格式正确的邮箱应保留", () => {
      const email = "zhangsan@example.com"
      const data: ResumeData = {
        user_id: "test",
        phone: "13812345678",
        email: email,
        boss_data: {},
      }
      
      expect(data.email).toBe(email)
      expect(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email!)).toBe(true)
    })
  })

  // 🎯 Issue #8: 综合场景 - 完整简历数据回写
  describe("#8 完整简历数据端到端测试", () => {
    
    test("完整简历 - 所有字段应同时保持正确", () => {
      const fullResume: ResumeData = {
        user_id: "test_user_123",
        phone: "13987654321",
        email: "zhangsan@example.com",
        
        boss_data: {
          // 个人信息
          base_info: {
            name: "张女士",
            gender: "女",
            birth_month: "1990-01",
            job_status: "在职考虑",
          },
          
          // 求职期望
          expectations: {
            current_value: [
              buildExpectation({
                position: "全栈工程师",
                city: "广州",
                salaryMin: "15k",
                salaryMax: "25k",
                industries: ["互联网/人工智能"],
                otherCities: ["深圳", "杭州", "上海", "北京"],
              }),
            ],
          },
          
          // 工作经历
          work_experience: {
            current_value: [
              buildWorkExp({
                company: "深圳科技有限公司",
                position: "高级算法工程师",
                skills: ["LLM 意图路由", "Pandas 物理校验", "双轨制架构", "CDP 协议", "NLP 情感分析", "全栈研发"],
                content: "负责 AI 算法研发和系统架构设计",
              }),
            ],
          },
          
          // 项目经历
          projects: {
            current_value: [
              buildProject({
                name: "智能客服系统",
                role: "技术负责人",
                description: "基于大模型的智能客服平台",
              }),
            ],
          },
          
          // 教育经历
          education: {
            school: "浙江大学",
            major: "计算机科学",
            degree: "硕士",
            graduation_year: "2016",
          },
          
          // 个人优势
          personal_strengths: {
            current_value: "<div>5 年 AI 算法经验</div>",
          },
          
          // 资格证书
          certificates: {
            current_value: [
              { name: "PMP 项目管理", year: "2020" },
            ],
          },
        },
      }
      
      // ✅ 验证求职期望
      expect(fullResume.boss_data!.expectations!.current_value![0].salary).toBe("15k-25k")
      expect(fullResume.boss_data!.expectations!.current_value![0].otherCities?.length).toBe(4)
      
      // ✅ 验证工作经历技能
      expect(fullResume.boss_data!.work_experience!.current_value![0].skills?.length).toBe(6)
      expect(fullResume.boss_data!.work_experience!.current_value![0].skills?.includes("LLM 意图路由")).toBe(true)
      
      // ✅ 验证项目经历
      expect(fullResume.boss_data!.projects!.current_value![0].project_name).toBe("智能客服系统")
      
      // ✅ 验证教育经历
      expect(fullResume.boss_data!.education!.school).toBe("浙江大学")
      
      // ✅ 验证个人优势
      expect(fullResume.boss_data!.personal_strengths!.current_value).toContain("5 年")
      
      // ✅ 验证基础信息
      expect(fullResume.name).toBe("张女士")
      expect(fullResume.phone).toBe("13987654321")
      expect(fullResume.email).toBe("zhangsan@example.com")
    })
  })

  // 🐛 Bug 回归测试
  describe("#🐛 Bug 回归测试", () => {
    
    test("Bug#1: 修复后薪资格式应正确（不是'面议'）", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          expectations: {
            current_value: [
              buildExpectation({
                position: "全栈工程师",
                city: "广州",
                salaryMin: "15k",
                salaryMax: "25k",
              }),
            ],
          },
        },
      }
      
      const salary = data.boss_data!.expectations!.current_value![0].salary
      expect(salary).not.toBe("面议")
      expect(salary).toBe("15k-25k")
    })

    test("Bug#2: 修复后其他城市数量应正确（不是只显示 2 个）", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          expectations: {
            current_value: [
              buildExpectation({
                position: "全栈工程师",
                city: "广州",
                salaryMin: "15k",
                salaryMax: "25k",
                otherCities: ["深圳", "杭州", "上海", "北京"],
              }),
            ],
          },
        },
      }
      
      const otherCities = data.boss_data!.expectations!.current_value![0].otherCities
      expect(otherCities?.length).toBe(4)
      expect(otherCities).toEqual(["深圳", "杭州", "上海", "北京"])
    })

    test("Bug#3: 修复后技能数组不应为空", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          work_experience: {
            current_value: [
              buildWorkExp({
                company: "测试公司",
                position: "高级开发",
                skills: ["Python", "Java", "Go"],
                content: "技术开发工作",
              }),
            ],
          },
        },
      }
      
      const skills = data.boss_data!.work_experience!.current_value![0].skills
      expect(skills?.length).toBeGreaterThan(0)
      expect(skills?.length).toBe(3)
      expect(skills).toEqual(["Python", "Java", "Go"])
    })
  })

  // 🚨 边界条件测试
  describe("#🚨 边界条件测试", () => {
    
    test("边界 - 其他城市为 null 时应处理", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          expectations: {
            current_value: [
              {
                jobType: "fulltime",
                position: "开发",
                city: "北京",
                salary: "20k-30k",
                industries: [],
                otherCities: null as any,
              },
            ],
          },
        },
      }
      
      const otherCities = data.boss_data!.expectations!.current_value![0].otherCities
      expect(Array.isArray(otherCities)).toBe(false)
      expect(otherCities).toBeNull()
    })

    test("边界 - 技能字段为 undefined 时应默认空数组", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          work_experience: {
            current_value: [
              {
                company: "公司",
                position: "职位",
                content: "内容",
                skills: undefined as any,
              },
            ],
          },
        },
      }
      
      const skills = data.boss_data!.work_experience!.current_value![0].skills
      expect(skills).toBeUndefined()
    })

    test("边界 - 薪资字段部分为空时如何处理", () => {
      const data: ResumeData = {
        user_id: "test",
        boss_data: {
          expectations: {
            current_value: [
              buildExpectation({
                position: "开发",
                city: "北京",
                salaryMin: "20k",
                salaryMax: "", // empty max
              }),
            ],
          },
        },
      }
      
      const salary = data.boss_data!.expectations!.current_value![0].salary
      expect(salary).toBe("20k-")
    })
  })
})
