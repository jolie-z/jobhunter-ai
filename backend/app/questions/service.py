import asyncio
import json
import re
from datetime import datetime
from typing import Any

from app.agents.qa_classifier_agent import QAClassifierAgent
from app.core.config import settings

# 全面启用全新的全局异步客户端
from app.core.feishu_client import feishu_client
from app.core.llm_client import get_openai_client
from app.questions.schemas import AddResumeQACardRequest, ShredInterviewRequest

# 仅保留纯数据解析工具，彻底剔除旧版网络 I/O 方法
from app.services.feishu_service import (
    extract_record_id,
    feishu_field_to_plain_str,
)

# 「来源岗位 / 关联面试」字段在不同读取通道返回形状不同（Q-M8-8/Q-M8-9 根因）：
# - GET 列表通道：[{"record_ids": [...], "table_id": ..., "text": ...}]
# - search 通道：{"link_record_ids": [...]}
# - 历史防御形态：[{"record_id": ...}] / 纯字符串列表
# 统一收敛为合法 record_id 字符串列表（recXXXX 形态校验内聚，写回时仍用纯 id 字符串列表）。
_RECORD_ID_RE = re.compile(r"rec[A-Za-z0-9]+")


def _is_valid_record_id(value: Any) -> bool:
    return bool(value) and bool(_RECORD_ID_RE.fullmatch(str(value)))


def _extract_link_ids(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        for rid in (value.get("link_record_ids") or []):
            if _is_valid_record_id(rid):
                ids.append(str(rid))
        return ids
    if not isinstance(value, list):
        return ids
    for entry in value:
        if isinstance(entry, dict):
            for rid in (entry.get("record_ids") or []):
                if _is_valid_record_id(rid):
                    ids.append(str(rid))
            rid = entry.get("record_id") or entry.get("recordId") or entry.get("id")
            if _is_valid_record_id(rid):
                ids.append(str(rid))
        elif isinstance(entry, str) and _is_valid_record_id(entry):
            ids.append(entry)
    return ids


async def list_questions() -> dict[str, Any]:
    try:
        # 已经使用了正确的异步调用
        records = await feishu_client.fetch_bitable_records(settings.FEISHU_TABLE_ID_INTERVIEW_REAL)
        items = []
        for r in records or []:
            f = r.get("fields", {}) or {}
            link_field = f.get("来源岗位 / 关联面试", [])
            related_jobs: list[str] = []
            seen_rids: set[str] = set()
            for rid in _extract_link_ids(link_field):
                if rid not in seen_rids:
                    seen_rids.add(rid)
                    related_jobs.append(rid)
            freq_raw = f.get("出现频次")
            try:
                frequency = int(freq_raw) if freq_raw is not None else 0
            except (ValueError, TypeError):
                frequency = 0

            raw_job_group = f.get("目标岗位群", "")
            if isinstance(raw_job_group, list):
                job_group = raw_job_group
            else:
                job_group = feishu_field_to_plain_str(raw_job_group)

            items.append({
                "record_id": r.get("record_id"),
                "question": feishu_field_to_plain_str(f.get("题目 / 核心拷问", "")),
                "mastery_status": feishu_field_to_plain_str(f.get("掌握状态", "⚪ 已收录")),
                "golden_answer": feishu_field_to_plain_str(f.get("我的黄金答案", "")),
                "ai_demo": feishu_field_to_plain_str(f.get("AI示范", "")),
                "source": feishu_field_to_plain_str(f.get("题目来源", "")),
                "tags": feishu_field_to_plain_str(f.get("考点标签", "")),
                "related_jobs": related_jobs,
                "question_type": feishu_field_to_plain_str(f.get("题目类型", "")),
                "industry": feishu_field_to_plain_str(f.get("所属行业", "")),
                "job_group": job_group,
                "company_and_job": feishu_field_to_plain_str(f.get("原公司与岗位", "")),
                "interview_stage": feishu_field_to_plain_str(f.get("面试轮次", "")),
                "original_text": feishu_field_to_plain_str(f.get("关联原文", "")),
                "frequency": frequency,
            })
        return {"status": "success", "items": items}
    except Exception as e:
        print(f"❌ 拉取面经库失败: {e}")
        return {"status": "failed", "items": [], "error": str(e)}

async def update_question(record_id: str, fields_to_update: dict[str, Any]) -> dict[str, Any]:
    if not fields_to_update:
        raise ValueError("未提供任何要更新的字段")
    # 替换为异步客户端调用
    success = await feishu_client.update_record(
        table_id=settings.FEISHU_TABLE_ID_INTERVIEW_REAL,
        record_id=record_id,
        fields=fields_to_update
    )
    if success:
        return {"status": "success", "record_id": record_id, "updated": fields_to_update}
    raise ValueError("飞书更新失败")

async def delete_question(record_id: str) -> dict[str, Any]:
    # 替换为异步客户端调用
    success = await feishu_client.delete_record(
        table_id=settings.FEISHU_TABLE_ID_INTERVIEW_REAL,
        record_id=record_id
    )
    if success:
        return {"status": "success"}
    raise ValueError("飞书API删除失败")

async def increment_drill_count(record_id: str) -> dict[str, Any]:
    # 剔除老旧的 Token 获取，直接通过异步客户端获取单条记录
    record = await feishu_client.get_record(
        table_id=settings.FEISHU_TABLE_ID_INTERVIEW_REAL,
        record_id=record_id
    )

    current_count = 0
    if record and isinstance(record.get("fields"), dict):
        raw = record["fields"].get("练习次数")
        try:
            current_count = int(raw) if raw is not None else 0
        except (ValueError, TypeError):
            current_count = 0

    new_count = current_count + 1
    fields_to_update = {
        "练习次数": new_count,
        # 「上次抽查时间」为 DateTime 字段：飞书只接受毫秒时间戳，
        # 字符串格式会被拒收（Q-M8-7：DatetimeFieldConvFail 502）
        "上次抽查时间": int(datetime.now().timestamp() * 1000),
    }

    # 替换为异步客户端调用
    success = await feishu_client.update_record(
        table_id=settings.FEISHU_TABLE_ID_INTERVIEW_REAL,
        record_id=record_id,
        fields=fields_to_update
    )
    if success:
        return {"status": "success", "record_id": record_id, "new_count": new_count}
    raise ValueError("增加练习次数失败")


async def add_qa_card_service(payload: AddResumeQACardRequest) -> dict[str, Any]:
    if not payload.question.strip():
        raise ValueError("问题不能为空")

    pure_record_id = extract_record_id(payload.job_id)

    # 1. 抓取父岗位基因数据
    parent_company, parent_job, parent_stage = "未知公司", "未知岗位", "未知轮次"
    try:
        # 替换为异步客户端调用
        parent_record = await feishu_client.get_record(
            table_id=settings.FEISHU_TABLE_ID_JOBS,
            record_id=pure_record_id
        )
        if parent_record:
            pf = parent_record.get("fields", {})
            parent_company = feishu_field_to_plain_str(pf.get("公司名称", "")) or "未知公司"
            parent_job = feishu_field_to_plain_str(pf.get("岗位名称", "")) or "未知岗位"
            parent_stage = feishu_field_to_plain_str(pf.get("跟进状态", "")) or "未知轮次"
    except Exception as e:
        print(f"⚠️ 读取父岗位数据失败: {e}")

    # 2. 拉取全量专属面经库，用于查重
    existing_records = await feishu_client.fetch_bitable_records(settings.FEISHU_TABLE_ID_INTERVIEW_REAL)

    q_list_text = ""
    records_map = {}
    if existing_records:
        for r in existing_records:
            r_id = r.get("record_id")
            f = r.get("fields", {})
            q_text = feishu_field_to_plain_str(f.get("题目 / 核心拷问", ""))
            if r_id and q_text:
                records_map[r_id] = f
                q_list_text += f"- ID: {r_id} | 题目: {q_text}\n"

    # 3. 呼叫大模型进行：拆词、分类、查重
    agent = QAClassifierAgent()
    core_tags, q_type, dup_id = await agent.classify_and_deduplicate(parent_job, payload.question, q_list_text)

    # 4. 根据查重结果，执行 更新 或 新增（关联岗位 id 两分支共用，非法 recXXXX 会被飞书整单拒收）
    valid_link_id = pure_record_id if _is_valid_record_id(pure_record_id) else ""
    if dup_id and dup_id in records_map:
        # 🎯 触发融合更新逻辑：频次 + 1，答案累加
        old_fields = records_map[dup_id]
        old_ans = feishu_field_to_plain_str(old_fields.get("我的黄金答案", ""))
        old_freq_raw = feishu_field_to_plain_str(old_fields.get("出现频次", "0"))
        try:
            old_freq = int(old_freq_raw) if old_freq_raw else 0
        except ValueError:
            old_freq = 0

        merged_ans = f"{old_ans}\n\n---\n[新增回答视角]\n{payload.answer.strip()}" if old_ans else payload.answer.strip()

        update_fields = {
            "我的黄金答案": merged_ans,
            "出现频次": old_freq + 1,
        }
        # 同时将新岗位加入关联列表（Q-M8-8：链接字段形状三态统一解析，
        # 非法 id 会让整条更新被飞书拒收，故仅合法 recXXXX 才补链）
        old_links = old_fields.get("来源岗位 / 关联面试", [])
        link_ids = _extract_link_ids(old_links)
        if valid_link_id and valid_link_id not in link_ids:
            link_ids.append(valid_link_id)
            update_fields["来源岗位 / 关联面试"] = link_ids

        success = await feishu_client.update_record(
            table_id=settings.FEISHU_TABLE_ID_INTERVIEW_REAL,
            record_id=dup_id,
            fields=update_fields
        )
        msg = "发现重复题目！已自动频次+1并累加答案。"
    else:
        # 🎯 触发新增逻辑：创建新卡片
        fields_data = {
            "题目 / 核心拷问": payload.question.strip(),
            "我的黄金答案": payload.answer.strip(),
            "掌握状态": "⚪ 已收录",
            "题目来源": "🌐 简历专项预测",
            "题目类型": q_type,
            "目标岗位群": core_tags,
            "原公司与岗位": f"{parent_company} - {parent_job}",
            "面试轮次": parent_stage,
            "出现频次": 1,
        }
        if valid_link_id:
            fields_data["来源岗位 / 关联面试"] = [valid_link_id]

        success = await feishu_client.create_record(
            table_id=settings.FEISHU_TABLE_ID_INTERVIEW_REAL,
            fields=fields_data
        )
        msg = "全新问题入库成功！已自动打标。"

    if success:
        return {"status": "success", "message": msg}
    else:
        raise ValueError("飞书写入失败")


SHRED_EXTRACT_PROMPT = """你是一个面试复盘专家。下面是一段候选人的真实面试流水账（口语或笔记，可能杂乱）。
请从中提取出【面试官实际问到的题目】，并为每题整理候选人的回答要点（若流水账中没有回答则留空字符串）。
只提取真实被问到的问题，不要自己编造新问题；相同考点只保留一条。

严格输出 JSON，格式如下：
{{"questions": [{{"question": "面试官的问题", "answer": "候选人回答要点，没有则为空字符串"}}]}}

【面试流水账】：
{record_text}"""


async def _extract_qa_from_record(record_text: str) -> list[dict[str, str]]:
    """呼叫 LLM 从面试流水账中提取问答对"""
    client = get_openai_client()
    if not client:
        raise ValueError("AI 服务未配置（缺少 api_key）")

    def _call():
        return client.chat.completions.create(
            model=settings.OPENAI_MODEL or "gpt-4o",
            messages=[{"role": "user", "content": SHRED_EXTRACT_PROMPT.format(record_text=record_text)}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )

    resp = await asyncio.to_thread(_call)
    data = json.loads(resp.choices[0].message.content)
    items = data.get("questions") or []
    normalized: list[dict[str, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        question = str(it.get("question", "")).strip()
        if not question:
            continue
        normalized.append({"question": question, "answer": str(it.get("answer", "")).strip()})
    return normalized


async def shred_interview_service(payload: ShredInterviewRequest) -> dict[str, Any]:
    """面经粉碎机：从面试流水账提取真题并入专属面经库（去重/融合）"""
    if not payload.record_text.strip():
        raise ValueError("流水账内容为空")

    pure_record_id = extract_record_id(payload.job_id)

    questions = await _extract_qa_from_record(payload.record_text)
    if not questions:
        return {
            "status": "success",
            "questions": [],
            "extracted_count": 0,
            "inserted_count": 0,
            "message": "未能从流水账中提取到面试问答",
        }

    # 1. 抓取父岗位基因数据
    parent_company, parent_job, parent_stage = "未知公司", "未知岗位", "未知轮次"
    try:
        parent_record = await feishu_client.get_record(
            table_id=settings.FEISHU_TABLE_ID_JOBS,
            record_id=pure_record_id
        )
        if parent_record:
            pf = parent_record.get("fields", {})
            parent_company = feishu_field_to_plain_str(pf.get("公司名称", "")) or "未知公司"
            parent_job = feishu_field_to_plain_str(pf.get("岗位名称", "")) or "未知岗位"
            parent_stage = feishu_field_to_plain_str(pf.get("跟进状态", "")) or "未知轮次"
    except Exception as e:
        print(f"⚠️ [粉碎机] 读取父岗位数据失败: {e}")

    # 2. 轻量按需拉取题库用于查重：仅取查重与融合核心字段，裁掉大文本降低 80%+ 网络传输
    needed_fields = ["题目 / 核心拷问", "出现频次", "来源岗位 / 关联面试", "我的黄金答案"]
    try:
        existing_records = await feishu_client.search_bitable_records(
            table_id=settings.FEISHU_TABLE_ID_INTERVIEW_REAL,
            field_names=needed_fields
        )
    except Exception as e:
        print(f"⚠️ [粉碎机] search_bitable_records 异常，降级全量拉取: {e}")
        existing_records = await feishu_client.fetch_bitable_records(settings.FEISHU_TABLE_ID_INTERVIEW_REAL)

    records_map: dict[str, dict[str, Any]] = {}
    if existing_records:
        for r in existing_records:
            r_id = r.get("record_id")
            f = r.get("fields", {})
            q_text = feishu_field_to_plain_str(f.get("题目 / 核心拷问", ""))
            if r_id and q_text:
                records_map[r_id] = f

    def _build_top_k_candidates(q_target: str, pool: dict[str, dict[str, Any]], top_k: int = 20) -> str:
        """
        从题库中预筛选出与新题相似度最高的 Top-K 候选，
        将 LLM 上下文严格锁定在 O(1) 常量规模，彻底杜绝题库膨胀导致的 Token 爆炸与超长等待。
        """
        if len(pool) <= top_k:
            return "".join(
                f"- ID: {rid} | 题目: {feishu_field_to_plain_str(f.get('题目 / 核心拷问', ''))}\n"
                for rid, f in pool.items()
            )

        q_chars = set(q_target.lower().replace(" ", ""))
        scored = []
        for rid, f in pool.items():
            existing_q = feishu_field_to_plain_str(f.get("题目 / 核心拷问", ""))
            if not existing_q:
                continue
            e_chars = set(existing_q.lower().replace(" ", ""))
            common = len(q_chars & e_chars)
            total = len(q_chars | e_chars) or 1
            score = common / total
            if existing_q in q_target or q_target in existing_q:
                score += 1.0
            scored.append((score, rid, existing_q))

        scored.sort(key=lambda x: x[0], reverse=True)
        return "".join(f"- ID: {rid} | 题目: {eq}\n" for _, rid, eq in scored[:top_k])

    agent = QAClassifierAgent()
    original_snippet = payload.record_text.strip()[:500]

    # 「来源岗位/关联面试」是飞书双向关联字段：写入非法 record_id 会让整条记录创建失败，
    # 因此仅当 id 符合 recXXXX 形态时才写入关联
    valid_link_id = pure_record_id if _is_valid_record_id(pure_record_id) else ""

    # 3. 🌟 串行「分类 → 写库」交替：每题写库后新记录实时并入 records_map，
    # 本批后续题目即可与同批新题查重（并发全分类再统一写库会造成批内重复入库）
    inserted = 0
    for q in questions:
        try:
            candidates_text = _build_top_k_candidates(q["question"], records_map, top_k=20)
            core_tags, q_type, dup_id = await agent.classify_and_deduplicate(
                parent_job, q["question"], candidates_text
            )

            if dup_id and dup_id in records_map:
                # 🎯 命中已有题：频次+1，回答视角累加，关联岗位补链
                old_fields = records_map[dup_id]
                old_ans = feishu_field_to_plain_str(old_fields.get("我的黄金答案", ""))
                old_freq_raw = feishu_field_to_plain_str(old_fields.get("出现频次", "0"))
                try:
                    old_freq = int(old_freq_raw) if old_freq_raw else 0
                except ValueError:
                    old_freq = 0

                update_fields: dict[str, Any] = {"出现频次": old_freq + 1}
                merged_ans = (
                    f"{old_ans}\n\n---\n[新增回答视角]\n{q['answer']}" if (old_ans and q['answer']) else (old_ans or q['answer'])
                )
                if merged_ans:
                    update_fields["我的黄金答案"] = merged_ans

                old_links = old_fields.get("来源岗位 / 关联面试", [])
                link_ids = _extract_link_ids(old_links)
                if valid_link_id and valid_link_id not in link_ids:
                    link_ids.append(valid_link_id)
                    update_fields["来源岗位 / 关联面试"] = link_ids

                await feishu_client.update_record(
                    table_id=settings.FEISHU_TABLE_ID_INTERVIEW_REAL,
                    record_id=dup_id,
                    fields=update_fields
                )
                # 🌟 同步本地快照（records_map[dup_id] 即 old_fields 本体）：
                # 否则同批后续题目再合并到同一题时，频次会基于陈旧值重复计算、
                # 新回答视角会互相覆盖而不是累加
                old_fields["出现频次"] = old_freq + 1
                if merged_ans:
                    old_fields["我的黄金答案"] = merged_ans
                if "来源岗位 / 关联面试" in update_fields:
                    old_fields["来源岗位 / 关联面试"] = update_fields["来源岗位 / 关联面试"]
            else:
                # 🎯 新题入库
                fields_data = {
                    "题目 / 核心拷问": q["question"],
                    "我的黄金答案": q["answer"],
                    "掌握状态": "⚪ 已收录",
                    "题目来源": "⚔️ 真实战场复盘",
                    "题目类型": q_type,
                    "目标岗位群": core_tags,
                    "原公司与岗位": f"{parent_company} - {parent_job}",
                    "面试轮次": parent_stage,
                    "关联原文": original_snippet,
                    "出现频次": 1,
                }
                if valid_link_id:
                    fields_data["来源岗位 / 关联面试"] = [valid_link_id]
                created = await feishu_client.create_record(
                    table_id=settings.FEISHU_TABLE_ID_INTERVIEW_REAL,
                    fields=fields_data
                )
                # 实时并入本地已拉取字典，供后续同批查重
                new_id = (created.get("data", {}).get("record", {}) or {}).get("record_id", "") if isinstance(created, dict) else ""
                if not new_id:
                    new_id = f"local-{len(records_map) + 1}"
                records_map[new_id] = fields_data

            inserted += 1
        except Exception as e:
            print(f"⚠️ [粉碎机] 单题入库写入失败（{q['question'][:20]}...）: {e}")

    return {
        "status": "success",
        "questions": questions,
        "extracted_count": len(questions),
        "inserted_count": inserted,
    }
