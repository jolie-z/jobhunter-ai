# tests/test_single_resume_auto_activate.py
"""单份简历自动生效 + 新手指引第二步判定收紧（2026-09-23 简历库新手体验批）。

- config_service._ensure_single_resume_active：库里恰好一份且无「启用」→ 自动排他启用；
  多份不动、已生效不动、失败只告警不抛，且生效后失效指挥中心 60s 活跃简历缓存。
- save 新建简历路径：创建成功后同样走自愈（新用户上传第一份简历保存即生效）；
  更新路径不自愈。
- setup_status._resume_exists：只认「当前状态=启用」的飞书简历；本地 resumes/*.md
  兜底已移除——新手指引第二步必须确认用户设置了生效简历。
"""
from unittest.mock import AsyncMock, Mock, patch

from app.settings import setup_status
from app.strategy import config_service


def _resume(record_id: str, status) -> dict:
    return {"record_id": record_id, "fields": {"当前状态": status}}


def _feishu_ok_response(record_id: str = "recNew") -> Mock:
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"code": 0, "data": {"record": {"record_id": record_id}}}
    return resp


def _mock_http_client(client_cls, method: str) -> None:
    """把 httpx.AsyncClient 替身配置成 async with 可用、指定方法返回飞书成功响应。"""
    client = client_cls.return_value
    client.__aenter__.return_value = client
    setattr(client, method, AsyncMock(return_value=_feishu_ok_response()))


async def test_single_inactive_resume_auto_activated():
    """仅一份且停用 → 自动排他启用，并失效活跃简历缓存。"""
    activated = []
    with patch.object(config_service, "activate_target_resume", side_effect=activated.append), \
         patch("app.pipeline.routes.feishu_status_router.invalidate_active_resume_meta_cache") as inv:
        await config_service._ensure_single_resume_active([_resume("recA", "停用")])
    assert activated == ["recA"]
    inv.assert_called_once()


async def test_single_active_resume_untouched():
    """已生效（字符串/富文本/字符串列表三种字段形态）→ 不重复启用，也不失效缓存。

    读路径（config GET）命中「已生效」时状态未变，缓存失效只会白白增加飞书查询；
    setup-status 自愈钩子如需强刷缓存，由钩子自身负责（见 setup_status 侧用例）。
    """
    activated = []
    with patch.object(config_service, "activate_target_resume", side_effect=activated.append), \
         patch("app.pipeline.routes.feishu_status_router.invalidate_active_resume_meta_cache") as inv:
        await config_service._ensure_single_resume_active([_resume("recA", "启用")])
        await config_service._ensure_single_resume_active([_resume("recA", [{"text": "启用"}])])
        await config_service._ensure_single_resume_active([_resume("recA", ["启用"])])
    assert activated == []
    inv.assert_not_called()


async def test_multiple_or_zero_resumes_untouched():
    """多份/空库绝不替用户挑底稿。"""
    activated = []
    with patch.object(config_service, "activate_target_resume", side_effect=activated.append):
        await config_service._ensure_single_resume_active([])
        await config_service._ensure_single_resume_active([_resume("recA", "停用"), _resume("recB", "停用")])
    assert activated == []


async def test_activation_failure_swallowed():
    """飞书故障只告警不抛，绝不阻塞配置读取/保存主流程。

    两个关键断言：缓存失效不得误触；记录状态绝不能被就地改写为「启用」——
    否则响应绿灯而飞书侧实际未生效，第二步判定与简历库界面互相矛盾。
    """

    def boom(_rid):
        raise RuntimeError("feishu down")

    record = _resume("recA", "停用")
    with patch.object(config_service, "activate_target_resume", side_effect=boom), \
         patch("app.pipeline.routes.feishu_status_router.invalidate_active_resume_meta_cache") as inv:
        await config_service._ensure_single_resume_active([record])  # 不应抛
    inv.assert_not_called()
    assert (record.get("fields") or {}).get("当前状态") == "停用"


async def test_get_config_heals_and_returns_active_status_same_response():
    """读取自愈命中时，同一次响应里的简历状态就是「启用」，无需前端二次刷新。"""
    records = [_resume("recA", "停用")]

    async def fake_fetch(table_id):
        return records

    with patch.object(config_service.feishu_client, "fetch_bitable_records",
                      new=AsyncMock(side_effect=fake_fetch)), \
         patch.object(config_service, "activate_target_resume", side_effect=lambda rid: None):
        data = await config_service.get_all_strategy_configs()
    assert data["resumes"][0]["status"] == "启用"


async def test_create_resume_triggers_auto_activate():
    """保存接口新建简历（record_id 为空）成功后走自愈；更新路径不自愈。"""
    activated = []

    async def fake_fetch(table_id):
        return [_resume("recNew", "停用")]

    with patch.object(config_service.feishu_client, "get_tenant_access_token",
                      new=AsyncMock(return_value="tok")), \
         patch.object(config_service.feishu_client, "fetch_bitable_records",
                      new=AsyncMock(side_effect=fake_fetch)), \
         patch.object(config_service, "activate_target_resume", side_effect=activated.append):
        # ---- 新建：触发自愈 ----
        with patch.object(config_service.httpx, "AsyncClient") as client_cls:
            _mock_http_client(client_cls, "post")
            new_id = await config_service.save_strategy_config_service(
                config_service.SaveConfigRequest(table_type="resume", record_id=None,
                                                 fields={"简历版本": "v1", "当前状态": "停用"})
            )
        assert new_id == "recNew"
        assert activated == ["recNew"]

        # ---- 更新：不触发自愈 ----
        activated.clear()
        with patch.object(config_service.httpx, "AsyncClient") as client_cls:
            _mock_http_client(client_cls, "put")
            upd_id = await config_service.save_strategy_config_service(
                config_service.SaveConfigRequest(table_type="resume", record_id="recNew",
                                                 fields={"简历版本": "v1 改"})
            )
        assert upd_id == "recNew"
        assert activated == []


async def test_create_resume_survives_heal_fetch_failure():
    """记录创建成功后、自愈阶段飞书抖动 → 接口仍返回成功 record_id（绝不变假失败）。"""

    async def fake_token():
        return "tok"

    async def broken_fetch(table_id):
        raise RuntimeError("feishu read flake")

    with patch.object(config_service.feishu_client, "get_tenant_access_token",
                      new=AsyncMock(return_value="tok")), \
         patch.object(config_service.feishu_client, "fetch_bitable_records",
                      new=AsyncMock(side_effect=broken_fetch)), \
         patch.object(config_service, "activate_target_resume") as activate:
        with patch.object(config_service.httpx, "AsyncClient") as client_cls:
            _mock_http_client(client_cls, "post")
            new_id = await config_service.save_strategy_config_service(
                config_service.SaveConfigRequest(table_type="resume", record_id=None,
                                                 fields={"简历版本": "v1", "当前状态": "停用"})
            )
    assert new_id == "recNew"
    activate.assert_not_called()


async def test_create_resume_skips_heal_on_stale_view():
    """保存后拉到的唯一记录与新建 record_id 不符（读后写延迟的陈旧视图）→ 跳过自愈。

    宁可不自动生效，也不能把「别的简历」错设为生效底稿。
    """

    async def fake_fetch(table_id):
        return [_resume("recOld", "停用")]

    with patch.object(config_service.feishu_client, "get_tenant_access_token",
                      new=AsyncMock(return_value="tok")), \
         patch.object(config_service.feishu_client, "fetch_bitable_records",
                      new=AsyncMock(side_effect=fake_fetch)), \
         patch.object(config_service, "activate_target_resume") as activate:
        with patch.object(config_service.httpx, "AsyncClient") as client_cls:
            _mock_http_client(client_cls, "post")
            new_id = await config_service.save_strategy_config_service(
                config_service.SaveConfigRequest(table_type="resume", record_id=None,
                                                 fields={"简历版本": "v1", "当前状态": "停用"})
            )
    assert new_id == "recNew"
    activate.assert_not_called()


async def test_setup_status_heals_once_with_throttle(monkeypatch):
    """体检接口在「无生效简历」时触发兜底自愈：仅触发一次，60s 节流内不再触发。"""
    import app.pipeline.config_status_service as css
    import app.settings.setup_status as ss
    import app.strategy.config_service as cs

    # 判定体已下沉 config_status_service，缓存操纵必须打在 service 模块命名空间
    monkeypatch.setattr(css, "_ACTIVE_RESUME_META_CACHE",
                        {"ts": css.time.time() + 9999, "value": None})
    monkeypatch.setattr(ss, "_LAST_HEAL_TS", {"ts": 0.0})
    monkeypatch.setattr(cs, "_ensure_single_resume_active", AsyncMock())
    # 自愈后失效缓存 → 重判会重新拉取活跃简历；单测内 mock 掉真实飞书查询
    monkeypatch.setattr("app.services.feishu_service.get_active_resume_meta", lambda: None)
    monkeypatch.setattr(ss, "get_configured_value",
                        lambda key: "tblX" if key == "FEISHU_TABLE_ID_RESUMES" else "")

    first = await ss.get_setup_status()
    assert first["data"]["resume"]["done"] is False
    cs._ensure_single_resume_active.assert_awaited_once()

    second = await ss.get_setup_status()
    cs._ensure_single_resume_active.assert_awaited_once()  # 节流生效
    assert second["data"]["resume"]["done"] is False


async def test_setup_status_heal_success_then_recheck_true(monkeypatch):
    """真链路闭环：自愈启用成功 → 缓存失效 → 重判读到「已生效」→ 第二步点亮。"""
    import app.pipeline.config_status_service as css
    import app.settings.setup_status as ss
    import app.strategy.config_service as cs

    monkeypatch.setattr(css, "_ACTIVE_RESUME_META_CACHE",
                        {"ts": css.time.time() + 9999, "value": None})
    monkeypatch.setattr(ss, "_LAST_HEAL_TS", {"ts": 0.0})
    monkeypatch.setattr(cs, "_ensure_single_resume_active", AsyncMock())
    # 缓存失效后重判：模拟飞书侧确实查到了启用中的简历
    monkeypatch.setattr("app.services.feishu_service.get_active_resume_meta",
                        lambda: {"id": "recA", "title": "主简历"})
    monkeypatch.setattr(ss, "get_configured_value",
                        lambda key: "tblX" if key == "FEISHU_TABLE_ID_RESUMES" else "")

    result = await ss.get_setup_status()
    assert result["data"]["resume"]["done"] is True
    cs._ensure_single_resume_active.assert_awaited_once()


def test_manual_activation_invalidates_meta_cache():
    """手动「设为生效」走 activate_target_resume 咽喉点，成功后立即失效活跃简历缓存。"""

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            # GET 校验目标 → PUT 启用 → POST search(空集，无其它生效) 三段全放行
            return {"code": 0, "data": {"record": {"record_id": "recA"}, "items": []}}

    fake_requests = Mock()
    fake_requests.get.return_value = FakeResp()
    fake_requests.put.return_value = FakeResp()
    fake_requests.post.return_value = FakeResp()

    with patch.object(config_service, "_get_svc", lambda: None), \
         patch.object(config_service, "get_tenant_access_token", lambda: "tok"), \
         patch.object(config_service, "requests", fake_requests), \
         patch("app.pipeline.routes.feishu_status_router.invalidate_active_resume_meta_cache") as inv:
        config_service.activate_target_resume("recA")
    inv.assert_called_once()


async def test_setup_status_resume_requires_active_resume(monkeypatch):
    """新手指引第二步：只认生效简历，本地文件存在不再兜底。"""
    import app.pipeline.config_status_service as css

    monkeypatch.setattr(css, "_ACTIVE_RESUME_META_CACHE",
                        {"ts": css.time.time() + 9999, "value": {"id": "recA", "title": "主简历"}})
    assert setup_status._resume_exists() is True

    monkeypatch.setattr(css, "_ACTIVE_RESUME_META_CACHE",
                        {"ts": css.time.time() + 9999, "value": None})
    assert setup_status._resume_exists() is False
