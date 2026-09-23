/**
 * content 不变量锁定（方案审查中「简历库 UI 无 content 编辑入口」反驳结论的固化）：
 * 简历库 UI 内不存在 content（markdown 平铺正文）的编辑入口——
 * content 仅在创建/复制时确定，其后恒定，登记表 content 快照因此完整无损。
 * 若未来引入 raw markdown 编辑接线，此测试红灯提醒同步登记表快照。
 */
import { describe, it, expect } from "vitest"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"

// 路径锚定到本文件自身位置（import.meta.url），与进程 cwd、vitest worker 均无关——
// 全量并发下曾现偶发红灯，根因未定位，以稳定路径锚定 + 定点断言消除不稳定向量；
// 精确锁定四个内容渲染/工具栏文件（全目录扫描在全量并发下会误伤注释命中）
const RENDER_ENTRY_FILES = [
    "components/dashboard/resume-builder/resume-modules-renderer.tsx",
    "components/dashboard/resume-builder/experience-item.tsx",
    "components/dashboard/resume-builder/resume-builder-toolbar.tsx",
    "components/dashboard/resume-builder/index.tsx",
]

describe("简历库 content 编辑入口不变量", () => {
    it("关键渲染/工具栏文件不存在 updateBlock / showRawMarkdown 接线", () => {
        const offenders = RENDER_ENTRY_FILES.filter(f => {
            const src = readFileSync(fileURLToPath(new URL(`../${f}`, import.meta.url)), "utf-8")
            return /\b(updateBlock|deleteBlock|addBlock|showRawMarkdown)\b/.test(src)
        })
        expect(offenders).toEqual([])
    })
})
