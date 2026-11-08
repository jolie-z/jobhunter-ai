"""飞书写探针（_probe_table_write / _explain_write_fail）单元测试。

全部 mock，不发真实飞书请求。覆盖：create 成功即删（零残留）、create 403
（协作者只给可阅读）、create 404（Table ID 失效）、delete 被拒（写入结论不推翻、
如实告知残留）、create 未回 record_id、网络异常、翻译矩阵定向分支。
被测函数为纯异步 service 层函数，与 test_settings_diagnostics_llm.py 同模式直调。
"""
import pytest


def _fake_client(post_json=None, delete_json=None, post_exc=None, del_exc=None, get_json=None, get_exc=None):
    """构造最小 httpx.AsyncClient 桩：只实现探针用到的 get（字段清单）/post/delete。"""

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        async def get(self, *a, **kw):
            if get_exc:
                raise get_exc
            return _Resp(get_json if get_json is not None else {"code": 0, "data": {"items": []}})

        async def post(self, *a, **kw):
            if post_exc:
                raise post_exc
            return _Resp(post_json)

        async def delete(self, *a, **kw):
            if del_exc:
                raise del_exc
            return _Resp(delete_json)

    return _Client()


TOKEN = "t-token"
APP = "app-token"
TABLE = "tbl-1"
LABEL = "简历库"


# ============================================================
# _explain_write_fail 翻译矩阵
# ============================================================

def test_explain_write_403_collaborator_readonly():
    from app.settings.diagnostics import _explain_write_fail

    detail, fix = _explain_write_fail(403, "Forbidden")
    assert "可阅读" in detail and "可编辑" in fix


def test_explain_write_404_bad_table():
    from app.settings.diagnostics import _explain_write_fail

    detail, _ = _explain_write_fail(404, "not found")
    assert "Table ID" in detail or "找不到" in detail


def test_explain_write_fallback():
    from app.settings.diagnostics import _explain_write_fail

    detail, fix = _explain_write_fail(999999, "something else")
    assert "飞书返回错误" in detail
    assert "可编辑" in fix


def test_explain_write_advanced_permission():
    """高级权限特征词（含英文报错混带 permission 的情形）优先于 403 分支。"""
    from app.settings.diagnostics import _explain_write_fail

    detail, fix = _explain_write_fail(403, "advance space permission denied")
    assert "高级权限" in detail
    assert "可编辑」角色" in fix

    detail2, fix2 = _explain_write_fail(0, "高级权限限制")
    assert "高级权限" in detail2
    assert "可编辑」角色" in fix2


def test_explain_write_field_error():
    """字段类报错：说明探针与真实保存写的字段不同、可忽略继续使用。"""
    from app.settings.diagnostics import _explain_write_fail

    detail, fix = _explain_write_fail(1254045, "FieldNameNotFound: 标题")
    assert "字段问题" in detail
    assert "可忽略本项继续使用" in fix


# ============================================================
# _probe_table_write 行为分支
# ============================================================

@pytest.mark.asyncio
async def test_probe_success_creates_then_deletes():
    """create 成功 + delete 成功：ok=True，零残留话术。"""
    from app.settings.diagnostics import _probe_table_write

    ok, detail, fix = await _probe_table_write(
        _fake_client(
            post_json={"code": 0, "data": {"record": {"record_id": "rec123"}}},
            delete_json={"code": 0},
        ),
        TOKEN, APP, TABLE, LABEL,
    )
    assert ok is True
    assert "写入与删除均成功" in detail
    assert fix == ""


@pytest.mark.asyncio
async def test_probe_uses_real_field_name():
    """字段清单里有文本字段：探针必须写该真实字段名，而不是写死的「标题」。"""
    from app.settings.diagnostics import _probe_table_write

    captured: dict = {}
    inner = _fake_client(
        post_json={"code": 0, "data": {"record": {"record_id": "rec123"}}},
        delete_json={"code": 0},
        get_json={"code": 0, "data": {"items": [
            {"field_name": "简历版本", "type": 1, "ui_type": "Text"},
            {"field_name": "当前状态", "type": 3, "ui_type": "SingleSelect"},
        ]}},
    )

    class _CaptureClient:
        async def get(self, *a, **kw):
            return await inner.get(*a, **kw)

        async def post(self, url, **kw):
            captured["fields"] = kw.get("json", {}).get("fields")
            return await inner.post(url, **kw)

        async def delete(self, *a, **kw):
            return await inner.delete(*a, **kw)

    ok, _, _ = await _probe_table_write(_CaptureClient(), TOKEN, APP, TABLE, LABEL)
    assert ok is True
    assert "简历版本" in captured["fields"]
    assert "标题" not in captured["fields"]


@pytest.mark.asyncio
async def test_probe_empty_record_when_no_text_field():
    """字段清单读不到或无文本字段：退化为空记录写入，不因 FieldNameNotFound 误报。"""
    from app.settings.diagnostics import _probe_table_write

    captured: dict = {}
    inner = _fake_client(
        post_json={"code": 0, "data": {"record": {"record_id": "rec123"}}},
        delete_json={"code": 0},
        get_json={"code": 0, "data": {"items": []}},
    )

    class _CaptureClient:
        async def get(self, *a, **kw):
            return await inner.get(*a, **kw)

        async def post(self, url, **kw):
            captured["fields"] = kw.get("json", {}).get("fields")
            return await inner.post(url, **kw)

        async def delete(self, *a, **kw):
            return await inner.delete(*a, **kw)

    ok, detail, _ = await _probe_table_write(_CaptureClient(), TOKEN, APP, TABLE, LABEL)
    assert ok is True
    assert captured["fields"] == {}
    assert "写入与删除均成功" in detail


@pytest.mark.asyncio
async def test_probe_create_403():
    from app.settings.diagnostics import _probe_table_write

    ok, detail, fix = await _probe_table_write(
        _fake_client(post_json={"code": 403, "msg": "Forbidden"}),
        TOKEN, APP, TABLE, LABEL,
    )
    assert ok is False
    assert "编辑权限" in detail or "可阅读" in detail
    assert "可编辑" in fix


@pytest.mark.asyncio
async def test_probe_create_404():
    from app.settings.diagnostics import _probe_table_write

    ok, detail, fix = await _probe_table_write(
        _fake_client(post_json={"code": 404, "msg": "not found"}),
        TOKEN, APP, TABLE, LABEL,
    )
    assert ok is False
    assert "Table ID" in detail or "找不到" in detail


@pytest.mark.asyncio
async def test_probe_delete_denied_keeps_write_verdict():
    """delete 被拒不推翻写入结论：ok=True 但如实告知残留并给标记。"""
    from app.settings.diagnostics import _PROBE_TAG, _probe_table_write

    ok, detail, fix = await _probe_table_write(
        _fake_client(
            post_json={"code": 0, "data": {"record": {"record_id": "rec123"}}},
            delete_json={"code": 99991679, "msg": "permission denied"},
        ),
        TOKEN, APP, TABLE, LABEL,
    )
    assert ok is True
    assert _PROBE_TAG in detail
    assert "手动清理" in detail


@pytest.mark.asyncio
async def test_probe_delete_exception_keeps_write_verdict():
    from app.settings.diagnostics import _PROBE_TAG, _probe_table_write

    ok, detail, _ = await _probe_table_write(
        _fake_client(
            post_json={"code": 0, "data": {"record": {"record_id": "rec123"}}},
            del_exc=ConnectionError("boom"),
        ),
        TOKEN, APP, TABLE, LABEL,
    )
    assert ok is True
    assert _PROBE_TAG in detail


@pytest.mark.asyncio
async def test_probe_create_without_record_id():
    """create 成功但未回 record_id：仍算写入成功，提示手动清理。"""
    from app.settings.diagnostics import _PROBE_TAG, _probe_table_write

    ok, detail, _ = await _probe_table_write(
        _fake_client(post_json={"code": 0, "data": {}}),
        TOKEN, APP, TABLE, LABEL,
    )
    assert ok is True
    assert _PROBE_TAG in detail


@pytest.mark.asyncio
async def test_probe_network_error():
    from app.settings.diagnostics import _probe_table_write

    ok, detail, fix = await _probe_table_write(
        _fake_client(post_exc=ConnectionError("timeout")),
        TOKEN, APP, TABLE, LABEL,
    )
    assert ok is False
    assert "网络" in detail
    assert "重跑" in fix
