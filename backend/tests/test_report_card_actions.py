# backend/tests/test_report_card_actions.py
"""战报卡片交互动作与批量放行自动化测试集。"""

import pytest
import sqlite3
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.report_card_actions import (
    is_report_card_action,
    handle_report_card_action,
)
from app.services.pipeline_card_builders import (
    JobCardItem,
    build_sub_card_ab,
    build_sub_card_mass,
    build_sub_card_rejected,
)


def test_is_report_card_action():
    assert is_report_card_action("approve_all_ab") is True
    assert is_report_card_action("approve_selected_ab") is True
    assert is_report_card_action("approve_all_mass") is True
    assert is_report_card_action("recall_selected_rejected") is True
    assert is_report_card_action("confirm_trash") is True
    assert is_report_card_action("open_ab_card") is True
    assert is_report_card_action("unknown_action") is False
    assert is_report_card_action("") is False


@pytest.mark.asyncio
async def test_approve_all_ab_success():
    """测试一键全部放行精投岗位，多维表格跟进状态更新为待投递"""
    chat_id = "oc_test_chat_123"
    action_value = {
        "action": "approve_all_ab",
        "record_ids": ["rec_1", "rec_2", "rec_3"]
    }

    with patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_update, \
         patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_card, \
         patch("app.services.report_card_actions.mark_job_approved") as mock_guard:

        await handle_report_card_action(chat_id, action_value)

        assert mock_update.call_count == 3
        mock_update.assert_any_call("rec_1", {"跟进状态": "待投递"})
        mock_update.assert_any_call("rec_2", {"跟进状态": "待投递"})
        mock_update.assert_any_call("rec_3", {"跟进状态": "待投递"})

        assert mock_guard.call_count == 3

        assert mock_card.call_count == 1
        card = mock_card.call_args[0][1]
        assert "3 个精投岗位已全部放行" in card["header"]["title"]["content"]
        assert "待投递" in str(card)


@pytest.mark.asyncio
async def test_approve_selected_ab_success():
    """测试下拉多选勾选特定岗位放行（验证写出具体放行数量 n）"""
    chat_id = "oc_test_chat_123"
    action_value = {"action": "approve_selected_ab"}
    selected_options = ["rec_selected_1", "rec_selected_2"]

    with patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_update, \
         patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_card, \
         patch("app.services.report_card_actions.mark_job_approved"):

        await handle_report_card_action(chat_id, action_value, selected_options=selected_options)

        assert mock_update.call_count == 2
        mock_update.assert_any_call("rec_selected_1", {"跟进状态": "待投递"})
        mock_update.assert_any_call("rec_selected_2", {"跟进状态": "待投递"})

        assert mock_card.call_count == 1
        card = mock_card.call_args[0][1]
        assert "选中的 2 个精投岗位放行成功" in card["header"]["title"]["content"]
        assert "待投递" in str(card)


@pytest.mark.asyncio
async def test_approve_selected_ab_empty_options_guard():
    """测试多选下拉未选择任何选项时的防呆拦截"""
    chat_id = "oc_test_chat_123"
    action_value = {"action": "approve_selected_ab"}

    with patch("app.services.feishu_service.update_feishu_record") as mock_update, \
         patch("app.services.report_card_actions.send_feishu_message", new_callable=AsyncMock) as mock_send:

        await handle_report_card_action(chat_id, action_value, selected_options=[])

        mock_update.assert_not_called()
        assert mock_send.call_count == 1
        msg = mock_send.call_args[0][1]
        assert "未勾选任何精投岗位" in msg


@pytest.mark.asyncio
async def test_approve_all_mass_success():
    """测试大厂海投一键放行（验证写出具体数量 n）"""
    chat_id = "oc_test_chat_123"
    action_value = {
        "action": "approve_all_mass",
        "record_ids": ["rec_mass_1", "rec_mass_2"]
    }

    with patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_update, \
         patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_card, \
         patch("app.services.report_card_actions.mark_job_approved"):

        await handle_report_card_action(chat_id, action_value)

        assert mock_update.call_count == 2
        mock_update.assert_any_call("rec_mass_1", {"跟进状态": "待投递"})
        mock_update.assert_any_call("rec_mass_2", {"跟进状态": "待投递"})

        assert mock_card.call_count == 1
        card = mock_card.call_args[0][1]
        assert "2 个大厂海投岗位已全部放行" in card["header"]["title"]["content"]


@pytest.mark.asyncio
async def test_recall_selected_rejected_dual_flow():
    """测试淘汰岗位误杀召回复活（验证具体数量 n 与流转至 AI 初评）。

    16cc0ee 召回三步链路后的真实语义：
    - rec_101（有飞书记录）：守卫查实时跟进状态（白名单放行）→ 重置「新线索」→ 本地标「召回待初评」→ 进入自动复评；
    - 102（纯本地 rowid、无 feishu_record_id 且无 job_link）：无法推送飞书复评 → 进失败名单，
      本地状态不动（不再是旧语义的直接标「召回待初评」），卡片为「部分完成」。
    """
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp_db:
        db_path = tmp_db.name
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE raw_jobs (rowid INTEGER PRIMARY KEY, feishu_record_id TEXT, process_status TEXT, job_link TEXT)"
            )
            conn.execute("INSERT INTO raw_jobs (rowid, feishu_record_id, process_status) VALUES (101, 'rec_101', '规则清洗淘汰')")
            conn.execute("INSERT INTO raw_jobs (rowid, feishu_record_id, process_status, job_link) VALUES (102, '', 'AI排雷淘汰', NULL)")

        chat_id = "oc_test_chat_123"
        action_value = {"action": "recall_selected_rejected"}
        selected_options = ["rec_101", "102"]

        with patch("app.services.report_card_actions._get_raw_db_path", return_value=db_path), \
             patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_update, \
             patch("app.services.feishu_service.get_job_record_from_feishu", return_value={"fields": {"跟进状态": "已淘汰"}}) as mock_record, \
             patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_card, \
             patch("app.services.report_card_actions.mark_job_approved"):

            await handle_report_card_action(chat_id, action_value, selected_options=selected_options)

            # 召回守卫 fail-closed：飞书路径先查实时跟进状态，白名单（新线索/已淘汰/空）才放行；
            # 无凭证环境下守卫会拒召（update 0 次调用），故必须 mock 掉守卫的记录查询
            mock_record.assert_called_once()
            # 验证仅针对 rec_101（飞书路径）调用了飞书写 API；102 无链接走失败分支不调
            mock_update.assert_called_once_with("rec_101", {"跟进状态": "新线索"})

            # 验证本地 SQLite：rec_101 标「召回待初评」；102 无岗位链接无法复评，保持原淘汰态
            with sqlite3.connect(db_path) as conn:
                st1 = conn.execute("SELECT process_status FROM raw_jobs WHERE feishu_record_id = 'rec_101'").fetchone()[0]
                st2 = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 102").fetchone()[0]
                assert st1 == "召回待初评"
                assert st2 == "AI排雷淘汰"

            assert mock_card.call_count == 1
            card = mock_card.call_args[0][1]
            assert "误杀召回部分完成 (成功 1 / 失败 1)" in card["header"]["title"]["content"]
            # 目标队列字段由 build_action_result_card 渲染为「AI 初步评估（已跳过初筛）」
            assert "AI 初步评估" in str(card)


@pytest.mark.asyncio
async def test_confirm_trash_dual_sync():
    """测试确认淘汰归档（飞书与本地 SQLite 双端一致性）"""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp_db:
        db_path = tmp_db.name
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE raw_jobs (rowid INTEGER PRIMARY KEY, feishu_record_id TEXT, process_status TEXT)"
            )
            conn.execute("INSERT INTO raw_jobs (rowid, feishu_record_id, process_status) VALUES (201, 'rec_trash_1', '待归档')")
            conn.execute("INSERT INTO raw_jobs (rowid, feishu_record_id, process_status) VALUES (202, '', '待归档')")

        chat_id = "oc_test_chat_123"
        action_value = {
            "action": "confirm_trash",
            "record_ids": ["rec_trash_1", "202"]
        }

        with patch("app.services.report_card_actions._get_raw_db_path", return_value=db_path), \
             patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_update, \
             patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_card:

            await handle_report_card_action(chat_id, action_value)

            mock_update.assert_called_once_with("rec_trash_1", {"跟进状态": "不合适"})

            with sqlite3.connect(db_path) as conn:
                st1 = conn.execute("SELECT process_status FROM raw_jobs WHERE feishu_record_id = 'rec_trash_1'").fetchone()[0]
                st2 = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 202").fetchone()[0]
                assert st1 == "已淘汰"
                assert st2 == "已淘汰"

            assert mock_card.call_count == 1
            card = mock_card.call_args[0][1]
            assert "2 个淘汰岗位已确认归档" in card["header"]["title"]["content"]


@pytest.mark.asyncio
async def test_partial_failure_handling():
    """测试部分失败场景，验证不假成功且以卡片准确汇报失败清单"""
    chat_id = "oc_test_chat_123"
    action_value = {
        "action": "approve_all_ab",
        "record_ids": ["rec_ok", "rec_fail"]
    }

    def _mock_update(rid, fields):
        if rid == "rec_fail":
            raise RuntimeError("飞书 API 超时")
        return True

    with patch("app.services.feishu_service.update_feishu_record", side_effect=_mock_update), \
         patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_card, \
         patch("app.services.report_card_actions.mark_job_approved"):

        await handle_report_card_action(chat_id, action_value)

        assert mock_card.call_count == 1
        card = mock_card.call_args[0][1]
        assert "部分放行完成" in card["header"]["title"]["content"]
        assert "rec_fail" in str(card)


@pytest.mark.asyncio
async def test_sub_card_builders_empty_and_populated():
    """测试子卡片构建器（覆盖空列表与有数据渲染）"""
    # 1. 空列表渲染
    card_ab_empty = build_sub_card_ab([])
    assert "0 条待审" in card_ab_empty["header"]["title"]["content"]
    assert "本轮暂无待审批的精投岗位" in card_ab_empty["elements"][0]["text"]["content"]

    card_mass_empty = build_sub_card_mass([])
    assert "0 条待审" in card_mass_empty["header"]["title"]["content"]

    card_rej_empty = build_sub_card_rejected([])
    assert "0 条淘汰" in card_rej_empty["header"]["title"]["content"]

    # 2. 有数据渲染
    sample_item = JobCardItem(
        job_id="rec_test_001",
        title="1. [BOSS] 测试企业 - AI产品经理",
        grade="A级",
        short_name="测试企业 · 产品经理",
        color="green",
        detail_url="https://feishu.cn/base/test?record=rec_test_001",
        extra_info="公司规模: 1000人以上"
    )
    card_ab_pop = build_sub_card_ab([sample_item])
    assert "共 1 条就绪" in card_ab_pop["header"]["title"]["content"]
    assert "rec_test_001" in str(card_ab_pop)


@pytest.mark.asyncio
async def test_handle_open_sub_cards_dispatch():
    """测试点击查看详情按钮调出对应的子卡片（open_ab_card / open_mass_card / open_rejected_card）"""
    chat_id = "oc_test_chat_123"

    with patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_send_card, \
         patch("app.services.report_card_actions._fetch_real_jobs_for_sub_card", return_value=[]):

        # 1. 调出精投卡片
        await handle_report_card_action(chat_id, {"action": "open_ab_card"})
        assert mock_send_card.call_count == 1
        assert "精投" in str(mock_send_card.call_args)

        # 2. 调出大厂海投卡片
        await handle_report_card_action(chat_id, {"action": "open_mass_card"})
        assert mock_send_card.call_count == 2
        assert "海投" in str(mock_send_card.call_args)

        # 3. 调出淘汰卡片
        await handle_report_card_action(chat_id, {"action": "open_rejected_card"})
        assert mock_send_card.call_count == 3
        assert "淘汰" in str(mock_send_card.call_args)


@pytest.mark.asyncio
async def test_fetch_real_jobs_filter_safety():
    """测试真实岗位拉取过滤安全性：杜绝拉取已投递历史岗位、杜绝假A级默认值、排除已召回记录"""
    from app.services.report_card_actions import _fetch_real_jobs_for_sub_card

    # 1. 验证精投岗位 (ab) 与大厂海投 (mass) 过滤
    mock_jobs = [
        # 正常待复核 A 级岗位 -> 应该匹配 ab
        {"job_id": "rec_ab_1", "follow_status": "简历人工复核", "grade": "A", "company_name": "公司A", "job_name": "岗位A", "platform": "boss", "is_custom": True},
        # 正常待复核 B 级岗位 -> 应该匹配 ab
        {"job_id": "rec_ab_2", "follow_status": "待人工复核", "grade": "B", "company_name": "公司B", "job_name": "岗位B", "platform": "liepin", "is_custom": False},
        # 已投递但评级为 A -> 绝对禁止匹配 (P0 防范)
        {"job_id": "rec_ab_3", "follow_status": "已投递", "grade": "A", "company_name": "公司C", "job_name": "岗位C", "platform": "boss", "is_custom": True},
        # 待复核但评级为 C -> 不匹配 ab，但匹配 mass
        {"job_id": "rec_ab_4", "follow_status": "海投人工复核", "grade": "C", "company_name": "公司D", "job_name": "岗位D", "platform": "51job", "is_custom": False},
        # 不合适/已淘汰 -> 绝对禁止匹配
        {"job_id": "rec_ab_5", "follow_status": "不合适", "grade": "A", "company_name": "公司E", "job_name": "岗位E", "platform": "zhilian", "is_custom": False},
    ]
    with patch("app.services.feishu_service.get_pending_review_jobs_from_feishu", return_value=mock_jobs):
        jobs_ab = _fetch_real_jobs_for_sub_card("ab")
        job_ids = [j.job_id for j in jobs_ab]
        assert "rec_ab_1" in job_ids
        assert "rec_ab_2" in job_ids
        assert "rec_ab_3" not in job_ids  # 已投递被排除
        assert "rec_ab_4" not in job_ids  # C级海投不入精投卡片
        assert "rec_ab_5" not in job_ids  # 不合适被排除

        jobs_mass = _fetch_real_jobs_for_sub_card("mass")
        mass_ids = [j.job_id for j in jobs_mass]
        assert "rec_ab_4" in mass_ids      # C级海投进入海投卡片
        assert "rec_ab_3" not in mass_ids  # 已投递被排除
        assert "rec_ab_5" not in mass_ids  # 不合适被排除

    # 3. 验证淘汰岗位 (rejected) 排除「召回待投递」与「已投递」
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp_db:
        db_path = tmp_db.name
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE raw_jobs (rowid INTEGER PRIMARY KEY, platform TEXT, job_title TEXT, "
                "company_name TEXT, reject_reason TEXT, feishu_record_id TEXT, process_status TEXT, job_link TEXT)"
            )
            # 正常淘汰岗位（带原平台链接）
            conn.execute("INSERT INTO raw_jobs VALUES (1, 'BOSS', '测试岗1', '公司1', '薪资不符', '', 'AI排雷淘汰', 'https://www.zhipin.com/job/1')")
            # 已召回复活的岗位（reject_reason 仍有值，但状态为召回待初评，绝对不能再次被淘汰拉取）
            conn.execute("INSERT INTO raw_jobs VALUES (2, 'BOSS', '测试岗2', '公司2', '误判原因', 'rec_rej_2', '召回待初评', 'https://www.zhipin.com/job/2')")
            # 已经投递的岗位
            conn.execute("INSERT INTO raw_jobs VALUES (3, 'BOSS', '测试岗3', '公司3', '旧原因', 'rec_rej_3', '已投递', '')")
            # 新线索岗位
            conn.execute("INSERT INTO raw_jobs VALUES (4, 'BOSS', '测试岗4', '公司4', '误判', 'rec_rej_4', '新线索', '')")

        with patch("app.services.report_card_actions._get_raw_db_path", return_value=db_path):
            jobs_rej = _fetch_real_jobs_for_sub_card("rejected")
            rej_ids = [j.job_id for j in jobs_rej]
            assert "1" in rej_ids
            assert "rec_rej_2" not in rej_ids  # 召回待初评严格被排除
            assert "rec_rej_3" not in rej_ids  # 已投递严格被排除
            assert "rec_rej_4" not in rej_ids  # 新线索严格被排除
            # 验证即使无飞书 record_id，也能提取原平台 job_link 作为详情链接
            rej_item = next(j for j in jobs_rej if j.job_id == "1")
            assert rej_item.detail_url == "https://www.zhipin.com/job/1"


@pytest.mark.asyncio
async def test_confirm_trash_failure_reporting():
    """测试确认淘汰失败时的真实告警回执卡片（防假成功）"""
    chat_id = "oc_test_chat_123"
    action_value = {
        "action": "confirm_trash",
        "record_ids": ["rec_fail_1"]
    }

    with patch("app.services.feishu_service.update_feishu_record", return_value=False), \
         patch("app.services.report_card_actions.send_feishu_card", new_callable=AsyncMock) as mock_card:

        await handle_report_card_action(chat_id, action_value)

        assert mock_card.call_count == 1
        card = mock_card.call_args[0][1]
        assert "淘汰归档部分异常" in card["header"]["title"]["content"]


def test_card_builders_form_structure():
    """测试三张子卡片中方式一表单容器、去除总表链接、保留岗位详情链接及高颜值回执卡片结构"""
    from app.services.pipeline_card_builders import (
        JobCardItem,
        build_sub_card_ab,
        build_sub_card_mass,
        build_sub_card_rejected,
        build_action_result_card,
    )

    test_jobs = [
        JobCardItem(job_id="rec_001", title="测试岗位1", grade="A级", short_name="测1", detail_url="https://feishu.cn/rec_001"),
        JobCardItem(job_id="rec_002", title="测试岗位2", grade="B级", short_name="测2", detail_url="https://feishu.cn/rec_002"),
    ]

    # 1. 精投卡片验证：总表入口已彻底删除，但各岗位详情直达保留
    card_ab = build_sub_card_ab(test_jobs)
    form_ab = next(e for e in card_ab["elements"] if e.get("tag") == "form")
    assert form_ab["name"] == "form_approve_ab"
    btn_ab = next(e for e in form_ab["elements"] if e.get("tag") == "button")
    assert btn_ab["action_type"] == "form_submit"
    assert "放行已勾选" in btn_ab["text"]["content"]
    assert "查阅全部精投岗位详情" not in str(card_ab)
    assert "https://feishu.cn/rec_001" in str(card_ab)

    # 2. 海投卡片验证：总表入口已彻底删除，文案收敛为海投岗位，不出现具体等级
    card_mass = build_sub_card_mass(test_jobs)
    form_mass = next(e for e in card_mass["elements"] if e.get("tag") == "form")
    assert form_mass["name"] == "form_approve_mass"
    btn_mass = next(e for e in form_mass["elements"] if e.get("tag") == "button")
    assert btn_mass["action_type"] == "form_submit"
    assert "放行已勾选" in btn_mass["text"]["content"]
    assert "查阅大厂海投岗位详情" not in str(card_mass)
    assert "C/D 级" not in str(card_mass)
    assert "https://feishu.cn/rec_001" in str(card_mass)

    # 3. 淘汰卡片验证：总表入口已删除，必须包含确认召回按钮并明确进入 AI 初评
    card_rej = build_sub_card_rejected(test_jobs)
    form_rej = next(e for e in card_rej["elements"] if e.get("tag") == "form")
    assert form_rej["name"] == "form_recall_rejected"
    btn_rej = next(e for e in form_rej["elements"] if e.get("tag") == "button")
    assert btn_rej["action_type"] == "form_submit"
    assert "AI 初评" in btn_rej["text"]["content"]
    assert "查阅全部岗位总表" not in str(card_rej)

    # 4. 回执卡片结构验证：必须包含双列指标与直达跳转按钮
    res_card = build_action_result_card(
        title="🎉 选中的 2 个精投岗位放行成功！",
        succ_cnt=2,
        target_queue="待投递",
        target_status="待投递",
        flow_desc="已推入待投递队列",
    )
    assert res_card["header"]["title"]["content"] == "🎉 选中的 2 个精投岗位放行成功！"
    cols = next(e for e in res_card["elements"] if e.get("tag") == "column_set")
    assert len(cols["columns"]) == 2
    actions = next(e for e in res_card["elements"] if e.get("tag") == "action")
    assert any("电脑端指挥中心" in btn["text"]["content"] for btn in actions["actions"])


def test_master_pipeline_card_structure():
    """测试主战报卡片（对齐图 2 规范）：4列效能指标、渠道明细、初评梯队与3个子卡片跳转动作"""
    from app.services.pipeline_card_builders import build_master_pipeline_card

    card = build_master_pipeline_card(
        task_time="2026-09-17 09:00", duration_mins=28, total_scraped=20, hard_passed=20,
        hard_rejected=0, ai_passed=16, ai_rejected=4, precision_cnt=8,
        channel_counts={"BOSS直聘": 5, "猎聘": 5, "智联招聘": 5, "51job": 5},
        grade_counts={"A": 2, "B": 6, "C": 4, "D/F": 3}, mass_review_cnt=4, other_review_cnt=0,
    )

    assert "全链路指挥中心 · 定时任务 · 09:00" in card["header"]["title"]["content"]

    # 校验 4 列看板
    col_set = next(e for e in card["elements"] if e.get("tag") == "column_set")
    cols = col_set["columns"]
    assert len(cols) == 4
    assert "本轮抓取" in str(cols[0]) and "20 条" in str(cols[0])
    assert "硬清洗通过" in str(cols[1]) and "20 条" in str(cols[1])
    assert "AI清洗通过" in str(cols[2]) and "16 条" in str(cols[2])
    assert "精投岗位" in str(cols[3]) and "8 条" in str(cols[3])

    # 校验渠道来源与初评梯队
    card_str = str(card)
    assert "BOSS直聘" in card_str
    assert "猎聘" in card_str
    assert "智联招聘" in card_str
    assert "51job" in card_str
    assert "A级" in card_str
    assert "精投岗位概览" in card_str
    assert "海投撞门槛" in card_str

    # 校验 3 个跳转按钮
    action_el = next(e for e in card["elements"] if e.get("tag") == "action")
    actions = action_el["actions"]
    assert len(actions) == 3
    action_types = [a["value"]["action"] for a in actions]
    assert "open_ab_card" in action_types
    assert "open_mass_card" in action_types
    assert "open_rejected_card" in action_types


def test_delivery_batch_card_structure():
    """测试每轮自动投递卡片同步：4列看板、成功条目、受阻条目与跳转入口"""
    from app.services.delivery_card_notifier import build_delivery_batch_card

    ok_jobs = [
        {"platform": "boss", "company_name": "腾讯", "job_name": "AI产品经理"},
        {"platform": "liepin", "company_name": "阿里巴巴", "job_name": "后端架构师"},
    ]
    failed_jobs = [
        ({"platform": "51job", "company_name": "测试企业", "job_name": "前端专家"}, "岗位已下线"),
    ]

    card = build_delivery_batch_card(
        window_label="上午波次 (10:00-11:30)",
        total_targets=3,
        ok_jobs=ok_jobs,
        failed_jobs=failed_jobs,
        skipped_cnt=0,
    )

    assert "自动投递战报" in card["header"]["title"]["content"]
    assert "上午波次" in str(card)

    # 4 列看板
    col_set = next(e for e in card["elements"] if e.get("tag") == "column_set")
    assert len(col_set["columns"]) == 4

    # 包含成功与失败清单
    card_str = str(card)
    assert "成功送达清单" in card_str
    assert "腾讯 - AI产品经理" in card_str
    assert "投递受阻清单" in card_str
    assert "岗位已下线" in card_str

    # 包含电脑端跳转
    action_el = next(e for e in card["elements"] if e.get("tag") == "action")
    assert any("电脑端指挥中心" in btn["text"]["content"] for btn in action_el["actions"])
