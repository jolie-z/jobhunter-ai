import { describe, it, expect } from "vitest";
import { parseResumeData } from "@/lib/utils/resume-parser";
import { resumeDataToResumeDataV2 } from "@/lib/resume-converter";

// 新版 Skill（resume_rewrite）输出的 markdown 形态：## 模块 + ### 条目 + 加粗字段行
const NEW_SKILL_MD = `## 💡 个人总结
**AI系统架构**：独立负责交付5项业务级AI SaaS产品，具备全链路落地能力

## 🛠️ 核心技能
**大模型与自动化**：OpenAI API、LangGraph、RPA

## 🏢 工作经历
### AI业务运营 / 智能客服训练师 (某美妆集团) (2019.07-2023.08)
- **负责**智能客服系统优化与问答模型搭建

### 独立AI应用开发者 / 全栈研发 (2024.04-至今)
- **负责**技术体系重塑与AI辅助编程实践

## 🚀 项目经历
### 全渠道库存自动化核销中台 (MVP) (2026.02)
- 针对电商库存核算难题独立设计并开发此中台

## 🎓 教育背景
- 某财经类大学 - 社会工作 - 全日制本科 (2015.07-2019.07)`;

describe("新版 Skill markdown → V2 结构化渲染", () => {
  it("工作/项目/教育条目应拆入固定字段而非挤成一坨", () => {
    const v1 = parseResumeData(NEW_SKILL_MD);
    expect(v1).not.toBeNull();
    const v2 = resumeDataToResumeDataV2(v1!);

    expect(v2.summary).toContain("AI系统架构");

    expect(v2.workExperience).toHaveLength(2);
    const job1 = v2.workExperience![0];
    expect(job1.company).toBe("某美妆集团");
    expect(job1.title).toBe("AI业务运营 / 智能客服训练师");
    expect(job1.years).toBe("2019.07-2023.08");
    expect(job1.description.join("")).toContain("智能客服系统优化");
    expect(v2.workExperience![1].years).toBe("2024.04-至今");

    expect(v2.personalProjects).toHaveLength(1);
    expect(v2.personalProjects![0].name).toBe("全渠道库存自动化核销中台 (MVP)");
    expect(v2.personalProjects![0].years).toBe("2026.02");

    expect(v2.education).toHaveLength(1);
    expect(v2.education![0].institution).toBe("某财经类大学");
    expect(v2.education![0].major).toBe("社会工作");
    expect(v2.education![0].degree).toBe("全日制本科");
    expect(v2.education![0].years).toBe("2015.07-2019.07");

    expect(v2.additional.technicalSkills.join("")).toContain("LangGraph");
  });
});
