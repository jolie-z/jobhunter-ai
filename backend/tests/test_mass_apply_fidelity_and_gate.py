import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

from app.automation.routes.delivery_router import auto_heal_and_approve
from app.tasks.executor import _handle_mass_apply, run_batch_ai_task
from app.tasks.state import task_status


@pytest.mark.asyncio
async def test_mass_apply_missing_greeting_raises_http_400():
    """测试海投岗位若未配置通用打招呼语，触发强门禁并抛出指向「全链路中心-打招呼语模块」的 400 错误"""
    fake_job_rec = {
        "id": "recTest123",
        "fields": {
            "跟进状态": "海投人工复核",
            "公司名称": "测试科技",
            "岗位名称": "Python后端开发",
            "招聘平台": "BOSS直聘",
            "打招呼语": "",
            "PDF备份": [{"name": "测试科技_Python后端开发.pdf", "file_token": "tok123"}],
            "图片保存": [{"name": "测试科技_Python后端开发-长图.jpg", "file_token": "img123"}],
        }
    }

    with patch("app.services.feishu_service.get_job_record_from_feishu", return_value=fake_job_rec), \
         patch("app.automation.materials._render_mass_resume_materials_with_name", new_callable=AsyncMock), \
         patch("app.automation.routes.delivery_router._get_autopilot_config") as mock_cfg:
        mock_cfg.return_value = {
            "mass_apply_greeting": "",  # 未配置
            "mass_apply_resume_id": "res123",
        }

        with pytest.raises(HTTPException) as exc_info:
            await auto_heal_and_approve(MagicMock(record_id="recTest123"))

        assert exc_info.value.status_code == 400
        assert "全链路中心-打招呼语模块" in exc_info.value.detail


@pytest.mark.asyncio
async def test_mass_apply_with_greeting_and_stale_pdf_forces_rerender():
    """测试海投岗位若挂载的是旧通用简历（通用简历-最新.pdf），强制自愈重新渲染高保真物料并写入通用打招呼语"""
    fake_job_rec = {
        "id": "recTest456",
        "fields": {
            "跟进状态": "海投人工复核",
            "公司名称": "未来公司",
            "岗位名称": "全栈工程师",
            "招聘平台": "BOSS直聘",
            "打招呼语": "旧打招呼语",
            "PDF备份": [{"name": "通用简历-最新.pdf", "file_token": "old_stale_tok"}],
        }
    }

    with patch("app.services.feishu_service.get_job_record_from_feishu", return_value=fake_job_rec), \
         patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_upd_rec, \
         patch("app.automation.routes.delivery_router._get_autopilot_config") as mock_cfg, \
         patch("app.automation.materials._render_mass_resume_materials_with_name", new_callable=AsyncMock) as mock_render, \
         patch("app.automation.routes.delivery_router._mark_approved_guarded"):

        mock_cfg.return_value = {
            "mass_apply_greeting": "您好！这是我预设的全新海投破冰语。",
            "mass_apply_resume_id": "res456",
        }
        mock_render.return_value = {
            "pdf_token": "new_pdf_token",
            "img_token": "new_img_token",
            "name": "未来公司_全栈工程师",
        }

        res = await auto_heal_and_approve(MagicMock(record_id="recTest456"))
        assert res["status"] == "success"

        # 校验 update_feishu_record 写入字段
        mock_upd_rec.assert_called_once()
        call_patch = mock_upd_rec.call_args[0][1]
        assert call_patch["跟进状态"] == "待投递"
        assert call_patch["打招呼语"] == "您好！这是我预设的全新海投破冰语。"
        assert call_patch["PDF备份"][0]["name"] == "未来公司_全栈工程师.pdf"
        assert call_patch["PDF备份"][0]["file_token"] == "new_pdf_token"


@pytest.mark.asyncio
async def test_handle_mass_apply_emits_stage_progress_and_enqueues():
    """测试 _handle_mass_apply 发射 4 阶段 stage_progress SSE 并正确入队待投递"""
    queue = asyncio.Queue()
    fields = {
        "公司名称": "智能科技",
        "岗位名称": "前端架构师",
        "招聘平台": "猎聘",
    }
    mats = {"pdf_token": "fallback_pdf", "img_token": "fallback_img", "name": "base"}

    with patch("app.automation.materials._render_mass_resume_materials_with_name", new_callable=AsyncMock) as mock_render, \
         patch("app.tasks.executor.update_feishu_record") as mock_update, \
         patch("app.automation.routes.delivery_router._mark_approved_guarded"):

        mock_render.return_value = {
            "pdf_token": "high_def_pdf",
            "img_token": "high_def_img",
            "name": "智能科技_前端架构师",
        }

        result = await _handle_mass_apply(
            record_id="recArch1",
            platform="猎聘",
            fields=fields,
            mats=mats,
            greeting="您好，对贵司前端架构师职位非常感兴趣！",
            queue=queue,
        )

        assert result["status"] == "success"
        mock_update.assert_called_once()
        patch_data = mock_update.call_args[0][1]
        assert patch_data["跟进状态"] == "待投递"
        assert patch_data["打招呼语"] == "您好，对贵司前端架构师职位非常感兴趣！"
        assert patch_data["PDF备份"][0]["file_token"] == "high_def_pdf"

        # 检查发出的 SSE 消息中包含 4 阶段进度
        events = []
        while not queue.empty():
            msg = await queue.get()
            if isinstance(msg, str) and msg.startswith("data: "):
                payload = json.loads(msg[6:].strip())
                events.append(payload)

        stages = [e.get("stage_title") for e in events if e.get("type") in ("progress", "stage_progress")]
        assert "母本校验" in stages
        assert "高清渲染" in stages
        assert "招呼装配" in stages
        assert "入队待投" in stages


@pytest.mark.asyncio
async def test_run_batch_ai_task_mass_apply_missing_greeting_gate():
    """测试批量任务引擎对 mass_apply 的通用打招呼语强门禁检测"""
    queue = asyncio.Queue()
    task_id = "test_mass_gate_tid"
    task_status[task_id] = {"status": "pending"}

    with patch("app.automation.db.get_autopilot_config") as mock_cfg, \
         patch("app.tasks.executor.get_mass_apply_resume_record_id", return_value="resId123"):
        mock_cfg.return_value = {
            "mass_apply_greeting": "",  # 未配置
            "mass_apply_resume_id": "resId123",
        }

        await run_batch_ai_task(
            task_id=task_id,
            task_type="mass_apply",
            job_ids=["BOSS直聘-rec001"],
            queue=queue,
        )

        assert task_status[task_id]["status"] == "failed"
        assert "全链路中心-打招呼语模块" in task_status[task_id]["error"]

        # 校验队列收到对应的 SSE 报错通知
        events = []
        while not queue.empty():
            msg = await queue.get()
            if isinstance(msg, str) and msg.startswith("data: "):
                events.append(json.loads(msg[6:].strip()))

        err_events = [e for e in events if e.get("type") == "error"]
        assert any("全链路中心-打招呼语模块" in e.get("message", "") for e in err_events)


@pytest.mark.asyncio
async def test_mass_apply_51job_only_skips_greeting_gate():
    """测试纯 51job 岗位无需打招呼语，不触发门禁阻断"""
    fake_job_rec = {
        "id": "rec51job123",
        "fields": {
            "跟进状态": "海投人工复核",
            "公司名称": "西藏奇正藏药",
            "岗位名称": "市场研究经理",
            "招聘平台": "51job",
            "打招呼语": "",
            "PDF备份": [],
        }
    }

    with patch("app.services.feishu_service.get_job_record_from_feishu", return_value=fake_job_rec), \
         patch("app.services.feishu_service.update_feishu_record", return_value=True) as mock_upd_rec, \
         patch("app.automation.routes.delivery_router._get_autopilot_config") as mock_cfg, \
         patch("app.automation.materials._render_mass_resume_materials_with_name", new_callable=AsyncMock) as mock_render, \
         patch("app.automation.routes.delivery_router._mark_approved_guarded"):

        mock_cfg.return_value = {
            "mass_apply_greeting": "",  # 未配置打招呼语
            "mass_apply_resume_id": "res456",
        }
        mock_render.return_value = {
            "pdf_token": "pdf51",
            "img_token": "img51",
            "name": "西藏奇正藏药_市场研究经理",
        }

        res = await auto_heal_and_approve(MagicMock(record_id="rec51job123"))
        assert res["status"] == "success"
        mock_upd_rec.assert_called_once()
        patch_data = mock_upd_rec.call_args[0][1]
        assert patch_data["跟进状态"] == "待投递"
        assert "打招呼语" not in patch_data
