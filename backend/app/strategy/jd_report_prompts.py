"""JD 画像报告的输出模板与写前校验（2026-10-12 从 jd_report_service 拆出，守 500 行红线）。

「详细核对版」格式契约（用户 2026-10-12 需求）：
- 四分类条目式（禁表格），每条 = 能力项（X/Y 岗位）+ 公约数详描（保留 JD 原文细节）
  + 差异与例外 + 来源标记〔来源:编号,编号〕；
- 业务经验章末强制「行业分布」小节（穷举行业，禁举例式写法）；
- 每章末「散点要求」收录未成公约数但有核对价值的要求；
- 末节固定「画像一句话总结」（同时是尾部截断的校验特征）。

来源标记协议（与前端 jd-report-dialog.tsx 的 JDSRC 预处理两端闭合）：
- LLM 只允许输出半角数字 + 半角逗号（〔来源:1,5,16〕），禁止「等 N 个」/全角标点进标记；
- 前端正则对全角冒号/逗号容错，编号在 meta.sample_jobs 查不到时降级纯文本。

上下文预算：PER_JD_CHARS=4000 × 20 样本 ≈ 8 万字符 ≈ 40-60k tokens 输入，
画像生成要求模型上下文 ≥128k；Context Exceeded 类错误原样透出给弹窗（用户可自行
换模型），不做运行时静默截样本——静默截样本会伤害画像代表性，宁可信失败。
"""

import re

_REPORT_MIN_CHARS = 200
# 尾部截断特征：prompt 模板固定末节，报告被 max_tokens 截断时必缺
_CLOSING_SECTION = "画像一句话总结"
# 「附：下游速览」：供下游 LLM 消费的精简版区块（详见 split_brief）
BRIEF_SECTION = "附：下游速览"
_REQUIRED_SECTIONS = (
    "硬技能", "软技能", "业务经验", "加分项", "行业分布", _CLOSING_SECTION, BRIEF_SECTION,
)
# 来源标记（LLM 输出形态）；「来 源」间空格与全角冒号/逗号容错与前端 annotateJdSources 同口径
SOURCE_MARKER_PATTERN = re.compile(r"〔\s*来\s*源\s*[:：]\s*([0-9,，\s]+)〕")
_BRIEF_HEADING_RE = re.compile(r"^#{1,3}\s*附[：:]\s*下游速览\s*$", re.M)

_SYSTEM_PROMPT_TEMPLATE = (
    "你是一个顶级的互联网大厂人才招聘专家。以下是若干候选岗位的 JD（职位描述）样本，"
    "你的任务是把它们整合成一份「可逐条核对 JD 要求」的详细能力画像报告。\n"
    "\n"
    "【输出格式（严格遵守）】\n"
    "# （自拟的报告标题）\n"
    "（一段样本构成说明：共提炼 X 条 A 级 + Y 条 B 级岗位，覆盖哪些岗位族群/行业）\n"
    "\n"
    "## 一、硬技能\n"
    "## 二、软技能\n"
    "## 三、业务经验\n"
    "（本章末尾必须有「### 行业分布」小节）\n"
    "## 四、加分项\n"
    "## 画像一句话总结\n"
    "## 附：下游速览\n"
    "（本区块供系统内部其他 LLM 引用，人工阅读以上正文即可）\n"
    "\n"
    "【每个条目的固定结构】（章内按出现频次降序）\n"
    "**能力项名称**（X/Y 岗位）\n"
    "公约数详细描述：把各 JD 对这一项的具体要求去重合并——重复的要求只写一次，"
    "但必须保留工具名、方法名、框架名、年限门槛、量化指标等原文细节，"
    "严禁泛化成「熟悉 XX」一句话。\n"
    "*差异与例外：各 JD 对这一项要求不一致的地方逐条列出（完全一致可省略本行）。*\n"
    "〔来源:1,5,16〕\n"
    "\n"
    "【硬性规则】\n"
    "1. 来源标记格式严格为〔来源:1,5,16〕：只允许半角数字和半角逗号，"
    "最多列 5 个代表性岗位的样本编号（编号见各样本标题）；"
    "标记内禁止出现「等 N 个」或其他任何文字。\n"
    "2. 业务经验章末的「### 行业分布」：穷举样本 JD 中出现的全部具体行业/领域"
    "（电商、医药、游戏、客服、供应链、金融等以实际 JD 为准），"
    "每个领域给出出现岗位数 + JD 对该领域经验的具体要求描述；"
    "禁止「如电商、医药等」举例式写法。\n"
    "3. 不重复但值得核对价值的要求（只有个别岗位提到），写入该章末尾的"
    "「散点要求」小节：每条注明来源岗位编号，最多 8 条。\n"
    "4. 频次 X/Y = 出现该要求的岗位数 / 样本岗位总数。\n"
    "5. 禁止开场白与过程叙述（如「好的，作为一名…」），第一行必须是 # 标题；禁止使用表格。\n"
    "6. 层级权重：A 级岗位为核心样本，画像必须覆盖其共性；B 级岗位仅作辅助印证与补充，"
    "与 A 级信号冲突时以 A 级为准。\n"
    "7. 末尾的「附：下游速览」区块（≤1200 字，禁止来源标记，不要复述正文细节）：\n"
    "- 硬技能：<Top 3-5 能力项，每项一句话概括核心要求>\n"
    "- 软技能：<同上>\n"
    "- 业务经验：<同上，并注明主要行业：xx/xx/xx>\n"
    "- 加分项：<Top 3>\n"
)


def build_system_prompt(a_count: int) -> str:
    prompt = _SYSTEM_PROMPT_TEMPLATE
    if a_count == 0:
        prompt += (
            "\n【冷启动说明】当前样本全部为 B 级岗位：报告标题须注明「基于 B 级岗位的冷启动画像」，"
            "并在「画像一句话总结」末尾提示用户给优质岗位补上 A 级评级后重新生成。\n"
        )
    return prompt


def validate_report(text: str) -> tuple[bool, str]:
    """写前质量校验：绝不把空值/乱码/偷懒简写/截断文本写库。

    旧实现 LLM 返回空会静默清空既有画像（2026-10-11 修复）；本版新增
    分类齐备 + 行业分布 + 末节特征三闸——拦住 LLM 偷懒返回简略版与
    max_tokens 尾部截断（截断时「画像一句话总结」必缺）。
    """
    stripped = (text or "").strip()
    if not stripped:
        return False, "AI 返回空内容"
    if len(stripped) < _REPORT_MIN_CHARS:
        return False, f"内容过短（{len(stripped)} < {_REPORT_MIN_CHARS} 字）"
    first_line = next((ln for ln in stripped.splitlines() if ln.strip()), "")
    if first_line.startswith("❌"):
        return False, "AI 返回了错误标记而非报告"
    if not first_line.lstrip().startswith("#"):
        return False, f"未以 Markdown 标题开头（首行：{first_line[:40]!r}）"
    missing = [s for s in _REQUIRED_SECTIONS if s not in stripped]
    if missing:
        return False, f"缺少必需章节：{'、'.join(missing)}"
    return True, ""


def extract_source_indices(text: str) -> list[list[int]]:
    """提取报告中全部来源标记的编号组（供测试与未来后端侧校验复用）。"""
    groups: list[list[int]] = []
    for m in SOURCE_MARKER_PATTERN.finditer(text):
        try:
            groups.append([int(n) for n in re.findall(r"\d+", m.group(1))])
        except ValueError:
            continue
    return groups


def split_brief(report_text: str) -> tuple[str, str]:
    """把「附：下游速览」区块从报告尾部拆出，返回 (value, brief) 双轨：

    - value：完整详细报告（不含速览区块）——弹窗展示、飞书镜像、本地落库；
    - brief：速览区块正文（去标题、清理来源标记）——get_global_jd_report()
      返回给全部下游 LLM 消费方，注入量从 ~10-15k tokens 降到 ~2k。

    无区块（旧报告/LLM 漏写被硬闸拦截前的历史数据）→ brief=""，调用方回退 value。
    """
    text = report_text or ""
    m = _BRIEF_HEADING_RE.search(text)
    if not m:
        return text.strip(), ""
    value = text[: m.start()].rstrip()
    value = re.sub(r"\n---\s*$", "", value).rstrip()  # 速览前若有分隔线一并去掉
    brief = text[m.end() :].strip()
    brief = SOURCE_MARKER_PATTERN.sub("", brief).strip()  # 速览不应携带来源标记
    return value, brief
