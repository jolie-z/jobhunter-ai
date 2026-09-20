import asyncio
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.automation import run_snapshot as _rs
from app.services import feishu_service


@pytest.mark.asyncio
async def test_workflow_delivery_node_failure_writes_feishu_status():
    """测试 workflow.py 的 delivery_node 在投递失败时，自动回写飞书跟进状态为「投递失败」"""
    from app.automation import workflow

    mock_state = {
        "record_id": "rec_test_wf_fail_01",
        "job_id": "rec_test_wf_fail_01",
        "platform": "boss",
        "job_url": "https://www.zhipin.com/job_detail/test.html",
        "company_name": "测试企业",
        "job_name": "AI产品经理",
        "grade": "B",
        "is_custom": False,
        "image_items": [{"token": "tok123", "name": "test.jpg"}],
        "greeting": "您好，沟通测试",
        "feishu_fields": {},
    }

    mock_tool = MagicMock()
    mock_tool.ainvoke = AsyncMock(return_value="❌ BOSS 投递引擎执行失败：网络连接超时")

    with patch("app.automation.workflow.deliver_boss_job", mock_tool), \
         patch("app.services.feishu_service.mark_job_delivery_failed") as mock_mark_failed, \
         patch("app.automation.workflow.update_feishu_status") as mock_update_status:

        try:
            res = await workflow.delivery_node(mock_state)

            assert "error" in res
            assert "❌ BOSS 投递引擎执行失败" in res["error"]
            # 断言调用了飞书回写
            mock_mark_failed.assert_called_once_with(
                "rec_test_wf_fail_01",
                "❌ BOSS 投递引擎执行失败：网络连接超时"
            )
            # 成功分支不应被调用
            mock_update_status.ainvoke.assert_not_called()
        finally:
            _rs.remove_delivery_failure("rec_test_wf_fail_01")


@pytest.mark.asyncio
async def test_delivery_router_record_batch_failure_writes_feishu():
    """测试 delivery_router 的 _record_batch_delivery_failure 登记台账并非阻塞回写飞书「投递失败」"""
    from app.automation.routes import delivery_router

    test_item = {
        "company": "测试科技",
        "title": "大模型专家",
        "platform": "51job",
        "grade": "A",
        "fields": {"岗位链接": "https://51job.com/test"}
    }

    with patch("app.automation.run_snapshot.record_delivery_failure") as mock_rs_record, \
         patch("app.services.feishu_service.mark_job_delivery_failed") as mock_feishu_mark:

        await delivery_router._record_batch_delivery_failure("rec_test_router_01", test_item, "51job今日附件上传配额已耗尽")

        mock_rs_record.assert_called_once()
        mock_feishu_mark.assert_called_once_with("rec_test_router_01", "51job今日附件上传配额已耗尽")


@pytest.mark.asyncio
async def test_delivery_tasks_stale_quota_failure_resets_and_launches():
    """测试 delivery_tasks 跨天配额失败自愈：
    昨日因 51job 配额耗尽被拦截的岗位，在次日波次发射时，
    跨天自愈逻辑优先将其从失败台账中摘除，成功恢复发射，不被失败守卫错误阻拦。
    """
    from app.automation import delivery_tasks
    from app.automation.upload_quota import QUOTA_EXHAUSTED_ERROR

    job_yesterday_quota = {
        "job_id": "rec_quota_stale_1",
        "job_name": "51job跨天恢复岗",
        "platform": "51job",
        "company_name": "51科技",
        "is_custom": False,
    }

    from datetime import datetime, timedelta
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

    # 模拟昨日发生的配额失败记录（命中 QUOTA_EXHAUSTED_ERROR 且 failed_at 动态标记为昨天）
    fake_stale_failure = {
        "rec_quota_stale_1": {
            "error": QUOTA_EXHAUSTED_ERROR,
            "failed_at": yesterday_str,
            "failure_count": 1,
            "retries": 1,
            "platform": "51job",
        }
    }

    delivering_history = []
    def spy_mark(jids):
        delivering_history.append(("mark", list(jids)))
    def spy_unmark(jids):
        delivering_history.append(("unmark", list(jids)))

    async def fake_resume(fn, jid, pipeline_app=None):
        return True, "✅ 投递成功"

    with patch("app.automation.run_snapshot.get_delivery_failures", return_value=dict(fake_stale_failure)), \
         patch("app.automation.run_snapshot.is_job_retrying", return_value=False), \
         patch("app.automation.run_snapshot.remove_delivery_failure") as mock_remove_fail, \
         patch("app.automation.run_snapshot.mark_job_delivering", side_effect=spy_mark), \
         patch("app.automation.run_snapshot.unmark_job_delivering", side_effect=spy_unmark), \
         patch("app.automation.delivery_tasks._delivery_guard_ok", return_value=True), \
         patch("app.automation.scheduler._check_non_workday", return_value=(True, "")), \
         patch("app.automation.scheduler._check_schedule_date_range", return_value=(True, "")), \
         patch("app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu", return_value=[job_yesterday_quota]), \
         patch("app.automation.delivery_tasks.get_autopilot_config", return_value={"is_enabled": True, "auto_deliver_platforms": ["51job"]}), \
         patch("app.automation.delivery_tasks._call_resume", side_effect=fake_resume), \
         patch("app.automation.materials.refresh_mass_materials_for_jobs", new_callable=AsyncMock, return_value=0), \
         patch("app.automation.self_heal.run_self_heal", new_callable=AsyncMock), \
         patch("app.services.delivery_card_notifier.send_delivery_round_report", new_callable=AsyncMock):

        mock_pipeline_app = MagicMock()
        mock_pipeline_app.aget_state = AsyncMock(return_value=None)
        await delivery_tasks.scheduled_delivery_batch_task(window_label="跨天自愈测试", pipeline_app=mock_pipeline_app)

        # 1. 跨天配额失败应该被从本地失败台账中主动移除（发射前跨天自愈 1 次 + 发射成功后清理 1 次，共 2 次）
        assert mock_remove_fail.call_count == 2
        mock_remove_fail.assert_has_calls([
            call("rec_quota_stale_1"),
            call("rec_quota_stale_1")
        ])
        # 2. 该岗位成功恢复发射，执行了单岗打标与释放
        assert ("mark", ["rec_quota_stale_1"]) in delivering_history
        assert ("unmark", ["rec_quota_stale_1"]) in delivering_history


@pytest.mark.asyncio
async def test_delivery_tasks_single_job_tagging_and_failure_guard():
    """测试 delivery_tasks 波次执行时：
    1. 失败台账中未获审批重试的岗位被守卫拦截，拒绝自动发射；
    2. 正常发射的岗位在发射前单岗打标、发射后释放，杜绝全量 running 冲刷；
    3. 发射失败后回写飞书「投递失败」。
    """
    from app.automation import delivery_tasks

    # 模拟两个岗位：job1 在失败台账中未重试，job2 正常就绪
    job1 = {"job_id": "rec_fail_guard_1", "job_name": "历史失败岗", "platform": "zhilian", "company_name": "旧公司"}
    job2 = {"job_id": "rec_fresh_ready_2", "job_name": "新就绪岗", "platform": "zhilian", "company_name": "新公司"}

    targets = [job1, job2]

    # 模拟本地失败台账（持久性故障，如引擎执行失败，必须被分诊拦截）
    fake_failures = {"rec_fail_guard_1": {"error": "❌ 智联投递引擎执行失败", "retries": 1}}

    delivering_history = []
    def spy_mark(jids):
        delivering_history.append(("mark", list(jids)))
    def spy_unmark(jids):
        delivering_history.append(("unmark", list(jids)))

    async def fake_resume(fn, jid, pipeline_app=None):
        if jid == "rec_fresh_ready_2":
            return False, "❌ 智联连接中断"
        return True, "成功"

    with patch("app.automation.run_snapshot.get_delivery_failures", return_value=fake_failures), \
         patch("app.automation.run_snapshot.is_job_retrying", return_value=False), \
         patch("app.automation.run_snapshot.mark_job_delivering", side_effect=spy_mark), \
         patch("app.automation.run_snapshot.unmark_job_delivering", side_effect=spy_unmark), \
         patch("app.automation.run_snapshot.record_delivery_failure") as mock_rs_fail, \
         patch("app.services.feishu_service.mark_job_delivery_failed") as mock_feishu_fail, \
         patch("app.automation.delivery_tasks._delivery_guard_ok", return_value=True), \
         patch("app.automation.scheduler._check_non_workday", return_value=(True, "")), \
         patch("app.automation.scheduler._check_schedule_date_range", return_value=(True, "")), \
         patch("app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu", return_value=targets), \
         patch("app.automation.delivery_tasks.get_autopilot_config", return_value={"is_enabled": True, "auto_deliver_platforms": ["zhilian"]}), \
         patch("app.automation.delivery_tasks._call_resume", side_effect=fake_resume), \
         patch("app.automation.materials.refresh_mass_materials_for_jobs", new_callable=AsyncMock, return_value=0), \
         patch("app.automation.self_heal.run_self_heal", new_callable=AsyncMock), \
         patch("app.services.delivery_card_notifier.send_delivery_round_report", new_callable=AsyncMock):

        mock_pipeline_app = MagicMock()
        mock_pipeline_app.aget_state = AsyncMock(return_value=None)
        await delivery_tasks.scheduled_delivery_batch_task(window_label="测试波次", pipeline_app=mock_pipeline_app)

        # 断言 1: job1 命中持久性故障被失败拦截守卫跳过，未执行发射打标
        # 断言 2: job2 执行了单岗打标并在发射后释放
        assert ("mark", ["rec_fresh_ready_2"]) in delivering_history
        assert ("unmark", ["rec_fresh_ready_2"]) in delivering_history
        # job1 绝对不应当出现在 mark 历史中
        assert not any("rec_fail_guard_1" in item[1] for item in delivering_history)

        # 断言 3: job2 失败后，同时记入本地台账并回写飞书
        mock_rs_fail.assert_called_once()
        mock_feishu_fail.assert_called_once_with("rec_fresh_ready_2", "❌ 智联连接中断")


@pytest.mark.asyncio
async def test_delivery_tasks_transient_failure_within_limit_retries_auto_launch():
    """测试 delivery_tasks 分诊放行：
    暂时性故障（如网络超时）在重试限额内（retries=1 < 2），波次守卫允许其自动重试发射（享受自愈红利）。
    """
    from app.automation import delivery_tasks

    job_transient = {"job_id": "rec_transient_1", "job_name": "暂时网络抖动岗", "platform": "zhilian", "company_name": "抖动公司"}
    targets = [job_transient]

    fake_transient_failures = {
        "rec_transient_1": {
            "error": "网络连接超时，请重试",
            "retries": 1,
            "platform": "zhilian"
        }
    }

    delivering_history = []
    def spy_mark(jids):
        delivering_history.append(("mark", list(jids)))
    def spy_unmark(jids):
        delivering_history.append(("unmark", list(jids)))

    async def fake_resume(fn, jid, pipeline_app=None):
        return True, "✅ 投递成功"

    with patch("app.automation.run_snapshot.get_delivery_failures", return_value=fake_transient_failures), \
         patch("app.automation.run_snapshot.is_job_retrying", return_value=False), \
         patch("app.automation.run_snapshot.mark_job_delivering", side_effect=spy_mark), \
         patch("app.automation.run_snapshot.unmark_job_delivering", side_effect=spy_unmark), \
         patch("app.automation.delivery_tasks._delivery_guard_ok", return_value=True), \
         patch("app.automation.scheduler._check_non_workday", return_value=(True, "")), \
         patch("app.automation.scheduler._check_schedule_date_range", return_value=(True, "")), \
         patch("app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu", return_value=targets), \
         patch("app.automation.delivery_tasks.get_autopilot_config", return_value={"is_enabled": True, "auto_deliver_platforms": ["zhilian"]}), \
         patch("app.automation.delivery_tasks._call_resume", side_effect=fake_resume), \
         patch("app.automation.materials.refresh_mass_materials_for_jobs", new_callable=AsyncMock, return_value=0), \
         patch("app.automation.self_heal.run_self_heal", new_callable=AsyncMock), \
         patch("app.services.delivery_card_notifier.send_delivery_round_report", new_callable=AsyncMock):

        mock_pipeline_app = MagicMock()
        mock_pipeline_app.aget_state = AsyncMock(return_value=None)
        await delivery_tasks.scheduled_delivery_batch_task(window_label="暂时性故障重试测试", pipeline_app=mock_pipeline_app)

        # 验证暂时性故障被放行发射：执行了单岗打标并释放
        assert ("mark", ["rec_transient_1"]) in delivering_history
        assert ("unmark", ["rec_transient_1"]) in delivering_history


@pytest.mark.asyncio
async def test_snapshot_service_dual_track_failed_jobs_aggregation():
    """测试快照服务 snapshot_service.py 双轨聚合：
    本地失败台账与飞书「投递失败」记录同时存在时，双轨融合且去重。
    """
    from app.automation import snapshot_service

    local_failures = {
        "rec_local_01": {
            "error": "本地登记错误",
            "company_name": "本地企业",
            "job_name": "本地岗位",
            "platform": "boss",
            "failed_at": datetime.now().strftime("%Y-%m-%d %H:%M")  # Q22：勿写死日期，防时间漂移
        }
    }

    feishu_failed_jobs = [
        # 与本地重合项（应被去重）
        {
            "job_id": "rec_local_01",
            "job_name": "本地岗位",
            "company_name": "本地企业",
            "platform": "boss",
            "error_msg": "飞书重合项"
        },
        # 仅在飞书存在的独立失败项（应被补充聚合）
        {
            "job_id": "rec_feishu_only_02",
            "job_name": "飞书独立失败岗",
            "company_name": "飞书企业",
            "platform": "51job",
            "error_msg": "附件上传失败"
        }
    ]

    with patch("app.automation.run_snapshot.get_delivery_failures", return_value=local_failures), \
         patch("app.services.feishu_service.get_failed_jobs_from_feishu", return_value=feishu_failed_jobs), \
         patch("app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_delivered_jobs_from_feishu", return_value=[]), \
         patch("app.automation.run_snapshot.get_dismissed_job_ids", return_value=set()), \
         patch("app.automation.run_snapshot.get_retrying_job_ids", return_value=set()):

        snap = await snapshot_service.build_jobs_snapshot()
        all_jobs = snap.get("data", [])

        failed_jobs = [j for j in all_jobs if j.get("status") == "failed" or j.get("status") == "error"]
        failed_ids = {j["job_id"] for j in failed_jobs}

        # 必须同时包含本地失败项和飞书独立项，且 rec_local_01 恰好只有 1 条（去重）
        assert "rec_local_01" in failed_ids
        assert "rec_feishu_only_02" in failed_ids
        assert len([j for j in failed_jobs if j["job_id"] == "rec_local_01"]) == 1


@pytest.mark.asyncio
async def test_failure_dedup_15s_window_prevents_double_counting():
    """测试办法 1 纯天然去重：
    1. 本地失败台账：同岗位在 15 秒内被底层与外层以不同错误文字连续调用，failure_count 严格保持为 1，绝不双倍计数；
    2. 飞书回写防抖：同岗位在 15 秒内连续回写，仅第一次发起真实 API 请求，第二次命中防抖直接返回 True。
    """
    from app.automation import run_snapshot as _rs
    from app.services import feishu_service

    test_jid = "rec_test_dedup_15s_01"

    # 清理现场
    _rs.remove_delivery_failure(test_jid)
    feishu_service._recent_failed_writes.pop(test_jid, None)

    try:
        # 1. 本地台账去重验证（模拟底层 workflow 抛出原始错，外层 tasks 带前缀）
        _rs.record_delivery_failure(test_jid, "网络连接超时", company="测试公司", job_name="后端专家")
        f1 = _rs.get_delivery_failures().get(test_jid)
        assert f1 is not None
        assert f1.get("failure_count") == 1

        # 紧接着外层兜底记录（文字不同）
        _rs.record_delivery_failure(test_jid, "智联投递异常: 网络连接超时", company="测试公司", job_name="后端专家")
        f2 = _rs.get_delivery_failures().get(test_jid)
        assert f2 is not None
        # 核心断言：15 秒内 failure_count 绝不被虚增为 2，仍然是 1
        assert f2.get("failure_count") == 1
        assert f2.get("error") == "智联投递异常: 网络连接超时"

        # 2. 飞书回写防抖验证
        with patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_update:
            # 第一次调用
            ok1 = feishu_service.mark_job_delivery_failed(test_jid, "网络连接超时")
            assert ok1 is True
            assert mock_update.call_count == 1

            # 紧接着第二次调用（模拟外层兜底，文字稍有差异）
            ok2 = feishu_service.mark_job_delivery_failed(test_jid, "智联: 网络连接超时")
            assert ok2 is True
            # 核心断言：命中 15 秒防抖，update_feishu_record 绝不被重复调用第二次
            assert mock_update.call_count == 1
    finally:
        _rs.remove_delivery_failure(test_jid)
        feishu_service._recent_failed_writes.pop(test_jid, None)


@pytest.mark.asyncio
async def test_feishu_scheduled_pull_excludes_delivery_failed_and_keeps_quota_skip_in_ready():
    """测试飞书拉取源与配额自愈闭环契约：
    1. get_scheduled_delivery_jobs_from_feishu 严格按「跟进状态 is 待投递」筛选，排除「投递失败」；
    2. _record_51job_quota_skip 预检跳过：仅写「自动投递失败日志」，绝对不写「跟进状态」；
    3. mark_job_delivery_failed 引擎撞墙：检测到 720721 配额错误时，豁免翻转门牌（仅写日志，不写「投递失败」）；
    4. 真实业务异常（如 BOSS 沟通异常）：严格写入「跟进状态: 投递失败」。
    """
    from unittest.mock import patch, MagicMock
    from app.services import feishu_service
    from app.automation.delivery_tasks import _record_51job_quota_skip
    from app.automation.upload_quota import QUOTA_EXHAUSTED_ERROR

    # 1. 验证拉取源 Filter 契约
    captured_payloads = []

    def mock_safe_request(method, url, headers=None, json=None, timeout=None):
        if json:
            captured_payloads.append(json)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {"record_id": "rec_ready_01", "fields": {"跟进状态": "待投递", "岗位名称": "产品经理"}}
                ]
            }
        }
        return mock_resp

    with patch("app.services.feishu_service.get_tenant_access_token", return_value="fake_token"), \
         patch("app.services.feishu_service.safe_feishu_request", side_effect=mock_safe_request):
        jobs = feishu_service.get_scheduled_delivery_jobs_from_feishu(max_pages=1)
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == "rec_ready_01"

        # 核心断言 1：飞书真实请求 Filter 必须锁定「跟进状态 is 待投递」，绝对排除「投递失败」
        assert len(captured_payloads) >= 1
        payload = captured_payloads[0]
        conditions = payload.get("filter", {}).get("conditions", [])
        assert any(c.get("field_name") == "跟进状态" and c.get("value") == ["待投递"] for c in conditions)

    # 2. 验证 _record_51job_quota_skip 预检跳过：仅写日志，不改门牌
    job_quota = {
        "job_id": "rec_quota_test_01",
        "job_name": "51job测试岗",
        "company_name": "测试企业",
        "platform": "51job",
        "grade": "B",
    }
    try:
        with patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_update_quota:
            await _record_51job_quota_skip(job_quota, "测试波次")
            mock_update_quota.assert_called_once()
            call_args = mock_update_quota.call_args[0]
            assert call_args[0] == "rec_quota_test_01"
            update_fields = call_args[1]
            assert "自动投递失败日志" in update_fields
            # 核心断言 2：预检跳过绝不修改「跟进状态」，保持「待投递」
            assert "跟进状态" not in update_fields
    finally:
        _rs.remove_delivery_failure("rec_quota_test_01")

    # 3. 验证 mark_job_delivery_failed 引擎撞墙（720721）：豁免翻转门牌
    feishu_service._recent_failed_writes.clear()
    with patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_update_engine_hit:
        ok_quota_hit = feishu_service.mark_job_delivery_failed("rec_engine_hit_01", QUOTA_EXHAUSTED_ERROR)
        assert ok_quota_hit is True
        mock_update_engine_hit.assert_called_once()
        fields_engine = mock_update_engine_hit.call_args[0][1]
        assert "自动投递失败日志" in fields_engine
        # 核心断言 3：即便引擎撞墙，也豁免翻转门牌为「投递失败」，保留原「待投递」
        assert "跟进状态" not in fields_engine

    # 4. 验证 mark_job_delivery_failed 普通真实失败：正常翻转门牌为「投递失败」
    feishu_service._recent_failed_writes.clear()
    with patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_update_normal_fail:
        ok_normal = feishu_service.mark_job_delivery_failed("rec_normal_fail_01", "❌ BOSS 投递受阻：网络连接超时")
        assert ok_normal is True
        mock_update_normal_fail.assert_called_once()
        fields_normal = mock_update_normal_fail.call_args[0][1]
        # 核心断言 4：普通失败必须严格写入「跟进状态: 投递失败」
        assert fields_normal.get("跟进状态") == "投递失败"
        assert "自动投递失败日志" in fields_normal

