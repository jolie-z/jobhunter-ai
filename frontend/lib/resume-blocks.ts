// 简历模块纯函数与类型（从 use-strategy-store.tsx 拆出，Q-M4-6 行数治理）
// store 通过 re-export 保持兼容导入路径

export type ResumeSubModule = {
    id: string;
    title: string;
    content: string;
}

export type ResumeModule = {
    id: string;
    type: 'basic' | 'experience';
    title: string;
    content?: string;
    subModules?: ResumeSubModule[];
}

let _blockIdCounter = 0;
export const genResumeBlockId = () => `blk-${Date.now()}-${++_blockIdCounter}`;

export function parseMarkdownToBlocks(md: string): ResumeModule[] {
    if (!md || !md.trim()) return [];
    const blocks: ResumeModule[] = [];
    const lines = md.split('\n');

    let currentBlock: ResumeModule | null = null;
    let currentSubModule: ResumeSubModule | null = null;

    for (const rawLine of lines) {
        const line = rawLine.trim();

        // 🌟 跳过历史序列化产生的 `****` 伪分割线；`---` 是合法的 Markdown 分隔线，
        // 保留为正文，避免用户真实内容在「解析→序列化」往返中被静默丢弃
        if (line === '****') {
            continue;
        }

        // 匹配一级标题 (兼容 '# 标题' 和 '#标题')
        if (line.startsWith('# ') || (line.startsWith('#') && !line.startsWith('##'))) {
            if (currentBlock) {
                blocks.push(currentBlock);
            }

            const title = line.startsWith('# ') ? line.substring(2).trim() : line.substring(1).trim();
            const type = (title.includes('经历') || title.includes('项目') || title.includes('工作')) ? 'experience' : 'basic';

            currentBlock = {
                id: genResumeBlockId(),
                type,
                title,
                content: '',
                subModules: type === 'experience' ? [] : undefined
            };
            currentSubModule = null; // 重置子模块
            continue;
        }

        if (!currentBlock) {
            // 忽略开头的无用空行
            if (!line) continue;
            currentBlock = {
                id: genResumeBlockId(),
                type: 'basic',
                title: '未命名模块',
                content: ''
            };
        }

        // 匹配二级/三级标题或旧版抬头 (仅在 experience 模块下)
        if (currentBlock.type === 'experience') {
            let isSubTitle = line.startsWith('## ') || line.startsWith('### ');

            if (!isSubTitle) {
                if (!currentSubModule && line !== '') {
                    // 兼容历史逻辑：如果还没有子模块，第一行非空文本作为第一个子模块标题
                    isSubTitle = true;
                } else if (/^\*\*.+?\*\*$/.test(line)) {
                    // 两全其美的启发式判断（解决加粗小标题被误切分的问题）：
                    // 如果一行完全被 ** 包裹，且包含简历抬头的典型特征（如 '·', '|', ' - ' 或年份 '20xx'），
                    // 我们才将其判定为旧版的【公司经历抬头】并切分。
                    // 否则，它仅仅是当前经历中的【普通段落小标题】（如 **项目亮点**），作为普通内容追加。
                    if (line.includes('·') || line.includes('|') || line.includes(' - ') || /\b20\d{2}\b/.test(line)) {
                        isSubTitle = true;
                    }
                }
            }

            if (isSubTitle) {
                let subTitle = line;
                subTitle = subTitle.replace(/^#{2,3}\s*/, '').replace(/^-\s*/, '');
                if (subTitle.startsWith('**') && subTitle.endsWith('**')) {
                    subTitle = subTitle.substring(2, subTitle.length - 2).trim();
                }
                subTitle = subTitle.replace(/：$/, '').replace(/:$/, '');

                currentSubModule = {
                    id: genResumeBlockId(),
                    title: subTitle || '未命名经历',
                    content: ''
                };
                currentBlock.subModules!.push(currentSubModule);
                continue;
            }
        }

        // 追加内容
        if (currentBlock.type === 'experience' && currentSubModule) {
            currentSubModule.content = currentSubModule.content ? currentSubModule.content + '\n' + rawLine : rawLine;
        } else {
            currentBlock.content = currentBlock.content ? currentBlock.content + '\n' + rawLine : rawLine;
        }
    }

    if (currentBlock) {
        blocks.push(currentBlock);
    }

    // 后处理：清理首尾空行
    for (const block of blocks) {
        if (block.content) block.content = block.content.trim();
        if (block.subModules) {
            for (const sub of block.subModules) {
                if (sub.content) sub.content = sub.content.trim();
            }
        }
    }

    return blocks;
}

export function serializeBlocksToMarkdown(blocks: ResumeModule[]): string {
    return blocks.map(block => {
        if (block.type === 'experience' && block.subModules) {
            const subs = block.subModules.map(sub => {
                const header = sub.title ? `## ${sub.title}` : '';
                return [header, sub.content].filter(Boolean).join('\n');
            }).join('\n\n');
            return `# ${block.title}\n\n${subs}`;
        } else {
            return `# ${block.title}\n\n${block.content || ''}`;
        }
    }).join('\n\n');
}

// 🌟 定义一套标准的默认简历 Markdown 模板
export const DEFAULT_RESUME_MARKDOWN = `# 个人信息
姓名：张三
手机：138-0000-0000
邮箱：zhangsan@example.com
求职意向：前端开发工程师

# 个人总结
用一段话概括你的核心优势、专业能力与职业亮点...

# 专业技能
例如：React / Next.js / TypeScript / Node.js / Figma（可换行或用顿号分隔）

# 工作经历
## 公司名称 · 职位 · 2023.09 - 2024.03
描述你的职责、成果与亮点...

# 项目经历
## 项目名称 · 担任角色 · 2023.09 - 2024.03
描述你的项目职责、成果与亮点...

# 教育背景
学校名称 · 专业/学位 · 2019.09 - 2023.06`;
