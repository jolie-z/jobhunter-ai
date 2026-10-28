import fs from "node:fs"
import path from "node:path"

/**
 * 构建身份自报家门：桌面壳附着同端口前端前，用它核对「运行中进程」与「磁盘 .next」
 * 是否同一构建。核心在模块加载时快照——next start 启动即固化；若进程是上一版本
 * 残留的僵尸（磁盘 .next 已被新版安装包覆盖），这里报出的仍是旧 BUILD_ID，壳据此
 * 拒绝附着、另起端口拉新服务。否则僵尸的旧内存清单会引用已被覆盖的 CSS/JS chunk
 * （404），globals.css 丢失 → Tailwind preflight/工具类全失效 → box-sizing 退回
 * content-box，打印页/PDF 右侧溢出排版全毁（2026-10-09 用户报修根因）。
 */
const BUILD_ID = (() => {
  try {
    return fs.readFileSync(path.join(process.cwd(), ".next", "BUILD_ID"), "utf8").trim()
  } catch {
    return "dev"
  }
})()

export const dynamic = "force-dynamic"

export async function GET() {
  return Response.json({ buildId: BUILD_ID })
}
