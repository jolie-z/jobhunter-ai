/**
 * 本地时间串工具
 * ==============
 * 与后端快照 / SQLite 的 "YYYY-MM-DD HH:mm:ss" 保持同格式同基准（浏览器本地时钟）。
 * 前端乐观写入 last_action_time 后要立刻参与看板置顶排序：若用 ISO（UTC），
 * 会与后端本地时间串混排时差 8 小时，卡片排序会跳到错误位置，直到下一跳快照矫正。
 */
export function nowLocalString(date: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0")
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} ${p(date.getHours())}:${p(date.getMinutes())}:${p(date.getSeconds())}`
}
