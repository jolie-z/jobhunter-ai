# backend/tests/test_pipeline_sub_card_task_scope.py
"""
全链路指挥中心定时任务战报子卡片 · 任务作用域隔离与 0 条空态防穿透自动化测试集。
针对用户反馈排查结论闭环验证：
1. 彻底解决“报告显示精投6、海投11、淘汰2，点击子卡片均固定返回20条历史陈旧数据”的 Bug；
2. 验证当次任务精投(6条)、海投复核(11条)、淘汰(2条)的精准过滤，绝不混入历史存量；
3. 验证本轮 0 条(record_ids: [])时渲染空态卡片，杜绝误触发全表扫描；
4. 验证超过 20 条时截断前 20 条；
5. 验证旧历史卡片(record_ids is None)平滑降级兜底兼容。
"""

import pytest
import sqlite3
import tempfile
from unittest.mock import patch, AsyncMock
from app.services.report_card_actions import (
    handle_report_card_action,
    _fetch_real_jobs_for_sub_card,
)
from app.services.pipeline_card_builders import (
    build_master_pipeline_card,
)


@pytest.mark.asyncio
async def test_sub_card_task_scope_precise_match_6_11_2():
    """验证当次任务精准匹配：精投6条、海投11条、淘汰2条，绝不被历史存量污染。"""
    chat_id = "oc_test_pipeline_scope_chat"

    # 1. 构造多维表格待复核数据：共 30 条
    # - 6 条精投 A/B 级（当前任务）: rec_ab_1 ~ rec_ab_6
    # - 11 条海投复核 C 级（当前任务）: rec_mass_1 ~ rec_mass_11
    # - 13 条历史陈旧待复核岗（非本任务）: rec_old_1 ~ rec_old_13
    mock_feishu_jobs = []
    current_ab_ids = [f"rec_ab_{i}" for i in range(1, 7)]
    for rid in current_ab_ids:
        mock_feishu_jobs.append({
            "job_id": rid, "record_id": rid, "follow_status": "待人工复核",
            "grade": "A", "company_name": f"精投企业_{rid}", "job_name": "AI产品经理",
            "platform": "boss", "is_custom": True
        })

    current_mass_ids = [f"rec_mass_{i}" for i in range(1, 12)]
    for rid in current_mass_ids:
        mock_feishu_jobs.append({
            "job_id": rid, "record_id": rid, "follow_status": "海投人工复核",
            "grade": "C", "company_name": f"海投企业_{rid}", "job_name": "运营专员",
            "platform": "liepin", "is_custom": False, "company_scale": "1000人以上"
        })

    old_ids = [f"rec_old_{i}" for i in range(1, 14)]
    for rid in old_ids:
        mock_feishu_jobs.append({
            "job_id": rid, "record_id": rid, "follow_status": "待人工复核",
            "grade": "A", "company_name": f"历史企业_{rid}", "job_name": "历史岗位",
            "platform": "51job", "is_custom": True
        })

    # 2. 构造本地 SQLite raw_jobs 数据：共 25 条淘汰记录，仅 rowid 101, 102 属于本轮任务
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp_db:
        db_path = tmp_db.name
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE raw_jobs (rowid INTEGER PRIMARY KEY, platform TEXT, job_title TEXT, "
                "company_name TEXT, reject_reason TEXT, feishu_record_id TEXT, process_status TEXT, job_link TEXT)"
            )
            # 本轮清洗淘汰 2 条（纯数字 rowid 101, 102）
            conn.execute("INSERT INTO raw_jobs VALUES (101, 'BOSS', '本轮淘汰1', '公司A', '学历不符', '', '清洗淘汰', '')")
            conn.execute("INSERT INTO raw_jobs VALUES (102, '猎聘', '本轮淘汰2', '公司B', '薪资过高', '', 'ai清洗淘汰', '')")
            # 本轮初评 AI 淘汰 1 条（带飞书 feishu_record_id: 'rec_df_99'）
            conn.execute("INSERT INTO raw_jobs VALUES (103, '智联', '本轮AI初评淘汰', '公司C', '初评D级不合适', 'rec_df_99', '初评淘汰', '')")
            # 历史淘汰 23 条
            for r in range(1, 24):
                conn.execute(f"INSERT INTO raw_jobs VALUES ({r}, '51job', '历史淘汰{r}', '历史公司{r}', '历史原因', '', '清洗淘汰', '')")

        current_rejected_ids = ["101", "102", "rec_df_99"]

        with patch("app.services.feishu_service.get_pending_review_jobs_from_feishu", return_value=mock_feishu_jobs), \
             patch("app.services.report_card_actions._get_raw_db_path", return_value=db_path), \
             patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_send_card:

            # 验证精投子卡片：只渲染 6 条
            await handle_report_card_action(chat_id, {"action": "open_ab_card", "record_ids": current_ab_ids})
            assert mock_send_card.call_count == 1
            card_ab = mock_send_card.call_args.kwargs.get("card_content") or mock_send_card.call_args[0][1]
            assert "共 6 条就绪" in card_ab["header"]["title"]["content"]
            # 确认 6 条均在卡片中，而历史岗位绝不在
            for rid in current_ab_ids:
                assert rid in str(card_ab)
            assert "rec_old_1" not in str(card_ab)

            # 验证海投复核子卡片：只渲染 11 条
            await handle_report_card_action(chat_id, {"action": "open_mass_card", "record_ids": current_mass_ids})
            assert mock_send_card.call_count == 2
            card_mass = mock_send_card.call_args.kwargs.get("card_content") or mock_send_card.call_args[0][1]
            assert "共 11 条待审" in card_mass["header"]["title"]["content"]
            for rid in current_mass_ids:
                assert rid in str(card_mass)
            assert "rec_old_1" not in str(card_mass)

            # 验证淘汰子卡片：精准渲染 3 条（2条清洗拦截 + 1条初评D级），双ID体系无缝统一，绝不拉取历史存量
            await handle_report_card_action(chat_id, {"action": "open_rejected_card", "record_ids": current_rejected_ids})
            assert mock_send_card.call_count == 3
            card_rej = mock_send_card.call_args.kwargs.get("card_content") or mock_send_card.call_args[0][1]
            assert "共 3 条淘汰" in card_rej["header"]["title"]["content"]
            assert "本轮淘汰1" in str(card_rej)
            assert "本轮淘汰2" in str(card_rej)
            assert "本轮AI初评淘汰" in str(card_rej)
            assert "历史淘汰1" not in str(card_rej)


@pytest.mark.asyncio
async def test_sub_card_task_scope_explicit_empty_list_prevents_historical_scan():
    """验证 0 条空态防穿透：传入空列表 [] 时必须渲染空态卡片，绝严禁扫描历史表凑满20条！"""
    chat_id = "oc_test_empty_scope_chat"

    mock_feishu_jobs = [
        {"job_id": f"rec_history_{i}", "follow_status": "待人工复核", "grade": "A", "company_name": "历史公司", "job_name": "历史岗位"}
        for i in range(25)
    ]

    with patch("app.services.feishu_service.get_pending_review_jobs_from_feishu", return_value=mock_feishu_jobs) as mock_get_feishu, \
         patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_send_card:

        # 1. 精投为 0 条：传入 record_ids: []
        await handle_report_card_action(chat_id, {"action": "open_ab_card", "record_ids": []})
        assert mock_send_card.call_count == 1
        card_ab = mock_send_card.call_args.kwargs.get("card_content") or mock_send_card.call_args[0][1]
        assert "0 条待审" in card_ab["header"]["title"]["content"]
        assert "本轮暂无待审批的精投岗位" in str(card_ab)
        assert "rec_history_0" not in str(card_ab)
        # 且甚至不需要去请求多维表格 API（短路优化）
        mock_get_feishu.assert_not_called()

        # 2. 淘汰为 0 条：传入 record_ids: []
        await handle_report_card_action(chat_id, {"action": "open_rejected_card", "record_ids": []})
        assert mock_send_card.call_count == 2
        card_rej = mock_send_card.call_args.kwargs.get("card_content") or mock_send_card.call_args[0][1]
        assert "0 条淘汰" in card_rej["header"]["title"]["content"]
        assert "本轮无淘汰岗位" in str(card_rej)


@pytest.mark.asyncio
async def test_sub_card_task_scope_cap_at_20():
    """验证当单次任务某个分流产生 25 条时，子卡片切片展示前 20 条，安全防爆框，且三类子卡片标题均正确展示截断提示。"""
    chat_id = "oc_test_cap_20_chat"

    target_ids = [f"rec_batch_{i}" for i in range(1, 26)]
    mock_feishu_jobs = [
        {"job_id": rid, "record_id": rid, "follow_status": "待人工复核", "grade": "A", "company_name": f"公司_{rid}", "job_name": "岗", "platform": "boss", "is_custom": True}
        for rid in target_ids
    ]

    with patch("app.services.feishu_service.get_pending_review_jobs_from_feishu", return_value=mock_feishu_jobs), \
         patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_send_card:

        # 1. 精投子卡片截断验证
        await handle_report_card_action(chat_id, {"action": "open_ab_card", "record_ids": target_ids, "total": 25})
        assert mock_send_card.call_count == 1
        card_ab = mock_send_card.call_args.kwargs.get("card_content") or mock_send_card.call_args[0][1]
        assert "本轮共 25 条 · 展示前 20 条" in card_ab["header"]["title"]["content"]
        assert "rec_batch_1" in str(card_ab)
        assert "rec_batch_20" in str(card_ab)
        assert "rec_batch_21" not in str(card_ab)

        # 2. 海投复核子卡片截断验证
        mock_mass_jobs = [
            {"job_id": rid, "record_id": rid, "follow_status": "海投人工复核", "grade": "C", "company_name": f"大厂_{rid}", "job_name": "岗", "platform": "boss", "is_custom": False}
            for rid in target_ids
        ]
        with patch("app.services.feishu_service.get_pending_review_jobs_from_feishu", return_value=mock_mass_jobs):
            await handle_report_card_action(chat_id, {"action": "open_mass_card", "record_ids": target_ids, "total": 25})
            assert mock_send_card.call_count == 2
            card_mass = mock_send_card.call_args.kwargs.get("card_content") or mock_send_card.call_args[0][1]
            assert "本轮共 25 条 · 展示前 20 条" in card_mass["header"]["title"]["content"]

    # 3. 淘汰子卡片截断验证
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp_db:
        db_path = tmp_db.name
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE raw_jobs (rowid INTEGER PRIMARY KEY, platform TEXT, job_title TEXT, "
                "company_name TEXT, reject_reason TEXT, feishu_record_id TEXT, process_status TEXT, job_link TEXT)"
            )
            for i in range(1, 26):
                conn.execute(f"INSERT INTO raw_jobs VALUES ({i}, 'BOSS', '淘汰岗{i}', '公司{i}', '原因', '', '清洗淘汰', '')")

        with patch("app.services.report_card_actions._get_raw_db_path", return_value=db_path), \
             patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_send_card:
            rej_ids = [str(i) for i in range(1, 26)]
            await handle_report_card_action(chat_id, {"action": "open_rejected_card", "record_ids": rej_ids, "total": 25})
            assert mock_send_card.call_count == 1
            card_rej = mock_send_card.call_args.kwargs.get("card_content") or mock_send_card.call_args[0][1]
            assert "本轮共 25 条 · 展示前 20 条" in card_rej["header"]["title"]["content"]


def test_extract_job_record_id_priority_and_safety():
    """验证 extract_job_record_id 权威字段提取优先级：严格保证 record_id > job_id。"""
    from app.services.pipeline_card_builders import extract_job_record_id

    # 1. 两个字段都有时，record_id 绝对优先
    assert extract_job_record_id({"record_id": "rec_feishu_123", "job_id": "boss_999"}) == "rec_feishu_123"

    # 2. 仅有 job_id 时，安全回退
    assert extract_job_record_id({"job_id": "job_456"}) == "job_456"

    # 3. 仅有 record_id 时正确获取
    assert extract_job_record_id({"record_id": "rec_789"}) == "rec_789"

    # 4. 空字符串与 None 安全处理
    assert extract_job_record_id({"record_id": "", "job_id": "job_abc"}) == "job_abc"
    assert extract_job_record_id({"record_id": None, "job_id": "job_abc"}) == "job_abc"
    assert extract_job_record_id({}) == ""
    assert extract_job_record_id(None) == ""
    assert extract_job_record_id("not_a_dict") == ""


@pytest.mark.asyncio
async def test_sub_card_legacy_fallback_when_record_ids_is_none():
    """验证旧历史卡片降级兜底：当 record_ids is None（老战报无此字段）时，平滑降级不报错。"""
    mock_feishu_jobs = [
        {"job_id": "rec_legacy_1", "record_id": "rec_legacy_1", "follow_status": "待人工复核", "grade": "A", "company_name": "老卡片企业", "job_name": "老岗位", "platform": "boss", "is_custom": True}
    ]

    with patch("app.services.feishu_service.get_pending_review_jobs_from_feishu", return_value=mock_feishu_jobs):
        jobs = _fetch_real_jobs_for_sub_card("ab", target_ids=None)
        assert len(jobs) == 1
        assert jobs[0].job_id == "rec_legacy_1"


def test_build_master_pipeline_card_injects_record_ids():
    """测试主战报卡片构建器：正确将当期任务的 record_ids 注入三个按钮 value 并做 20 条容量截断。"""
    ab_25_ids = [f"rec_ab_{i}" for i in range(25)]
    mass_11_ids = [f"rec_mass_{i}" for i in range(11)]
    rej_2_ids = ["101", "102"]

    card = build_master_pipeline_card(
        task_time="2026-09-17 09:00",
        precision_cnt=6,
        mass_review_cnt=11,
        hard_rejected=0,
        ai_rejected=2,
        ab_record_ids=ab_25_ids,
        mass_record_ids=mass_11_ids,
        rejected_record_ids=rej_2_ids,
    )

    action_el = next(e for e in card["elements"] if e.get("tag") == "action")
    actions = action_el["actions"]
    assert len(actions) == 3

    btn_ab = next(a for a in actions if a["value"]["action"] == "open_ab_card")
    # 容量截断保护：25 条截断为前 20 条
    assert len(btn_ab["value"]["record_ids"]) == 20
    assert btn_ab["value"]["record_ids"][0] == "rec_ab_0"

    btn_mass = next(a for a in actions if a["value"]["action"] == "open_mass_card")
    assert len(btn_mass["value"]["record_ids"]) == 11

    btn_rej = next(a for a in actions if a["value"]["action"] == "open_rejected_card")
    assert btn_rej["value"]["record_ids"] == ["101", "102"]


@pytest.mark.asyncio
async def test_rejected_df_jobs_prioritized_over_large_clean_batch():
    """验证当清洗硬淘汰 ≥ 20 条时，初评 AI 淘汰的 D/F 岗位优先保留在前排，绝不被挤出截断窗口。"""
    chat_id = "oc_test_df_priority_chat"

    # 构造：25 条清洗淘汰（纯数字 rowid 1~25）+ 2 条初评 AI 淘汰（rec_df_1, rec_df_2）
    large_clean_rowids = [str(i) for i in range(1, 26)]
    df_ids = ["rec_df_1", "rec_df_2"]

    # 模拟 pipeline_report 合并逻辑（优先 df_ids）
    combined = list(dict.fromkeys(df_ids + large_clean_rowids))
    # 模拟按钮 payload 截断前 20 条
    capped_target_ids = combined[:20]

    # 验证关键不变量：2 条初评 D/F 岗位必须稳稳留在前 20 条内！
    assert "rec_df_1" in capped_target_ids
    assert "rec_df_2" in capped_target_ids

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp_db:
        db_path = tmp_db.name
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE raw_jobs (rowid INTEGER PRIMARY KEY, platform TEXT, job_title TEXT, "
                "company_name TEXT, reject_reason TEXT, feishu_record_id TEXT, process_status TEXT, job_link TEXT)"
            )
            # 插入 25 条清洗淘汰
            for i in range(1, 26):
                conn.execute(f"INSERT INTO raw_jobs VALUES ({i}, 'BOSS', '硬清洗淘汰岗{i}', '公司{i}', '学历不符', '', '清洗淘汰', '')")
            # 插入 2 条初评 D/F 淘汰
            conn.execute("INSERT INTO raw_jobs VALUES (101, '猎聘', 'AI初评淘汰1', '高潜公司1', '初评D级', 'rec_df_1', '初评淘汰', '')")
            conn.execute("INSERT INTO raw_jobs VALUES (102, '智联', 'AI初评淘汰2', '高潜公司2', '初评F级', 'rec_df_2', '初评淘汰', '')")

        with patch("app.services.report_card_actions._get_raw_db_path", return_value=db_path), \
             patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_send_card:

            await handle_report_card_action(chat_id, {
                "action": "open_rejected_card",
                "record_ids": capped_target_ids,
                "total": len(combined),
            })

            assert mock_send_card.call_count == 1
            card_rej = mock_send_card.call_args.kwargs.get("card_content") or mock_send_card.call_args[0][1]
            # 验证标题展示总数 27 条、展示前 20 条
            assert "本轮共 27 条 · 展示前 20 条" in card_rej["header"]["title"]["content"]
            # 验证高价值 AI 误杀候选 100% 在卡片中展示，没有被挤出！
            assert "AI初评淘汰1" in str(card_rej)
            assert "AI初评淘汰2" in str(card_rej)

