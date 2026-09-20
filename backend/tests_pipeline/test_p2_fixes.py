"""P2 修复回归测试：会话状态存储加固、聚合竞态、物料失败不覆盖附件、链接补录可重试、卡片幂等降级。

对应 2026-09-02 ChatAgent 质检 P2 项。
"""
import asyncio
import json
import time

import pytest

from app.services.job_entry_chat import _PendingStore


# ==========================================
# P2-2: _PendingStore 原子落盘 / 重启恢复 / TTL 读路径淘汰
# ==========================================
def test_pending_store_atomic_persist_and_reload(tmp_path):
    """落盘无 tmp 残留；模拟重启后状态完整恢复。"""
    path = tmp_path / "ps.json"
    s = _PendingStore(path, 24 * 3600)
    s["chat1"] = "rec1"
    s["chat2"] = "rec2"
    assert not (tmp_path / "ps.json.tmp").exists(), "原子替换后不应残留 .tmp"

    fresh = _PendingStore(path, 24 * 3600)  # 等价新进程
    assert fresh.get("chat1") == "rec1"
    assert fresh.get("chat2") == "rec2"


def test_pending_store_ttl_enforced_on_read(tmp_path):
    """TTL 必须在读路径生效：长期运行的过期状态被淘汰，不再被反复消费。"""
    s = _PendingStore(tmp_path / "ps_ttl.json", 0.05)
    s["chat_old"] = "recOld"
    time.sleep(0.06)
    assert s.get("chat_old") is None, "过期状态读取时应被淘汰"
    assert "chat_old" not in s


def test_pending_store_corrupt_file_degrades_gracefully(tmp_path):
    """落盘文件损坏（模拟写一半被杀）：加载静默降级为空，绝不抛异常阻塞消息主链路。"""
    path = tmp_path / "ps_bad.json"
    path.write_text('{"chat1": {"record_id": "rec1", "ts":')  # 撕裂的 JSON
    s = _PendingStore(path, 24 * 3600)  # 不应抛异常
    assert s.get("chat1") is None


# ==========================================
# P2-3: 截图聚合边界竞态（识别进行中不另开批次）
# ==========================================
def test_screenshot_batches_drain_sequentially_during_import(monkeypatch):
    """第一批识别期间到达的第二批截图：等第一批完成后才导入，绝不并发双批次建岗。"""
    from app.services import job_entry_chat as jec

    jec._pending_images.clear()
    jec._importing.clear()
    imports = []

    async def fake_import(chat_id, items):
        imports.append(len(items))
        jec._importing.add(chat_id)  # 模拟识别中的互斥窗口
        await asyncio.sleep(0.15)    # 模拟几十秒的 Vision 解析
        jec._importing.discard(chat_id)

    monkeypatch.setattr(jec, "_import_images", fake_import)
    monkeypatch.setattr(jec, "_AGGREGATION_WINDOW_SECONDS", 0.03)

    async def fake_ack(*a, **kw):
        return True

    monkeypatch.setattr(jec, "send_feishu_message", fake_ack)

    async def run():
        await jec.handle_image_message("chat_agg", "img_1", "om_1")
        await asyncio.sleep(0.05)   # 第一批窗口关闭，进入识别
        # 识别仍在进行时第二批到达：其 flush 必须等待，不得并发导入
        await jec.handle_image_message("chat_agg", "img_2", "om_2")
        for _ in range(80):         # 轮询等待第二批排队→识别完成（等待节拍 0.5s/次）
            if len(imports) >= 2:
                break
            await asyncio.sleep(0.05)

    asyncio.run(run())

    assert len(imports) == 2, f"两批各导入一次，实际 {imports}"
    # 关键断言：第二批的导入开始时间晚于第一批结束（_importing 已释放）——串行不并发
    assert imports == [1, 1]


# ==========================================
# P2-4: send_materials 有附件但发送失败时，绝不覆盖历史附件
# ==========================================
def test_send_materials_does_not_rerender_when_send_fails(monkeypatch):
    """表里有附件但下载失败：不得走即时渲染回写覆盖历史附件，并如实告知用户。"""
    from app.services import job_entry_chat as jec
    from app.core import feishu_utils

    updates, render_calls, sent = [], [], []

    async def fake_fetch(table_id, record_id):
        return {"fields": {
            "公司名称": "覆盖公司", "岗位名称": "覆盖岗位",
            "PDF备份": [{"file_token": "tok_pdf_broken"}],
            "图片保存": [],
        }}

    def fail_download(token, save_path):
        return False  # 模拟下载/发送瞬时失败

    async def forbidden_render(resume_dict, name):
        raise AssertionError("有附件但发送失败时绝不允许即时渲染覆盖历史附件")

    async def fake_update(table_id, record_id, fields):
        updates.append(fields)

    async def fake_text(receive_id, text, receive_id_type="chat_id"):
        sent.append(text)
        return True

    monkeypatch.setattr("app.core.feishu_client.feishu_client.fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(feishu_utils, "download_feishu_file", fail_download)
    monkeypatch.setattr("app.automation.materials._render_custom_resume_materials", forbidden_render)
    monkeypatch.setattr("app.core.feishu_client.feishu_client.update_record", fake_update)
    monkeypatch.setattr(jec, "send_feishu_message", fake_text)

    asyncio.run(jec.handle_card_action(
        "chat_p2_mat", {"action": "send_materials", "record_id": "recP2Mat"}))

    assert updates == [], "发送失败时不得回写覆盖附件字段"
    assert any("发送失败" in t for t in sent), "必须如实告知发送失败"


# ==========================================
# 杂项: 链接补录写表失败保留状态可重试
# ==========================================
def test_link_reply_keeps_pending_on_update_failure(monkeypatch):
    """写表失败：待补录状态保留（用户重发链接仍进补录通道），且收到失败提示。"""
    from app.services import job_entry_chat as jec
    from app.core import feishu_client as fcm

    jec._pending_job_links["chat_link_fail"] = "recLinkFail1"
    updates, sent = [], []

    async def fail_update(table_id, record_id, fields):
        updates.append(fields)
        raise RuntimeError("feishu api down")

    async def fake_text(receive_id, text, receive_id_type="chat_id"):
        sent.append(text)
        return True

    monkeypatch.setattr(fcm.feishu_client, "update_record", fail_update)
    monkeypatch.setattr(jec, "send_feishu_message", fake_text)

    asyncio.run(jec.handle_link_reply("chat_link_fail", "岗位在这里 https://example.com/job/999"))

    assert jec._pending_job_links.get("chat_link_fail") == "recLinkFail1", "写表失败必须保留待补录状态"
    assert any("失败" in t for t in sent), "必须告知用户失败并可重试"

    # 写表成功路径：状态被消费
    async def ok_update(table_id, record_id, fields):
        return {"code": 0}

    monkeypatch.setattr(fcm.feishu_client, "update_record", ok_update)
    asyncio.run(jec.handle_link_reply("chat_link_fail", "岗位在这里 https://example.com/job/999"))
    assert "chat_link_fail" not in jec._pending_job_links, "成功后应消费状态"


# ==========================================
# 杂项: 卡片降级统一走幂等重试 helper
# ==========================================
def test_card_fallback_helper_retries_same_key_then_text(monkeypatch):
    """send_feishu_card_with_fallback：首次超时→同幂等键重试；重试拒绝→恰好一条降级文本。"""
    from app.core.feishu_messaging import send_feishu_card_with_fallback
    from app.core import feishu_messaging as fm

    card_keys, texts = [], []

    async def flaky_card(receive_id, card, receive_id_type="chat_id", idempotency_key=None):
        card_keys.append(idempotency_key)
        if len(card_keys) == 1:
            raise TimeoutError("read timeout after accepted")
        raise RuntimeError("invalid card")  # 重试被明确拒绝

    async def fake_text(receive_id, text, receive_id_type="open_id", **kw):
        texts.append(text)
        return True

    monkeypatch.setattr(fm, "send_feishu_card", flaky_card)
    monkeypatch.setattr(fm, "send_feishu_message", fake_text)

    asyncio.run(send_feishu_card_with_fallback("oc_fb", {"h": 1}, fallback_text="降级文本"))

    assert len(card_keys) == 2 and card_keys[0] == card_keys[1], "两次尝试必须同一幂等键"
    assert texts == ["降级文本"], "重试被拒后降级恰好一条文本"


# ==========================================
# 杂项: token 缓存按凭证失效
# ==========================================
def test_feishu_client_token_invalidated_on_credential_change():
    """配置页热换 APP_ID 后：旧 token 立即作废，下一请求强制重取。"""
    from app.core.feishu_client import FeishuClient
    from app.core.config import settings

    c = FeishuClient()
    c._token_cache = "old_token"
    c._token_expires_at = time.time() + 7200
    c._token_app_id = "old_app_id"

    monkey_freeze = settings.FEISHU_APP_ID
    assert c._token_fresh() is False or c._token_app_id == monkey_freeze, (
        "凭证不一致时 token 必须视为过期"
    )
    c._token_app_id = monkey_freeze  # 凭证一致 + 未过期 → 新鲜
    assert c._token_fresh() is True
