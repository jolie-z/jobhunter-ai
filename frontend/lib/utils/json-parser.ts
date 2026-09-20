// 🌟 全局极其坚固的 JSON 解析器
export function safeParseJSON(raw: string | null | undefined): any {
  if (!raw) return null;
  const t = String(raw).trim();
  if (!t) return null;

  // 🌟 新增：如果字符串显然不是 JSON（不是以 { 或 [ 开头），直接返回原字符串
  // 这样可以防止 JSON.parse 碰到 Markdown 的 # 号报错
  if (!t.startsWith('{') && !t.startsWith('[') && !t.startsWith('`')) {
    return t;
  }

  try {
    return JSON.parse(t);
  } catch (e) {
    const backticks = "\x60\x60\x60";
    const r1 = new RegExp("^" + backticks + "(?:json)?\\s*", "i");
    const r2 = new RegExp("\\s*" + backticks + "\\s*$");
    const stripped = t.replace(r1, "").replace(r2, "").trim();
    try {
      return JSON.parse(stripped);
    } catch (e2) {
      // 🌟 核心改进：如果 JSON 解析彻底失败，且包含 # 号，说明它可能是纯文本/Markdown
      if (t.includes('#')) {
        return t;
      }
      console.warn("❌ JSON解析彻底失败:", e2);
      return null;
    }
  }
}
