export interface Agent1Decision {
  decision: "keep" | "cut"
  reason: string
  matchedPoints?: string[]
}

export interface Agent2Rewrite {
  logic: string
  dataRequests: string[]
}

export interface Agent3QA {
  status: "pass" | "warn"
  message: string
}

export interface AiNotes {
  agent1: Agent1Decision
  agent2?: Agent2Rewrite
  agent3?: Agent3QA
}

export type BlockMode = "diff" | "cut" | "editable"

export interface ResumeBlock {
  id: string
  title: string
  mode: BlockMode
  original: string
  notes?: AiNotes
  rewritten?: string
}

export interface ResumeModule {
  id: string
  title: string
  blocks: ResumeBlock[]
}

export function adapterJobToModules(job: any, fallbackText: string = ""): ResumeModule[] {
  if (!job) return [];
  // 安全判定 isRaw，支持严格 TS
  const isRaw = !job.aiRewriteJson || (typeof job.aiRewriteJson === 'string' ? job.aiRewriteJson.trim() === "" : Object.keys(job.aiRewriteJson as any).length === 0);

  // 1. 提取真实的简历长文本作为底料：优先取手动改写版 -> 其次取大盘默认启用的简历 -> 兜底空提示
  let sourceText = "";
  if (isRaw) {
    sourceText = job.manualRefinedResume || fallbackText || "暂无简历数据，请开始编辑...";
  } else {
    sourceText = typeof job.aiRewriteJson === 'string' ? job.aiRewriteJson : JSON.stringify(job.aiRewriteJson);
  }

  // 2. 动态 Markdown 切割引擎：按一级标题切分
  const sections = sourceText.split(/(?=^#\s+[^#\n])/m).filter(s => s.trim());
  if (sections.length === 0) {
    // 🌟 修复：明确指定对象为 ResumeBlock 类型，防止类型推导为普通 string
    const defaultBlock: ResumeBlock = {
      id: `blk-default`, title: "内容", mode: "diff",
      original: sourceText, rewritten: sourceText
    };
    return [{ id: `cat-default`, title: "简历内容", blocks: [defaultBlock] }];
  }

  return sections.map((sec, i) => {
    const lines = sec.split('\n');
    const title = lines[0].replace(/^#\s*/, '').trim();
    let content = lines.slice(1).join('\n').trim();

    // 🌟 彻底安全清洗处理历史分割线
    content = content.replace(/^(\*{3,4}|-{3,4})\s*\n*/, '').trim();

    if (title.includes("经历") || title.includes("项目")) {
      // 🌟 兼容 `#` 二级标题和配置大盘特有的 `**` 加粗子标题
      const subSections = content.split(/(?=^\*\*.*?\*\*\n)|(?=^##\s+[^#\n])/m).filter(s => s.trim());
      if (subSections.length > 0) {
        // 🌟 修复：明确 map 返回的每一项为 ResumeBlock 类型
        const blocks = subSections.map((sub, j): ResumeBlock => {
          const subLines = sub.split('\n');
          // 清理标题周围的标记
          const subTitle = subLines[0].replace(/^##\s*/, '').replace(/^\*\*/, '').replace(/\*\*$/, '').trim();
          const subContent = subLines.slice(1).join('\n').trim();
          return {
            id: `blk-${i}-${j}`, title: subTitle || "经历条目", mode: "diff",
            original: isRaw ? subContent : "原始简历文本(待AI拆解补充)...",
            notes: isRaw ? undefined : { agent1: { decision: "keep", reason: "强匹配当前岗位 JD，予以保留并精修。" } },
            rewritten: isRaw ? "" : subContent
          }
        });
        return { id: `cat-${i}`, title, blocks };
      }
    }

    // 🌟 修复：明确指定兜底块为 ResumeBlock 类型
    const fallbackBlock: ResumeBlock = {
      id: `blk-${i}-0`, title, mode: "diff",
      original: isRaw ? content : "原始数据...",
      notes: isRaw ? undefined : { agent1: { decision: "keep", reason: "强匹配当前岗位 JD，予以保留并精修。" } },
      rewritten: isRaw ? "" : content
    };

    return {
      id: `cat-${i}`, title,
      blocks: [fallbackBlock]
    };
  });
}