import { describe, it, expect } from "vitest"
import {
  applyListStyle,
  hasListStylePrefix,
  GLYPH_BULLETS,
} from "../components/dashboard/resume-builder/bullet-style"

describe("hasListStylePrefix", () => {
  it("should recognize markdown list lines", () => {
    expect(hasListStylePrefix("- 要点")).toBe(true)
    expect(hasListStylePrefix("+ 要点")).toBe(true)
    expect(hasListStylePrefix("* 要点")).toBe(true)
    expect(hasListStylePrefix("1. 要点")).toBe(true)
    expect(hasListStylePrefix("1、要点")).toBe(true)
    expect(hasListStylePrefix("  - 缩进要点")).toBe(true)
  })

  it("should recognize glyph bullet lines", () => {
    expect(hasListStylePrefix("■ 实心方块要点")).toBe(true)
    expect(hasListStylePrefix("▸ 三角要点")).toBe(true)
    expect(hasListStylePrefix("➢ 箭头要点")).toBe(true)
    expect(hasListStylePrefix("· 中点要点")).toBe(true)
    for (const glyph of GLYPH_BULLETS) {
      expect(hasListStylePrefix(`${glyph} 要点`)).toBe(true)
    }
  })

  it("should recognize ordered style prefixes", () => {
    expect(hasListStylePrefix("一、中文编号")).toBe(true)
    expect(hasListStylePrefix("十二、中文编号")).toBe(true)
    expect(hasListStylePrefix("① 圆圈数字")).toBe(true)
    expect(hasListStylePrefix("⑫ 圆圈数字")).toBe(true)
    expect(hasListStylePrefix("a) 字母编号")).toBe(true)
    expect(hasListStylePrefix("B. 大写字母")).toBe(true)
  })

  it("should not treat body lines as list", () => {
    expect(hasListStylePrefix("负责核心微服务架构搭建")).toBe(false)
    expect(hasListStylePrefix("**要点**：加粗起头的正文行")).toBe(false)
    expect(hasListStylePrefix("○形图案设计经验")).toBe(false) // 无空格分隔的普通词
    expect(hasListStylePrefix("")).toBe(false)
  })
})

describe("applyListStyle", () => {
  it("should convert markdown lists to glyph bullets", () => {
    const md = "职责说明\n- 第一条要点\n- 第二条要点\n\n结尾行"
    expect(applyListStyle(md, "square")).toBe(
      "职责说明\n■ 第一条要点\n■ 第二条要点\n\n结尾行"
    )
  })

  it("should convert glyph bullets back to standard markdown list", () => {
    const md = "■ 第一条\n◆ 第二条\n正文"
    expect(applyListStyle(md, "disc")).toBe("- 第一条\n- 第二条\n正文")
  })

  it("should convert markdown list to numbered styles with per-block renumbering", () => {
    const md = "- 甲\n- 乙\n\n- 丙"
    expect(applyListStyle(md, "cn")).toBe("一、甲\n二、乙\n\n一、丙")
    expect(applyListStyle(md, "num")).toBe("1. 甲\n2. 乙\n\n1. 丙")
  })

  it("should convert circled and alpha numbering", () => {
    const md = "1. 甲\n2. 乙\n3. 丙\n4. 丁"
    expect(applyListStyle(md, "circled")).toBe("① 甲\n② 乙\n③ 丙\n④ 丁")
    expect(applyListStyle(md, "alpha")).toBe("a) 甲\nb) 乙\nc) 丙\nd) 丁")
  })

  it("must NOT treat date ranges or decimals as ordered list items (R1 P0 regression)", () => {
    const md = "2023.09 - 2024.08 某某公司\n负责核心业务\n99.9% 的准确率"
    // 时间区间与小数不是列表，应用样式必须原样保留
    expect(applyListStyle(md, "square")).toBe(md)
    expect(applyListStyle(md, "num")).toBe(md)
    expect(hasListStylePrefix("2023.09 - 2024.08 某某公司")).toBe(false)
    expect(hasListStylePrefix("99.9% 的准确率")).toBe(false)
    // 带空格的 `2023. 要点` 仍是合法 markdown 有序列表
    expect(hasListStylePrefix("2023. 年度总结")).toBe(true)
    // `1、要点` 中文顿号紧贴形式保留，但 4 位以上数字+顿号（如年份）不算
    expect(hasListStylePrefix("1、要点")).toBe(true)
    expect(hasListStylePrefix("2023、年度大事记")).toBe(false)
  })

  it("should renumber across mixed source prefixes within one block", () => {
    const md = "▸ 要点一\n1. 要点二\n一、要点三"
    expect(applyListStyle(md, "diamond")).toBe("◆ 要点一\n◆ 要点二\n◆ 要点三")
    expect(applyListStyle(md, "num")).toBe("1. 要点一\n2. 要点二\n3. 要点三")
  })

  it("should keep bold subtitle lines and plain body lines untouched", () => {
    const md = "**核心贡献**\n- 要点一\n- 要点二"
    expect(applyListStyle(md, "triangle")).toBe("**核心贡献**\n▸ 要点一\n▸ 要点二")
  })

  it("should preserve indentation of nested list lines", () => {
    const md = "- 顶层\n  - 嵌套"
    expect(applyListStyle(md, "circle")).toBe("○ 顶层\n  ○ 嵌套")
  })

  it("should return content unchanged for unknown style or empty input", () => {
    expect(applyListStyle("- 要点", "nope")).toBe("- 要点")
    expect(applyListStyle("", "square")).toBe("")
  })

  it("should not treat **bold** body line as list item", () => {
    const md = "**要点**：这是一个加粗起头的正文长行\n- 真要点"
    expect(applyListStyle(md, "square")).toBe(
      "**要点**：这是一个加粗起头的正文长行\n■ 真要点"
    )
  })
})
