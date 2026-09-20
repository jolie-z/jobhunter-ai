import asyncio
import os
import sys
from pathlib import Path

import common.config as _ccfg
from app.core.config import settings
from app.core.feishu_utils import extract_feishu_text

# 🌟 核心修复：LLM 客户端从新基建导入，常量按原真名导入并赋予别名
from app.core.llm_client import get_openai_client
from app.interview.render import render_handbook_page
from app.services.feishu_service import (
    extract_record_id,
    get_job_record_from_feishu,
    update_feishu_record,
)

# 将父级外部目录加入 sys.path 以便导入旧依赖（如需后续彻底重构可移除）
SCRAPER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "Auto-Job-Hunter-OpenSource", "interview_scraper")
if SCRAPER_DIR not in sys.path:
    sys.path.append(SCRAPER_DIR)

# 公司情报走 backend 原生 Serper 引擎（外部 company_searcher 与本项目 common 包撞名，
# 在 backend 进程内 import 必然失败，故不再从那里导入）
from ai_agents.company_intel import search_company_ai_news  # noqa: E402


async def get_core_job_keywords(raw_title: str) -> list:
    """🌟 智能提取长岗位名称，生成【精准 -> 泛化】的搜索关键词矩阵"""
    if not raw_title or len(raw_title) <= 2:
        return [raw_title]

    prompt = f"""你是一个资深的招聘专家与数据检索专家。
请提取以下长岗位名称中的「核心职位名词」，并生成一个用于数据库模糊查询的【搜索关键词降级列表】（从精准到宽泛，最多输出3个词）。
规则：
1. 砍掉所有部门、业务线、前缀（如"Lark-"、"2025校招"）。
2. 第1个词：精准去水后的核心岗位名。
3. 第2个词：去掉修饰词，保留核心业务领域（如"智能客服"、"数据分析"）。
4. 第3个词：最宽泛的底层职业大类（如"运营"、"产品经理"、"研发"）。
5. 用英文逗号分隔，不要有任何多余字符！

示例：
- "人力资源ai产品经理" -> "AI产品经理,产品经理"
- "客户中心智能客服运营" -> "智能客服运营,智能客服"
- "抖音电商-数据分析师（急缺）" -> "数据分析师,数据分析,数据"

当前岗位名称：{raw_title}"""

    try:
        llm_client = get_openai_client()
        resp = await asyncio.to_thread(
            llm_client.chat.completions.create,
            model=_ccfg.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        content = resp.choices[0].message.content.strip()
        keywords = [k.strip() for k in content.split(",") if k.strip()]
        print(f"🧠 [智能搜索矩阵] 原岗位: '{raw_title}' -> 降级策略: {keywords}")
        return keywords if keywords else [raw_title]
    except Exception as e:
        print(f"⚠️ 核心岗位词提取失败: {e}")
        return [raw_title]

async def generate_handbook_action(job_id: str):
    """后台生成临考锦囊动作"""
    import inspect

    # 面经 RAG 已收编进本仓库（原依赖外部项目 interview_scraper）
    from app.interview.interview_rag import ask_for_interview_summary

    pure_record_id = extract_record_id(job_id)

    # 1. 获取当前岗位的最新数据
    record = await asyncio.to_thread(get_job_record_from_feishu, pure_record_id, _ccfg.FEISHU_TABLE_ID_JOBS)
    if not record:
        print(f"❌ 找不到岗位 {pure_record_id}，锦囊生成终止。")
        return
    fields = record.get("fields", {})

    company_intel = extract_feishu_text(fields.get("公司业务情报", ""))
    predicted_qa = extract_feishu_text(fields.get("专属面试预测", ""))
    reverse_questions = extract_feishu_text(fields.get("反问环节建议", ""))

    raw_job_group = extract_feishu_text(fields.get("岗位名称", "AI产品经理"))
    job_keywords = await get_core_job_keywords(raw_job_group)

    company_name = extract_feishu_text(fields.get("公司名称", "目标公司"))
    industry = extract_feishu_text(fields.get("所属行业", ""))
    jd_text = extract_feishu_text(fields.get("岗位详情", ""))

    async def fetch_summary_with_fallback(keywords, _ind):
        for keyword in keywords:
            print(f"🔍 正在尝试使用关键词 [{keyword}] 检索面经...")
            try:
                if inspect.iscoroutinefunction(ask_for_interview_summary):
                    res = await ask_for_interview_summary(keyword, None, False)
                else:
                    res = await asyncio.to_thread(ask_for_interview_summary, keyword, None, False)

                if res and res[0]:
                    text = res[0]
                    if isinstance(text, list):
                        text = "".join([str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in text])

                    if "库里暂时没有该方向的面经" not in text and "0 篇相关" not in text:
                        print(f"✅ 成功命中面经！最终匹配使用关键词: [{keyword}]")
                        return text
                    else:
                        print(f"📭 关键词 [{keyword}] 无结果，准备尝试更宽泛的词...")
            except Exception as e:
                print(f"⚠️ 关键词 [{keyword}] 检索异常: {e}")

        return "> ⚠️ 经过多轮降级泛化检索，底层库中暂无匹配面经。"

    summary_text = ""

    if not company_intel or not predicted_qa:
        print("⚠️ 检测到面试情报为空，正在自动呼叫 AI 间谍网络进行全网拉取...")

        try:
            if inspect.iscoroutinefunction(search_company_ai_news):
                company_intel = await search_company_ai_news(company_name)
            else:
                company_intel = await asyncio.to_thread(search_company_ai_news, company_name)
        except Exception as e:
            print(f"❌ 公司情报抓取失败: {e}")
            company_intel = "> ⚠️ 网络波动或代理拦截，公司情报抓取失败。"

        summary_text = await fetch_summary_with_fallback(job_keywords, industry)

        if jd_text and summary_text and not summary_text.startswith("### 📭") and not summary_text.startswith("> ⚠️"):
            prediction_prompt = f"你是一个资深大厂面试官。请结合【岗位JD】和【通用面经】，预测3个核心业务问题及高分回答思路。\n\n【岗位JD】：{jd_text}\n\n【通用面经】：{summary_text}"

            resume_text = extract_feishu_text(fields.get("AI改写JSON", "")) or extract_feishu_text(fields.get("AI改写简历", ""))

            rq_prompt = f"""你现在是一名顶级面试教练。请结合【公司情报】、【岗位JD】和【候选人简历】，为候选人生成 5 个高含金量的面试反问问题（即面试结尾候选人问面试官的问题）。
要求按以下5个战略维度分布：
1. 业务深度/痛点型：结合公司近期新闻或JD痛点。
2. 团队协作/文化型：了解真实工作环境。
3. 个人成长/挑战型：结合简历优势。
4. 公司远景/战略型：展现宏观视野。
5. 反馈/闭环型：询问评价或后续流程。
请用结构化的 Markdown 格式输出，每一条附带提问具体话术和意图说明。
【公司情报】：\n{company_intel}\n\n【岗位JD】：\n{jd_text}\n\n【候选人简历】：\n{resume_text or '未提供'}"""

            try:
                llm_client = get_openai_client()
                async def _gen_qa():
                    resp = await asyncio.to_thread(llm_client.chat.completions.create, model=_ccfg.LLM_MODEL, messages=[{"role": "user", "content": prediction_prompt}], temperature=0.4)
                    return resp.choices[0].message.content
                async def _gen_rq():
                    resp = await asyncio.to_thread(llm_client.chat.completions.create, model=_ccfg.LLM_MODEL, messages=[{"role": "user", "content": rq_prompt}], temperature=0.4, max_tokens=2000)
                    return resp.choices[0].message.content

                predicted_qa, reverse_questions = await asyncio.gather(_gen_qa(), _gen_rq())
            except Exception as e:
                print(f"❌ 预测面试题/反问生成失败: {e}")
                predicted_qa, reverse_questions = "> ⚠️ AI预测失败", "> ⚠️ AI反问失败"
        else:
            predicted_qa = "> ⚠️ 前置数据缺失，无法生成预测。"
            reverse_questions = "> ⚠️ 前置数据缺失，无法生成反问环节。"

        try:
            await asyncio.to_thread(update_feishu_record, pure_record_id, {
                "公司业务情报": company_intel,
                "专属面试预测": predicted_qa,
                "反问环节建议": reverse_questions
            }, _ccfg.FEISHU_TABLE_ID_JOBS)
        except Exception as e:
            print(f"❌ 回写飞书失败: {e}")

    else:
        print("⚡ 检测到面试情报已存在，跳过 AI 生成，直接提取已有数据封装 H5...")
        summary_text = await fetch_summary_with_fallback(job_keywords, industry)

    # 2. 将内容打包为 H5
    render_data = {
        "company_name": company_name,
        "raw_job_group": raw_job_group,
        "company_intel": company_intel,
        "summary_text": summary_text,
        "predicted_qa": predicted_qa,
        "reverse_questions": reverse_questions,
    }
    html_content = render_handbook_page(render_data)

    # 3. 异步写入 HTML 文件
    html_filename = f"handbook_{pure_record_id}.html"
    base_dir = getattr(settings, "BASE_DIR", Path(__file__).parent.parent.parent)
    pdf_dir = Path(base_dir) / "static" / "pdfs"

    def _write_html():
        pdf_dir.mkdir(parents=True, exist_ok=True)
        html_path = pdf_dir / html_filename
        html_path.write_text(html_content, encoding="utf-8")
        return html_path

    html_path = await asyncio.to_thread(_write_html)
    print(f"✅ 面试锦囊 H5 已写入: {html_path}")

    # 4. 将活链接写回飞书
    tunnel_domain = getattr(settings, "TUNNEL_DOMAIN", "")
    if tunnel_domain:
        download_url = f"{tunnel_domain}/api/get_pdf/{pure_record_id}"
        try:
            await asyncio.to_thread(update_feishu_record, pure_record_id, {"PDF链接直达": download_url}, _ccfg.FEISHU_TABLE_ID_JOBS)
            print(f"✅ 飞书链接已回写: {download_url}")
        except Exception as e:
            print(f"❌ 写回飞书链接失败: {e}")
    else:
        print("⚠️ 未配置 TUNNEL_DOMAIN，跳过 PDF 直达链接回写")
