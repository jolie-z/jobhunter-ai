"""飞书聊天框岗位极速录入（截图通道）测试。

覆盖：录入回执摘要格式化、多图聚合窗口、下载失败降级、
webhook image/不支持消息分支分发、幂等防重、坏 import_job 工具修复。
外部边界（飞书图片下载、Vision 解析、消息发送）Mock，内部聚合/格式化逻辑全量真实执行。
"""
import asyncio
import json
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import webhook
from app.services import job_entry_chat
from app.services import materials_delivery
from app.services import eval_pipeline_feedback


@pytest.fixture(autouse=True)
def _reset_pending_state():
    job_entry_chat._pending_images.clear()
    job_entry_chat._pending_job_links.clear()
    job_entry_chat._pending_pipeline.clear()
    yield
    job_entry_chat._pending_images.clear()
    job_entry_chat._pending_job_links.clear()
    job_entry_chat._pending_pipeline.clear()
    job_entry_chat._PENDING_LINKS_PATH.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _reset_feishu_msg_dedup(tmp_path, monkeypatch):
    """防重锁已持久化到磁盘：每个用例重定向落盘路径并清空内存态，避免跨运行误判重复。"""
    from app.core import feishu_msg_dedup

    monkeypatch.setattr(feishu_msg_dedup, "_PERSIST_PATH", tmp_path / "feishu_seen_msg_ids.json")
    monkeypatch.setattr(feishu_msg_dedup, "_seen", feishu_msg_dedup.OrderedDict())
    monkeypatch.setattr(feishu_msg_dedup, "_loaded", True)
    yield
    job_entry_chat._PENDING_PIPELINE_PATH.unlink(missing_ok=True)


@pytest.fixture()
def client():
    """轻量 app：只挂 webhook 路由，不拉起完整应用 lifespan。"""
    api = FastAPI()
    api.include_router(webhook.router)
    return TestClient(api)


def _patch_chat_pipeline(monkeypatch, import_results, sent, downloads=None, cards=None, card_error=None):
    """把聊天录入链路的外部边界换成可控桩。

    import_results 记录解析入参，sent 记录文本消息，cards 记录发出的卡片；
    card_error 非空时模拟卡片发送失败（验证降级为纯文本）。
    """
    async def fake_download(message_id: str, file_key: str) -> bytes:
        if downloads is not None and file_key in downloads:
            raise downloads[file_key]
        return b"\xff\xd8fake-jpeg-bytes"  # JPEG 魔数

    async def fake_import(images_base64):
        import_results.append(images_base64)
        return {
            "公司名称": "测试公司", "岗位名称": "测试岗位", "城市": "上海",
            "招聘平台": "截图解析", "record_id": "recTestLink001",
        }

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    async def fake_card(receive_id: str, card_content: dict, receive_id_type: str = "chat_id", **kw):
        if card_error:
            raise card_error
        if cards is not None:
            cards.append(card_content)

    monkeypatch.setattr(job_entry_chat, "_AGGREGATION_WINDOW_SECONDS", 0.05)
    monkeypatch.setattr(job_entry_chat, "download_message_image", fake_download)
    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)
    monkeypatch.setattr(job_entry_chat, "send_feishu_card", fake_card)
    # 卡片幂等降级 helper 直连 feishu_messaging，桩必须同时打到源头
    from app.core import feishu_messaging as _fm
    monkeypatch.setattr(_fm, "send_feishu_card", fake_card)
    monkeypatch.setattr(_fm, "send_feishu_message", fake_send)

    import app.jobs.service as jobs_service
    monkeypatch.setattr(jobs_service, "import_job_from_images_service", fake_import)


# ==========================================
# 录入回执摘要格式化
# ==========================================
def test_format_job_import_summary_contains_key_fields():
    from app.jobs.service import format_job_import_summary

    summary = format_job_import_summary({
        "公司名称": "字节跳动",
        "岗位名称": "后端开发工程师",
        "薪资": "30-50K",
        "城市": "北京",
        "招聘平台": "boss直聘",
        "岗位详情": "一段非常长的 JD 正文，不应该出现在摘要里",
        "跟进状态": "新线索",
    })
    assert "字节跳动" in summary
    assert "后端开发工程师" in summary
    assert "30-50K" in summary
    assert "北京" in summary
    assert "新线索" in summary
    assert "非常长的 JD 正文" not in summary  # 大字段不进聊天回执


def test_format_job_import_summary_skips_unknown_fields():
    from app.jobs.service import format_job_import_summary

    summary = format_job_import_summary({
        "公司名称": "未知",
        "岗位名称": "-",
        "城市": "上海",
        "薪资": "",
    })
    assert "未知" not in summary
    assert "-" not in summary
    assert "上海" in summary
    assert "✅" in summary


def test_format_job_import_summary_includes_record_link():
    from app.jobs.service import format_job_import_summary

    summary = format_job_import_summary({
        "公司名称": "链接测试公司",
        "城市": "上海",
        "record_id": "recFmtLink009",
    })
    assert "recFmtLink009" in summary
    assert "https://feishu.cn/base/" in summary
    assert "table=" in summary and "record=recFmtLink009" in summary


# ==========================================
# 聚合窗口与录入链路
# ==========================================
def test_single_image_triggers_import_and_card_reply(monkeypatch):
    import_results, sent, cards = [], [], []
    _patch_chat_pipeline(monkeypatch, import_results, sent, cards=cards)

    async def run():
        await job_entry_chat.handle_image_message("chat_single", "img_1", "om_single")
        await asyncio.sleep(0.4)  # 等聚合窗口关闭 + 解析完成

    asyncio.run(run())

    assert len(import_results) == 1
    # 魔数识别为 JPEG，base64 带 data URL 前缀
    assert import_results[0][0].startswith("data:image/jpeg;base64,")
    # 首响：收到第一张图立刻有确认，不等聚合窗口
    assert any("已收到截图" in s for s in sent)
    assert any("正在识别" in s for s in sent)
    # 回执卡（绿头：字段摘要+复核按钮）+ 评估确认卡（蓝头：单按钮+底部灰色小字提示）
    assert len(cards) == 2, "回执卡 + 评估确认卡"
    receipt_md = cards[0]["elements"][0]["text"]["content"]
    assert "测试公司" in receipt_md and "新线索" in receipt_md
    receipt_btn = cards[0]["elements"][-1]["actions"][0]
    assert receipt_btn["url"].endswith("record=recTestLink001")
    assert "base/" in receipt_btn["url"] and "table=" in receipt_btn["url"]
    confirm_elements = cards[1]["elements"]
    assert confirm_elements[0]["actions"][0]["value"] == {"action": "run_pipeline", "record_id": "recTestLink001"}
    note_text = confirm_elements[1]["elements"][0]["content"]
    assert "AI 评估" in note_text and "绝不自动投递" in note_text
    # 截图路径没有岗位链接 → 进入反问补录状态
    assert job_entry_chat._pending_job_links.get("chat_single") == "recTestLink001"
    assert any("网页链接" in s for s in sent)
    # 同时反问是否评估这个岗位（ticket 02，文字兜底 + 按钮卡片主交互）
    assert job_entry_chat._pending_pipeline.get("chat_single") == "recTestLink001"
    assert any("网页链接" in s and "跳过" in s for s in sent)


def test_card_send_failure_falls_back_to_text(monkeypatch):
    import_results, sent, cards = [], [], []
    _patch_chat_pipeline(
        monkeypatch, import_results, sent, cards=cards,
        card_error=RuntimeError("card send failed"),
    )

    async def run():
        await job_entry_chat.handle_image_message("chat_cardfail", "img_1", "om_cf")
        await asyncio.sleep(0.4)

    asyncio.run(run())

    assert cards == [], "卡片发送失败时不应有卡片送达"
    assert any("测试公司" in s and "新线索" in s for s in sent), "应降级为纯文本回执"
    assert any("recTestLink001" in s for s in sent), "纯文本回执应带多维表格详情链接"


def test_rapid_images_aggregated_into_one_import(monkeypatch):
    import_results, sent = [], []
    _patch_chat_pipeline(monkeypatch, import_results, sent)

    async def run():
        await job_entry_chat.handle_image_message("chat_multi", "img_1", "om_m1")
        await asyncio.sleep(0.01)
        await job_entry_chat.handle_image_message("chat_multi", "img_2", "om_m2")
        await asyncio.sleep(0.01)
        await job_entry_chat.handle_image_message("chat_multi", "img_3", "om_m3")
        await asyncio.sleep(0.4)

    asyncio.run(run())

    assert len(import_results) == 1, "窗口内连发的多张截图应合并为一次 Vision 解析"
    assert len(import_results[0]) == 3
    assert sum("已收到截图" in s for s in sent) == 1, "首响确认只在批次开始时发一次"


def test_download_failure_replies_error_without_import(monkeypatch):
    import_results, sent = [], []
    _patch_chat_pipeline(
        monkeypatch, import_results, sent,
        downloads={"img_bad": RuntimeError("HTTP 404")},
    )

    async def run():
        await job_entry_chat.handle_image_message("chat_fail", "img_bad", "om_fail")
        await asyncio.sleep(0.4)

    asyncio.run(run())

    assert import_results == [], "全部图片下载失败时不应调用解析服务"
    assert any("下载失败" in s and "HTTP" in s for s in sent), "失败回执应带出具体原因"


def test_import_images_duplicate_intercepted_without_new_record(monkeypatch):
    """查重命中：回复疑似重复警示（含母本信息与复核链接），不建新档、不进补链/评估反问。"""
    import app.jobs.service as jobs_service
    from app.jobs.service import DuplicateJobError

    sent, cards = [], []
    _patch_chat_pipeline(monkeypatch, [], sent, cards=cards)

    async def fake_import_dup(images_base64):
        raise DuplicateJobError({
            "record_id": "recDup001",
            "公司名称": "已存在公司",
            "岗位名称": "已存在岗位",
            "跟进状态": "新线索",
            "review_url": "https://feishu.cn/base/appX?table=tblX&record=recDup001",
        })

    monkeypatch.setattr(jobs_service, "import_job_from_images_service", fake_import_dup)

    async def run():
        await job_entry_chat.handle_image_message("chat_dup", "img_1", "om_dup")
        await asyncio.sleep(0.4)

    asyncio.run(run())

    assert cards == [], "查重拦截不应发送回执卡/评估确认卡"
    assert any("疑似重复" in s for s in sent), "应回复疑似重复警示"
    assert any("已存在公司" in s and "已存在岗位" in s for s in sent), "警示应带出母本公司与岗位"
    assert any("recDup001" in s for s in sent), "警示应带出已有记录的复核链接"
    assert job_entry_chat._pending_job_links.get("chat_dup") is None, "查重拦截后不应进入补链反问"
    assert job_entry_chat._pending_pipeline.get("chat_dup") is None, "查重拦截后不应进入评估反问"


def test_import_images_missing_core_fields_intercepted(monkeypatch):
    """核心字段缺失：回复拦截话术并列出缺失项，不建垃圾档、不进反问。"""
    import app.jobs.service as jobs_service
    from app.jobs.service import InvalidJobFieldsError

    sent, cards = [], []
    _patch_chat_pipeline(monkeypatch, [], sent, cards=cards)

    async def fake_import_invalid(images_base64):
        raise InvalidJobFieldsError(["公司名称", "岗位详情"])

    monkeypatch.setattr(jobs_service, "import_job_from_images_service", fake_import_invalid)

    async def run():
        await job_entry_chat.handle_image_message("chat_invalid", "img_1", "om_invalid")
        await asyncio.sleep(0.4)

    asyncio.run(run())

    assert cards == [], "字段缺失拦截不应发送回执卡/评估确认卡"
    assert any("公司名称" in s and "岗位详情" in s for s in sent), "拦截话术应列出缺失字段"
    assert any("未予建档" in s for s in sent), "拦截话术应说明未建档原因"
    assert any("粘贴纯文本" in s for s in sent), "应给出补料建议"
    assert job_entry_chat._pending_job_links.get("chat_invalid") is None, "拦截后不应进入补链反问"
    assert job_entry_chat._pending_pipeline.get("chat_invalid") is None, "拦截后不应进入评估反问"


def test_unsupported_message_replies_hint(monkeypatch):
    sent = []

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)

    asyncio.run(job_entry_chat.handle_unsupported_message("chat_unsupported", "audio"))

    assert len(sent) == 1
    assert "截图" in sent[0] and "文字" in sent[0]


# ==========================================
# webhook 消息分发分支
# ==========================================
def _make_message_event(msg_type: str, message_id: str, content: dict) -> dict:
    return {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_type": msg_type,
                "chat_id": f"oc_test_{message_id}",
                "message_id": message_id,
                "create_time": str(int(time.time() * 1000)),
                "content": json.dumps(content, ensure_ascii=False),
            }
        },
    }


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_webhook_image_message_dispatches_handler(client: TestClient, monkeypatch):
    called = []

    async def fake_handle(chat_id: str, image_key: str, message_id: str = ""):
        called.append((chat_id, image_key, message_id))

    monkeypatch.setattr(webhook, "handle_image_message", fake_handle)

    payload = _make_message_event("image", "om_img_unique_1", {"image_key": "v3_00abc"})
    resp = client.post("/feishu/webhook", json=payload)

    assert resp.status_code == 200
    assert _wait_until(lambda: called), "图片消息应触发岗位录入处理"
    assert called[0] == ("oc_test_om_img_unique_1", "v3_00abc", "om_img_unique_1")


def test_webhook_duplicate_image_message_ignored(client: TestClient, monkeypatch):
    called = []

    async def fake_handle(chat_id: str, image_key: str, message_id: str = ""):
        called.append((chat_id, image_key))

    monkeypatch.setattr(webhook, "handle_image_message", fake_handle)

    payload = _make_message_event("image", "om_img_dup_1", {"image_key": "v3_dup"})
    client.post("/feishu/webhook", json=payload)
    assert _wait_until(lambda: len(called) == 1)
    client.post("/feishu/webhook", json=payload)  # 同一 message_id 重放
    time.sleep(0.3)
    assert len(called) == 1, "重复消息应被幂等防重锁拦截"


def test_webhook_unsupported_message_dispatches_hint(client: TestClient, monkeypatch):
    called = []

    async def fake_hint(chat_id: str, msg_type: str):
        called.append((chat_id, msg_type))

    monkeypatch.setattr(webhook, "handle_unsupported_message", fake_hint)

    payload = _make_message_event("audio", "om_audio_unique_1", {"file_key": "xxx"})
    resp = client.post("/feishu/webhook", json=payload)

    assert resp.status_code == 200
    assert _wait_until(lambda: called), "不支持的消息类型应回复友好提示"
    assert called[0] == ("oc_test_om_audio_unique_1", "audio")


# ==========================================
# ChatOps import_job 工具修复
# ==========================================
def test_import_job_tool_success(monkeypatch):
    from app.core import chatops_tools

    async def fake_import(text: str):
        return {"公司名称": "工具测试公司", "岗位名称": "工具测试岗", "薪资": "-", "城市": "深圳"}

    import app.jobs.service as jobs_service
    monkeypatch.setattr(jobs_service, "import_job_from_text_service", fake_import)

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    chatops_tools.set_runtime_context(loop, "chat_tool_test")
    try:
        result = chatops_tools.import_job.invoke({"text": "某公司招聘后端工程师，30-50K"})
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()

    assert "✅" in result
    assert "工具测试公司" in result
    assert "深圳" in result
    assert "-" not in result  # 无效字段被过滤


def test_import_job_tool_requires_text():
    from app.core import chatops_tools

    result = chatops_tools.import_job.invoke({"text": ""})
    assert "❌" in result


# ==========================================
# 岗位链接补录闭环
# ==========================================
def test_link_reply_updates_bitable_record(monkeypatch):
    import asyncio
    from app.core import feishu_client as feishu_client_module

    job_entry_chat._pending_job_links["chat_link"] = "recLink777"
    updates = []

    async def fake_update(table_id, record_id, fields):
        updates.append((table_id, record_id, fields))
        return {"code": 0}

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        return True

    monkeypatch.setattr(feishu_client_module.feishu_client, "update_record", fake_update)
    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)

    asyncio.run(job_entry_chat.handle_link_reply("chat_link", "岗位在这里 https://example.com/job/12345 谢谢"))

    assert len(updates) == 1
    table_id, record_id, fields = updates[0]
    assert record_id == "recLink777"
    assert fields["岗位链接"]["link"] == "https://example.com/job/12345"
    assert "chat_link" not in job_entry_chat._pending_job_links, "补录成功后应清除待补录状态"


def test_link_reply_converts_boss_mobile_url(monkeypatch):
    """手机端 BOSS 分享链接补录时应自动转译为桌面端 job_detail 链接。"""
    import asyncio
    from app.core import feishu_client as feishu_client_module

    job_entry_chat._pending_job_links["chat_boss"] = "recBoss001"
    updates = []

    async def fake_update(table_id, record_id, fields):
        updates.append((table_id, record_id, fields))
        return {"code": 0}

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        return True

    monkeypatch.setattr(feishu_client_module.feishu_client, "update_record", fake_update)
    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)

    mobile_url = (
        "https://m.zhipin.com/mpa/html/weijd/weijd-job/3e3336b9f7653dbf0nN62dy4FlRX"
        "?date8=20260828&sid=tosee_jd_xxx~&openWeapp=1&fromSource=2"
    )
    asyncio.run(job_entry_chat.handle_link_reply("chat_boss", mobile_url))

    assert len(updates) == 1
    link = updates[0][2]["岗位链接"]["link"]
    assert link == "https://www.zhipin.com/job_detail/3e3336b9f7653dbf0nN62dy4FlRX.html"


def test_normalize_job_url_patterns():
    from app.jobs.service import normalize_job_url

    boss_mobile = (
        "https://m.zhipin.com/mpa/html/weijd/weijd-job/3e3336b9f7653dbf0nN62dy4FlRX"
        "?date8=20260828&sid=tosee_jd_xxx~&openWeapp=1&fromSource=2"
    )
    assert normalize_job_url(boss_mobile) == "https://www.zhipin.com/job_detail/3e3336b9f7653dbf0nN62dy4FlRX.html"
    # 支持包含连字符 -- 与下划线 _ 的复杂真实 BOSS 加密 ID
    assert normalize_job_url("https://m.zhipin.com/mpa/html/weijd/weijd-job/0a0b3fa18724f4300nVy3N--EFJY?date8=2026") == \
        "https://www.zhipin.com/job_detail/0a0b3fa18724f4300nVy3N--EFJY.html"
    assert normalize_job_url("https://m.zhipin.com/mpa/html/weijd/test123_456") == \
        "https://www.zhipin.com/job_detail/test123_456.html"
    # m 站 job_detail 形态（可能带 ~ 尾巴）同样转译
    assert normalize_job_url("https://m.zhipin.com/job_detail/abc123def~.html?ka=share") == \
        "https://www.zhipin.com/job_detail/abc123def~.html"
    # 桌面链接 / 其他平台 / 空值原样返回
    desktop = "https://www.zhipin.com/job_detail/abc123.html?lid=xxx"
    assert normalize_job_url(desktop) == desktop
    liepin = "https://www.liepin.com/job/12345.shtml"
    assert normalize_job_url(liepin) == liepin
    assert normalize_job_url("") == ""


def test_link_reply_skip_word(monkeypatch):
    import asyncio
    from app.core import feishu_client as feishu_client_module

    job_entry_chat._pending_job_links["chat_skip"] = "recSkip001"
    updates = []
    sent = []

    async def fake_update(table_id, record_id, fields):
        updates.append((table_id, record_id, fields))
        return {"code": 0}

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(feishu_client_module.feishu_client, "update_record", fake_update)
    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)

    assert job_entry_chat.should_intercept_link_reply("chat_skip", "跳过")
    asyncio.run(job_entry_chat.handle_link_reply("chat_skip", "跳过"))

    assert updates == [], "跳过时不应写多维表格"
    assert "chat_skip" not in job_entry_chat._pending_job_links


def test_link_intercept_not_triggered_for_normal_text():
    assert not job_entry_chat.should_intercept_link_reply("chat_none", "https://example.com/x")
    assert not job_entry_chat.should_intercept_link_reply("chat_none", "随便说句话")
    job_entry_chat._pending_job_links["chat_wait"] = "rec001"
    assert job_entry_chat.should_intercept_link_reply("chat_wait", "链接是 https://a.b/c")
    assert job_entry_chat.should_intercept_link_reply("chat_wait", "跳过")
    assert not job_entry_chat.should_intercept_link_reply("chat_wait", "帮我跑下全链路")


def test_pending_link_state_survives_restart():
    """待补录状态落盘：重启（新进程新实例）后可恢复；超期状态被丢弃。"""
    job_entry_chat._set_pending_link("chat_persist", "recPersist42")
    assert job_entry_chat._PENDING_LINKS_PATH.exists(), "设置待补录状态时应落盘"

    # 模拟重启：新建 store 实例（等价于新进程从磁盘加载）
    fresh = job_entry_chat._PendingStore(job_entry_chat._PENDING_LINKS_PATH, 24 * 3600)
    assert fresh.get("chat_persist") == "recPersist42"

    # 超过 TTL 的状态恢复时应被丢弃
    job_entry_chat._PENDING_LINKS_PATH.write_text(
        json.dumps({"chat_old": {"record_id": "recOld", "ts": 0}})
    )
    expired = job_entry_chat._PendingStore(job_entry_chat._PENDING_LINKS_PATH, 24 * 3600)
    assert "chat_old" not in expired

    # 消费状态后文件同步更新
    job_entry_chat._set_pending_link("chat_consume", "recC1")
    assert job_entry_chat._pop_pending_link("chat_consume") == "recC1"
    on_disk = json.loads(job_entry_chat._PENDING_LINKS_PATH.read_text())
    assert "chat_consume" not in on_disk


def test_webhook_intercepts_link_reply(client: TestClient, monkeypatch):
    from app.api.routes import webhook as webhook_module

    agent_calls, link_calls = [], []

    async def fake_agent(chat_id: str, text: str):
        agent_calls.append((chat_id, text))

    async def fake_link(chat_id: str, text: str):
        link_calls.append((chat_id, text))

    monkeypatch.setattr(webhook_module, "process_chatops_query", fake_agent)
    monkeypatch.setattr(webhook_module, "handle_link_reply", fake_link)

    job_entry_chat._pending_job_links["oc_test_om_text_link_1"] = "recHook001"
    payload = _make_message_event("text", "om_text_link_1", {"text": "https://example.com/job/abc"})
    resp = client.post("/feishu/webhook", json=payload)

    assert resp.status_code == 200
    assert _wait_until(lambda: bool(link_calls)), "待补录状态下回复链接应被拦截处理"
    assert link_calls[0][1].startswith("https://example.com/job/abc")
    time.sleep(0.3)
    assert agent_calls == [], "链接补录回复不应再投递给 Agent"


# ==========================================
# 单岗位全链路确认（ticket 02）
# ==========================================
def test_pipeline_confirm_triggers_single_job_pipeline(monkeypatch):
    """回复「走全链路」→ 触发单岗位流水线，必须 stop_at_review=True 且不自动投递。"""
    import asyncio
    from app.automation import full_auto

    job_entry_chat._pending_pipeline["chat_pipe"] = "recPipe001"
    launches, sent = [], []

    deliveries = []

    async def fake_deliver(chat_id, record_id, company="", job=""):
        deliveries.append(record_id)
        return True  # 新契约：交付函数返回真实成败

    async def fake_launch(record_id, raw_rowid=None, pipeline_task_id=None, stop_at_review=False, on_node_done=None, resume=False):
        launches.append({"record_id": record_id, "stop_at_review": stop_at_review})
        return {
            "company_name": "流水线公司", "job_name": "流水线岗位",
            "grade": "A", "outcome": "stopped", "error": "简历人工复核",
        }

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)
    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)
    monkeypatch.setattr(eval_pipeline_feedback, "_deliver_materials_to_chat", fake_deliver)
    progress_cards, updates = [], []

    async def fake_pcard(rid, card, receive_id_type="chat_id"):
        progress_cards.append(card)
        return "om_prog_1"

    async def fake_pupdate(msg_id, card):
        updates.append(card)
        return True

    monkeypatch.setattr(eval_pipeline_feedback, "send_feishu_card", fake_pcard)
    monkeypatch.setattr(eval_pipeline_feedback, "update_feishu_card", fake_pupdate)

    assert job_entry_chat.should_intercept_pipeline_confirm("chat_pipe", "走全链路")
    asyncio.run(job_entry_chat.handle_pipeline_confirm("chat_pipe", "走全链路"))

    assert len(launches) == 1
    assert launches[0]["record_id"] == "recPipe001"
    assert launches[0]["stop_at_review"] is True, "必须停在人工复核断点，绝不自动投递"
    assert "chat_pipe" not in job_entry_chat._pending_pipeline
    assert progress_cards and "正在评估" in progress_cards[0]["header"]["title"]["content"], "应发进度卡"
    assert updates and updates[-1]["header"]["template"] == "green", "完成后进度卡应变绿"
    assert deliveries == ["recPipe001"], "完成后应触发物料交付到聊天框"


def test_pipeline_decline_word(monkeypatch):
    import asyncio

    job_entry_chat._pending_pipeline["chat_decline"] = "recDecline1"
    launches, sent = [], []

    async def fake_launch(**kw):
        launches.append(kw)

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    from app.automation import full_auto
    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)
    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)

    assert job_entry_chat.should_intercept_pipeline_confirm("chat_decline", "先放着")
    asyncio.run(job_entry_chat.handle_pipeline_confirm("chat_decline", "先放着"))

    assert launches == [], "婉拒时不应触发流水线"
    assert "chat_decline" not in job_entry_chat._pending_pipeline
    assert any("先放着" in s for s in sent)


def test_pipeline_intercept_not_triggered_without_pending():
    assert not job_entry_chat.should_intercept_pipeline_confirm("chat_none", "走全链路")
    job_entry_chat._pending_pipeline["chat_p"] = "rec1"
    assert job_entry_chat.should_intercept_pipeline_confirm("chat_p", "好的，走全链路吧")
    assert not job_entry_chat.should_intercept_pipeline_confirm("chat_p", "帮我查下进度"), "无关消息应放行给 Agent"


def test_webhook_intercepts_pipeline_confirm(client: TestClient, monkeypatch):
    from app.api.routes import webhook as webhook_module

    agent_calls, pipe_calls = [], []

    async def fake_agent(chat_id: str, text: str):
        agent_calls.append((chat_id, text))

    async def fake_pipe(chat_id: str, text: str):
        pipe_calls.append((chat_id, text))

    monkeypatch.setattr(webhook_module, "process_chatops_query", fake_agent)
    monkeypatch.setattr(webhook_module, "handle_pipeline_confirm", fake_pipe)

    job_entry_chat._pending_pipeline["oc_test_om_text_pipe_1"] = "recHookPipe1"
    payload = _make_message_event("text", "om_text_pipe_1", {"text": "走全链路"})
    resp = client.post("/feishu/webhook", json=payload)

    assert resp.status_code == 200
    assert _wait_until(lambda: bool(pipe_calls)), "「走全链路」应被拦截触发流水线"
    time.sleep(0.3)
    assert agent_calls == [], "全链路确认不应投递给 Agent"


# ==========================================
# 卡片按钮回调（card.action.trigger）
# ==========================================
def test_build_pipeline_confirm_card_single_button_with_note():
    card = job_entry_chat.build_pipeline_confirm_card("recBtn001")
    actions = card["elements"][0]["actions"]
    assert len(actions) == 1, "确认卡只保留评估按钮"
    assert actions[0]["value"] == {"action": "run_pipeline", "record_id": "recBtn001"}
    note = card["elements"][1]
    assert note["tag"] == "note", "底部提示应为灰色小字 note 元素"
    assert "AI 评估" in note["elements"][0]["content"]


def test_card_action_run_pipeline_launches_with_guard(monkeypatch):
    import asyncio
    from app.automation import full_auto

    launches, sent = [], []

    async def fake_launch(record_id, raw_rowid=None, pipeline_task_id=None, stop_at_review=False, on_node_done=None, resume=False):
        launches.append({"record_id": record_id, "stop_at_review": stop_at_review})
        return {"company_name": "按钮公司", "job_name": "按钮岗位", "grade": "B", "outcome": "stopped", "error": "简历人工复核"}

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    async def fake_deliver(chat_id, record_id, company="", job=""):
        pass

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)
    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)
    monkeypatch.setattr(eval_pipeline_feedback, "_deliver_materials_to_chat", fake_deliver)
    progress_cards, updates = [], []

    async def fake_pcard(rid, card, receive_id_type="chat_id"):
        progress_cards.append(card)
        return "om_prog_1"

    async def fake_pupdate(msg_id, card):
        updates.append(card)
        return True

    monkeypatch.setattr(eval_pipeline_feedback, "send_feishu_card", fake_pcard)
    monkeypatch.setattr(eval_pipeline_feedback, "update_feishu_card", fake_pupdate)

    asyncio.run(job_entry_chat.handle_card_action("chat_btn", {"action": "run_pipeline", "record_id": "recBtn777"}))

    assert len(launches) == 1
    assert launches[0]["stop_at_review"] is True, "按钮触发同样必须停复核断点"
    assert launches[0]["record_id"] == "recBtn777"
    assert progress_cards and "正在评估" in progress_cards[0]["header"]["title"]["content"], "按钮触发应发进度卡"
    assert "recBtn777" not in eval_pipeline_feedback._inflight_pipelines, "执行完成后应移除在飞标记"


def test_card_action_duplicate_click_ignored(monkeypatch):
    import asyncio
    from app.automation import full_auto

    launches, sent = [], []
    release = asyncio.Event()

    async def fake_launch(record_id, **kw):
        launches.append(record_id)
        await release.wait()
        return {"company_name": "x", "job_name": "y", "grade": "B", "outcome": "stopped"}

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    async def fake_deliver(chat_id, record_id, company="", job=""):
        pass

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)
    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)
    monkeypatch.setattr(eval_pipeline_feedback, "_deliver_materials_to_chat", fake_deliver)
    progress_cards, updates = [], []

    async def fake_pcard(rid, card, receive_id_type="chat_id"):
        progress_cards.append(card)
        return "om_prog_1"

    async def fake_pupdate(msg_id, card):
        updates.append(card)
        return True

    monkeypatch.setattr(eval_pipeline_feedback, "send_feishu_card", fake_pcard)
    monkeypatch.setattr(eval_pipeline_feedback, "update_feishu_card", fake_pupdate)

    async def run():
        task1 = asyncio.create_task(job_entry_chat.handle_card_action("chat_dup", {"action": "run_pipeline", "record_id": "recDup1"}))
        await asyncio.sleep(0.05)  # 让第一次进入 in-flight
        await job_entry_chat.handle_card_action("chat_dup", {"action": "run_pipeline", "record_id": "recDup1"})
        release.set()
        await asyncio.wait_for(asyncio.shield(task1), timeout=15)

    asyncio.run(run())

    assert launches == ["recDup1"], "重复点击不应触发第二次流水线"
    assert any("已经在跑了" in s for s in sent)


def test_card_action_explain_pipeline(monkeypatch):
    import asyncio

    sent = []

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)

    asyncio.run(job_entry_chat.handle_card_action("chat_exp", {"action": "explain_pipeline"}))

    assert len(sent) == 1
    assert "评估这个岗位" in sent[0] and "绝不自动投递" in sent[0]
    assert "指挥中心" in sent[0]  # 名词区分：说明里包含与指挥中心全链路的对照


def test_card_action_unknown_and_missing_record(monkeypatch):
    import asyncio

    sent = []

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(job_entry_chat, "send_feishu_message", fake_send)

    asyncio.run(job_entry_chat.handle_card_action("chat_bad", {"action": "run_pipeline"}))  # 缺 record_id
    assert any("缺少岗位标识" in s for s in sent)

    asyncio.run(job_entry_chat.handle_card_action("chat_bad", {"action": "whatever"}))  # 未知动作
    assert len(sent) == 1, "未知动作不应发消息"


# ==========================================
# 物料交付到聊天框（ticket 03 核心）
# ==========================================
def test_deliver_materials_sends_pdf_image_greeting_and_card(monkeypatch):
    import asyncio
    from app.core import feishu_client as feishu_client_module
    from app.core import feishu_messaging as fm
    from app.core import feishu_utils

    record_fields = {
        "公司名称": "物料公司", "岗位名称": "物料岗位", "城市": "广州",
        "薪资": "15-30K", "招聘平台": "Boss直聘",
        "PDF备份": [{"file_token": "tok_pdf"}],
        "图片保存": [{"file_token": "tok_img"}],
        "打招呼语": "您好，看到贵司 AI 产品经理岗位，我有 3 年相关经验…",
    }

    async def fake_fetch(table_id, record_id):
        return {"fields": record_fields}

    def fake_download(file_token, save_path):
        with open(save_path, "wb") as f:
            f.write(b"fake-bytes")
        return True

    async def fake_upload_file(data, name):
        return f"file_key_{name}"

    async def fake_upload_image(data):
        return "img_key_1"

    files_sent, images_sent, cards_sent = [], [], []

    async def fake_send_file(receive_id, file_key, receive_id_type="chat_id"):
        files_sent.append(file_key)
        return True

    async def fake_send_image(receive_id, image_key, receive_id_type="chat_id"):
        images_sent.append(image_key)
        return True

    async def fake_send_card(receive_id, card_content, receive_id_type="chat_id"):
        cards_sent.append(card_content)

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        return True

    async def fake_report(fields):
        return b"fake-report-image"

    async def fake_ensure_field():
        return False  # 跳过真实飞书字段检查与云盘上传

    monkeypatch.setattr(feishu_client_module.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(feishu_utils, "download_feishu_file", fake_download)
    monkeypatch.setattr(fm, "upload_file_to_feishu", fake_upload_file)
    monkeypatch.setattr(fm, "upload_image_to_feishu", fake_upload_image)
    monkeypatch.setattr(fm, "send_feishu_file", fake_send_file)
    monkeypatch.setattr(fm, "send_feishu_image", fake_send_image)
    monkeypatch.setattr(fm, "send_feishu_card", fake_send_card)
    monkeypatch.setattr(materials_delivery, "send_feishu_card", fake_send_card)
    monkeypatch.setattr(materials_delivery, "send_feishu_message", fake_send)
    monkeypatch.setattr(materials_delivery, "_generate_eval_report_image", fake_report)
    monkeypatch.setattr(materials_delivery, "_ensure_eval_report_field", fake_ensure_field)

    asyncio.run(job_entry_chat._deliver_materials_to_chat("chat_mat", "recMat001"))

    assert files_sent == ["file_key_物料公司-物料岗位-简历.pdf"], "PDF 应下载→上传→以文件消息发送"
    assert images_sent == ["img_key_1", "img_key_1"], "简历长图 + 评估报告长图各一张"
    assert len(cards_sent) == 1, "物料就绪全生命周期交互卡片"
    card = cards_sent[0]
    assert "物料已就绪" in card["header"]["title"]["content"]
    assert any(
        action.get("url", "").endswith("record=recMat001")
        for el in card["elements"] if el.get("tag") == "action"
        for action in el.get("actions", [])
    ), "卡片应包含跳转多维表格复核按钮"


def test_deliver_materials_empty_reports_hint(monkeypatch):
    import asyncio
    from app.core import feishu_client as feishu_client_module

    sent = []

    async def fake_fetch(table_id, record_id):
        return {"fields": {"公司名称": "空物料公司", "岗位名称": "空物料岗位"}}

    async def fake_send(receive_id: str, text: str, receive_id_type: str = "chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(feishu_client_module.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(materials_delivery, "send_feishu_message", fake_send)

    asyncio.run(job_entry_chat._deliver_materials_to_chat("chat_empty", "recEmpty1"))

    assert any("没找到可发送的物料" in s for s in sent)


# ==========================================
# 评估报告 HTML 长图
# ==========================================
def test_build_eval_report_html_contains_all_parts():
    fields = {
        "公司名称": "报告公司", "岗位名称": "报告岗位", "招聘平台": "Boss直聘",
        "城市": "广州", "薪资": "15-30K", "跟进状态": "简历人工复核",
        "综合评级 (A-F)": "B",
        "核心-角色匹配": 5, "核心-技能重合": 4, "高权-职级资历": 3,
        "高权-薪资契合": 5, "高权-面试概率": 2, "中权-公司阶段": 4,
        "中权-赛道前景": 2, "中权-成长空间": 4,
        "理想画像与能力信号": "理想画像是…\n- **大模型**：LangGraph\n【结论】看好",
        "致命硬伤与毒点": "暂无硬伤",
        "AI评估详情": "**【角色匹配】** 5/5\n候选人拥有智能客服训练师经验，与JD的AI产品运营高度匹配。\n\n**【薪资契合】** 3/5\n【岗位基本信息】薪资范围为面议，基于信息缺失给中性分。",
    }
    html = job_entry_chat.build_eval_report_html(fields)
    assert "报告公司" in html and "报告岗位" in html
    assert 'grade-badge' in html, "评级徽章应渲染"
    for label in ("核心-角色匹配", "中权-成长空间"):
        assert label in html
    assert "5/5" in html and 'class="dot f"' in html, "5 分制点阵应渲染"
    assert "理想画像是…" in html and "暂无硬伤" in html
    assert "<strong>大模型</strong>" in html, "粗体应转换为 strong 标签"
    assert "**" not in html.replace("**/", ""), "不应残留 markdown 星号语法"
    assert '<span class="chip">结论</span>' in html, "【标签】应转换为 chip"
    assert '<ul class="md-list">' in html, "列表行应转为 ul 列表"
    assert "绝不自动投递" in html
    assert '<div class="score-reason">' in html, "各维度评分依据应渲染"
    assert "候选人拥有智能客服训练师经验" in html, "维度原因文本应出现"
    assert "基于信息缺失给中性分" in html
    assert html.count('class="score-reason"') == 2, "只有提供了依据的维度才渲染原因（2 维）"


def test_build_eval_report_html_skips_empty_sections():
    html = job_entry_chat.build_eval_report_html({"公司名称": "X", "岗位名称": "Y"})
    assert "（本岗位无深度评估报告）" in html


def test_deliver_materials_reads_v2_json_directly(monkeypatch):
    """「AI改写JSON」为 V2 JSON（方案 A 新格式）时直读渲染，禁止再走 markdown LLM 解析。"""
    import asyncio
    import json as _json
    from app.core import feishu_client as feishu_client_module
    from app.core import feishu_utils
    from app.core import feishu_messaging as fm
    from app.automation import materials

    v2 = {
        "personalInfo": {"name": "张三", "phone": "13800000000"},
        "summary": "定制总结",
        "workExperience": [], "personalProjects": [], "education": [],
    }
    fields = {
        "公司名称": "直读公司", "岗位名称": "直读岗位",
        "AI改写JSON": _json.dumps(v2, ensure_ascii=False),  # 无附件 → 触发按需渲染
    }

    async def fake_fetch(table_id, record_id):
        return {"fields": fields}

    def forbidden_markdown_parse(md):
        raise AssertionError("V2 JSON 已存在时不应再调用 markdown LLM 解析")

    rendered, updated_records, sent = [], [], []

    async def fake_render(resume_dict, name):
        rendered.append({"resume_dict": resume_dict, "name": name})
        return {"pdf_token": "tok_pdf2", "img_token": "tok_img2", "name": name}

    async def fake_update(table_id, record_id, fields_update):
        updated_records.append(fields_update)
        return {"code": 0}

    # 生产侧经 asyncio.to_thread 调用（要求同步函数），桩必须是 def——
    # async 桩会在 to_thread 里被创建却永不 await（RuntimeWarning + 返回协程对象污染分支）
    def fake_active_rid():
        return None  # 跳过隐私合并分支

    def fake_download(token, save_path):
        with open(save_path, "wb") as f:
            f.write(b"x")
        return True

    async def fake_up_file(data, name):
        return f"fk_{name}"

    async def fake_up_img(data):
        return "ik_1"

    async def fake_s_file(rid, key, receive_id_type="chat_id"):
        return True

    async def fake_s_img(rid, key, receive_id_type="chat_id"):
        return True

    async def fake_s_card(rid, card, receive_id_type="chat_id"):
        pass

    async def fake_send(rid, text, receive_id_type="chat_id", **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(feishu_client_module.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(feishu_client_module.feishu_client, "update_record", fake_update)
    monkeypatch.setattr("app.services.feishu_service.get_active_resume_record_id", fake_active_rid)
    monkeypatch.setattr("ai_agents.markdown_to_json.parse_markdown_to_json", forbidden_markdown_parse)
    monkeypatch.setattr(materials, "_render_custom_resume_materials", fake_render)
    monkeypatch.setattr(feishu_utils, "download_feishu_file", fake_download)
    monkeypatch.setattr(fm, "upload_file_to_feishu", fake_up_file)
    monkeypatch.setattr(fm, "upload_image_to_feishu", fake_up_img)
    monkeypatch.setattr(fm, "send_feishu_file", fake_s_file)
    monkeypatch.setattr(fm, "send_feishu_image", fake_s_img)
    monkeypatch.setattr(fm, "send_feishu_card", fake_s_card)
    monkeypatch.setattr(materials_delivery, "send_feishu_card", fake_s_card)
    monkeypatch.setattr(materials_delivery, "send_feishu_message", fake_send)
    monkeypatch.setattr(materials_delivery, "_generate_eval_report_image", lambda fields: b"report")
    monkeypatch.setattr(materials_delivery, "_ensure_eval_report_field", lambda: False)

    asyncio.run(job_entry_chat._deliver_materials_to_chat("chat_v2", "recV2Json1"))

    assert len(rendered) == 1
    assert rendered[0]["resume_dict"]["personalInfo"]["name"] == "张三"
    assert rendered[0]["name"].startswith("直读公司_直读岗位")
    assert any("PDF 简历" in s and "简历长图" in s for s in sent), "JSON 直读渲染的物料应正常交付"
    assert updated_records, "渲染出的物料应挂回多维表格附件"


# ==========================================
# 富文本 post 类型支持（多行文本）
# ==========================================
def test_extract_post_text():
    from app.services.job_entry_chat import extract_post_text

    content = json.dumps({
        "title": "",
        "content": [[
            {"tag": "text", "text": "帮我把\n1.个人总结下的：熟练掌握改为 熟练掌握GPT/Claude"},
            {"tag": "a", "text": "链接文字", "href": "https://x.com"},
        ]]
    }, ensure_ascii=False)
    out = extract_post_text(content)
    assert "个人总结" in out and "GPT/Claude" in out and "链接文字" in out
    assert extract_post_text("not-json") == ""
    assert extract_post_text("{}") == ""


def test_webhook_post_message_walks_text_pipeline(client: TestClient, monkeypatch):
    from app.api.routes import webhook as webhook_module

    agent_calls, edit_calls, hint_calls = [], [], []

    async def fake_agent(chat_id, text):
        agent_calls.append(text)

    async def fake_edit(chat_id, text):
        edit_calls.append(text)

    async def fake_hint(chat_id, msg_type):
        hint_calls.append(msg_type)

    from app.services import resume_edit_chat

    monkeypatch.setattr(webhook_module, "process_chatops_query", fake_agent)
    monkeypatch.setattr(resume_edit_chat, "handle_edit_message", fake_edit)
    monkeypatch.setattr(webhook_module, "handle_unsupported_message", fake_hint)
    monkeypatch.setattr(resume_edit_chat, "should_intercept_edit", lambda cid, t: "改为" in t)

    # 多行修改指令 → post 类型 → 应进编辑流而非"不支持"提示
    payload = _make_message_event("post", "om_post_edit_1", {
        "content": [[
            {"tag": "text", "text": "帮我把个人总结的熟练掌握改为 熟练掌握GPT/Claude/Deepseek"},
        ]]
    })
    resp = client.post("/feishu/webhook", json=payload)
    assert resp.status_code == 200
    assert _wait_until(lambda: bool(edit_calls)), "post 富文本应走文本管道进入编辑流"
    assert "改为" in edit_calls[0]
    time.sleep(0.2)
    assert hint_calls == [], "post 不应再落入不支持提示"

    # 普通 post 文本（无编辑意图）→ 投递 Agent
    payload2 = _make_message_event("post", "om_post_chat_1", {
        "content": [[{"tag": "text", "text": "看看今天的进度"}]]
    })
    monkeypatch.setattr(resume_edit_chat, "should_intercept_edit", lambda cid, t: False)
    client.post("/feishu/webhook", json=payload2)
    assert _wait_until(lambda: bool(agent_calls)), "普通 post 文本应投递 Agent"


def test_webhook_ignores_app_and_bot_sender_messages(client: TestClient, monkeypatch):
    from app.api.routes import webhook as webhook_module

    agent_calls = []

    async def fake_agent(chat_id, text):
        agent_calls.append(text)

    monkeypatch.setattr(webhook_module, "process_chatops_query", fake_agent)

    # 模拟机器人自身发送的消息回调（sender_type="app"）
    payload = _make_message_event("text", "om_bot_self_msg_1", {"text": "✅ 新版物料已生成并发送"})
    payload["event"]["sender"] = {"sender_type": "app", "sender_id": {"open_id": "ou_bot_01"}}

    resp = client.post("/feishu/webhook", json=payload)
    assert resp.status_code == 200
    time.sleep(0.3)
    assert len(agent_calls) == 0, "机器人/应用自身发送的消息必须被守卫丢弃，绝不得投递 Agent 导致自循环"
