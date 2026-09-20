import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.tasks.wave_pipeline import run_wave_evaluation_pipeline


@pytest.mark.asyncio
async def test_wave_evaluation_pipeline_funnel_split():
    """验证三波次漏斗流水线：高分岗贯通三波次，低分岗在波次 1 就地归档。"""
    job_ids = ["boss-recA", "boss-recC"]
    task_id = "test-task-123"
    resume_text = "【精通 Python 与大模型全栈架构】具备 5 年以上核心链路设计经验。"
    preferences_text = "期望大模型与后端架构岗位。"
    queue = asyncio.Queue()

    prefetched = {
        "recA": {
            "fields": {
                "公司名称": "优质AI科技",
                "岗位名称": "大模型架构师",
                "岗位详情": "负责大模型系统底层设计与 Agent 流水线开发，要求精通 Python 与 RAG 架构设计，具备丰富经验。" * 3,
                "薪资": "35-50K",
                "城市": "北京",
                "经验要求": "5-10年",
                "学历要求": "本科",
                "招聘平台": "BOSS直聘",
            }
        },
        "recC": {
            "fields": {
                "公司名称": "普通外包公司",
                "岗位名称": "初级测试员",
                "岗位详情": "负责业务手工点点点测试与基础用例编写，要求熟悉基础测试流程。" * 4,
                "薪资": "6-8K",
                "城市": "北京",
                "经验要求": "1-3年",
                "学历要求": "大专",
                "招聘平台": "BOSS直聘",
            }
        },
    }

    # Mock 外部边界 (Serper 联网与大模型调用)
    def mock_eval_single(job_data, resume, intel, prefs, task_mode, pcb):
        cid = job_data["company"]
        if "优质" in cid:
            return {
                "success": True,
                "ai_score": 95,
                "grade": "A",
                "update_data": {"综合评级 (A-F)": "A", "初评总分": 95},
                "usage": {"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600},
                "rationales_text": "技能高度契合",
            }
        else:
            return {
                "success": True,
                "ai_score": 55,
                "grade": "C",
                "update_data": {"综合评级 (A-F)": "C", "初评总分": 55},
                "usage": {"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600},
                "rationales_text": "技能匹配度低",
            }

    mock_deep = {
        "dream_picture": "卓越的 Agent 架构师",
        "ats_ability_analysis": "Python, LangChain, RAG",
        "resume_audit": "项目经历非常亮眼",
        "strong_fit_assessment": "高并发与多Agent架构实战",
        "risk_red_flags": "无显著硬伤",
        "deep_action_plan": "建议直接约面",
    }

    with patch("app.tasks.wave_pipeline.research_company_serper", AsyncMock(return_value="公司前景优良")), \
         patch("app.tasks.wave_pipeline.evaluate_single_job", side_effect=mock_eval_single), \
         patch("app.tasks.wave_pipeline.deep_evaluate_resume", return_value=(mock_deep, {"prompt_tokens": 1000, "completion_tokens": 200})), \
         patch("app.tasks.wave_pipeline.process_resume_rewrite", return_value=("# 个人简历\n重构版内容", {"prompt_tokens": 1500, "completion_tokens": 500})), \
         patch("app.tasks.wave_pipeline.process_greeting_generation", return_value=("您好！看到贵司大模型架构师岗位...", {"prompt_tokens": 300, "completion_tokens": 50})), \
         patch("app.tasks.wave_pipeline.convert_and_stitch_resume", return_value="{}"), \
         patch("app.tasks.wave_pipeline.update_feishu_record", return_value=True):

        success, failed, skipped = await run_wave_evaluation_pipeline(
            job_ids=job_ids,
            task_id=task_id,
            resume_text=resume_text,
            preferences_text=preferences_text,
            queue=queue,
            prefetched=prefetched,
        )

    # 验证最终统计
    assert success == 2
    assert failed == 0
    assert skipped == 0

    # 消费 SSE 队列中的事件，验证波次推流
    events = []
    while not queue.empty():
        msg = await queue.get()
        events.append(msg)

    raw_text = "".join(events)
    # 验证包含波次 1、漏斗门禁、波次 2、波次 3 的清晰阶段标识
    assert "【波次 1/3：批量初评】" in raw_text
    assert "【漏斗门禁】" in raw_text
    assert "【波次 2/3：深度画像】" in raw_text
    assert "【波次 3/3：定制改写与破冰】" in raw_text
    # 验证普通岗位就地归档
    assert "初评就地归档" in raw_text
    # 验证优质岗位全链路处理完成
    assert "全链路处理完成，已生成定制简历与打招呼语" in raw_text


@pytest.mark.asyncio
async def test_wave_pipeline_small_batch_serial_and_cache_display():
    """验证小批量 (<3) 自动采用智能串行调度，且 SSE 透传 (🔥命中缓存: xxx) 标识。"""
    job_ids = ["boss-job1", "boss-job2"]
    queue = asyncio.Queue()
    prefetched = {
        "job1": {
            "fields": {
                "公司名称": "测试公司A", "岗位名称": "Python开发",
                "岗位详情": "岗位详情内容长于五十个字符岗位详情内容长于五十个字符岗位详情内容长于五十个字符岗位详情内容长于五十个字符",
                "薪资": "20-30K", "城市": "上海", "经验要求": "3-5年", "学历要求": "本科",
            }
        },
        "job2": {
            "fields": {
                "公司名称": "测试公司B", "岗位名称": "AI产品经理",
                "岗位详情": "岗位详情内容长于五十个字符岗位详情内容长于五十个字符岗位详情内容长于五十个字符岗位详情内容长于五十个字符",
                "薪资": "25-35K", "城市": "北京", "经验要求": "3-5年", "学历要求": "本科",
            }
        },
    }

    mock_res = {
        "success": True,
        "ai_score": 65,
        "grade": "C",
        "update_data": {"综合评级 (A-F)": "C", "初评总分": 65},
        "usage": {"prompt_tokens": 4800, "completion_tokens": 200, "cached_tokens": 4096},
        "rationales_text": "基本匹配",
    }

    with patch("app.tasks.wave_pipeline.research_company_serper", AsyncMock(return_value="")), \
         patch("app.tasks.wave_pipeline.evaluate_single_job", return_value=mock_res), \
         patch("app.tasks.wave_pipeline.warmup_eval_cache") as mock_warmup, \
         patch("app.tasks.wave_pipeline.update_feishu_record", return_value=True):

        success, failed, skipped = await run_wave_evaluation_pipeline(
            job_ids=job_ids,
            task_id="test-small-batch",
            resume_text="简历内容",
            preferences_text="偏好内容",
            queue=queue,
            prefetched=prefetched,
        )

    # 验证 <3 时没有调用 warmup 点火，而是直接串行运行
    mock_warmup.assert_not_called()
    assert success == 2

    events = []
    while not queue.empty():
        events.append(await queue.get())
    raw_text = "".join(events)
    # 验证串行提示和命中缓存输出
    assert "启用智能串行评估以天然继承前缀缓存" in raw_text
    assert "🔥命中缓存: 4096" in raw_text


@pytest.mark.asyncio
async def test_wave_pipeline_large_batch_primer():
    """验证大批量 (>=3) 触发 1-token 点火预热。"""
    job_ids = ["boss-job1", "boss-job2", "boss-job3"]
    queue = asyncio.Queue()
    prefetched = {
        f"job{i}": {
            "fields": {
                "公司名称": f"公司{i}", "岗位名称": f"岗位{i}",
                "岗位详情": "详情内容很多很长超过五十个字详情内容很多很长超过五十个字详情内容很多很长超过五十个字详情内容很多很长超过五十个字",
                "薪资": "20K", "城市": "深圳", "经验要求": "1年", "学历要求": "大专",
            }
        } for i in range(1, 4)
    }

    mock_res = {
        "success": True, "ai_score": 60, "grade": "C",
        "update_data": {"综合评级 (A-F)": "C"}, "usage": {},
    }

    with patch("app.tasks.wave_pipeline.research_company_serper", AsyncMock(return_value="")), \
         patch("app.tasks.wave_pipeline.evaluate_single_job", return_value=mock_res), \
         patch("app.tasks.wave_pipeline.warmup_eval_cache", return_value={"success": True, "prompt": 4500, "cached": 0}) as mock_warmup, \
         patch("app.tasks.wave_pipeline.update_feishu_record", return_value=True):

        success, failed, skipped = await run_wave_evaluation_pipeline(
            job_ids=job_ids, task_id="test-large-batch", resume_text="简历", preferences_text="偏好",
            queue=queue, prefetched=prefetched,
        )

    # 验证 >=3 时触发了 warmup 点火
    mock_warmup.assert_called_once()
    assert success == 3


@pytest.mark.asyncio
async def test_wave_pipeline_feishu_write_failure_captured():
    """验证 Wave 2 飞书回写失败时不会被静默吞掉，而是作为失败计入统计。"""
    job_ids = ["boss-jobA"]
    queue = asyncio.Queue()
    prefetched = {
        "jobA": {
            "fields": {
                "公司名称": "优质科技", "岗位名称": "AI算法",
                "岗位详情": "岗位详情内容长于五十个字符岗位详情内容长于五十个字符岗位详情内容长于五十个字符岗位详情内容长于五十个字符",
                "薪资": "40K", "城市": "北京", "经验要求": "5年", "学历要求": "硕士",
            }
        }
    }

    mock_res = {
        "success": True, "ai_score": 95, "grade": "A",
        "update_data": {"综合评级 (A-F)": "A", "初评总分": 95}, "usage": {},
    }
    mock_deep = {"dream_picture": "画像", "ats_ability_analysis": "分析"}

    # 初评回写成功，但深评回写失败 (return_value: True, 然后 False)
    write_results = [True, False]
    def mock_write(*args, **kwargs):
        return write_results.pop(0) if write_results else False

    with patch("app.tasks.wave_pipeline.research_company_serper", AsyncMock(return_value="")), \
         patch("app.tasks.wave_pipeline.evaluate_single_job", return_value=mock_res), \
         patch("app.tasks.wave_pipeline.deep_evaluate_resume", return_value=(mock_deep, {})), \
         patch("app.tasks.wave_pipeline.update_feishu_record", side_effect=mock_write):

        success, failed, skipped = await run_wave_evaluation_pipeline(
            job_ids=job_ids, task_id="test-fail-feishu", resume_text="简历", preferences_text="偏好",
            queue=queue, prefetched=prefetched,
        )

    # 优质岗位深评飞书回写失败，应当被捕获并计入 failed
    assert failed == 1
    assert success == 0


def test_evaluate_single_job_preserves_cached_tokens():
    """单元测试：验证 evaluate_single_job 内部的 total_usage 正确保留并透传 cached_tokens (彻底修复累计器丢字段 Bug)"""
    from ai_agents.ai_evaluator import evaluate_single_job

    job_data = {
        "record_id": "rec_test_eval_usage",
        "company": "测试公司",
        "job_title": "AI产品经理",
        "jd_text": "岗位详情" * 20,
    }

    mock_10dim_res = {
        "grade": "B",
        "scores": {
            "role_match": 4, "skills_align": 4, "seniority": 4, "compensation": 4,
            "interview_prob": 4, "company_stage": 4, "market_fit": 4, "growth": 4,
        },
        "score_rationales": {"role_match": "高度匹配"},
    }
    mock_usage = {
        "prompt_tokens": 5000,
        "completion_tokens": 200,
        "total_tokens": 5200,
        "cached_tokens": 4096,
    }

    with patch("ai_agents.ai_evaluator._call_10dim_evaluation", return_value=(mock_10dim_res, mock_usage)):
        res = evaluate_single_job(job_data, "简历文本", company_intel="公司情报", task_mode="eval_only")

    assert res["success"] is True
    usage = res.get("usage", {})
    assert "cached_tokens" in usage, "evaluate_single_job 返回的 usage 必须包含 cached_tokens 键"
    assert usage["cached_tokens"] == 4096, f"预期 cached_tokens 为 4096，实际为 {usage.get('cached_tokens')}"
    assert usage["prompt_tokens"] == 5000
    assert usage["completion_tokens"] == 200


def test_skill_greeting_returns_cached_tokens():
    """单元测试：验证 skill_greeting 模块正确从 API 响应中提取 cached_tokens"""
    from unittest.mock import MagicMock
    from types import SimpleNamespace
    from ai_agents.skill_greeting import run_skill_based_greeting

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="<GREETING>您好，很高兴与您沟通！</GREETING>"))]
    mock_resp.usage = SimpleNamespace(
        prompt_tokens=1200,
        completion_tokens=60,
        total_tokens=1260,
        prompt_tokens_details=SimpleNamespace(cached_tokens=1024),
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("ai_agents.skill_greeting.get_openai_client", return_value=mock_client):
        greeting, usage = run_skill_based_greeting("岗位JD", {}, "母本简历", "AI工程师")

    assert greeting == "您好，很高兴与您沟通！"
    assert "cached_tokens" in usage
    assert usage["cached_tokens"] == 1024


def test_warmup_rewrite_cache_returns_cached_tokens():
    """单元测试：验证 warmup_rewrite_cache 1-token 点火预热函数正确解析并返回 prompt 与 cached_tokens"""
    from unittest.mock import MagicMock
    from types import SimpleNamespace
    from ai_agents.skill_rewrite import warmup_rewrite_cache

    mock_resp = MagicMock()
    mock_resp.usage = SimpleNamespace(
        prompt_tokens=4800,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("ai_agents.skill_rewrite.get_openai_client", return_value=mock_client):
        res = warmup_rewrite_cache("这是不可变母本简历内容")

    assert res["success"] is True
    assert res["prompt"] == 4800
    assert res["cached"] == 0


@pytest.mark.asyncio
async def test_wave_pipeline_wave3_primer_on_large_batch():
    """验证 Wave 3：当优质改写岗位数 >= 3 时，触发 1-token 点火预热并透传 resume_text 底稿"""
    job_ids = ["boss-high1", "boss-high2", "boss-high3"]
    queue = asyncio.Queue()
    prefetched = {
        f"high{i}": {
            "fields": {
                "公司名称": f"优质公司{i}", "岗位名称": f"架构师{i}",
                "岗位详情": "详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字",
                "薪资": "45K", "城市": "上海", "经验要求": "5年", "学历要求": "本科",
            }
        } for i in range(1, 4)
    }

    mock_res = {
        "success": True, "ai_score": 92, "grade": "A",
        "update_data": {"综合评级 (A-F)": "A", "初评总分": 92}, "usage": {},
    }
    mock_deep = {"dream_picture": "画像", "ats_ability_analysis": "词典"}

    with patch("app.tasks.wave_pipeline.research_company_serper", AsyncMock(return_value="")), \
         patch("app.tasks.wave_pipeline.evaluate_single_job", return_value=mock_res), \
         patch("app.tasks.wave_pipeline.warmup_eval_cache", return_value={"success": True, "prompt": 4500, "cached": 0}), \
         patch("app.tasks.wave_pipeline.deep_evaluate_resume", return_value=(mock_deep, {"prompt_tokens": 1000, "completion_tokens": 200})), \
         patch("app.tasks.wave_pipeline.warmup_deep_eval_cache", return_value={"success": True, "prompt": 2000, "cached": 0}), \
         patch("app.tasks.wave_pipeline.warmup_rewrite_cache", return_value={"success": True, "prompt": 4800, "cached": 0}) as mock_warmup_rew, \
         patch("app.tasks.wave_pipeline.process_resume_rewrite", return_value=("# 简历", {"prompt_tokens": 8000, "cached_tokens": 4800})) as mock_proc_rew, \
         patch("app.tasks.wave_pipeline.process_greeting_generation", return_value=("打招呼", {})), \
         patch("app.tasks.wave_pipeline.convert_and_stitch_resume", return_value="{}"), \
         patch("app.tasks.wave_pipeline.update_feishu_record", return_value=True):

        success, failed, skipped = await run_wave_evaluation_pipeline(
            job_ids=job_ids, task_id="test-wave3-large", resume_text="母本简历内容", preferences_text="求职偏好",
            queue=queue, prefetched=prefetched,
        )

    assert success == 3
    assert failed == 0
    # 验证 >= 3 时触发了 Wave 3 点火
    mock_warmup_rew.assert_called_once_with("母本简历内容")
    # 验证 process_resume_rewrite 正确接收到了传入的 original_resume_override 内存底本 (第5个参数)
    assert mock_proc_rew.call_count == 3
    for call in mock_proc_rew.call_args_list:
        args = call.args
        assert "母本简历内容" in args


@pytest.mark.asyncio
async def test_wave_pipeline_wave3_serial_on_small_batch():
    """验证 Wave 3：当优质改写岗位数 < 3 时，采用智能串行改写，不触发额外的点火预热"""
    job_ids = ["boss-high1", "boss-high2"]
    queue = asyncio.Queue()
    prefetched = {
        f"high{i}": {
            "fields": {
                "公司名称": f"优质公司{i}", "岗位名称": f"架构师{i}",
                "岗位详情": "详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字",
                "薪资": "45K", "城市": "上海", "经验要求": "5年", "学历要求": "本科",
            }
        } for i in range(1, 3)
    }

    mock_res = {
        "success": True, "ai_score": 92, "grade": "A",
        "update_data": {"综合评级 (A-F)": "A", "初评总分": 92}, "usage": {},
    }
    mock_deep = {"dream_picture": "画像", "ats_ability_analysis": "词典"}

    with patch("app.tasks.wave_pipeline.research_company_serper", AsyncMock(return_value="")), \
         patch("app.tasks.wave_pipeline.evaluate_single_job", return_value=mock_res), \
         patch("app.tasks.wave_pipeline.deep_evaluate_resume", return_value=(mock_deep, {"prompt_tokens": 1000, "completion_tokens": 200})), \
         patch("app.tasks.wave_pipeline.warmup_rewrite_cache") as mock_warmup_rew, \
         patch("app.tasks.wave_pipeline.process_resume_rewrite", return_value=("# 简历", {"prompt_tokens": 8000, "cached_tokens": 4800})), \
         patch("app.tasks.wave_pipeline.process_greeting_generation", return_value=("打招呼", {})), \
         patch("app.tasks.wave_pipeline.convert_and_stitch_resume", return_value="{}"), \
         patch("app.tasks.wave_pipeline.update_feishu_record", return_value=True):

        success, failed, skipped = await run_wave_evaluation_pipeline(
            job_ids=job_ids, task_id="test-wave3-small", resume_text="母本简历内容", preferences_text="求职偏好",
            queue=queue, prefetched=prefetched,
        )

    assert success == 2
    assert failed == 0
    # 验证 < 3 时不调用 Wave 3 点火（智能串行天然继承缓存）
    mock_warmup_rew.assert_not_called()



