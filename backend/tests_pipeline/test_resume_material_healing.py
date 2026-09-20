import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_check_job_materials_ready(monkeypatch):
    """测试物料齐全时 check-job-materials 返回 is_ready 为 True"""
    mock_rec = {
        "record_id": "rec_ready_1",
        "fields": {
            "岗位名称": "AI产品经理",
            "公司名称": "测试大厂",
            "招聘平台": "智联招聘",
            "岗位链接": {"link": "https://zhaopin.com/job/123"},
            "PDF备份": [{"file_token": "token_pdf_123", "name": "简历.pdf"}],
            "打招呼语": "您好，我对该岗位非常感兴趣",
            "AI改写JSON": "{\"title\": \"定制简历\"}"
        }
    }
    monkeypatch.setattr("app.services.feishu_service.get_job_record_from_feishu", lambda rid, tid: mock_rec)

    res = client.post("/api/automation/check-job-materials", json={"record_id": "rec_ready_1"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["has_url"] is True
    assert data["has_pdf"] is True
    assert data["has_greeting"] is True
    assert data["is_ready"] is True


def test_check_job_materials_missing_pdf(monkeypatch):
    """测试缺少 PDF 附件时 check-job-materials 返回 is_ready 为 False"""
    mock_rec = {
        "record_id": "rec_missing_1",
        "fields": {
            "岗位名称": "AI算法工程师",
            "公司名称": "测试公司",
            "招聘平台": "BOSS直聘",
            "岗位链接": "https://zhipin.com/job/456",
            "PDF备份": [],
            "打招呼语": "",
            "AI改写JSON": ""
        }
    }
    monkeypatch.setattr("app.services.feishu_service.get_job_record_from_feishu", lambda rid, tid: mock_rec)

    res = client.post("/api/automation/check-job-materials", json={"record_id": "rec_missing_1"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["has_url"] is True
    assert data["has_pdf"] is False
    assert data["has_greeting"] is False
    assert data["is_ready"] is False


@pytest.mark.asyncio
async def test_auto_heal_and_approve(monkeypatch):
    """测试 auto-heal-and-approve 自动补全 PDF、打招呼语并将状态更新为待投递"""
    # 🌟 配置桩：海投岗放行有「海投通用打招呼语」硬门禁，共享测试库不保证配置过
    # （空配置库下该用例必吃 400）。双路打桩覆盖 _get_autopilot_config 的取值优先级
    def _fake_cfg():
        return {
            "mass_apply_greeting": "您好，看到您的经历与该岗位非常匹配，期待进一步沟通",
            "mass_apply_resume_id": "rec_mass_base",
        }

    monkeypatch.setattr("app.automation.router.get_autopilot_config", _fake_cfg, raising=False)
    monkeypatch.setattr("app.automation.db.get_autopilot_config", _fake_cfg)

    mock_rec = {
        "record_id": "rec_heal_1",
        "fields": {
            "岗位名称": "AI产品架构师",
            "公司名称": "先锋科技",
            "招聘平台": "智联招聘",
            "岗位链接": "https://zhaopin.com/job/789",
            "PDF备份": [],
            "打招呼语": "",
            "AI改写JSON": ""
        }
    }
    monkeypatch.setattr("app.services.feishu_service.get_job_record_from_feishu", lambda rid, tid: mock_rec)

    async def mock_render_materials(resume_id, name):
        return {"pdf_token": "new_pdf_token_888", "img_token": "new_img_token_888", "name": name}

    monkeypatch.setattr("app.automation.materials._render_mass_resume_materials_with_name", mock_render_materials)

    updated_data = {}
    def mock_update(rid, patch_dict):
        updated_data.update(patch_dict)
        return True

    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", mock_update)

    res = client.post("/api/automation/auto-heal-and-approve", json={"record_id": "rec_heal_1"})
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert updated_data.get("跟进状态") == "待投递"
    assert updated_data.get("PDF备份")[0]["file_token"] == "new_pdf_token_888"
    assert bool(updated_data.get("打招呼语")) is True


@pytest.mark.asyncio
async def test_auto_heal_rerenders_custom_pdf_for_custom_job(monkeypatch):
    """精投岗挂着海投命名 PDF（如「我的简历.pdf」）时，auto-heal 必须重渲染定制简历，
    不得把旧通用简历当合规物料直接放行（旧通用简历 + 定制打招呼语混投）"""
    # 配置桩：同 test_auto_heal_and_approve，海投打招呼语门禁兜底
    def _fake_cfg():
        return {
            "mass_apply_greeting": "您好，看到您的经历与该岗位非常匹配，期待进一步沟通",
            "mass_apply_resume_id": "rec_mass_base",
        }

    monkeypatch.setattr("app.automation.router.get_autopilot_config", _fake_cfg, raising=False)
    monkeypatch.setattr("app.automation.db.get_autopilot_config", _fake_cfg)

    mock_rec = {
        "record_id": "rec_heal_2",
        "fields": {
            "岗位名称": "AI产品架构师",
            "公司名称": "先锋科技",
            "招聘平台": "智联招聘",
            "岗位链接": "https://zhaopin.com/job/789",
            # 🌟 关键场景：有附件 token，但挂的是海投命名的旧通用简历
            "PDF备份": [{"file_token": "stale_mass_token", "name": "我的简历.pdf"}],
            "打招呼语": "定制打招呼语原文",
            "AI改写JSON": "{\"title\": \"定制简历\"}"
        }
    }
    monkeypatch.setattr("app.services.feishu_service.get_job_record_from_feishu", lambda rid, tid: mock_rec)

    custom_render_calls: list[tuple] = []

    async def mock_render_custom(struct_data, name):
        custom_render_calls.append((struct_data, name))
        return {"pdf_token": "custom_pdf_token_999", "img_token": "custom_img_token_999", "name": name}

    async def mock_render_mass_should_not_be_called(resume_id, name):
        raise AssertionError("精投岗挂着海投命名 PDF 时应走定制渲染，而非海投母本渲染")

    monkeypatch.setattr("app.automation.materials._render_custom_resume_materials", mock_render_custom)
    monkeypatch.setattr("app.automation.materials._render_mass_resume_materials_with_name", mock_render_mass_should_not_be_called)

    updated_data = {}
    def mock_update(rid, patch_dict):
        updated_data.update(patch_dict)
        return True

    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", mock_update)

    res = client.post("/api/automation/auto-heal-and-approve", json={"record_id": "rec_heal_2"})
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    # 触发了定制渲染并覆盖挂载
    assert len(custom_render_calls) == 1
    assert updated_data.get("PDF备份")[0]["file_token"] == "custom_pdf_token_999"
    assert updated_data.get("PDF备份")[0]["name"] == "先锋科技_AI产品架构师.pdf"
    # 定制打招呼语不被海投通用语覆盖
    assert "打招呼语" not in updated_data


def test_resume_batch_dual_track_approve_and_takeover(monkeypatch):
    """测试 resume_batch 双轨兼容：非流水线岗位放行更新为待投递，转人工精修保留数据"""
    updated_records = []
    def mock_update(rid, patch_dict):
        updated_records.append((rid, patch_dict))
        return True

    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", mock_update)

    # 1. 测试 approve 放行
    res_approve = client.post("/api/automation/resume_batch", json={
        "thread_ids": ["boss直聘-rec_manual_1", "智联招聘-rec_manual_2"],
        "action": "approve"
    })
    assert res_approve.status_code == 200
    assert res_approve.json()["status"] == "success"
    assert len(updated_records) == 2
    assert updated_records[0][1]["跟进状态"] == "待投递"

    # 2. 测试 reject（老板拒绝）：门牌写「已拒绝」，AI 草稿完整保留，仅归档于全部岗位列表
    updated_records.clear()
    res_takeover = client.post("/api/automation/resume_batch", json={
        "thread_ids": ["boss直聘-rec_manual_3"],
        "action": "reject"
    })
    assert res_takeover.status_code == 200
    assert res_takeover.json()["status"] == "success"
    assert len(updated_records) == 1
    assert updated_records[0][1]["跟进状态"] == "已拒绝"
    assert res_takeover.json()["data"]["details"][0]["status"] == "rejected_manual"


@pytest.mark.asyncio
async def test_auto_heal_skips_image_rendering_for_non_boss_platforms(monkeypatch):
    """验证智联/51job等非BOSS直聘平台放行时，need_image 为 False，直接跳过长图排版与长图上传大幅提速"""
    def _fake_cfg():
        return {
            "mass_apply_greeting": "您好，看到您的经历与该岗位非常匹配",
            "mass_apply_resume_id": "rec_mass_base",
        }

    monkeypatch.setattr("app.automation.router.get_autopilot_config", _fake_cfg, raising=False)
    monkeypatch.setattr("app.automation.db.get_autopilot_config", _fake_cfg)

    mock_rec = {
        "record_id": "rec_zhilian_speedup",
        "fields": {
            "岗位名称": "AI产品经理",
            "公司名称": "上海贝锐信息科技",
            "招聘平台": "智联招聘",
            "岗位链接": "https://zhaopin.com/job/123",
            "PDF备份": [],
            "打招呼语": "专属定制打招呼语",
            "AI改写JSON": "{\"title\": \"AI定制\"}"
        }
    }
    monkeypatch.setattr("app.services.feishu_service.get_job_record_from_feishu", lambda rid, tid: mock_rec)

    captured_kwargs = {}

    async def mock_render_custom(struct_data, name, need_image=True):
        captured_kwargs["need_image"] = need_image
        # 智联只返回 pdf_token，不生成 img_token
        return {"pdf_token": "pdf_token_only_123", "name": name}

    monkeypatch.setattr("app.automation.materials._render_custom_resume_materials", mock_render_custom)

    updated_data = {}
    def mock_update(rid, patch_dict):
        updated_data.update(patch_dict)
        return True

    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", mock_update)

    res = client.post("/api/automation/auto-heal-and-approve", json={"record_id": "rec_zhilian_speedup"})
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    # 🌟 确凿断言：智联招聘平台传入 need_image=False
    assert captured_kwargs.get("need_image") is False
    # 🌟 确凿断言：更新字典中包含 PDF 附件，但不包含图片保存（省去数兆长图上传公网）
    assert "PDF备份" in updated_data
    assert "图片保存" not in updated_data
    assert updated_data.get("跟进状态") == "待投递"


@pytest.mark.asyncio
async def test_mass_materials_cache_isolates_need_image_dimension(monkeypatch):
    """C1 回归（混合平台缓存投毒）：智联 need_image=False 先渲染并写入缓存后，
    10 分钟内 BOSS need_image=True 绝不能复用这条缺长图的物料；同维度 BOSS 之间正常复用。"""
    import app.automation.materials as mat
    from app.core import feishu_client as feishu_client_mod
    from app.core import pdf_renderer
    from app.services import export_service

    monkeypatch.setattr(mat, "_MASS_MATERIALS_CACHE", {})

    async def fake_get_record(table_id, record_id):
        return None

    monkeypatch.setattr(feishu_client_mod.feishu_client, "get_record", fake_get_record)

    calls = {"pdf": 0, "img": 0}

    async def fake_render_pdf(url, page_size="A4"):
        calls["pdf"] += 1
        return b"%PDF-fake"

    async def fake_render_img(url):
        calls["img"] += 1
        return b"JPEG-fake"

    monkeypatch.setattr(pdf_renderer, "render_resume_pdf", fake_render_pdf)
    monkeypatch.setattr(pdf_renderer, "render_resume_image", fake_render_img)

    async def fake_upload(path, file_name=""):
        return f"tok::{file_name}"

    monkeypatch.setattr(export_service, "upload_file_to_feishu_async", fake_upload)

    # 1) 智联先来：只要 PDF，缓存里是一条没有 img_token 的物料
    zhilian = await mat._render_mass_resume_materials("rec_mass", need_image=False)
    assert zhilian["pdf_token"] and "img_token" not in zhilian
    assert calls == {"pdf": 1, "img": 0}

    # 2) BOSS 随后到：必须重新渲染出长图，而不是命中智联那条缺图缓存
    boss = await mat._render_mass_resume_materials("rec_mass", need_image=True)
    assert boss["pdf_token"] and boss["img_token"]
    assert calls == {"pdf": 2, "img": 1}

    # 3) 同维度复用：再来一个 BOSS 直接命中缓存，不再触发渲染
    boss_again = await mat._render_mass_resume_materials("rec_mass", need_image=True)
    assert boss_again == boss
    assert calls == {"pdf": 2, "img": 1}


@pytest.mark.asyncio
async def test_auto_heal_mass_resume_id_falls_back_to_feishu_active_when_config_blank(monkeypatch):
    """配置里海投母本 ID 仅为空白时，auto-heal 必须 strip 后回退飞书当前激活简历，而不是拿空串去渲染"""
    def _fake_cfg():
        return {
            "mass_apply_greeting": "您好，看到您的经历与该岗位非常匹配",
            "mass_apply_resume_id": "   ",
        }

    monkeypatch.setattr("app.automation.router.get_autopilot_config", _fake_cfg, raising=False)
    monkeypatch.setattr("app.automation.db.get_autopilot_config", _fake_cfg)
    monkeypatch.setattr("app.services.feishu_service.get_active_resume_record_id", lambda: "rec_active_from_feishu")

    mock_rec = {
        "record_id": "rec_heal_fallback",
        "fields": {
            "岗位名称": "AI产品经理",
            "公司名称": "回退科技",
            "招聘平台": "智联招聘",
            "岗位链接": "https://zhaopin.com/job/321",
            "PDF备份": [],
            "打招呼语": "",
            "AI改写JSON": ""
        }
    }
    monkeypatch.setattr("app.services.feishu_service.get_job_record_from_feishu", lambda rid, tid: mock_rec)

    seen_resume_ids: list[str] = []

    async def mock_render_mass(resume_id, name, need_image=True):
        seen_resume_ids.append(resume_id)
        return {"pdf_token": "pdf_fallback_1", "name": name}

    monkeypatch.setattr("app.automation.materials._render_mass_resume_materials_with_name", mock_render_mass)

    updated_data = {}

    def mock_update(rid, patch_dict):
        updated_data.update(patch_dict)
        return True

    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", mock_update)

    res = client.post("/api/automation/auto-heal-and-approve", json={"record_id": "rec_heal_fallback"})
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    # 🌟 确凿断言：渲染拿到的是飞书激活简历 ID，而非空白配置
    assert seen_resume_ids == ["rec_active_from_feishu"]
    assert updated_data.get("PDF备份")[0]["file_token"] == "pdf_fallback_1"
    assert updated_data.get("跟进状态") == "待投递"


@pytest.mark.asyncio
async def test_resolve_mass_resume_id_strips_blank_config_and_falls_back(monkeypatch):
    """海投母本 ID 唯一口径（workflow / delivery_router / 物料保鲜共用）：
    纯空格配置必须 strip 后回退飞书激活简历；带空白的有效 ID 去空白后原样返回。"""
    import app.services.feishu_service as fs
    from app.automation.materials import resolve_mass_resume_id

    monkeypatch.setattr(fs, "get_active_resume_record_id", lambda: "rec_active_123")
    assert await resolve_mass_resume_id({"mass_apply_resume_id": "   "}) == "rec_active_123"
    assert await resolve_mass_resume_id({}) == "rec_active_123"
    assert await resolve_mass_resume_id(None) == "rec_active_123"
    assert await resolve_mass_resume_id({"mass_apply_resume_id": " rec_cfg_9 "}) == "rec_cfg_9"


@pytest.mark.asyncio
async def test_mass_render_falls_back_to_active_resume_struct_when_target_empty(monkeypatch):
    """指定简历读不到结构化数据、前端打印路由又不可用时，本地引擎必须拿到基准启用简历的数据，
    而不是拿空 dict 渲染并上传一份空简历（此前该兜底导入了不存在的函数，是静默死代码）。"""
    import app.automation.materials as mat
    import app.services.feishu_service as fs
    from app.core import feishu_client as feishu_client_mod
    from app.core import pdf_renderer, resume_html_builder
    from app.services import export_service

    monkeypatch.setattr(mat, "_MASS_MATERIALS_CACHE", {})
    active_struct = {"personalInfo": {"name": "基准简历"}, "skills": ["Python"]}

    async def fake_get_record(table_id, record_id):
        if record_id == "rec_active":
            return {"fields": {"结构化数据": json.dumps(active_struct, ensure_ascii=False)}}
        return None

    monkeypatch.setattr(feishu_client_mod.feishu_client, "get_record", fake_get_record)
    monkeypatch.setattr(fs, "get_active_resume_record_id", lambda: "rec_active")

    async def frontend_route_down(url, page_size="A4"):
        raise RuntimeError("frontend print route down")

    monkeypatch.setattr(pdf_renderer, "render_resume_pdf", frontend_route_down)

    seen_dicts: list[dict] = []

    def fake_build_html(resume_dict, skin="classic"):
        seen_dicts.append(resume_dict)
        return "<html>ok</html>"

    monkeypatch.setattr(resume_html_builder, "build_resume_html", fake_build_html)

    async def fake_html_to_pdf(html, page_size="A4"):
        return b"%PDF-local"

    monkeypatch.setattr(pdf_renderer, "render_html_to_pdf", fake_html_to_pdf)

    async def fake_upload(path, file_name=""):
        return f"tok::{file_name}"

    monkeypatch.setattr(export_service, "upload_file_to_feishu_async", fake_upload)

    res = await mat._render_mass_resume_materials("rec_missing_struct", need_image=False)
    assert res and res["pdf_token"]
    # 🌟 确凿断言：本地引擎收到的是基准简历数据，不是空 dict
    assert seen_dicts == [active_struct]
