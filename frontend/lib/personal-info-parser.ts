export interface PersonalInfoField {
  id: string;
  label: string;
  value: string;
}

export interface PersonalInfo {
  name: string;
  jobTitle: string;
  fields: PersonalInfoField[];
}

export const DEFAULT_PERSONAL_INFO: PersonalInfo = {
  name: "您的姓名",
  jobTitle: "求职意向/职位名称",
  fields: [
    { id: "phone", label: "电话", value: "13800000000" },
    { id: "email", label: "邮箱", value: "your@email.com" },
    { id: "wechat", label: "微信", value: "wechat_id" },
    { id: "github", label: "个人主页", value: "https://github.com/yourname" },
  ],
};

/**
 * Parses the raw Markdown text under the "# 个人信息" header.
 */
export function parsePersonalInfo(markdown: string): PersonalInfo {
  const result: PersonalInfo = {
    name: "",
    jobTitle: "",
    fields: [],
  };

  if (!markdown) return DEFAULT_PERSONAL_INFO;

  const lines = markdown.split("\n");
  let fieldCounter = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    // Matches bullet points like "- **姓名**：张三" or "- 电话: 13800" or just "邮箱：xx"
    const match = trimmed.match(/^(?:[-*]\s*)?(?:\*\*)?([^:*：]+)(?:\*\*)?[:：]\s*(.*)$/);
    
    if (match) {
      const label = match[1].trim();
      const value = match[2].trim();

      if (label === "姓名") {
        result.name = value;
      } else if (label === "求职意向" || label === "意向岗位") {
        result.jobTitle = value;
      } else {
        result.fields.push({
          id: `field-${Date.now()}-${fieldCounter++}`,
          label,
          value,
        });
      }
    } else {
      // If it doesn't match the standard bullet format, but contains Name
      if (trimmed.includes("姓名：")) {
        result.name = trimmed.split("姓名：")[1].trim();
      }
      // If it's just raw text, we could potentially try to parse it, 
      // but for now, we rely on the standard bullet list format.
    }
  }

  // Fallback defaults if empty
  if (!result.name) result.name = DEFAULT_PERSONAL_INFO.name;
  if (!result.jobTitle) result.jobTitle = DEFAULT_PERSONAL_INFO.jobTitle;

  return result;
}

/**
 * Serializes the PersonalInfo object back to standard Markdown.
 */
export function serializePersonalInfo(info: PersonalInfo): string {
  const lines: string[] = [];
  
  if (info.name) {
    lines.push(`- **姓名**：${info.name}`);
  }
  if (info.jobTitle) {
    lines.push(`- **求职意向**：${info.jobTitle}`);
  }
  
  for (const field of info.fields) {
    if (field.label && field.value) {
      lines.push(`- **${field.label}**：${field.value}`);
    }
  }
  
  return lines.join("\n");
}
