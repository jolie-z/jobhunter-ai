"""即时任务战报 2026-10-10 需求批次回归锁。

覆盖：
- 3.1 时间精确到秒（自证非整点舍入）
- 3.2 主卡自动投递岗位数 + delivered 详情卡（平台+公司+岗位title）
- 3.3 其他待审批两行标注
- 3.4 自动投递执行情况段（平台分布+失败原因汇总）
- 3.5 第四分流按钮 + delivered 卡交互注册 + 数据分支按 record_ids 精确过滤
- 问题2：归档回执词与词表对齐（已确认淘汰）+ 快照排除终态
"""
from datetime import datetime
from unittest.mock import patch

from app.services.pipeline_card_builders import (
    JobCardItem,
    build_master_pipeline_card,
    build_sub_card_delivered,
)


def _card_with_delivery():
    return build_master_pipeline_card(
        task_time="2026-10-10 22:03:08",
        duration_mins=30,
        total_scraped=12,
        hard_passed=12,
        hard_rejected=0,
        ai_passed=11,
        ai_rejected=1,
        precision_cnt=5,
        channel_counts={"BOSS直聘": 3, "猎聘": 3, "智联招聘": 3, "51job": 3},
        grade_counts={"A": 0, "B": 5, "C": 3, "D/F": 3},
        mass_review_cnt=3,
        auto_delivered_cnt=3,
        delivered_record_ids=["recD1", "recD2", "recD3", "recF1", "recF2", "recF3"],
        delivered_by_platform={"BOSS直聘": 2, "猎聘": 1},
        delivery_fail_reasons={"页面改版导致选择器失效": 2, "登录态失效": 1},
        delivery_fail_cnt=3,
        trigger_source="manual",
    )


def test_master_card_time_to_seconds():
    """3.1 正文时间带秒，肉眼可验证非整点舍入"""
    card = _card_with_delivery()
    time_el = card["elements"][0]
    assert "2026-10-10 22:03:08" in time_el["text"]["content"]
    # 标题继承同一时间源（含秒）
    assert "22:03:08" in card["header"]["title"]["content"]


def test_master_card_pending_labels():
    """3.3 其他待审批两行标注"""
    card = _card_with_delivery()
    content = str(card["elements"])
    assert "【已在待审批tab等待审批放行】" in content
    assert "【已执行自动投递】" in content


def test_master_card_delivery_section():
    """3.2/3.4 自动投递执行情况段：总量、平台分布、失败原因汇总"""
    card = _card_with_delivery()
    content = str(card["elements"])
    assert "🚀 自动投递执行情况" in content
    assert "投递成功" in content and "BOSS直聘" in content and "猎聘" in content
    assert "投递失败" in content
    assert "页面改版导致选择器失效" in content
    assert "登录态失效" in content


def test_master_card_delivery_section_hidden_when_no_delivery():
    """无投递动作时整段收起（不出现空段落）"""
    card = build_master_pipeline_card(task_time="2026-10-10 22:03:08")
    assert "自动投递执行情况" not in str(card["elements"])


def test_master_card_fourth_button():
    """3.5 第四分流按钮携带 delivered ids 与 total"""
    card = _card_with_delivery()
    action_el = next(e for e in card["elements"] if e.get("tag") == "action")
    delivered_btn = next(
        a for a in action_el["actions"] if a["value"].get("action") == "open_delivered_card"
    )
    assert delivered_btn["value"]["record_ids"] == ["recD1", "recD2", "recD3", "recF1", "recF2", "recF3"]
    assert delivered_btn["value"]["total"] == 6


def test_sub_card_delivered_renders_status_and_reason():
    """3.5 详情卡：成功/失败状态着色 + 失败原因 + 表格详情链接"""
    jobs = [
        JobCardItem(
            job_id="recOK",
            title="1. [BOSS直聘] 字节跳动 - 后端开发",
            grade="✅ 投递成功",
            short_name="字节跳动 · 后端开发",
            color="green",
            detail_url="https://feishu.cn/base/x?table=y&record=recOK",
        ),
        JobCardItem(
            job_id="recFail",
            title="2. [猎聘] 腾讯 - 测试开发",
            grade="❌ 投递失败：简历附件上传超时",
            short_name="腾讯 · 测试开发",
            color="red",
            detail_url="https://feishu.cn/base/x?table=y&record=recFail",
        ),
    ]
    card = build_sub_card_delivered(jobs=jobs, total=7)
    content = str(card)
    assert "🚀 自动投递详情" in content
    assert "本轮共 7 条 · 展示前 2 条" in content
    assert "✅ 投递成功" in content
    assert "❌ 投递失败：简历附件上传超时" in content
    assert "表格详情" in content
    assert "更多请前往电脑端客户端查看完整情况" in content


def test_sub_card_delivered_empty_state():
    card = build_sub_card_delivered(jobs=[], total=0)
    assert "本轮无自动投递岗位" in str(card["elements"])


def test_delivered_action_registered():
    """3.5 交互注册：open_delivered_card 属于战报动作集合且有 builder 映射"""
    from app.services.report_card_actions import REPORT_CARD_ACTIONS, is_report_card_action
    assert is_report_card_action("open_delivered_card")
    assert "open_sub_card_delivered" in REPORT_CARD_ACTIONS


def test_fetch_delivered_jobs_filters_by_task_ids():
    """3.5 数据分支：严格按当次任务 record_ids 过滤 + 状态/失败原因映射"""
    import app.services.report_card_actions as rca

    fake_rows = [
        {"record_id": "recOK", "platform": "BOSS直聘", "company": "字节跳动", "job_title": "后端开发",
         "follow_status": "已投递", "fail_log": ""},
        {"record_id": "recFail", "platform": "猎聘", "company": "腾讯", "job_title": "测试开发",
         "follow_status": "投递失败", "fail_log": "简历附件上传超时"},
        {"record_id": "recOther", "platform": "智联招聘", "company": "别家", "job_title": "不该出现",
         "follow_status": "已投递", "fail_log": ""},
    ]
    with patch.object(rca.feishu_service, "get_delivery_result_jobs", return_value=fake_rows):
        items = rca._fetch_real_jobs_for_sub_card("delivered", target_ids=["recOK", "recFail"])

    assert len(items) == 2, "任务隔离：recOther 不得混入"
    ok = next(i for i in items if i.job_id == "recOK")
    fail = next(i for i in items if i.job_id == "recFail")
    assert "✅ 投递成功" in ok.grade and ok.color == "green"
    assert "❌ 投递失败：简历附件上传超时" in fail.grade and fail.color == "red"
    assert ok.detail_url.endswith("record=recOK")


def test_fetch_delivered_jobs_empty_ids_returns_empty():
    """显式空 ID 列表 = 当次任务 0 条 → 空态，严禁扫历史库"""
    import app.services.report_card_actions as rca
    with patch.object(rca.feishu_service, "get_delivery_result_jobs") as m:
        items = rca._fetch_real_jobs_for_sub_card("delivered", target_ids=[])
    assert items == []
    m.assert_not_called()


def test_archive_receipt_word_aligns_vocab():
    """问题2：归档回执词必须取自词表 REJECT_CONFIRMED（已确认淘汰），杜绝「已归档淘汰」旧词复活"""
    import inspect
    import app.services.report_card_actions as rca
    src = inspect.getsource(rca)
    assert "已归档淘汰" not in src, "旧词「已归档淘汰」不得回潮"
    assert "target_queue=process_status.REJECT_CONFIRMED" in src


def test_snapshot_excludes_confirmed_reject():
    """问题2：快照 SQL 排除「已确认淘汰」终态（飞书归档后桌面端看板同步离场）"""
    import inspect
    import app.automation.snapshot_service as ss
    src = inspect.getsource(ss)
    assert "process_status NOT IN" in src
    assert "process_status.REJECT_CONFIRMED" in src


def test_delivery_stats_plumbing_into_builder():
    """ plumbing：send_pipeline_master_card 从 job_results 统计投递数据并传入 builder（mock 发送验证）"""
    import asyncio
    from app.automation import pipeline_report as pr

    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return {"elements": []}

    job_results = [
        {"record_id": "recA", "platform": "BOSS直聘", "grade": "D", "outcome": "delivered"},
        {"record_id": "recB", "platform": "猎聘", "grade": "D", "outcome": "failed", "error": "滑动验证失败"},
        {"record_id": "recC", "platform": "猎聘", "grade": "B", "outcome": "waiting"},
    ]
    with patch("app.services.pipeline_card_builders.build_master_pipeline_card", side_effect=fake_builder), \
         patch("app.core.feishu_messaging.is_valid_receive_id", return_value=True), \
         patch("app.core.feishu_messaging.send_feishu_card", return_value=True), \
         patch("app.services.report_feishu._get_receive_id", return_value="oc_test"):
        ok = asyncio.run(pr.send_pipeline_master_card(
            started_at=datetime(2026, 10, 10, 22, 3, 8),
            scrape_counts={"BOSS直聘": 2},
            cleaning={"hard_rejected": 0, "hard_passed": 2, "ai_rejected": 0, "ai_passed": 2},
            job_results=job_results,
            trigger_source="manual",
        ))
    assert ok is True
    assert captured["delivered_record_ids"] == ["recA", "recB"], "失败岗位 record_id 也必须进详情卡按钮值（R1 P1）"
    assert captured["delivered_by_platform"] == {"BOSS直聘": 1}
    assert captured["delivery_fail_cnt"] == 1
    assert any("滑动验证失败" in r for r in captured["delivery_fail_reasons"])
    assert captured["task_time"] == "2026-10-10 22:03:08"


def test_failed_jobs_record_ids_in_button_value():
    """R1 P1 回归锁：失败岗位的 record_id 必须进详情卡按钮值（否则详情卡永远看不到失败明细）"""
    card = _card_with_delivery()
    action_el = next(e for e in card["elements"] if e.get("tag") == "action")
    delivered_btn = next(
        a for a in action_el["actions"] if a["value"].get("action") == "open_delivered_card"
    )
    # 3 成功 + 3 失败都要在按钮值里
    assert len(delivered_btn["value"]["record_ids"]) == 6
    assert delivered_btn["value"]["total"] == 6


def test_fetch_delivered_jobs_none_ids_rejects_full_scan():
    """R1 P1 回归锁：target_ids=None（异常路径）强制空态，严禁回退全表扫描历史投递"""
    import app.services.report_card_actions as rca
    fake_rows = [{"record_id": "recHistory", "platform": "猎聘", "company": "历史公司",
                  "job_title": "历史岗位", "follow_status": "已投递", "fail_log": ""}]
    with patch.object(rca.feishu_service, "get_delivery_result_jobs", return_value=fake_rows) as m:
        items = rca._fetch_real_jobs_for_sub_card("delivered", target_ids=None)
    assert items == []
    m.assert_not_called(), "None 兜底必须在拉取前拒绝，不得触发飞书全量拉取"


def test_delivery_result_jobs_paginates():
    """R1 P1 回归锁：拉取函数必须翻页（has_more/page_token），单页截断会让新投递永远拉不到"""
    import asyncio
    import app.services.feishu_service as fs

    calls = []

    class FakeResp:
        def __init__(self, payload):
            self._p = payload
        def json(self):
            return {"code": 0, "data": self._p}

    def fake_request(method, url, headers=None, json=None):
        calls.append(json)
        status = json["filter"]["conditions"][0]["value"][0]
        page_token = json.get("page_token")
        if status == "已投递":
            items = [{"record_id": f"recP{i}", "fields": {}} for i in range(100)]
            has_more = page_token is None  # 首页还有第二页
            next_token = "page2" if has_more else ""
            return FakeResp({"items": items, "has_more": has_more, "page_token": next_token})
        return FakeResp({"items": [], "has_more": False})

    with patch.object(fs, "get_tenant_access_token", return_value="tok"), \
         patch.object(fs, "safe_feishu_request", side_effect=fake_request):
        jobs = fs.get_delivery_result_jobs()

    delivered_calls = [c for c in calls if c["filter"]["conditions"][0]["value"][0] == "已投递"]
    assert len(delivered_calls) == 2, "首页 has_more=True 必须带 page_token 翻第二页"
    assert delivered_calls[1]["page_token"] == "page2"
    assert len([j for j in jobs if j["record_id"].startswith("recP")]) == 200, "两页记录全部入内存"
