import { describe, it, expect } from "vitest"
import { parseJobDescription } from "../lib/utils/job-description"

const LIEPIN_FLATTENED =
  "园区有到地铁站的巴士，七八分钟即可到达公司，方便又舒适。 C# Web 全栈开发工程师 岗位职责： " +
  "1、负责智能相机产品研发、图像与视频流采集、预处理及实时传输模块开发； " +
  "2、负责行为识别检测系统的前后端全栈开发，包括目标检测、姿态估计、异常行为分析等算法的工程化； " +
  "3、负责项目落地，与软件开发工程师、算法工程师实现接口对接。 任职要求： " +
  "1、软件工程、计算机类相关专业本科以上学历，熟悉C# Web Mvc开发，熟悉 .NET Core、.NET 6 或 .NET 8 等 Web api 应用开发技术框架，3年以上相关经验，具备从需求分析到系统上线的端到端交付能力； " +
  "2、熟悉 Vibe Coding，了解 Claude Code、Trae 等 Agent 编程工具； " +
  "3、熟悉 HTML5、JavaScript、CSS 等前端基础知识，掌握 Vue、Element UI、Naive UI 等前端技能； " +
  "4、熟练使用 Microsoft SQL Server、MySQL 等数据库，以及相关的 ORM 框架； " +
  "5、了解 Python 语言，熟悉模型训练的相关概念和知识者优先。 " +
  "6、有计算机视觉/行为识别项目经验者优先，熟悉工业相机SDK（海康、Basler、大恒等）或视频流协议（RTSP、GigEVision），有图像采集与实时处理经验者优先。 " +
  "7、熟悉AI Agent 架构，具备大模型应用开发经验者优先。 " +
  "8、具有主动意识并独立解决问题的能力，能够承受较大的工作压力，有较强的责任心和事业心； " +
  "9、有较强的学习能力，有创新意识、对新技术应用感兴趣；性格开朗、热情，有良好的团队协作能力。"

describe("parseJobDescription", () => {
  it("把猎聘整行塌缩的 JD 还原为标题 + 编号条目", () => {
    const blocks = parseJobDescription(LIEPIN_FLATTENED)

    const headings = blocks.filter((b) => b.kind === "heading").map((b) => b.text)
    expect(headings).toEqual(["岗位职责", "任职要求"])

    const firstSection = blocks.findIndex((b) => b.kind === "heading" && b.text === "岗位职责")
    const secondSection = blocks.findIndex((b) => b.kind === "heading" && b.text === "任职要求")
    expect(firstSection).toBeGreaterThanOrEqual(0)
    expect(secondSection).toBeGreaterThan(firstSection)

    const dutyItems = blocks.slice(firstSection + 1, secondSection).filter((b) => b.kind === "item")
    expect(dutyItems.map((b) => (b.kind === "item" ? b.marker : ""))).toEqual(["1", "2", "3"])
    expect(dutyItems[0].kind === "item" && dutyItems[0].text).toContain("智能相机产品研发")

    const requirementItems = blocks.slice(secondSection + 1).filter((b) => b.kind === "item")
    expect(requirementItems).toHaveLength(9)
    expect(requirementItems[0].kind === "item" && requirementItems[0].text).toContain("软件工程")
    expect(requirementItems[8].kind === "item" && requirementItems[8].text).toContain("团队协作能力")

    // 开头的公司介绍与岗位名保留为段落，而不是并进第一条
    const first = blocks[0]
    expect(first.kind).toBe("paragraph")
    expect(first.kind === "paragraph" && first.text).toContain("园区有到地铁站的巴士")
  })

  it("保留已有换行文本，并识别「一、岗位职责」式标题", () => {
    const blocks = parseJobDescription(
      [
        "一、岗位职责",
        "1. AI Agent 开发：基于大模型、MCP、API 等技术，开发企业级 AI Agent 和自动化应用。",
        "2. AI 全栈开发：熟练使用 Codex、Claude Code 等 AI 编程工具。",
        "二、任职要求",
        "1. 开发能力：熟悉 Java、Python、Node。",
      ].join("\n")
    )

    expect(blocks.map((b) => b.kind)).toEqual([
      "heading",
      "item",
      "item",
      "heading",
      "item",
    ])
    expect(blocks[0]).toEqual({ kind: "heading", text: "一、岗位职责" })
    expect(blocks[3]).toEqual({ kind: "heading", text: "二、任职要求" })
  })

  it("不把小数/版本号当成编号条目", () => {
    const blocks = parseJobDescription("薪资 1.5-2万，产品已迭代到 3.0 版本。")
    expect(blocks).toHaveLength(1)
    expect(blocks[0].kind).toBe("paragraph")
  })

  it("不把「3年以上经验」这类正文当成条目", () => {
    const blocks = parseJobDescription("3年以上相关经验，熟悉 .NET 6 或 .NET 8。")
    expect(blocks).toHaveLength(1)
    expect(blocks[0].kind).toBe("paragraph")
  })

  it("正文里的「岗位职责」字样不误判为标题", () => {
    const blocks = parseJobDescription("本岗位职责包含跨团队协作与交付。")
    expect(blocks).toHaveLength(1)
    expect(blocks[0].kind).toBe("paragraph")
  })

  it("支持（1）与带圈数字编号", () => {
    const blocks = parseJobDescription("任职要求：（1）本科以上学历；② 有项目经验。")
    expect(blocks[0]).toEqual({ kind: "heading", text: "任职要求" })
    expect(blocks.slice(1).map((b) => (b.kind === "item" ? b.marker : ""))).toEqual(["1", "②"])
  })

  it("去掉猎聘清洗后可能残留的行首冒号", () => {
    const blocks = parseJobDescription("： 1、负责服务端开发； 2、负责接口联调。")
    expect(blocks.map((b) => (b.kind === "item" ? b.marker : ""))).toEqual(["1", "2"])
  })

  it("识别【岗位职责】式方括号标题", () => {
    const blocks = parseJobDescription(
      "【岗位职责】 1、负责服务端开发； 2、负责接口联调。 【任职要求】 1、本科以上学历。"
    )
    expect(blocks.filter((b) => b.kind === "heading").map((b) => b.text)).toEqual([
      "岗位职责",
      "任职要求",
    ])
  })

  it("识别自由命名的中文序号章节（一、Agent设计与搭建）", () => {
    const blocks = parseJobDescription(
      "【职位概述】 一、Agent设计与搭建 1、深入业务一线，识别高频痛点。 2、设计工具调用逻辑。 " +
        "二、知识库建设与维护 1、制定数据清洗方案。"
    )
    expect(blocks.filter((b) => b.kind === "heading").map((b) => b.text)).toEqual([
      "职位概述",
      "一、Agent设计与搭建",
      "二、知识库建设与维护",
    ])
    expect(blocks.filter((b) => b.kind === "item").map((b) => (b.kind === "item" ? b.marker : ""))).toEqual([
      "1",
      "2",
      "1",
    ])
  })

  it("不把「一、二线城市」这类正文误判为章节标题", () => {
    const blocks = parseJobDescription("熟悉一、二线城市市场，能接受出差。")
    expect(blocks).toHaveLength(1)
    expect(blocks[0].kind).toBe("paragraph")
  })

  it("空文本返回空数组", () => {
    expect(parseJobDescription("")).toEqual([])
    expect(parseJobDescription("   ")).toEqual([])
    expect(parseJobDescription(undefined as unknown as string)).toEqual([])
  })
})
